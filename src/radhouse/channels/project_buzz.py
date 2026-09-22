"""One private Buzz project channel coordinated by the Radhouse identity."""

import re

from radhouse.application.conversations import Conversations
from radhouse.application.project_coordination import (
    accept_preview,
    apply_result,
    coordination_prompt,
    parse_coordination_plan,
    status_text,
)
from radhouse.application.service import fingerprint
from radhouse.channels.buzz_conversations import BuzzConversationCycle, reply_target
from radhouse.channels.buzz_files import reference_files
from radhouse.channels.commands import Envelope
from radhouse.domain.access import AuthContext
from radhouse.domain.conversations import ConversationMessage, MessageRoute
from radhouse.domain.projects import ProjectCoordination
from radhouse.domain.tasks import Rejected, StartTask


_STATUS = re.compile(
    r"(?:status|progress|any (?:progress|update|updates)|what(?:'s| is) (?:the )?status|"
    r"what(?:'s| is) happening|what(?:'s| is) (?:the )?(?:builder|researcher|reviewer|deployer|agent) "
    r"(?:doing|working on|up to)|how(?:'s| is) (?:it|the task|the work) (?:going|progressing))[?.! ]*",
    re.I,
)
_ACCEPT = re.compile(r"(?:looks good|preview (?:is )?(?:good|accepted|approved)|accept (?:the )?preview)", re.I)
_REVIEW = re.compile(r"\b(?:review|reviewer|check the (?:pr|revision|work))\b", re.I)
_DEPLOY = re.compile(r"\b(?:deploy|release|deployment)\b", re.I)
_RESEARCH = re.compile(r"\b(?:research|compare|alternatives|documentation|investigate|figure out)\b", re.I)
_BUILD = re.compile(r"\b(?:build|implement|fix|change|improve|update|feature|import)\b", re.I)
_PAUSE = re.compile(r"\s*(?:pause|hold)(?:\s+(?:this|the))?(?:\s+(?:work|task|project))?[?.! ]*", re.I)
_RESUME = re.compile(r"\s*(?:resume|continue)(?:\s+(?:this|the))?(?:\s+(?:work|task|project))?[?.! ]*", re.I)
_STOP = re.compile(r"\s*(?:stop|cancel)(?:\s+(?:this|the))?(?:\s+(?:work|task|project))?[?.! ]*", re.I)


