from types import SimpleNamespace

import pytest

from radhouse.application.coordinator import Coordinator
from radhouse.channels.project_buzz import ProjectBuzzConversationCycle
from radhouse.domain.conversations import ConversationLink
from radhouse.domain.tasks import InputFile
from radhouse.domain.projects import ProjectCoordination


pytestmark = pytest.mark.postgres


class Relay:
    def __init__(self, events=()):
        self.events = list(events)

    def verify_conversation(self, _link):
        return {}

    def messages(self, _link, _since):
        return list(self.events)

    def history_page(self, _link, _since, _before=None):
        return list(self.events), None


def test_unaddressed_project_request_routes_once_to_builder_and_status_is_read_only(
    service, store, clock,
):
    now = int(clock().timestamp())
    channel = "0d84100d-9a9c-45c0-b91f-5be6074519a3"
    owner = "a" * 64
    coordinator = ConversationLink(
        "expenses-coordinator", channel, "personal-alice:alice:buzz", "alice",
        owner, "b" * 64, "bot-alpha", "personal-alice", now,
        member_pubkeys=("b" * 64, "c" * 64, "d" * 64),
        default_agent=True, coordinator=True, channel_kind="stream",
    )
    researcher = ConversationLink(
        "expenses-researcher", channel, "personal-alice:alice:buzz", "alice",
        owner, "c" * 64, "bot-alpha", "personal-alice", now,
        member_pubkeys=coordinator.member_pubkeys, default_agent=False,
        channel_kind="stream",
    )
    builder = ConversationLink(
        "expenses-builder", channel, "personal-alice:alice:buzz", "alice",
        owner, "d" * 64, "bot-beta", "personal-alice", now,
        member_pubkeys=coordinator.member_pubkeys, default_agent=False,
        channel_kind="stream",
    )
    with store.transaction() as tx:
        tx._connection.execute(
            "UPDATE channel_bindings SET subject=%s WHERE subject='alice@buzz'",
            (owner,),
        )
        tx._connection.execute(
            "UPDATE bots SET display_name='Builder',role_name='Builder' "
            "WHERE bot_id='bot-beta'"
        )
        for link in (coordinator, researcher, builder):
            tx.save_conversation_link(link)
    assignment = {
        "id": "1" * 64,
        "pubkey": owner,
        "created_at": now,
        "kind": 9,
        "tags": [["h", channel]],
        "content": "Build the Splitwise CSV import for the Expenses project.",
        "sig": "2" * 128,
    }
    relay = Relay([assignment])
    cycle = ProjectBuzzConversationCycle(
        service,
        SimpleNamespace(link=coordinator, relay=relay),
        (
            SimpleNamespace(link=researcher, relay=Relay()),
            SimpleNamespace(link=builder, relay=Relay()),
        ),
    )

    assert cycle.ingress() == 1
    assert cycle.ingress() == 1
    with store.transaction() as tx:
        tasks = tx.tasks()
        state = tx.project_coordination("personal-alice")
        assert len(tasks) == 1
        assert tasks[0].bot_id == "bot-beta"
        assert state.active_task_id == tasks[0].task_id
        assert state.phase == "building"
        assert tx.conversation_message(assignment["id"])["processed"] is True

    relay.events.append({
        **assignment,
        "id": "3" * 64,
        "created_at": now + 1,
        "content": "What is Builder up to?",
    })
    cycle.ingress()
    with store.transaction() as tx:
        assert len(tx.tasks()) == 1
        reply = tx.conversation_message("reply:" + "3" * 64)["message"]
        assert "Project status · building" in reply.content
        assert "Builder · Working" in reply.content
        assert "Needs you: nothing" in reply.content

    relay.events.append({
        **assignment,
        "id": "4" * 64,
        "created_at": now + 2,
        "tags": [["h", channel], ["mention", "c" * 64, "agent-address"]],
        "content": "@Researcher start a separate investigation",
    })
    cycle.ingress()
    with store.transaction() as tx:
        assert len(tx.tasks()) == 1
        reply = tx.conversation_message("reply:" + "4" * 64)["message"]
        assert "Builder is still working" in reply.content


