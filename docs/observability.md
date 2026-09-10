# Telemetry, logs, and analytics

Status: accepted version 1.0 responsibility; collection, access, and storage
details below are proposed design. Updated: 2026-09-10. No collection is deployed.

Observability should answer three everyday questions: **What is my bot doing?**
**Is the installation healthy?** **What happened, and can we recover?** The same
trusted evidence should support work progress, security supervision, maintenance,
and aggregate analytics without creating a second copy of everyone's private work.

## Information with a purpose

| Information | Purpose and examples | Visibility |
| --- | --- | --- |
| Work progress | Queued, running, waiting for input, blocked, finished; task/run timeline and outcome links | Assigned operator and explicitly authorized collaborators/viewers |
| Proactive-assignment coverage | Last successful review, reviewed-through source position, backlog, admitted/throttled occurrences, deduplicated findings, delivery state, and explicit usefulness feedback | Operators see their assignment's coverage and briefings; administrators receive bounded operational evidence without private message content |
| Operational metrics | Queue delay, runtime/tool latency, resource pressure, capacity, errors, last successful check, model actually served | Fleet aggregates for administrators; scoped workload detail for operators |
| Diagnostic logs and traces | Correlate admission, inference, tool operations, delegation, and adapter failures to find a cause | Role- and resource-scoped; privacy-safe fields by default |
| Security and audit events | Actor, attempted operation, allow/deny outcome, grant/policy revision, sharing approval, evidence reference | Disclosed, narrowly scoped oversight; private payloads remain separate |
| Maintenance evidence | Installed/running versions, exact plan and admitting policy/approver, occurrence/deadline, checkpoint readiness, forced stops, possible transient-work loss, uncertain actions, health checks, overdue updates and recovery | Administrators; affected operators see availability and their work's recovery |
| Backup capacity and freshness | Requested/admitted recovery target; policy/evidence revision; last usable capture age; actual used/reserved bytes; cleanup backlog; blocked writes; integrity and restore-test status | Administrators receive storage/qualification detail; operators see scoped protection status and missed targets |
| Analytics | Completion and failure rates, wait times, bottlenecks, resource use, intervention rates, and human feedback | Scoped personal/project views and appropriately aggregated fleet views |

Keep task content in its existing private/project stores. A task conversation is
not automatically a diagnostic log. Logs should refer to authorized evidence
instead of duplicating prompts, responses, files, terminal output, or browser
history. Feedback is evidence about a particular result; completion rate alone
does not establish quality. Do not turn uncertain supervisor labels into an
authoritative “trust score” that automatically widens access.

## Correlate work without expanding access

Use stable bot/project/task/run identifiers and an operation/trace identifier
to follow one assignment through its subtasks and maintenance interruptions.
Record the actual inference provider/model/version when available; otherwise
record unknown. A retry is an attempt within the same work, not a new success.
State metric definitions and denominators so retries, cancellations, waiting
for people, and failures are distinguishable.

Identifiers and timestamps are sensitive metadata too. Trace identifiers grant
no access. Apply authorization to search, log tailing, dashboards, downloads,
and deep links, not just the page that contains a link. Restrict high-detail
diagnostics to permitted targets with a visible reason and expiry. Never enable
raw private-content capture automatically because a security alert fired.

Keep metric dimensions bounded; do not put prompt text, filenames, URLs, or an
ever-growing task-ID set into metric labels. Detailed correlations belong in
scoped event records. Show units, time ranges, sample coverage, and freshness.
Do not report inference charges when the local server only provides usage;
label any estimated resource cost and its assumptions separately.

## Trusted evidence and graceful degradation

Write important admission, authorization, publication, and maintenance receipts
outside worker-editable storage. Worker logs are useful diagnostic input, but a
compromised worker can omit or forge them. Authenticate event sources, distinguish
source time from receipt time, handle duplicates, and expose dropped events.
External storage improves tamper resistance; it is not immutable against the
installation's privileged administrator.

Sampling may reduce diagnostic trace volume. Required authorization and change
receipts must not be silently sampled away. If a protected operation cannot
retain its required receipt, stop admission of that operation and show why.
An analytics outage should not unnecessarily stop unrelated local work; hard
permission/resource enforcement must not depend on an LLM, dashboard, or metrics
backend being available.

Apply queue, disk, and retention limits to telemetry itself. A noisy bot must
not exhaust shared storage or erase the only recovery evidence. Required audit
records need an explicit retention policy and an observable capacity threshold;
ordinary debug output can have a shorter expiry. Define bounded defaults and
deletion behavior before release, including snapshots and backups that retain
older copies. Empty or stale telemetry means **unknown**, not healthy.

## Local by default

Store telemetry within the installation by default. Do not send product usage,
private traces, or crash content to Running Digitally or a third-party analytics
service by default. An administrator can configure a compatible external backend
only through an explicit destination, content-scope, and credential decision.
Outbound support bundles need a preview and the normal content/audience approval;
an administrator's infrastructure role does not authorize exporting another
person's unshared content.

Prefer structured allowlisted fields and collection-time minimization. Exclude
credentials, authorization headers, cookies, query strings, and raw content from
routine capture. Redaction is additional protection, not proof that arbitrary
logs contain no secrets. Expose privacy-safe incident categories to administrators
and keep sensitive evidence behind its original audience. In small installations,
aggregates can identify a person's activity; disclose the oversight signals and
avoid presenting detailed per-person behavior as anonymous.

## Fit the first release

Instrument the existing controller and adapters once; use that evidence for the
work UI and supervisor. A useful built-in status, event, and maintenance view is
required. Prefer a compatible structured export over requiring every small
installation to operate several additional monitoring services. Backend choice,
retention defaults, schemas, and resource sizing remain architecture decisions.

OpenTelemetry distinguishes metrics, logs, and traces, and documents controls for
handling sensitive telemetry. Borrow those interoperable signal concepts and
data-minimization practices; no particular collector or backend is selected or
claimed to enforce Radhouse authorization yet.
[OpenTelemetry signals](https://opentelemetry.io/docs/concepts/signals/),
[handling sensitive data](https://opentelemetry.io/docs/security/handling-sensitive-data/).

## Qualification examples

Follow a synthetic task from admission through inference, delegated work, result,
and an update interruption. Explain its delay and actual outcome without opening
private content. Test unauthorized search/tailing/exports, malicious log fields,
token redaction, worker event forgery, duplicate retries, missing metrics, clock
skew, disk pressure, and retention expiry. Required operations must refuse missing
audit evidence while unaffected work remains usable. Compare metric totals to
known synthetic events and verify that no default outbound telemetry leaves the
installation.

Related: [security supervisor](security-supervisor.md),
[boundary experience](boundary-experience.md), and [work model](work-model.md).
