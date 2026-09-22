"""Enroll only an operator-configured agent, using its owner's native signature."""

from dataclasses import asdict, replace
import json
from uuid import UUID

from coincurve import PublicKeyXOnly

from radhouse.channels.buzz_conversations import BuzzConversationCycle
from radhouse.channels.nostr import sha256, verify_event
from radhouse.domain.access import require_access, require_assurance
from radhouse.domain.conversations import ConversationLink
from radhouse.domain.tasks import Rejected


def agent_profile_events(relay, bot, attestation):
    """Build the standard Buzz profile for the configured Radhouse bot role."""
    role = bot.role_name.strip() or "Agent"
    normalized_role = "-".join(role.lower().split())[:64] or "agent"
    # Preserve the established Researcher wire value while allowing another
    # configured role to advertise its own standard capability.
    capability = {"researcher": "research"}.get(normalized_role, normalized_role)
    return [
        relay.event(
            0,
            json.dumps(
                {
                    "name": bot.display_name,
                    "display_name": bot.display_name,
                    "about": (
                        f"Your Radhouse {role}. Assign work here and keep its "
                        "progress, references and results together."
                    ),
                }
            ),
            [attestation],
        ),
        relay.event(
            10100,
            json.dumps(
                {
                    "name": bot.display_name,
                    "agent_type": "agent",
                    "channel_add_policy": "owner_only",
                    "capabilities": [capability],
                    "channels": [],
                    "status": "online",
                }
            ),
        ),
    ]


def verify_owner_attestation(value, owner, agent):
    if (
        not isinstance(value, list)
        or len(value) != 4
        or value[:3] != ["auth", owner, ""]
        or not isinstance(value[3], str)
    ):
        raise Rejected("buzz_agent_attestation_denied", 403)
    try:
        signature = bytes.fromhex(value[3])
        message = bytes.fromhex(sha256(f"nostr:agent-auth:{agent}:".encode()))
        valid = len(signature) == 64 and PublicKeyXOnly(bytes.fromhex(owner)).verify(
            signature, message
        )
    except ValueError:
        valid = False
    if not valid:
        raise Rejected("buzz_agent_attestation_denied", 403)