def test_ambiguous_project_goal_uses_one_tools_disabled_plan_then_routes_once(
    service, store, clock, fake_work, monkeypatch,
):
    now = int(clock().timestamp())
    channel = "4d84100d-9a9c-45c0-b91f-5be6074519a3"
    owner = "a" * 64
    coordinator = ConversationLink(
        "plan-coordinator", channel, "personal-alice:alice:buzz", "alice",
        owner, "b" * 64, "bot-alpha", "personal-alice", now,
        member_pubkeys=("b" * 64, "c" * 64, "d" * 64),
        default_agent=True, coordinator=True, channel_kind="stream",
    )
    researcher = ConversationLink(
        "plan-researcher", channel, "personal-alice:alice:buzz", "alice",
        owner, "c" * 64, "bot-alpha", "personal-alice", now,
        member_pubkeys=coordinator.member_pubkeys, default_agent=False,
        channel_kind="stream",
    )
    builder = ConversationLink(
        "plan-builder", channel, "personal-alice:alice:buzz", "alice",
        owner, "d" * 64, "bot-beta", "personal-alice", now,
        member_pubkeys=coordinator.member_pubkeys, default_agent=False,
        channel_kind="stream",
    )
    with store.transaction() as tx:
        tx._connection.execute(
            "UPDATE channel_bindings SET subject=%s WHERE subject='alice@buzz'",
            (owner,),
        )
        tx._connection.execute(
            "UPDATE bots SET display_name='Researcher',role_name='Researcher' "
            "WHERE bot_id='bot-alpha'"
        )
        tx._connection.execute(
            "UPDATE bots SET display_name='Builder',role_name='Builder' "
            "WHERE bot_id='bot-beta'"
        )
        for link in (coordinator, researcher, builder):
            tx.save_conversation_link(link)
    request = {
        "id": "8" * 64,
        "pubkey": owner,
        "created_at": now,
        "kind": 9,
        "tags": [["h", channel]],
        "content": "Work out the best approach for the next Expenses iteration.",
        "sig": "9" * 128,
    }
    relay = Relay([request])
    cycle = ProjectBuzzConversationCycle(
        service,
        SimpleNamespace(link=coordinator, relay=relay),
        (
            SimpleNamespace(link=researcher, relay=Relay()),
            SimpleNamespace(link=builder, relay=Relay()),
        ),
    )
    source_file = InputFile("groups.csv", "group,amount\nGroceries,12", "text/csv")
    monkeypatch.setattr(
        "radhouse.channels.project_buzz.reference_files",
        lambda _relay, _event: (source_file,),
    )
    fake_work.result_content = (
        'RADHOUSE_COORDINATION_PLAN: {"route":"research_then_build",'
        '"summary":"Check the input, then implement the smallest useful iteration.",'
        '"clarification":null,"title":"Improve the Expenses importer"}'
    )

    assert cycle.ingress() == 1
    with store.transaction() as tx:
        tasks = tx.tasks()
        state = tx.project_coordination("personal-alice")
        assert len(tasks) == 1
        assert tasks[0].bot_id == "bot-alpha"
        assert tasks[0].disable_tools is True
        assert tasks[0].budget_remaining == 1
        assert state.phase == "planning"
        assert state.planning_task_id == tasks[0].task_id

    result = Coordinator(service, "worker-one").run_once()
    assert len(result.receipts) == 1 and result.receipts[0].outcome == "completed"
    cycle.ingress()

    with store.transaction() as tx:
        tasks = tx.tasks()
        state = tx.project_coordination("personal-alice")
        research_tasks = [
            task for task in tasks
            if task.bot_id == "bot-alpha" and not task.disable_tools
        ]
        assert len(tasks) == 2 and len(research_tasks) == 1
        assert research_tasks[0].files == (source_file,)
        assert state.phase == "research"
        assert state.active_task_id == research_tasks[0].task_id
        assert state.planning_task_id is None
        assert tx.task_title(research_tasks[0].task_id).title == "Improve the Expenses importer"
        note = tx.conversation_message("coord-plan-route:" + request["id"])["message"]
        assert "I routed the first step to Researcher" in note.content

    fake_work.result_content = "The CSV contains one two-person expense group."
    result = Coordinator(service, "worker-one").run_once()
    assert len(result.receipts) == 1 and result.receipts[0].outcome == "completed"
    cycle.ingress()

    with store.transaction() as tx:
        tasks = tx.tasks()
        state = tx.project_coordination("personal-alice")
        builder_tasks = [task for task in tasks if task.bot_id == "bot-beta"]
        assert len(tasks) == 3 and len(builder_tasks) == 1
        assert builder_tasks[0].files == (source_file,)
        assert builder_tasks[0].previous_result == fake_work.result_content
        assert state.phase == "building"
        assert state.active_task_id == builder_tasks[0].task_id