class ProjectBuzzConversationCycle:
    """Route owner messages while specialists keep their normal task paths."""

    def __init__(self, service, coordinator, specialists):
        self.service, self.store = service, service.store
        self.coordinator = coordinator
        self.link, self.relay = coordinator.link, coordinator.relay
        self.specialists = tuple(specialists)
        self.conversations = Conversations(service)

    def _authorize(self):
        self.relay.verify_conversation(self.link)
        with self.store.transaction() as tx:
            self.conversations.authorize(tx, self.link, write=True)
        for specialist in self.specialists:
            specialist.relay.verify_conversation(specialist.link)
            with self.store.transaction() as tx:
                self.conversations.authorize(tx, specialist.link, write=True)

    def _roles(self):
        with self.store.transaction() as tx:
            bots = {bot.bot_id: bot for bot in tx.bots(self.link.principal_id, self.link.project_id)}
        result = {}
        for configured in self.specialists:
            bot = bots.get(configured.link.bot_id)
            if bot is not None and bot.state == "ready":
                role = bot.role_name.casefold()
                for name in ("researcher", "builder", "reviewer", "deployer"):
                    if name in role:
                        result[name] = configured
        return result, bots

    def _state(self):
        with self.store.transaction() as tx:
            state = tx.project_coordination(self.link.project_id)
            if state is None:
                state = ProjectCoordination(self.link.project_id).validate()
                tx.save_project_coordination(state, None)
            return state

    def _save_state(self, old, new):
        with self.store.transaction() as tx:
            current = tx.project_coordination(old.project_id)
            if current != old:
                raise Rejected("project_coordination_revision_conflict")
            tx.save_project_coordination(new, old.revision)

    def _planning_candidate(self, event, state, roles, bots):
        if state.active_task_id is not None or roles.get("researcher") is None:
            return False
        mentioned, addressed = self._mentioned(event, bots)
        if addressed or mentioned or reply_target(event):
            return False
        content = self._coordinator_content(event, bots)
        if (
            _STATUS.fullmatch(content)
            or _ACCEPT.search(content)
            or state.phase in {"preview_feedback", "correction", "merge_ready", "deployed"}
        ):
            return False
        research, build = bool(_RESEARCH.search(content)), bool(_BUILD.search(content))
        if (_DEPLOY.search(content) or _REVIEW.search(content)) and not (research or build):
            return False
        return research and build or not research and not build

    def _start_planning(self, state, event, files, roles, bots):
        selected = roles["researcher"]
        bot = bots[selected.link.bot_id]
        prompt = coordination_prompt(
            event["content"],
            phase=state.phase,
            available_roles=tuple(sorted(roles)),
            attachments=tuple((item.name, item.media_type) for item in files),
        )
        key = "project-plan:" + fingerprint(
            [state.project_id, event["id"], event["content"]]
        )
        actor = AuthContext(selected.link.principal_id, "buzz", selected.link.owner_pubkey)
        task = self.service.admit(
            actor,
            Envelope(
                "buzz", key, selected.link.conversation_id,
                selected.link.binding_revision, key,
            ),
            StartTask(
                selected.link.bot_id,
                selected.link.project_id,
                prompt,
                bot.provider_binding,
                budget=1,
                disable_tools=True,
            ),
        )
        updated = state.evolve(
            active_bot_id=task.bot_id,
            active_task_id=task.task_id,
            planning_task_id=task.task_id,
            planning_source_message_id=event["id"],
            phase="planning",
            status_note="Radhouse is choosing the smallest useful project path.",
        ).validate()
        # Admission is idempotent. Persist the source event and coordination
        # pointer together so a restart cannot mark the request processed while
        # losing the planner task that owns it.
        with self.store.transaction() as tx:
            current = tx.project_coordination(state.project_id)
            if current != state:
                raise Rejected("project_coordination_revision_conflict")
            tx.save_conversation_message(
                ConversationMessage(
                    event["id"], self.link.link_id, self.link.principal_id,
                    event["content"], "buzz", event["created_at"],
                    task_id=task.task_id, reply_to=reply_target(event), files=files,
                    state="planning",
                ),
                event=event,
                processed=True,
            )
            tx.save_project_coordination(updated, state.revision)
        self._note(
            "coord-plan-start:" + event["id"],
            "I’m working out the smallest useful path for this request. Reply status anytime for details.",
            reply_to=event["id"],
            task_id=task.task_id,
        )
        return updated

    def _finish_planning(self, state, planner_task, roles, bots):
        with self.store.transaction() as tx:
            source = tx.conversation_message(state.planning_source_message_id)
        if source is None:
            updated = state.evolve(
                active_bot_id=None,
                active_task_id=None,
                planning_task_id=None,
                planning_source_message_id=None,
                phase="blocked",
                status_note="The original project request is unavailable.",
            ).validate()
            self._save_state(state, updated)
            return updated
        allowed = {"clarify"}
        if roles.get("researcher"):
            allowed.add("research")
        if roles.get("builder"):
            allowed.add("build")
        if roles.get("researcher") and roles.get("builder"):
            allowed.add("research_then_build")
        try:
            if planner_task.outcome != "completed" or not planner_task.result:
                raise Rejected("coordination_plan_failed", 409)
            plan = parse_coordination_plan(
                planner_task.result, allowed_routes=frozenset(allowed)
            )
        except Rejected:
            updated = state.evolve(
                active_bot_id=None,
                active_task_id=None,
                planning_task_id=None,
                planning_source_message_id=None,
                phase="blocked",
                status_note="Radhouse could not confidently route the request.",
            ).validate()
            self._save_state(state, updated)
            self._note(
                "coord-plan-invalid:" + source["message"].message_id,
                "I could not confidently choose the next agent. Please say whether you want research, implementation, or both.",
                reply_to=source["message"].message_id,
            )
            return updated
        if plan.route == "clarify":
            updated = state.evolve(
                active_bot_id=None,
                active_task_id=None,
                planning_task_id=None,
                planning_source_message_id=None,
                phase="intake",
                status_note=plan.clarification,
            ).validate()
            self._save_state(state, updated)
            self._note(
                "coord-plan-clarify:" + source["message"].message_id,
                plan.clarification,
                reply_to=source["message"].message_id,
            )
            return updated
        role = "researcher" if plan.route.startswith("research") else "builder"
        selected = roles[role]
        bot = bots[selected.link.bot_id]
        source_message = source["message"]
        brief = source_message.content + "\n\nCoordination note: " + plan.summary
        key = "project-plan-dispatch:" + fingerprint(
            [state.project_id, source_message.message_id, plan.route]
        )
        actor = AuthContext(selected.link.principal_id, "buzz", selected.link.owner_pubkey)
        task = self.service.admit(
            actor,
            Envelope(
                "buzz", key, selected.link.conversation_id,
                selected.link.binding_revision, key,
            ),
            StartTask(
                selected.link.bot_id,
                selected.link.project_id,
                brief,
                bot.provider_binding,
                files=source_message.files,
            ),
        )
        if plan.title:
            self.service.record_agent_title(task.task_id, plan.title)
        anchor_id = "planned:" + key
        with self.store.transaction() as tx:
            if tx.conversation_message(anchor_id) is None:
                tx.save_conversation_message(
                    ConversationMessage(
                        anchor_id,
                        selected.link.link_id,
                        selected.link.principal_id,
                        source_message.content,
                        "buzz",
                        source_message.created_at,
                        task_id=task.task_id,
                        files=source_message.files,
                        state="planned",
                    ),
                    route=MessageRoute("start"),
                    event=source["event"],
                    processed=True,
                )
        updated = state.evolve(
            active_bot_id=task.bot_id,
            active_task_id=task.task_id,
            latest_task_id=task.task_id,
            planning_task_id=None,
            planning_source_message_id=None,
            phase="research" if role == "researcher" else "building",
            handoff_bot_id=(
                roles["builder"].link.bot_id
                if plan.route == "research_then_build"
                else None
            ),
            handoff_brief=(
                "Use the Researcher result as context and implement the requested project change."
                if plan.route == "research_then_build"
                else None
            ),
            status_note=f"{bot.display_name} is working.",
        ).validate()
        self._save_state(state, updated)
        self._note(
            "coord-plan-route:" + source_message.message_id,
            f"Plan: {plan.summary}\n\nI routed the first step to {bot.display_name}. Reply status anytime for details.",
            reply_to=source_message.message_id,
            task_id=task.task_id,
        )
        return updated

    def _note(self, message_id, text, *, reply_to=None, task_id=None):
        with self.store.transaction() as tx:
            if tx.conversation_message(message_id) is None:
                tx.save_conversation_message(
                    ConversationMessage(
                        message_id, self.link.link_id, self.link.bot_id, text,
                        "radhouse", int(self.service._now().timestamp()),
                        task_id=task_id, reply_to=reply_to, state="coordination",
                    ),
                    processed=True,
                )

    def _record_owner_event(self, event, *, files=(), task_id=None, state="coordination"):
        with self.store.transaction() as tx:
            if tx.conversation_message(event["id"]) is None:
                tx.save_conversation_message(
                    ConversationMessage(
                        event["id"], self.link.link_id, self.link.principal_id,
                        event["content"], "buzz", event["created_at"],
                        task_id=task_id, reply_to=reply_target(event), files=files,
                        state=state,
                    ),
                    event=event,
                    processed=True,
                )

    def _reconcile(self, state, roles, bots):
        if state.active_task_id is None:
            return state
        with self.store.transaction() as tx:
            task = tx.task(state.active_task_id)
        if state.planning_task_id is not None:
            if task is None:
                updated = state.evolve(
                    active_bot_id=None,
                    active_task_id=None,
                    planning_task_id=None,
                    planning_source_message_id=None,
                    phase="blocked",
                    status_note="The coordination planning task is unavailable.",
                ).validate()
                self._save_state(state, updated)
                return updated
            if task.phase != "closed":
                return state
            return self._finish_planning(state, task, roles, bots)
        if task is None or task.phase != "closed":
            return state
        bot = bots.get(task.bot_id)
        if bot is None:
            updated = state.evolve(
                active_bot_id=None, active_task_id=None, phase="blocked",
                status_note="The active agent is no longer assigned to this project.",
            ).validate()
            self._save_state(state, updated)
            return updated
        if task.outcome != "completed" or not task.result:
            updated = state.evolve(
                active_bot_id=None,
                active_task_id=None,
                phase="blocked",
                status_note=f"{bot.display_name} stopped without a usable result.",
            ).validate()
        else:
            updated = apply_result(state, bot.role_name, task.result)
        self._save_state(state, updated)
        self._note(
            "coord-result:" + task.task_id,
            updated.status_note or f"{bot.display_name} finished.",
            task_id=task.task_id,
        )
        state = updated
        # A completed research/build plan and a Reviewer correction are the two
        # native automatic handoffs. Merge and deployment always wait for the owner.
        target = state.handoff_bot_id if task.outcome == "completed" and task.result else None
        brief = state.handoff_brief if target else None
        files = (
            task.files
            if target and "research" in bot.role_name.casefold()
            else ()
        )
        if (
            task.outcome == "completed"
            and task.result
            and "reviewer" in bot.role_name.casefold()
            and state.reviewer_verdict == "CHANGES_NEEDED"
        ):
            target = roles.get("builder").link.bot_id if roles.get("builder") else None
            brief = "Address the Reviewer findings against the same pull request and update the same preview."
            files = ()
        if target and brief:
            selected = next((item for item in self.specialists if item.link.bot_id == target), None)
            if selected is not None:
                state = self._handoff(
                    state, selected, task.task_id, brief, bots, files=files
                )
        return state

    def _handoff(self, state, selected, previous_task_id, brief, bots, *, files=()):
        bot = bots[selected.link.bot_id]
        key = "project-handoff:" + fingerprint(
            [state.project_id, previous_task_id, selected.link.bot_id, brief]
        )
        actor = AuthContext(selected.link.principal_id, "buzz", selected.link.owner_pubkey)
        task = self.service.admit(
            actor,
            Envelope("buzz", key, selected.link.conversation_id,
                     selected.link.binding_revision, key),
            StartTask(
                selected.link.bot_id, selected.link.project_id, brief,
                bot.provider_binding, files=files,
                follows_task_id=previous_task_id,
            ),
        )
        message_id = "handoff:" + key
        with self.store.transaction() as tx:
            if tx.conversation_message(message_id) is None:
                tx.save_conversation_message(
                    ConversationMessage(
                        message_id, selected.link.link_id, selected.link.principal_id,
                        brief, "radhouse", int(self.service._now().timestamp()),
                        task_id=task.task_id, files=files, state="handoff",
                    ),
                    route=MessageRoute("start", follows_task_id=previous_task_id),
                    processed=True,
                )
        old = state
        role = bot.role_name.casefold()
        state = state.evolve(
            active_bot_id=task.bot_id,
            active_task_id=task.task_id,
            latest_task_id=task.task_id,
            phase=(
                "building" if "builder" in role else
                "deployment" if "deploy" in role else
                "research" if "research" in role else
                "review"
            ),
            handoff_bot_id=None,
            handoff_brief=None,
            status_note=f"Handed the next step to {bot.display_name}.",
        ).validate()
        self._save_state(old, state)
        self._note(
            "coord-handoff:" + task.task_id,
            f"Previous step complete; handing the next step to {bot.display_name}.",
            task_id=task.task_id,
        )
        return state

    def _mentioned(self, event, bots):
        signed = {
            tag[1] for tag in event["tags"]
            if len(tag) in {2, 3} and tag[0] == "mention"
            and (len(tag) == 2 or tag[2] == "agent-address")
        }
        if signed:
            if signed == {self.link.agent_pubkey}:
                return [], False
            admitted = {item.link.agent_pubkey for item in self.specialists}
            if len(signed) != 1 or not signed <= admitted:
                return [], True
            matches = [item for item in self.specialists if item.link.agent_pubkey in signed]
            return matches, True
        matches = []
        for item in self.specialists:
            bot = bots.get(item.link.bot_id)
            if bot and re.search(
                rf"(?<![\w@])@{re.escape(bot.display_name)}(?=$|[\s,:.!?])",
                event["content"], re.I,
            ):
                matches.append(item)
        coordinator = bots.get(self.link.bot_id)
        if coordinator and re.match(
            rf"^\s*@{re.escape(coordinator.display_name)}(?=$|[\s,:.!?])",
            event["content"], re.I,
        ):
            return [], False
        return matches, re.match(r"^\s*@[^\s,:]+", event["content"]) is not None

    def _coordinator_content(self, event, bots):
        """Read intent after an owner-facing @Radhouse prefix; retain the signed source unchanged."""
        content = event["content"].strip()
        coordinator = bots.get(self.link.bot_id)
        if coordinator:
            content = re.sub(
                rf"^@{re.escape(coordinator.display_name)}(?=$|[\s,:.!?])[\s,:.!?]*",
                "", content, count=1, flags=re.I,
            )
        return content.strip()

    def _select(self, event, state, roles, bots):
        mentioned, addressed = self._mentioned(event, bots)
        if addressed:
            if len(mentioned) != 1:
                return None, "Mention exactly one assigned project agent.", False, state
            if (
                state.active_bot_id is not None
                and mentioned[0].link.bot_id != state.active_bot_id
            ):
                active = bots.get(state.active_bot_id)
                name = active.display_name if active else "Another project agent"
                return None, f"{name} is still working. Wait for that step to finish before starting another agent.", False, state
            return mentioned[0], None, True, state
        parent_id = reply_target(event)
        if parent_id:
            with self.store.transaction() as tx:
                parent = tx.conversation_reply_in_channel(self.link.channel_id, parent_id)
            if parent is not None:
                selected = next(
                    (item for item in self.specialists
                     if item.link.link_id == parent["message"].link_id), None
                )
                if selected is not None:
                    if (
                        state.active_bot_id is not None
                        and selected.link.bot_id != state.active_bot_id
                    ):
                        active = bots.get(state.active_bot_id)
                        name = active.display_name if active else "Another project agent"
                        return None, f"{name} is still working. Wait for that step to finish before starting another agent.", False, state
                    return selected, None, False, state
        content = self._coordinator_content(event, bots)
        research, build = bool(_RESEARCH.search(content)), bool(_BUILD.search(content))
        new_work = research or build
        if _STATUS.fullmatch(content):
            latest = self._task(state.latest_task_id) if state.latest_task_id else None
            selected = next((item for item in self.specialists
                             if item.link.bot_id == state.active_bot_id), None) or next(
                (item for item in self.specialists
                 if latest is not None and item.link.bot_id == latest.bot_id), None,
            )
            current = self._task(state.active_task_id) if state.active_task_id else latest
            with self.store.transaction() as tx:
                activity = (
                    tx.latest_event(current.task_id, "runtime_activity")
                    if current is not None
                    else None
                )
            name = (
                "Radhouse"
                if state.planning_task_id is not None
                else bots.get(state.active_bot_id).display_name
                if state.active_bot_id in bots
                else None
            )
            return selected, status_text(
                state,
                name,
                task=current,
                activity=activity.data if activity else None,
                now=int(self.service._now().timestamp()),
            ), False, state
        if state.active_bot_id:
            selected = next((item for item in self.specialists if item.link.bot_id == state.active_bot_id), None)
            return selected, None, False, state
        if _ACCEPT.search(content):
            try:
                state = accept_preview(state)
            except Rejected:
                return None, "The current preview revision is not recorded yet, so I cannot send it to review.", False, state
            return roles.get("reviewer"), None, False, state
        if _DEPLOY.search(content) and not new_work:
            if (state.reviewer_verdict != "READY"
                    or state.reviewed_revision != state.preview_revision
                    or state.preview_revision != state.source_revision):
                return None, "Deployment is waiting for a READY review of the current revision.", False, state
            return roles.get("deployer"), None, False, state
        if _REVIEW.search(content) and not new_work:
            return roles.get("reviewer"), None, False, state
        if state.phase in {"preview_feedback", "correction"}:
            return roles.get("builder"), None, False, state
        if research and roles.get("researcher"):
            if build and roles.get("builder"):
                state = state.evolve(
                    handoff_bot_id=roles["builder"].link.bot_id,
                    handoff_brief="Use the Researcher result as context and implement the requested project change.",
                ).validate()
            return roles["researcher"], None, False, state
        return roles.get("builder") or roles.get("researcher"), None, False, state

    def _task(self, task_id):
        with self.store.transaction() as tx:
            return tx.task(task_id)

    def _control(self, state, event, action, bots):
        if state.active_task_id is None or state.active_bot_id is None:
            return state, "There is no active project work to control."
        selected = next(
            (item for item in self.specialists if item.link.bot_id == state.active_bot_id),
            None,
        )
        task = self._task(state.active_task_id)
        if selected is None or task is None or task.phase == "closed":
            return state, "The active project step has already finished."
        actor = AuthContext(selected.link.principal_id, "buzz", selected.link.owner_pubkey)
        envelope = Envelope(
            "buzz", event["id"], selected.link.conversation_id,
            selected.link.binding_revision, event["id"],
        )
        if action == "pause":
            controlled = self.service.pause(
                actor, task.task_id, task.state_revision, envelope=envelope
            )
            updated = state.evolve(
                phase="paused",
                status_note=(
                    "Pause requested; the exact active run is still reconciling."
                    if controlled.phase == "stopping"
                    else "Project work is paused."
                ),
            ).validate()
            response = updated.status_note
        elif action == "resume":
            controlled = self.service.resume(
                actor, task.task_id, task.state_revision, envelope=envelope
            )
            role = bots[task.bot_id].role_name.casefold()
            phase = (
                "research" if "research" in role else
                "review" if "review" in role else
                "deployment" if "deploy" in role else
                "building"
            )
            updated = state.evolve(
                phase=phase,
                status_note=f"{bots[task.bot_id].display_name} resumed the active project step.",
            ).validate()
            response = updated.status_note
        else:
            controlled = self.service.cancel(
                actor, task.task_id, task.state_revision, envelope=envelope
            )
            updated = state.evolve(
                phase="blocked",
                pending_message_id=None,
                handoff_bot_id=None,
                handoff_brief=None,
                status_note=(
                    "Stop requested; the exact active run is still reconciling."
                    if controlled.phase == "stopping"
                    else "The active project step was cancelled."
                ),
            ).validate()
            response = updated.status_note
        self._save_state(state, updated)
        return updated, response

    def ingress(self):
        self._authorize()
        roles, bots = self._roles()
        state = self._reconcile(self._state(), roles, bots)
        # Process an attachment-bearing follow-up after its active parent closes.
        if state.pending_message_id and state.active_task_id is None:
            with self.store.transaction() as tx:
                pending = tx.conversation_message(state.pending_message_id)
                link = tx.conversation_link(pending["message"].link_id) if pending else None
            if pending and link:
                completed = self.conversations.process(link, state.pending_message_id)
                task = self._task(completed.task_id)
                old = state
                state = state.evolve(
                    active_bot_id=task.bot_id, active_task_id=task.task_id,
                    latest_task_id=task.task_id, pending_message_id=None,
                    phase=(
                        "research" if "research" in bots[task.bot_id].role_name.casefold() else
                        "review" if "review" in bots[task.bot_id].role_name.casefold() else
                        "deployment" if "deploy" in bots[task.bot_id].role_name.casefold() else
                        "building"
                    ),
                ).validate()
                self._save_state(old, state)
        with self.store.transaction() as tx:
            status = tx.conversation_status(self.link.link_id)
        events = self.relay.messages(
            self.link, max(self.link.activated_at, status["cursor_time"] - 300)
        )
        before = (status["scan_time"], status["scan_id"]) if status["scan_id"] else None
        archive, next_page = self.relay.history_page(self.link, self.link.activated_at, before)
        events = sorted({e["id"]: e for e in events + archive}.values(),
                        key=lambda e: (e["created_at"], e["id"]))
        for event in events:
            with self.store.transaction() as tx:
                if tx.conversation_message(event["id"]) is not None:
                    continue
            files = ()
            try:
                files = reference_files(self.relay, event)
                if not event["content"].strip() or len(event["content"]) > 4096:
                    raise Rejected("conversation_message_requires_brief", 422)
                state = self._reconcile(state, roles, bots)
                intent = self._coordinator_content(event, bots)
                control = (
                    "pause" if _PAUSE.fullmatch(intent) else
                    "resume" if _RESUME.fullmatch(intent) else
                    "stop" if _STOP.fullmatch(intent) else
                    None
                )
                if control:
                    state, response = self._control(state, event, control, bots)
                    self._record_owner_event(
                        event, files=files, task_id=state.active_task_id,
                        state="project_control:" + control,
                    )
                    self._note("reply:" + event["id"], response, reply_to=event["id"])
                    continue
                if self._planning_candidate(event, state, roles, bots):
                    state = self._start_planning(state, event, files, roles, bots)
                    continue
                selected, response, addressed, selected_state = self._select(event, state, roles, bots)
                if selected_state != state:
                    self._save_state(state, selected_state)
                    state = selected_state
                if response:
                    self._record_owner_event(
                        event, files=files, task_id=state.active_task_id,
                        state="status" if _STATUS.fullmatch(intent) else "coordination",
                    )
                    self._note("reply:" + event["id"], response, reply_to=event["id"])
                    continue
                if selected is None:
                    self._record_owner_event(event, files=files, task_id=state.active_task_id)
                    self._note("reply:" + event["id"], "No assigned agent can take that step yet.", reply_to=event["id"])
                    continue
                selected_role = bots[selected.link.bot_id].role_name.casefold()
                if ("reviewer" in selected_role
                        and (_ACCEPT.search(event["content"]) or _REVIEW.search(event["content"]))):
                    if (
                        _ACCEPT.search(event["content"])
                        and state.accepted_preview_revision != state.preview_revision
                    ):
                        try:
                            accepted = accept_preview(state)
                        except Rejected:
                            self._record_owner_event(event, files=files, state="review_waiting")
                            self._note(
                                "reply:" + event["id"],
                                "The current preview revision is not recorded yet, so I cannot send it to review.",
                                reply_to=event["id"],
                            )
                            continue
                        self._save_state(state, accepted)
                        state = accepted
                    if (not state.preview_revision
                            or state.preview_revision != state.source_revision
                            or not state.preview_digest
                            or not state.preview_url
                            or not state.pull_request):
                        self._record_owner_event(event, files=files, state="review_waiting")
                        self._note(
                            "reply:" + event["id"],
                            "Review needs a current pull request and matching preview revision from Builder.",
                            reply_to=event["id"],
                        )
                        continue
                    previous = state.latest_task_id
                    if previous is None:
                        self._note("reply:" + event["id"], "There is no preview task to review.", reply_to=event["id"])
                        continue
                    with self.store.transaction() as tx:
                        tx.save_conversation_message(
                            ConversationMessage(
                                event["id"], self.link.link_id, self.link.principal_id,
                                event["content"], "buzz", event["created_at"],
                                task_id=previous, reply_to=reply_target(event),
                                state="preview_accepted" if _ACCEPT.search(event["content"]) else "review_requested",
                            ), event=event, processed=True,
                        )
                    brief = (
                        f"Review pull request {state.pull_request} at the exact recorded source and preview revision "
                        f"{state.preview_revision} (preview digest {state.preview_digest}) at {state.preview_url}. "
                        "Verify the pull request and preview correspond to that revision. "
                        "Run independent code, test, DOM and visual checks. End with READY or CHANGES_NEEDED and "
                        "a RADHOUSE_PROJECT_UPDATE report containing reviewed_revision and reviewer_verdict."
                    )
                    state = self._handoff(state, selected, previous, brief, bots)
                    continue
                if "deployer" in selected_role and _DEPLOY.search(event["content"]):
                    if (
                        state.reviewer_verdict != "READY"
                        or state.reviewed_revision != state.preview_revision
                        or state.preview_revision != state.source_revision
                    ):
                        self._record_owner_event(event, files=files, state="deployment_waiting")
                        self._note(
                            "reply:" + event["id"],
                            "Deployment is waiting for a READY review of the current revision.",
                            reply_to=event["id"],
                        )
                        continue
                    previous = state.latest_task_id
                    if previous is None:
                        self._note("reply:" + event["id"], "There is no reviewed task to deploy.", reply_to=event["id"])
                        continue
                    with self.store.transaction() as tx:
                        tx.save_conversation_message(
                            ConversationMessage(
                                event["id"], self.link.link_id, self.link.principal_id,
                                event["content"], "buzz", event["created_at"],
                                task_id=previous, reply_to=reply_target(event),
                                state="deployment_approved",
                            ), event=event, processed=True,
                        )
                    brief = (
                        f"The owner approved merge and private deployment of reviewed revision {state.reviewed_revision}. "
                        "Use the project's existing target and authority. Verify merge, deployment, health and rollback; "
                        "end with RADHOUSE_PROJECT_UPDATE containing merged_revision, deployment_url, "
                        "deployed_revision and deployment_status."
                    )
                    state = self._handoff(state, selected, previous, brief, bots)
                    continue
                parent = reply_target(event)
                message = ConversationMessage(
                    event["id"], selected.link.link_id, selected.link.principal_id,
                    event["content"], "buzz", event["created_at"],
                    reply_to=parent, files=files, addressed=addressed,
                )
                if files and state.active_task_id:
                    if state.pending_message_id is not None:
                        self._record_owner_event(
                            event, files=files, task_id=state.active_task_id,
                            state="pending_limit",
                        )
                        self._note(
                            "reply:" + event["id"],
                            "One attachment follow-up is already saved behind the active task. Wait for that handoff before sending another file set.",
                            reply_to=event["id"],
                        )
                        continue
                    with self.store.transaction() as tx:
                        tx.save_conversation_message(
                            message,
                            route=MessageRoute("start", follows_task_id=state.active_task_id),
                            event=event,
                        )
                    old = state
                    state = state.evolve(
                        pending_message_id=message.message_id,
                        status_note="Attachment feedback is saved behind the active task.",
                    ).validate()
                    self._save_state(old, state)
                    self._note(
                        "pending:" + event["id"],
                        "I saved these attachments with your feedback. They will become the next correlated step after the active task finishes.",
                        reply_to=event["id"],
                    )
                    continue
                self.conversations.receive(selected.link, message, event=event)
                completed = self.conversations.process(selected.link, message.message_id)
                task = self._task(completed.task_id) if completed.task_id else None
                if task and task.phase != "closed":
                    old = state
                    role = bots[task.bot_id].role_name.casefold()
                    phase = (
                        "research" if "research" in role else
                        "review" if "review" in role else
                        "deployment" if "deploy" in role else
                        "building"
                    )
                    state = state.evolve(
                        active_bot_id=task.bot_id, active_task_id=task.task_id,
                        latest_task_id=task.task_id, phase=phase,
                        status_note=f"{bots[task.bot_id].display_name} is working.",
                    ).validate()
                    self._save_state(old, state)
                    if not addressed:
                        self._note(
                            "coord-route:" + event["id"],
                            f"I routed this step to {bots[task.bot_id].display_name}.",
                            reply_to=event["id"], task_id=task.task_id,
                        )
            except Rejected as error:
                self._record_owner_event(event, state="rejected:" + error.code)
                self._note(
                    "reply:" + event["id"],
                    "I could not safely route that project message. The project state is preserved; open Radhouse for details.",
                    reply_to=event["id"],
                )
        with self.store.transaction() as tx:
            tx.conversation_progress(
                self.link.link_id,
                cursor=max([status["cursor_time"], *[e["created_at"] for e in events]]),
            )
            tx.conversation_scan_progress(self.link.link_id, next_page)
        return len(events)

    def egress(self):
        # Coordinator messages use the established durable signed outbox.
        return BuzzConversationCycle(self.service, self.relay, self.link).egress()

    def run(self, phase):
        try:
            count = {"ingress": self.ingress, "egress": self.egress}[phase]()
            return {"link_id": self.link.link_id, "count": count, "error_code": None}
        except Rejected as error:
            with self.store.transaction() as tx:
                tx.conversation_progress(self.link.link_id, error=error.code)
            return {"link_id": self.link.link_id, "count": 0, "error_code": error.code}
