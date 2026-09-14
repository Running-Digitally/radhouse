"""One bounded conversation cycle alongside the existing task coordinator."""

from dataclasses import replace

from radhouse.application.conversations import Conversations
from radhouse.application.service import fingerprint
from radhouse.channels.buzz_files import reference_files
from radhouse.channels.nostr import encoded, sha256
from radhouse.domain.conversations import ConversationMessage
from radhouse.domain.tasks import Rejected


def reply_target(event):
    references = [tag for tag in event["tags"] if tag[0] == "e"]
    replies = [tag[1] for tag in references if len(tag) >= 4 and tag[3] == "reply"]
    roots = [tag[1] for tag in references if len(tag) >= 4 and tag[3] == "root"]
    if len(replies) > 1 or len(roots) > 1:
        raise Rejected("conversation_reply_ambiguous", 422)
    return next(iter(replies or roots), None)


class BuzzConversationCycle:
    def __init__(self, service, relay, link):
        self.conversations = Conversations(service)
        self.service, self.store, self.relay, self.link = (
            service,
            service.store,
            relay,
            link,
        )

    def _authorized(self):
        # Fresh relay membership and current controller authority on each
        # ingress/delivery boundary; never accept a saved membership snapshot.
        self.relay.verify_dm(self.link)
        with self.store.transaction() as tx:
            self.conversations.authorize(tx, self.link, write=True)

    def ingress(self):
        self._authorized()
        with self.store.transaction() as tx:
            status = tx.conversation_status(self.link.link_id)
        # Overlap recent reads to admit delayed events without echoing receipts.
        events = self.relay.messages(
            self.link, max(self.link.activated_at, status["cursor_time"] - 300)
        )
        # One durable archive page per cycle eventually catches arbitrarily
        # delayed events, without an unbounded full-history read on each poll.
        before = (status["scan_time"], status["scan_id"]) if status["scan_id"] else None
        archive, next_page = self.relay.history_page(
            self.link, self.link.activated_at, before
        )
        events = sorted(
            {e["id"]: e for e in events + archive}.values(),
            key=lambda e: (e["created_at"], e["id"]),
        )
        for event in events:
            with self.store.transaction() as tx:
                existing = tx.conversation_message(event["id"])
            if existing and existing["processed"]:
                continue
            self._authorized()
            if existing:
                self.conversations.process(self.link, event["id"])
                continue
            try:
                files = reference_files(self.relay, event)
                parent = reply_target(event)
                if not event["content"].strip() or len(event["content"]) > 4096:
                    raise Rejected("conversation_message_requires_brief", 422)
            except Rejected as error:
                if error.status != 422:
                    raise
                self._reject_message(event, error.code)
                continue
            message = ConversationMessage(
                event["id"],
                self.link.link_id,
                self.link.principal_id,
                event["content"],
                "buzz",
                event["created_at"],
                reply_to=parent,
                files=files,
            )
            self.conversations.receive(self.link, message, event=event)
            self.conversations.process(self.link, message.message_id)
        # Received web messages also use the same command implementation.
        with self.store.transaction() as tx:
            pending = tx.conversation_pending(self.link.link_id)
        for row in pending:
            self._authorized()
            self.conversations.process(self.link, row["message"].message_id)
        with self.store.transaction() as tx:
            self.conversations.authorize(tx, self.link)
            tx.conversation_progress(
                self.link.link_id,
                cursor=max([status["cursor_time"], *[e["created_at"] for e in events]]),
            )
            tx.conversation_scan_progress(self.link.link_id, next_page)
        return len(events)

    def _reject_message(self, event, code):
        """Retain an actionable rejection so one unsupported file cannot block a DM."""
        with self.store.transaction() as tx:
            self.conversations.authorize(tx, self.link, write=True)
            tx.save_conversation_message(
                ConversationMessage(
                    event["id"],
                    self.link.link_id,
                    self.link.principal_id,
                    event["content"],
                    "buzz",
                    event["created_at"],
                    state="rejected:" + code,
                ),
                event=event,
                processed=True,
            )
            tx.save_conversation_message(
                ConversationMessage(
                    "reply:" + event["id"],
                    self.link.link_id,
                    self.link.bot_id,
                    "I could not use that message. Send a short assignment with up to four UTF-8 text references (64 KB total), uploaded to this Buzz community. No task was started.",
                    "radhouse",
                    int(self.service._now().timestamp()),
                    reply_to=event["id"],
                    state="reply",
                ),
                processed=True,
            )

    def _task_messages(self):
        with self.store.transaction() as tx:
            self.conversations.authorize(tx, self.link)
            for task_id in tx.conversation_changed_tasks(self.link.link_id):
                task = tx.task(task_id)
                if (
                    task is None
                    or task.owner_id != self.link.principal_id
                    or task.bot_id != self.link.bot_id
                    or task.project_id != self.link.project_id
                ):
                    raise Rejected("conversation_task_denied", 403)
                # Guidance changes must not repost the completed result. Their
                # own stable identity also deduplicates reconnect/restart delivery.
                from radhouse.application.guidance import PROTOCOL, outcome_message_id, outcome_text
                controls = {"control:" + fingerprint([self.link.principal_id, message_id]): message_id
                            for message_id in tx.conversation_guidance_messages(self.link, task.task_id)}
                for receipt in task.guidance:
                    outcome = receipt.get("application_state")
                    if receipt.get("protocol") != PROTOCOL or outcome not in {"applied", "too_late", "not_applied", "unknown"}:
                        continue
                    outcome_id = outcome_message_id(task.task_id, receipt)
                    # New controls retain their source event before the runtime
                    # POST. Resolve its frozen route even if processing has not
                    # yet marked the incoming message complete. The bounded
                    # lookup above is only for older retained receipts.
                    parent = controls.get(receipt.get("id"))
                    if receipt.get("source_channel") == "buzz" and receipt.get("source_event_id"):
                        source = tx.conversation_message(receipt["source_event_id"])
                        if source is not None:
                            message, route = source["message"], source["route"]
                            if (message.link_id != self.link.link_id or message.author != self.link.principal_id
                                    or route is None or route.action != "guide" or route.task_id != task.task_id
                                    or "control:" + fingerprint([message.author, message.message_id]) != receipt["id"]):
                                raise Rejected("conversation_guidance_denied", 403)
                            parent = message.message_id
                    if tx.conversation_message(outcome_id) is None:
                        tx.save_conversation_message(ConversationMessage(
                            outcome_id, self.link.link_id, self.link.bot_id,
                            outcome_text(receipt), "radhouse", int(self.service._now().timestamp()),
                            task_id=task.task_id, state="guidance",
                            reply_to=parent,
                            task_state_revision=task.state_revision,
                        ), processed=True)
                identity = sha256(
                    encoded(
                        [
                            task.task_id,
                            task.phase,
                            task.outcome,
                            task.blockers,
                            task.result_digest,
                        ]
                    )
                )
                message_id = "task:" + identity
                existing = tx.conversation_message(message_id)
                if existing:
                    tx.save_conversation_message(
                        replace(
                            existing["message"], task_state_revision=task.state_revision
                        ),
                        processed=True,
                    )
                    continue
                text = self.conversations.describe(task)
                if task.result:
                    preview = task.result[:1200]
                    text = preview + ("\n\n[Preview — full result in Radhouse]" if len(task.result) > 1200 else "")
                    if self.service.review_links is not None:
                        text += "\n\nReview in Radhouse (sign-in required):\n" + self.service.review_links.issue(tx, self.link, task)
                tx.save_conversation_message(
                    ConversationMessage(
                        message_id,
                        self.link.link_id,
                        self.link.bot_id,
                        text,
                        "radhouse",
                        int(self.service._now().timestamp()),
                        task_id=task.task_id,
                        reply_to=tx.conversation_task_anchor(self.link, task.task_id),
                        state="result" if task.result else "progress",
                        task_state_revision=task.state_revision,
                    ),
                    processed=True,
                )

    def _publication_messages(self):
        # Publication does not change task.state_revision. Discover it separately
        # and persist one message before preparing any signed delivery.
        with self.store.transaction() as tx:
            self.conversations.authorize(tx, self.link)
            for task_id in tx.conversation_unannounced_publications(self.link.link_id):
                task = tx.task(task_id)
                if (task is None or task.owner_id != self.link.principal_id
                        or task.bot_id != self.link.bot_id or task.project_id != self.link.project_id):
                    raise Rejected("conversation_task_denied", 403)
                publication = tx.publication(task_id)
                tx.save_conversation_message(ConversationMessage(
                    "publication:" + publication.publication_id, self.link.link_id,
                    self.link.bot_id, "Reviewed in Radhouse and published to the approved audience.",
                    "radhouse", int(self.service._now().timestamp()), task_id=task_id,
                    reply_to=tx.conversation_task_anchor(self.link, task_id),
                    state="publication", task_state_revision=task.state_revision,
                ), processed=True)

    def _prepare_outbox(self):
        # Iterate history in bounded pages. Existing deliveries are retained and
        # skipped; there is no per-process cursor that could lose a message.
        with self.store.transaction() as tx:
            self.conversations.authorize(tx, self.link)
            rows = tx.conversation_undelivered_messages(self.link.link_id, limit=20)
            for row in rows:
                message = row["message"]
                if (
                    message.author == self.link.principal_id
                    and message.source == "buzz"
                ):
                    continue
                text = message.content
                if message.author == self.link.principal_id:
                    text = f"{self.link.principal_id} · via Radhouse\n\n{text}"
                    if message.files:
                        text += "\n\nReferences saved with this task: " + ", ".join(
                            file.name for file in message.files
                        )
                tags = [
                    ["h", self.link.channel_id],
                    ["radhouse-mirror", message.message_id],
                ]
                if message.task_id:
                    tags.append(["radhouse-task", message.task_id])
                if message.state == "result":
                    tags.append(["radhouse-review", message.task_id])
                if message.reply_to:
                    parent = tx.conversation_reply(self.link.link_id, message.reply_to)
                    parent_event = (
                        (
                            parent["event"]
                            or tx.conversation_event(parent["message"].message_id)
                        )
                        if parent
                        else None
                    )
                    if parent is not None and parent_event is None:
                        # A web message gets its signed mirror only after its
                        # command finishes. Never freeze an unthreaded child in
                        # this window; a later cycle uses the exact parent event.
                        continue
                    if parent_event:
                        root = next(
                            (
                                t[1]
                                for t in parent_event["tags"]
                                if len(t) >= 4 and t[0] == "e" and t[3] == "root"
                            ),
                            parent_event["id"],
                        )
                        tags.extend(
                            [
                                ["e", root, "", "root"],
                                ["e", parent_event["id"], "", "reply"],
                            ]
                        )
                event = self.relay.event(9, text, tags)
                tx.conversation_enqueue(
                    message.message_id, self.link.link_id, message.message_id, event
                )

    def egress(self):
        self._authorized()
        self._task_messages()
        self._publication_messages()
        self._prepare_outbox()
        with self.store.transaction() as tx:
            pending = tx.conversation_outgoing(self.link.link_id)
        delivered = 0
        for delivery in pending:
            self._authorized()
            try:
                self.relay.publish(delivery["event"])
            except Rejected as error:
                with self.store.transaction() as tx:
                    tx.conversation_acknowledge(
                        delivery["delivery_key"], error=error.code
                    )
                raise
            with self.store.transaction() as tx:
                tx.conversation_acknowledge(delivery["delivery_key"])
            delivered += 1
        return delivered

    def run(self, phase):
        try:
            count = {"ingress": self.ingress, "egress": self.egress}[phase]()
            return {"link_id": self.link.link_id, "count": count, "error_code": None}
        except Rejected as error:
            with self.store.transaction() as tx:
                tx.conversation_progress(self.link.link_id, error=error.code)
            return {"link_id": self.link.link_id, "count": 0, "error_code": error.code}