def test_new_work_with_later_review_and_deploy_steps_routes_to_builder(
    service, store, clock,
):
    now = int(clock().timestamp())
    channel = "2d84100d-9a9c-45c0-b91f-5be6074519a3"
    owner = "a" * 64
    coordinator = ConversationLink(
        "workflow-coordinator", channel, "personal-alice:alice:buzz", "alice",
        owner, "b" * 64, "bot-alpha", "personal-alice", now,
        member_pubkeys=("b" * 64, "d" * 64),
        default_agent=True, coordinator=True, channel_kind="stream",
    )
    specialists = (
        ConversationLink(
            "workflow-builder", channel, "personal-alice:alice:buzz", "alice",
            owner, "d" * 64, "bot-beta", "personal-alice", now,
            member_pubkeys=coordinator.member_pubkeys, default_agent=False,
            channel_kind="stream",
        ),
    )
    with store.transaction() as tx:
        tx._connection.execute(
            "UPDATE channel_bindings SET subject=%s WHERE subject='alice@buzz'",
            (owner,),
        )
        tx._connection.execute(
            "UPDATE bots SET display_name='Builder',role_name='Builder' "
            "WHERE bot_id='bot-beta'"
        )
        tx.save_conversation_link(coordinator)
        for link in specialists:
            tx.save_conversation_link(link)
    assignment = {
        "id": "a" * 64,
        "pubkey": owner,
        "created_at": now,
        "kind": 9,
        "tags": [["h", channel]],
        "content": (
            "Import these CSV files as two separate groups. Build this feature, "
            "then review and deploy it."
        ),
        "sig": "b" * 128,
    }
    relay = Relay([assignment])
    cycle = ProjectBuzzConversationCycle(
        service,
        SimpleNamespace(link=coordinator, relay=relay),
        tuple(SimpleNamespace(link=link, relay=Relay()) for link in specialists),
    )

    assert cycle.ingress() == 1
    with store.transaction() as tx:
        tasks = tx.tasks()
        state = tx.project_coordination("personal-alice")
        assert len(tasks) == 1
        assert tasks[0].bot_id == "bot-beta"
        assert state.phase == "building"
        reply = tx.conversation_message("reply:" + assignment["id"])
        assert "Deployment is waiting" not in reply["message"].content
        assert "Builder" in tx.conversation_message(
            "coord-route:" + assignment["id"]
        )["message"].content


