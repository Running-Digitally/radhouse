# VS1-B: one useful task through Radhouse and Buzz

VS1-B turns the proven controller contracts and qualified Hermes boundary into
one usable operator journey. A person starts a bounded research task in the
Radhouse work home, follows that same task in Buzz, receives one cited artifact,
and completes the exact protected review from either surface. Radhouse remains
the sole task, permission, budget, audience, and publication authority.

This milestone is delivered in three end-to-end increments. Each increment must
leave the previous one usable and must preserve one task identity across process
restart, channel reconnect, and the currently served model behind the selected
provider binding.

## Increment A: durable Hermes task execution

**Implementation status:** the public controller, PostgreSQL fixture schema, and
Hermes adapter now implement this increment. The normal task path receives its
result from `AgentWorkPort`; `OperationsPort` remains separate for future
mediated effects. No live deployment or inference request is implied by these
tests.

The original VS0 service separated `RuntimePort.start_or_attach()` from an
`OperationsPort` that fabricates the final report. That separation was useful for
testing an uncertain external effect, but a live Hermes run both executes the
assignment and produces its result. Treating the Hermes result as a second
operation would require an in-memory run map or a duplicate source of task truth.

Replace that live path with one `AgentWorkPort` contract:

```python
@dataclass(frozen=True)
class RuntimeDispatch:
    run_id: str
    session_id: str
    provider_binding: str
    runtime_revision: str
    submitted_at: datetime
    retention_until: datetime

@dataclass(frozen=True)
class RuntimeResult:
    state: Literal["running", "completed", "failed", "cancelled", "unknown"]
    content: str | None = None

class AgentWorkPort(Protocol):
    def capabilities(self) -> RuntimeCapabilities: ...
    def start_or_attach(
        self, task: Task, attempt: Attempt, dispatch_key: str
    ) -> RuntimeDispatch: ...
    def result(self, dispatch: RuntimeDispatch) -> RuntimeResult: ...
    def stop(self, dispatch: RuntimeDispatch) -> bool: ...
```

Radhouse PostgreSQL owns the dispatch row. It stores the task and attempt IDs,
Hermes run and session IDs, dispatch key and request digest, runtime/config
revision, provider binding, submission time, and the advertised idempotency
retention limit. The controller commits the prepared attempt before contacting
Hermes and commits the returned run ID before polling it. A lost start response
may repeat the identical Hermes request with the same dispatch key only while the
retention contract is still valid. After that boundary, or when Hermes cannot
prove the original run, the task needs attention; Radhouse does not create a new
run automatically.

The Hermes adapter uses the authenticated Runs API with proxy inheritance
disabled, a fixed endpoint supplied by the private deployment overlay, finite
connect/read/deadline limits, one selected bot profile, and no provider or model
override. The bot's Hermes profile contains the stable `nemo-chat` style binding
selected for that deployment; the Runs API request carries no physical model or
provider field. The provider capability adapter records the served revision
separately before admission and after an operator model change.
Plain HTTP is accepted only on an IP loopback origin; cross-machine deployments
must terminate HTTPS or provide an explicitly managed local tunnel.

`OperationsPort` remains available for later mediated service effects, where an
effect has its own idempotency and lookup contract. It no longer manufactures
the normal agent result.

Acceptance for increment A:

- identical dispatch retry attaches to the original Hermes run;
- changed payload with the same dispatch key is rejected;
- controller restart reuses the PostgreSQL dispatch row;
- missing or expired Hermes evidence becomes `operation_unknown` without a new
  model request;
- stop targets only the recorded run and leaves independent work running;
- completion stores at most one bounded result and closes one attempt; and
- the model can change behind the stable provider binding without changing the
  task, bot, workspace, session, or dispatch identity.

The implemented tests cover all seven conditions, including a hard controller
exit after runtime admission, retention expiry without reattachment, exact-run
cancellation after a lost start reply, and an independent running sibling. The
canonical `scripts/vs0.py verify` path remains the reproducible release check.

## Increment B: the operator work home

Add a small TypeScript interface backed by the existing FastAPI application.
The first screen contains assigned agents, current work, blocked/needs-attention
states, and one prominent **Start a task** action. The task view shows its project,
agent, audience, provider binding, progress events, result, and exact review
scope. It exposes pause, resume, cancel, prepare-review, and publish only when the
server says the current principal may use them.

The interface does not encode permissions. FastAPI authenticates the person and
rechecks current role, bot grant, project membership, channel binding, assurance,
task revision, artifact digest, and audience for every command. The private pilot
may bind its selected Authentik deployment; public development uses a synthetic
OIDC issuer and contains no deployment hostname, client secret, or user data.

Use a small vanilla TypeScript client and generated/checked response types before
adding a UI framework. This keeps the first operator proof easy to inspect and
avoids selecting a long-term component system before the work flow is tested.

Acceptance for increment B includes an unfamiliar operator completing the flow
without a terminal or setup manual, a viewer seeing no write controls, clear
explanations for unavailable actions, reconnect without duplicate submission,
and protected review failure when assurance, revision, content, or audience has
changed.

## Increment C: real Buzz parity

The Buzz adapter converts a verified signed event and an active conversation/key
binding into the same application commands used by the work home. It records the
Buzz event ID as the delivery identity, rejects mirrors and stale bindings, and
delivers Radhouse task events back to the room with a durable delivery receipt.
It never calls Hermes directly.

Native protected review in Buzz displays the exact task, artifact digest,
audience, and expiry. The signed Buzz key must already be bound to the currently
authenticated Radhouse person, and the commit still requires fresh human
assurance and all ordinary Radhouse authorization checks. A reaction or ordinary
chat reply is not an approval.

Acceptance for increment C runs the same task in both directions: start in
Radhouse and review in Buzz, then start in Buzz and review in Radhouse. Duplicate,
late, mirrored, restored, and revoked events create no second task, model call,
publication, or permission. A Buzz outage delays delivery but does not cancel or
repeat admitted agent work.

## Affected code and verification order

| Increment | Primary code | Tests |
| --- | --- | --- |
| A | `domain/tasks.py`, `application/ports.py`, `application/service.py`, PostgreSQL migration/store, `integrations/hermes.py` | fake Runs API, PostgreSQL restart/recovery, adapter timeouts, stop isolation, provider-switch continuity |
| B | work-home/query API, OIDC authentication adapter, `web/` TypeScript client | API authorization, browser-level operator/viewer journeys, reconnect and stale-review cases |
| C | `channels/buzz.py`, binding and delivery storage, native Buzz review component | signed-event fixtures followed by the pinned real relay/client, cross-surface recovery and revocation |

Implement and review in that order. Increment A fixes the task/runtime ownership
contract before a UI or relay depends on it. Increment B proves the core remains
usable without Buzz. Increment C adds the accepted interchangeable operator
surface without creating another execution or policy owner.

## Deployment boundary

Public code and tests use synthetic names and endpoints. The private overlay owns
host identities, addresses, credentials, TLS origins, selected Authentik/Buzz
instances, runtime hashes, network grants, backup evidence, and live request
budgets. Connecting or deploying these increments is a separate admitted change;
passing public tests does not authorize a model switch, network rule, account,
listener, or retained user workload.
