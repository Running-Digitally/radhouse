"""Conversation intent feeds existing task commands; it never computes grants."""

from dataclasses import asdict, replace
import re

from radhouse.channels.commands import Envelope
from radhouse.domain.access import AuthContext, require_access
from radhouse.domain.conversations import ConversationMessage, MessageRoute
from radhouse.domain.tasks import Rejected, StartTask, validate_input_files
from radhouse.application.service import fingerprint


_STATUS = re.compile(
    r"(?:status|progress|any (?:progress|update|updates)|what(?:'s| is) (?:the )?status|how(?:'s| is) (?:it|the task|the work) (?:going|progressing))[?.! ]*",
    re.I,
)
_NEW = re.compile(r"^(?:separately[, :]+|new task[: ,]+)", re.I)


def _without_agent_prefix(content, display_name):
    return re.sub(
        rf"^\s*@{re.escape(display_name)}(?=$|[\s,:])[: ,]*",
        "",
        content,
        count=1,
        flags=re.I,
    )


class Conversations:
    def __init__(self, service):
        self.service = service

    @property
    def store(self):
        return self.service.store

    def authorize(self, tx, link, *, write=False):
        if (
            self.service.conversation_scope is not None
            and not self.service.conversation_scope(link)
        ):
            raise Rejected("conversation_link_denied", 403)
        if not link.active or tx.conversation_link(link.link_id) != link:
            raise Rejected("conversation_link_denied", 403)
        enrollment = tx.conversation_enrollment(link.link_id)
        if enrollment is not None and not enrollment["ready"]:
            raise Rejected("conversation_enrollment_pending", 403)
        actor = AuthContext(link.principal_id, "buzz", link.owner_pubkey)
        envelope = Envelope(
            "buzz", "read", link.conversation_id, link.binding_revision, "read"
        )
        self.service._binding(tx, actor, envelope, link.project_id)
        require_access(
            tx.access(link.principal_id), link.bot_id, link.project_id, write=write
        )
        project = tx.project(link.project_id)
        if project is None or project.state != "active":
            raise Rejected("project_unavailable", 403)
        return actor

    def history(self, actor, envelope, link_id, *, after=0, before=None, tail=False):
        with self.store.transaction() as tx:
            link = tx.conversation_link(link_id)
            if link is None or link.principal_id != actor.principal_id:
                raise Rejected("conversation_link_denied", 403)
            # A web session still proves its own binding; the underlying Buzz
            # link/grants must also remain active for the linked history.
            self.service._binding(tx, actor, envelope, link.project_id)
            self.authorize(tx, link)
            rows = tx.conversation_history(
                link_id, after=after, before=before, tail=tail
            )
            status = tx.conversation_status(link_id)
            return {
                "link": asdict(link),
                "messages": [
                    {**asdict(r["message"]), "sequence": r["sequence"]} for r in rows
                ],
                "cursor": rows[-1]["sequence"] if rows else after,
                "error_code": status["error_code"],
            }

    def _route(self, tx, link, message):
        content = message.content
        if message.addressed:
            bot = next(
                (item for item in tx.bots(link.principal_id) if item.bot_id == link.bot_id),
                None,
            )
            if bot is None:
                raise Rejected("bot_unavailable", 409)
            content = _without_agent_prefix(content, bot.display_name)
        explicit_start = (
            message.addressed
            and not message.reply_to
            and not _STATUS.fullmatch(content.strip())
            and not (link.workflow_version == 'artifact-v1' and content.strip().lower().rstrip('.!?') in {'pause', 'resume', 'cancel'})
        )
        if explicit_start:
            return MessageRoute("start")
        if (
            tx.conversation_pending(link.link_id, limit=1)
            and not message.reply_to
            and not _NEW.match(content)
        ):
            return MessageRoute("clarify")
        target = None
        if message.reply_to:
            reply = tx.conversation_reply(link.link_id, message.reply_to)
            if reply is None and len(link.member_pubkeys) > 1:
                reply = tx.conversation_reply_in_channel(
                    link.channel_id, message.reply_to
                )
            if reply is None:
                return MessageRoute("clarify")
            parent_link = tx.conversation_link(reply["message"].link_id)
            if (
                parent_link is None
                or parent_link.channel_id != link.channel_id
                or parent_link.principal_id != link.principal_id
                or parent_link.project_id != link.project_id
                or parent_link.conversation_id != link.conversation_id
            ):
                return MessageRoute("clarify")
            target = (
                tx.task(reply["message"].task_id) if reply["message"].task_id else None
            )
            if target is not None and target.bot_id != link.bot_id:
                if link.workflow_version == 'artifact-v1':
                    return MessageRoute('clarify')
                if target.phase == "closed" and target.result:
                    return MessageRoute("start", follows_task_id=target.task_id)
                return MessageRoute("clarify")
        tasks = [
            tx.task(task_id) for task_id in tx.conversation_task_messages(link.link_id)
        ]
        tasks = [t for t in tasks if t is not None]
        active = [t for t in tasks if t.phase != "closed"]
        if target is None and not message.reply_to:
            if len(active) > 1 and not _NEW.match(content):
                return MessageRoute("clarify")
            target = active[0] if active else tx.task(tx.conversation_focus(link))
        if _STATUS.fullmatch(content.strip()):
            return MessageRoute("status", target.task_id if target else None)
        if link.workflow_version == 'artifact-v1' and target is not None:
            control = content.strip().lower().rstrip('.!?')
            if control in {'pause', 'resume', 'cancel'}:
                return MessageRoute(control, target.task_id, target.state_revision)
        if _NEW.match(content):
            return MessageRoute("start")
        if message.files and target is not None and target.phase != "closed":
            return MessageRoute("clarify")
        if target is not None:
            if target.phase == "closed":
                if link.workflow_version == 'artifact-v1':
                    # S2c adds bounded natural-language interpretation. Until
                    # then a completed-work reply cannot create a fresh planner.
                    return MessageRoute('clarify', target.task_id)
                return MessageRoute(
                    "start", follows_task_id=target.task_id if target.result else None
                )
            return MessageRoute("guide", target.task_id, target.state_revision)
        if len(tasks) > 1:
            return MessageRoute("clarify")
        return MessageRoute("start")

    def receive(self, link, message, *, event=None):
        if (
            message.link_id != link.link_id
            or message.author != link.principal_id
            or message.source not in {"buzz", "radhouse"}
            or not message.content.strip()
            or len(message.content) > 4096
        ):
            raise Rejected("invalid_conversation_message", 422)
        validate_input_files(message.files, code="invalid_conversation_message")
        with self.store.transaction() as tx:
            self.authorize(tx, link, write=True)
            old = tx.conversation_message(message.message_id)
            if old:
                if (
                    old["message"].link_id,
                    old["message"].author,
                    old["message"].content,
                    old["message"].reply_to,
                    old["message"].files,
                ) != (
                    message.link_id,
                    message.author,
                    message.content,
                    message.reply_to,
                    message.files,
                ):
                    raise Rejected("conversation_message_conflict")
                return old
            # Freeze routing before any task/control effect. Retrying after a
            # crash cannot accidentally target a newer active task.
            route = self._route(tx, link, message)
            if link.workflow_version == 'artifact-v1' and route.task_id:
                work = tx.work_for_task(route.task_id)
                if work is None:
                    route = MessageRoute('clarify')
                else:
                    route = replace(route, work_id=work.work_id,
                                    work_revision=work.state_revision, scope_revision=work.scope_revision)
            tx.save_conversation_message(message, route=route, event=event)
            return tx.conversation_message(message.message_id)

    def process(self, link, message_id):
        with self.store.transaction() as tx:
            actor = self.authorize(tx, link, write=True)
            row = tx.conversation_message(message_id)
            if row is None or row["message"].link_id != link.link_id:
                raise Rejected("conversation_message_denied", 403)
            if row["processed"]:
                return row["message"]
            message, route = row["message"], row["route"]
            bot = next(
                (b for b in tx.bots(actor.principal_id) if b.bot_id == link.bot_id),
                None,
            )
            if bot is None:
                raise Rejected("bot_unavailable")
        envelope = Envelope(
            "buzz", message_id, link.conversation_id, link.binding_revision, message_id
        )
        if link.workflow_version == 'artifact-v1':
            return self._process_work(link, actor, envelope, message, route, bot)
        task = None
        response_id = "reply:" + message_id
        if route.action == "start":
            brief = message.content
            if message.addressed:
                brief = _without_agent_prefix(brief, bot.display_name)
            task = self.service.admit(
                actor,
                envelope,
                StartTask(
                    link.bot_id,
                    link.project_id,
                    _NEW.sub("", brief, count=1),
                    bot.provider_binding,
                    files=message.files,
                    follows_task_id=route.follows_task_id,
                ),
            )
            reply = "I have your assignment. I’ll keep its progress and result in this conversation."
            if task.disable_tools:
                reply += " Tools are disabled for this task."
            elif task.allowed_tools:
                reply += " This task is restricted to: " + ", ".join(task.allowed_tools) + "."
        elif route.action == "guide":
            try:
                task = self.service.guide(
                    actor,
                    route.task_id,
                    route.expected_revision,
                    message.content,
                    envelope=envelope,
                )
                control_id = "control:" + fingerprint(
                    [actor.principal_id, envelope.command_key]
                )
                receipt = next(
                    (g for g in task.guidance if g.get("id") == control_id), None
                )
                from radhouse.application.guidance import TERMINAL, outcome_message_id, outcome_text
                reply = outcome_text(receipt or {})
                if receipt and receipt.get("application_state") in TERMINAL:
                    response_id = outcome_message_id(task.task_id, receipt)
            except Rejected as error:
                if error.code not in {
                    "stale_state",
                    "task_not_accepting_control",
                    "control_outcome_unknown",
                    "permission_response_required",
                    "task_control_limit",
                    "runtime_guidance_receipts_unavailable",
                }:
                    raise
                task = self.service.get(actor, route.task_id, envelope=envelope)
                reply = "Your message is saved. This task cannot accept that update right now; check its current state before trying again."
        elif route.action == "status":
            task = (
                self.service.get(actor, route.task_id, envelope=envelope)
                if route.task_id
                else None
            )
            reply = (
                self.describe(task, bot.display_name)
                if task
                else "There is no active task in this conversation. Reply to a task message to ask about that work."
            )
            if task and task.result and self.service.review_links is not None:
                with self.store.transaction() as tx:
                    publication = tx.publication(task.task_id)
                    if publication is not None:
                        reply += "\n\nReview status · Approved and published to the approved audience."
                    else:
                        reply += "\n\nReview required · Sign in to Radhouse:\n" + self.service.review_links.issue(tx, link, task)
        else:
            reply = "Which task do you mean? Reply to its message so I can keep your instruction with the right work."
        completed = replace(
            message, task_id=task.task_id if task else None, state=route.action
        )
        response = ConversationMessage(
            response_id,
            link.link_id,
            link.bot_id,
            reply,
            "radhouse",
            int(self.service._now().timestamp()),
            task_id=completed.task_id,
            reply_to=message_id,
            state="reply",
        )
        with self.store.transaction() as tx:
            self.authorize(tx, link, write=True)
            tx.save_conversation_message(completed, processed=True)
            if tx.conversation_message(response.message_id) is None:
                tx.save_conversation_message(response, processed=True)
        return completed

    def _process_work(self, link, actor, envelope, message, route, bot):
        from radhouse.application.work_service import WorkService
        from radhouse.domain.work import WorkCommand
        work_service = WorkService(self.service)
        view = None
        if route.action == 'start':
            brief = _without_agent_prefix(message.content, bot.display_name) if message.addressed else message.content
            view = work_service.submit(actor, envelope, StartTask(link.bot_id, link.project_id,
                _NEW.sub('', brief, count=1), bot.provider_binding, files=message.files))
            reply = 'Your artifact request is saved. Its progress and result belong to this work.'
        elif route.action == 'status' and route.work_id:
            view = work_service.get(actor, route.work_id, envelope=envelope)
            reply = self.describe_work(view)
        elif route.action in {'guide', 'pause', 'resume', 'cancel'} and route.work_id:
            command = WorkCommand('guidance' if route.action == 'guide' else route.action,
                route.work_revision, route.scope_revision, message.content if route.action == 'guide' else None)
            try:
                result = work_service.apply_command(actor, route.work_id, command, envelope=envelope)
                view = result.work
                reply = ('Your update was applied.' if result.application_state == 'applied'
                         else 'Your update is saved; its application is not yet confirmed.') if route.action == 'guide' else self.describe_work(view)
            except Rejected as error:
                if error.status in {401, 403, 404}:
                    raise
                view = work_service.get(actor, route.work_id, envelope=envelope)
                reply = 'Your message is saved. This work cannot accept that update in its current state.\n' + self.describe_work(view)
        else:
            reply = 'Reply to the work you mean, or start a separate assignment. No new work was started.'
        completed = replace(message, task_id=view.task_id if view else None, state=route.action)
        response = ConversationMessage('reply:' + message.message_id, link.link_id, link.bot_id,
            reply, 'radhouse', int(self.service._now().timestamp()), task_id=completed.task_id,
            reply_to=message.message_id, state='reply')
        with self.store.transaction() as tx:
            self.authorize(tx, link, write=True)
            tx.save_conversation_message(completed, processed=True)
            if tx.conversation_message(response.message_id) is None:
                tx.save_conversation_message(response, processed=True)
        return completed

    @staticmethod
    def describe_work(view):
        text = view.title + '\n' + view.state_label
        if view.blockers:
            text += '\n' + '\n'.join(blocker.message for blocker in view.blockers)
        if view.artifact is not None:
            text += '\nArtifact retained: ' + view.artifact.name + '. Open the work in Radhouse.'
        return text

    @staticmethod
    def describe(task, agent_name="Researcher"):
        if task is None:
            return "There is no selected task."
        if "runtime_unavailable" in task.blockers:
            return f"{agent_name}’s runtime is unavailable. Your assignment is saved; recovery will use this same task."
        if task.phase == "queued" and task.blockers == ("provider_unavailable",):
            return f"{agent_name} is waiting for the model provider. Your assignment is saved; Radhouse will check availability again automatically."
        if task.blockers:
            return "This task needs attention. Your work is saved; open its details for the current hold or decision."
        if task.phase == "closed":
            return {
                "completed": "The result is ready for your review.",
                "cancelled": "This task was cancelled.",
                "failed": "This task stopped with an error; its saved work is retained.",
            }.get(task.outcome, "This task has finished.")
        return {
            "queued": "Your assignment is queued.",
            "active": f"{agent_name} is working on your assignment.",
            "recovering": "I’m recovering the existing task; I haven’t submitted another assignment.",
            "stopping": "The task is stopping.",
        }[task.phase]