def test_owner_radhouse_request_hands_current_preview_to_reviewer_once(
    service, store, clock, fake_work,
):
    now = int(clock().timestamp())
    channel = "3d84100d-9a9c-45c0-b91f-5be6074519a3"
    owner = "a" * 64
    members = ("b" * 64, "c" * 64, "d" * 64)
    def link(name, pubkey, bot_id, *, coordinator=False):
        return ConversationLink(
            name, channel, "personal-alice:alice:buzz", "alice",
            owner, pubkey, bot_id, "personal-alice", now,
            member_pubkeys=members, default_agent=coordinator,
            coordinator=coordinator, channel_kind="stream",
        )
    # The live coordinator has its own Buzz identity but shares an existing
    # specialist bot grant. The bot's display name is therefore not Radhouse.
    lead = link("review-handoff-coordinator", members[0], "bot-beta", coordinator=True)
    reviewer = link("review-handoff-reviewer", members[1], "bot-alpha")
    builder = link("review-handoff-builder", members[2], "bot-beta")
    with store.transaction() as tx:
        tx._connection.execute(
            "UPDATE channel_bindings SET subject=%s WHERE subject='alice@buzz'",
            (owner,),
        )
        tx._connection.execute(
            "UPDATE bots SET display_name='Reviewer',role_name='Reviewer' WHERE bot_id='bot-alpha'"
        )
        tx._connection.execute(
            "UPDATE bots SET display_name='Builder',role_name='Builder' WHERE bot_id='bot-beta'"
        )
        for item in (lead, reviewer, builder):
            tx.save_conversation_link(item)
    assignment = {
        "id": "1" * 64, "pubkey": owner, "created_at": now, "kind": 9,
        "tags": [["h", channel]], "content": "Build the Expenses preview.", "sig": "2" * 128,
    }
    relay = Relay([assignment])
    cycle = ProjectBuzzConversationCycle(
        service, SimpleNamespace(
            link=lead, relay=relay,
            candidate=SimpleNamespace(display_name="Radhouse"),
        ),
        tuple(SimpleNamespace(link=item, relay=Relay()) for item in (reviewer, builder)),
    )
    assert cycle.ingress() == 1
    revision = "3" * 40
    fake_work.result_content = (
        "Preview ready.\nRADHOUSE_PROJECT_UPDATE: "
        '{"repository":"Satish-s-RADHouse/Expenses","pull_request":"https://github.com/Satish-s-RADHouse/Expenses/pull/3",'
        f'"source_revision":"{revision}","preview_revision":"{revision}",'
        f'"preview_digest":"{"4" * 64}","preview_url":"https://builder-preview.runningdigitally.com/"}}'
    )
    Coordinator(service, "worker-one").run_once()
    cycle.ingress()
    with store.transaction() as tx:
        state = tx.project_coordination("personal-alice")
        assert state.phase == "preview_feedback"
        builder_task_id = state.latest_task_id
    request = {
        **assignment, "id": "5" * 64, "created_at": now + 1,
        "content": "@Radhouse Can you send the work to Reviewer",
        "tags": [["h", channel], ["p", lead.agent_pubkey]],
    }
    relay.events.append(request)
    cycle.ingress()
    cycle.ingress()
    with store.transaction() as tx:
        state = tx.project_coordination("personal-alice")
        tasks = tx.tasks()
        assert len(tasks) == 2
        assert state.phase == "review"
        assert state.active_task_id != builder_task_id
        review_task = next(task for task in tasks if task.task_id == state.active_task_id)
        assert review_task.bot_id == "bot-alpha"
        assert review_task.follows_task_id == builder_task_id
        assert tx.conversation_message(request["id"])["processed"] is True

    # A duplicate review can be cancelled after a valid READY verdict. That
    # cancelled task must not poison the owner's later deployment handoff.
    fake_work.result_content = (
        "READY for the current preview.\nRADHOUSE_PROJECT_UPDATE: "
        f'{{"reviewed_revision":"{revision}","reviewer_verdict":"READY"}}'
    )
    Coordinator(service, "worker-one").run_once()
    cycle.ingress()
    with store.transaction() as tx:
        assert tx.project_coordination("personal-alice").reviewer_verdict == "READY"
        tx._connection.execute(
            "UPDATE bots SET display_name='Deployer',role_name='Deployer' WHERE bot_id='bot-beta'"
        )
    relay.events.append({
        **request, "id": "6" * 64, "created_at": now + 2,
        "content": "@Radhouse send the current work to Reviewer again",
    })
    cycle.ingress()
    relay.events.append({
        **request, "id": "7" * 64, "created_at": now + 3,
        "content": "@Radhouse stop this work",
    })
    cycle.ingress()
    cycle.ingress()
    with store.transaction() as tx:
        state = tx.project_coordination("personal-alice")
        assert state.phase == "blocked"
        assert state.reviewer_verdict == "READY"
        assert tx.task(state.latest_task_id).outcome == "cancelled"

    relay.events.append({
        **request, "id": "8" * 64, "created_at": now + 4,
        "content": "@Radhouse can you now send it for deployment?",
    })
    cycle.ingress()
    with store.transaction() as tx:
        state = tx.project_coordination("personal-alice")
        deployed = tx.task(state.active_task_id)
        assert state.phase == "deployment"
        assert deployed.bot_id == "bot-beta"
        assert deployed.follows_task_id is None
        assert revision in deployed.brief
        assert "https://github.com/Satish-s-RADHouse/Expenses/pull/3" in deployed.brief


