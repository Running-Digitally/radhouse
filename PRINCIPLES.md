# Product and security principles

These are design commitments for Radhouse. The implementation and its security
properties are not yet qualified; this document is not a claim that a completed
system already enforces them.

## Amplify capability while preserving human agency

Agents should help people explore, create, and accomplish useful work. People
set the purpose and retain consequential decisions. Agents complete assigned
work, report results, and suggest follow-ups; suggestions do not authorize new
work or wider access.

## Make the first useful action obvious

**The best user manual is no user manual.** The interface should explain what a
person can do, what an agent is doing, and what needs attention. An operator
should be able to use an assigned agent without knowing how to administer VMs,
configure identity providers, or maintain model servers.

Administrators manage infrastructure, allocation, and grants. Operators work
with assigned agents and request additional capacity or access. Viewers have
explicitly scoped read-only access.

Make work context, audience, and bot access understandable before work starts
and whenever a boundary changes. Selected task inputs do not describe everything
a persistent bot can access or remember. Names and themes are editable labels;
they must not alter identity, grants, or the truth of a boundary indicator.
See [boundary experience](docs/boundary-experience.md) and
[naming preferences](docs/naming-preferences.md).

## Be flexible but opinionated

Ship a clear recommended setup, useful defaults, and a limited set of qualified
alternatives. Expose adaptation through documented configuration schemas and
component adapters. Test configuration and installation paths with synthetic
fixtures and private overlays using the same contracts as public examples.

An advanced option must explain which guarantees change. Unsupported
combinations must be refused clearly. There is no blanket switch that silently
removes role, assignment, or grant enforcement.

## Treat agent computers as untrusted compute

Persistent agent environments may contain software the platform does not trust.
Enforce isolation, service permissions, and resource limits outside the agent's
instructions. Installing software inside an agent VM must not grant access to
the host, another agent's private workspace, or infrastructure credentials.

VM isolation is one layer. Network paths, credential custody, browsers, shared
services, and control-plane authority need explicit boundaries of their own.

## Begin with the least access needed

Grants should identify the resource, allowed operations, scope, and revocation
behavior. Access to one resource does not imply access to similar resources.
Read permission does not imply write or send permission.

For example, a future private-email integration could start with selected
read-only material. Broader mailbox access and sending would be separate
decisions. Version 1.0 plans optional receive-only bot mail; it does not start
with broad access to a person's existing inbox or calendar.

Trust can inform a person's decision to widen a grant. An agent, its seniority,
or its supervisor cannot promote itself into additional permissions.

## Make credential custody explicit

GitHub access is mediated by default so the agent does not receive the upstream
credential. A separately granted advanced mode may expose a direct scoped token
inside the agent VM and therefore has different guarantees.

Software inside that VM may obtain an exposed token. Pausing the VM does not
revoke a copied token. The design must address upstream revocation and must not
silently fall back from mediation to direct credentials.

## Keep private work private by default

An agent's application content is private by default. Sharing and supervised
mode are explicit and visible. Infrastructure administrator power is a separate
reality from routine permission to read private content in the application.

Shared project membership permits access to released project material, not
every member's private history. Publication from private work requires a human
to review the exact content and audience.

## Supervise with limited evidence and authority

Security-event visibility covers all agents. Optional private review is enabled
per agent: a scoped reviewer examines selected content within that privacy
boundary and supplies limited findings to a central supervisor.

For security incidents, the supervisor warns and recommends. Authorized humans
decide intervention. A finding does not authorize automatic pauses, quarantine,
or grant changes. Existing deterministic permission and resource limits still
enforce directly. Review findings can be wrong and must not be presented as
complete protection.

The supervisor also owns update checks and maintenance coordination. The default
is automatic weekly OS updates and planned guest restarts under a disclosed
administrator-managed policy, with advance notice and verified work preservation
before installation. Exact plans and scoped authorization are enforced outside
the model. The policy for work that cannot checkpoint by the deadline remains
open. An approved maintenance restart does not grant general incident-response
power. Upstream update text,
bot-installed software, and a supervisor's own recommendation cannot authorize
new privileges. Preserve work and qualify recovery, artifact trust, compatibility,
and running versions. See the [supervisor contract](docs/security-supervisor.md).

## Treat network access as a data-release decision

Public research agents may follow public leads within their granted access.
Private-data workloads default to restricted outbound access. Broader browsing
requires an explicit administrator grant and a clear explanation of its limits.

A domain allowlist alone does not prevent disclosure through a permitted
request. Qualification must consider request contents, tool operations, direct
credential access, and combinations of profiles. Warnings cannot guarantee that
private information stays inside a broadly connected agent environment.

## Let agents coordinate without acquiring authority

Agents may delegate bounded subtasks to existing project agents. Owners may
shape reporting lines, and agents may organize their collaboration within
admitted work. A lead coordinates assignments, results, and progress; humans
retain cancellation and priority changes.

Delegated work uses only the recipient's grants and released context, within
shared budgets. Reporting lines do not create agents, change permissions, or
grant access to private histories. People configure schedules and their limits;
agents may suggest routines but cannot enable or expand them.

## Preserve context and tell the truth about execution

Agent identity, files, memory, and assignments should survive qualified runtime
and model changes. The operator selects the inference provider. A supported
service-following route may track the model served behind its stable alias,
without silently changing providers.

Record the model actually used and expose compatibility or recovery failures.
Do not replay side-effecting actions blindly after interruptions. Background
work should queue behind interactive work according to explicit resource policy.

## Make claims inspectable

Provide useful telemetry, logs, and analytics within the installation. Scope
access to evidence, minimize private content at collection, and disclose missing
or stale coverage. Security and maintenance receipts must not depend on a
worker's editable logs. No product telemetry leaves the installation by default;
external destinations require an explicit configuration and data-access decision.
See the [observability contract](docs/observability.md).

Separate intended behavior from measured capability. Release checks must cover
permission denial, recovery, revocation, supported deployment paths, and useful
end-to-end work. A successful model response or a convincing demo is not proof
of the surrounding boundaries.

Public examples and tests use generic, synthetic data. Each installation owns
its private configuration, credentials, and user data outside this repository.