class BuzzEnrollment:
    def __init__(self, service, candidates):
        self.service = service
        self.candidates = candidates

    def _authorize(self, tx, actor, envelope, candidate, *, assure=False):
        if (
            not candidate.active
            or actor.channel != "buzz"
            or actor.principal_id != candidate.principal_id
            or actor.subject != candidate.owner_pubkey
        ):
            raise Rejected("buzz_agent_candidate_denied", 403)
        self.service._binding(tx, actor, envelope, candidate.project_id)
        if (
            envelope.conversation_id != candidate.conversation_id
            or envelope.binding_revision != candidate.binding_revision
        ):
            raise Rejected("binding_denied", 403)
        require_access(
            tx.access(actor.principal_id),
            candidate.bot_id,
            candidate.project_id,
            write=True,
        )
        if assure:
            require_assurance(actor, self.service._now())
        bot = next(
            (
                bot
                for bot in tx.bots(actor.principal_id)
                if bot.bot_id == candidate.bot_id
            ),
            None,
        )
        if bot is None:
            raise Rejected("bot_unavailable", 409)
        return bot

    def list(self, actor, envelope):
        result = []
        with self.service.store.transaction() as tx:
            for configured in self.candidates:
                try:
                    bot = self._authorize(tx, actor, envelope, configured.candidate)
                except Rejected as error:
                    if error.status == 403:
                        continue
                    raise
                saved = tx.conversation_enrollment(configured.candidate.link_id)
                link = tx.conversation_link(configured.candidate.link_id)
                bot = configured.profile(bot)
                result.append(
                    {
                        "link_id": configured.candidate.link_id,
                        "agent_pubkey": configured.relay.pubkey,
                        "owner_pubkey": actor.subject,
                        "display_name": bot.display_name,
                        "channel_id": link.channel_id if link else None,
                        "ready": bool(saved and saved["ready"]),
                    }
                )
        return result

    def enroll(self, actor, envelope, link_id, channel_id, attestation):
        configured = next(
            (item for item in self.candidates if item.candidate.link_id == link_id),
            None,
        )
        if configured is None:
            raise Rejected("buzz_agent_candidate_denied", 403)
        candidate, relay = configured.candidate, configured.relay
        try:
            if str(UUID(channel_id)) != channel_id:
                raise ValueError()
        except ValueError:
            raise Rejected("buzz_agent_channel_denied", 422) from None
        with self.service.store.transaction() as tx:
            bot = configured.profile(
                self._authorize(tx, actor, envelope, candidate, assure=True)
            )
            previous = tx.conversation_link(link_id)
            saved = tx.conversation_enrollment(link_id)
        if candidate.channel_id is not None and channel_id != candidate.channel_id:
            raise Rejected("buzz_agent_channel_denied", 403)
        verify_owner_attestation(
            attestation, candidate.owner_pubkey, candidate.agent_pubkey
        )
        relay.owner_attestation = attestation
        link = ConversationLink(
            link_id=candidate.link_id,
            channel_id=channel_id,
            conversation_id=candidate.conversation_id,
            principal_id=candidate.principal_id,
            owner_pubkey=candidate.owner_pubkey,
            agent_pubkey=candidate.agent_pubkey,
            bot_id=candidate.bot_id,
            project_id=candidate.project_id,
            activated_at=candidate.activated_at
            or int(self.service._now().timestamp()),
            binding_revision=candidate.binding_revision,
            active=candidate.active,
            member_pubkeys=configured.member_pubkeys,
            default_agent=configured.default_agent,
            coordinator=configured.coordinator,
            channel_kind=configured.channel_kind,
        )
        if previous:
            if (
                not configured.matches(previous)
                or previous.channel_id != channel_id
                or saved is None
            ):
                raise Rejected("buzz_agent_enrollment_conflict", 409)
            link = previous
        relay.verify_conversation(link)
        directory = relay.query(
            [
                {
                    "kinds": [30177],
                    "authors": [candidate.owner_pubkey],
                    "#d": [candidate.agent_pubkey],
                    "limit": 1,
                }
            ]
        )
        if len(directory) != 1:
            raise Rejected("buzz_agent_directory_unavailable", 409)
        event = verify_event(directory[0], 30177)
        try:
            content = json.loads(event["content"])
        except ValueError:
            content = None
        directory_keys = {"name", "parallelism", "respond_to"}
        if isinstance(content, dict) and "persona_id" in content:
            directory_keys.add("persona_id")
            try:
                UUID(content["persona_id"])
            except (TypeError, ValueError, AttributeError):
                content = None
        if (
            event["pubkey"] != candidate.owner_pubkey
            or event["tags"] != [["d", candidate.agent_pubkey]]
            or not isinstance(content, dict)
            or set(content) != directory_keys
            or content.get("name") != bot.display_name
            or content.get("respond_to") != "owner-only"
            or not isinstance(content.get("parallelism"), int)
            or isinstance(content.get("parallelism"), bool)
            or not 1 <= content["parallelism"] <= 10
        ):
            raise Rejected("buzz_agent_directory_denied", 403)
        with self.service.store.transaction() as tx:
            self._authorize(tx, actor, envelope, candidate, assure=True)
            tx.save_conversation_link(link)
            saved = tx.conversation_enrollment(link_id)
            if saved is None:
                saved = {
                    "ready": False,
                    "auth_tag": attestation,
                    "events": agent_profile_events(relay, bot, attestation),
                }
                tx.save_conversation_enrollment(link_id, saved)
        relay.owner_attestation = saved["auth_tag"]
        for event in saved["events"]:
            relay.publish(event)
        relay.verify_conversation(link)
        with self.service.store.transaction() as tx:
            self._authorize(tx, actor, envelope, candidate, assure=True)
            tx.save_conversation_enrollment(link_id, {**saved, "ready": True})
        return {
            "link_id": link_id,
            "channel_id": channel_id,
            "agent_pubkey": relay.pubkey,
            "ready": True,
        }