def test_accepted_ready_review_hands_off_one_private_release_without_owner_message(
    service, store, clock, fake_work,
):
    now = int(clock().timestamp())
    channel = "4d84100d-9a9c-45c0-b91f-5be6074519a3"
    owner = "a" * 64
    members = ("b" * 64, "c" * 64, "d" * 64)
    def link(name, pubkey, bot_id, *, coordinator=False):
        return ConversationLink(
            name, channel, "personal-alice:alice:buzz", "alice",
            owner, pubkey, bot_id, "personal-alice", now,
            member_pubkeys=members, default_agent=coordinator,
            coordinator=coordinator, channel_kind="stream",
        )
    lead = link("automatic-release-coordinator", members[0], "bot-beta", coordinator=True)
    reviewer = link("automatic-release-reviewer", members[1], "bot-alpha")
    deployer = link("automatic-release-deployer", members[2], "bot-beta")
    revision = "3" * 40
    with store.transaction() as tx:
        tx._connection.execute(
            "UPDATE channel_bindings SET subject=%s WHERE subject='alice@buzz'", (owner,),
        )
        tx._connection.execute(
            "UPDATE bots SET display_name='Reviewer',role_name='Reviewer' WHERE bot_id='bot-alpha'"
        )
        tx._connection.execute(
            "UPDATE bots SET display_name='Deployer',role_name='Deployer' WHERE bot_id='bot-beta'"
        )
        for item in (lead, reviewer, deployer):
            tx.save_conversation_link(item)
        tx.save_project_coordination(ProjectCoordination(
            "personal-alice", phase="review", repository="Satish-s-RADHouse/Expenses",
            pull_request="https://github.com/Satish-s-RADHouse/Expenses/pull/3",
            source_revision=revision, preview_revision=revision,
            preview_digest="4" * 64,
            preview_url="https://builder-preview.runningdigitally.com/",
            deployment_url="https://builder-preview.runningdigitally.com/",
            deployment_status="failed",
        ).validate(), None)
    cycle = ProjectBuzzConversationCycle(
        service, SimpleNamespace(link=lead, relay=Relay()),
        tuple(SimpleNamespace(link=item, relay=Relay()) for item in (reviewer, deployer)),
        automatic_private_release=True,
        private_deployment_url="https://expenses.deployed.runningdigitally.com/",
    )
    roles, bots = cycle._roles()
    cycle._handoff(cycle._state(), roles["reviewer"], None, "Review exact work", bots)
    fake_work.result_content = (
        "READY.\nRADHOUSE_PROJECT_UPDATE: "
        f'{{"reviewed_revision":"{revision}","reviewer_verdict":"READY"}}'
    )
    Coordinator(service, "worker-one").run_once()
    cycle.ingress()
    cycle.ingress()
    with store.transaction() as tx:
        state = tx.project_coordination("personal-alice")
        tasks = tx.tasks()
        assert state.phase == "deployment"
        assert len(tasks) == 2
        release = tx.task(state.active_task_id)
        review = next(task for task in tasks if task.task_id != release.task_id)
        assert release.bot_id == "bot-beta"
        assert release.follows_task_id == review.task_id
        assert revision in release.brief
        assert "expenses.deployed.runningdigitally.com" in release.brief
        assert state.accepted_preview_revision is None


def test_private_release_hands_builder_preview_to_reviewer_without_owner_message(
    service, store, clock, fake_work,
):
    now = int(clock().timestamp())
    channel = "5d84100d-9a9c-45c0-b91f-5be6074519a3"
    owner = "a" * 64
    members = ("b" * 64, "c" * 64, "d" * 64)
    def link(name, pubkey, bot_id, *, coordinator=False):
        return ConversationLink(
            name, channel, "personal-alice:alice:buzz", "alice",
            owner, pubkey, bot_id, "personal-alice", now,
            member_pubkeys=members, default_agent=coordinator,
            coordinator=coordinator, channel_kind="stream",
        )
    lead = link("private-review-coordinator", members[0], "bot-beta", coordinator=True)
    reviewer = link("private-review-reviewer", members[1], "bot-alpha")
    builder = link("private-review-builder", members[2], "bot-beta")
    with store.transaction() as tx:
        tx._connection.execute(
            "UPDATE channel_bindings SET subject=%s WHERE subject='alice@buzz'", (owner,),
        )
        tx._connection.execute(
            "UPDATE bots SET display_name='Reviewer',role_name='Reviewer' WHERE bot_id='bot-alpha'"
        )
        tx._connection.execute(
            "UPDATE bots SET display_name='Builder',role_name='Builder' WHERE bot_id='bot-beta'"
        )
        for item in (lead, reviewer, builder):
            tx.save_conversation_link(item)
    cycle = ProjectBuzzConversationCycle(
        service, SimpleNamespace(link=lead, relay=Relay()),
        tuple(SimpleNamespace(link=item, relay=Relay()) for item in (reviewer, builder)),
        automatic_private_release=True,
        private_deployment_url="https://expenses.deployed.runningdigitally.com/",
    )
    roles, bots = cycle._roles()
    cycle._handoff(cycle._state(), roles["builder"], None, "Build the import", bots)
    revision = "3" * 40
    fake_work.result_content = (
        "Preview ready.\nRADHOUSE_PROJECT_UPDATE: "
        '{"repository":"Satish-s-RADHouse/Expenses","pull_request":"https://github.com/Satish-s-RADHouse/Expenses/pull/3",'
        f'"source_revision":"{revision}","preview_revision":"{revision}",'
        f'"preview_digest":"{"4" * 64}","preview_url":"https://builder-preview.runningdigitally.com/"}}'
    )
    Coordinator(service, "worker-one").run_once()
    cycle.ingress()
    cycle.ingress()
    with store.transaction() as tx:
        state = tx.project_coordination("personal-alice")
        tasks = tx.tasks()
        assert len(tasks) == 2
        assert state.phase == "review"
        review = tx.task(state.active_task_id)
        assert review.bot_id == "bot-alpha"
        assert review.follows_task_id == next(task.task_id for task in tasks if task.bot_id == "bot-beta")
        assert revision in review.brief
        assert state.accepted_preview_revision is None


def test_project_pause_resume_and_stop_control_only_the_active_task(
    service, store, clock,
):
    now = int(clock().timestamp())
    channel = "1d84100d-9a9c-45c0-b91f-5be6074519a3"
    owner = "a" * 64
    coordinator = ConversationLink(
        "control-coordinator", channel, "personal-alice:alice:buzz", "alice",
        owner, "b" * 64, "bot-alpha", "personal-alice", now,
        member_pubkeys=("b" * 64, "d" * 64),
        default_agent=True, coordinator=True, channel_kind="stream",
    )
    builder = ConversationLink(
        "control-builder", channel, "personal-alice:alice:buzz", "alice",
        owner, "d" * 64, "bot-beta", "personal-alice", now,
        member_pubkeys=coordinator.member_pubkeys, default_agent=False,
        channel_kind="stream",
    )
    with store.transaction() as tx:
        tx._connection.execute(
            "UPDATE channel_bindings SET subject=%s WHERE subject='alice@buzz'",
            (owner,),
        )
        tx._connection.execute(
            "UPDATE bots SET display_name='Builder',role_name='Builder' "
            "WHERE bot_id='bot-beta'"
        )
        for link in (coordinator, builder):
            tx.save_conversation_link(link)
    assignment = {
        "id": "5" * 64, "pubkey": owner, "created_at": now, "kind": 9,
        "tags": [["h", channel]], "content": "Build the requested improvement.",
        "sig": "6" * 128,
    }
    relay = Relay([assignment])
    cycle = ProjectBuzzConversationCycle(
        service,
        SimpleNamespace(link=coordinator, relay=relay),
        (SimpleNamespace(link=builder, relay=Relay()),),
    )
    cycle.ingress()
    with store.transaction() as tx:
        task_id = tx.tasks()[0].task_id

    for offset, content in enumerate(("pause this work", "resume this work", "stop this work"), 1):
        relay.events.append({
            **assignment,
            "id": str(6 + offset) * 64,
            "created_at": now + offset,
            "content": content,
        })
        cycle.ingress()

    cycle.ingress()  # Reconcile the cancelled task into durable project state.
    with store.transaction() as tx:
        tasks = tx.tasks()
        state = tx.project_coordination("personal-alice")
        assert len(tasks) == 1 and tasks[0].task_id == task_id
        assert tasks[0].outcome == "cancelled"
        assert state.active_task_id is None
        assert state.handoff_bot_id is None
        assert state.phase == "blocked"
        assert tx.conversation_message("reply:" + "7" * 64)["message"].content == "Project work is paused."
        assert "resumed" in tx.conversation_message("reply:" + "8" * 64)["message"].content
        assert "cancelled" in tx.conversation_message("reply:" + "9" * 64)["message"].content