class ConfiguredBuzzConversation:
    def __init__(
        self,
        service,
        relay,
        candidate,
        *,
        member_pubkeys=None,
        default_agent=True,
        coordinator=False,
        channel_kind="dm",
    ):
        self.service, self.relay, self.candidate = service, relay, candidate
        # Keep the original compact snapshot for ordinary two-person DMs.
        # Explicit membership is needed only when several agents share a
        # project conversation.
        self.member_pubkeys = tuple(sorted(member_pubkeys or ()))
        self.default_agent = default_agent
        self.coordinator = coordinator
        self.channel_kind = channel_kind
        self.project_members = ()

    def profile(self, bot):
        name = self.candidate.display_name if self.coordinator else None
        return replace(
            bot,
            display_name=name or bot.display_name,
            role_name="Project coordinator" if self.coordinator else bot.role_name,
        )

    def matches(self, link):
        values = asdict(link)
        return (
            self.candidate.channel_id is None
            or self.candidate.channel_id == link.channel_id
        ) and all(
            values[field] == getattr(self.candidate, field)
            for field in (
                "link_id",
                "conversation_id",
                "principal_id",
                "owner_pubkey",
                "agent_pubkey",
                "bot_id",
                "project_id",
                "binding_revision",
                "active",
            )
        ) and (
            tuple(sorted(link.member_pubkeys or (link.agent_pubkey,)))
            == tuple(sorted(self.member_pubkeys or (link.agent_pubkey,)))
            and link.default_agent == self.default_agent
            and link.coordinator == self.coordinator
            and link.channel_kind == self.channel_kind
        )

    def run(self, phase):
        with self.service.store.transaction() as tx:
            link = tx.conversation_link(self.candidate.link_id)
            enrollment = tx.conversation_enrollment(self.candidate.link_id)
        if link is None or not enrollment or not enrollment["ready"]:
            return {
                "link_id": self.candidate.link_id,
                "count": 0,
                "error_code": None,
                "enrollment": "pending",
            }
        if (
            not self.matches(link)
            or self.candidate.channel_id is not None
            and self.candidate.channel_id != link.channel_id
        ):
            return {
                "link_id": self.candidate.link_id,
                "count": 0,
                "error_code": "buzz_agent_enrollment_conflict",
            }
        try:
            verify_owner_attestation(
                enrollment["auth_tag"], link.owner_pubkey, link.agent_pubkey
            )
        except Rejected as error:
            with self.service.store.transaction() as tx:
                tx.conversation_progress(link.link_id, error=error.code)
            return {"link_id": link.link_id, "count": 0, "error_code": error.code}
        self.relay.owner_attestation = enrollment["auth_tag"]
        if self.coordinator:
            from types import SimpleNamespace
            from radhouse.channels.project_buzz import ProjectBuzzConversationCycle
            members = []
            for configured in self.project_members:
                if configured.coordinator:
                    continue
                with self.service.store.transaction() as tx:
                    member_link = tx.conversation_link(configured.candidate.link_id)
                    member_enrollment = tx.conversation_enrollment(configured.candidate.link_id)
                if (
                    member_link is None
                    or not member_enrollment
                    or not member_enrollment["ready"]
                    or not configured.matches(member_link)
                ):
                    continue
                try:
                    verify_owner_attestation(
                        member_enrollment["auth_tag"],
                        member_link.owner_pubkey,
                        member_link.agent_pubkey,
                    )
                except Rejected:
                    continue
                configured.relay.owner_attestation = member_enrollment["auth_tag"]
                members.append(SimpleNamespace(link=member_link, relay=configured.relay))
            return ProjectBuzzConversationCycle(
                self.service,
                SimpleNamespace(link=link, relay=self.relay),
                tuple(members),
            ).run(phase)
        return BuzzConversationCycle(self.service, self.relay, link).run(phase)
