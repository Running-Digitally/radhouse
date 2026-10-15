# ADR-0003: Stabilize trust boundaries while developing in public

Status: accepted owner direction; implementation and qualification tracked in the plan.

Date: 2026-10-15

## Context

Radhouse is a public source repository with an evolving product and architecture.
The owner reports that the current installation serves only the owner on a
private LAN, has no customers, and has no public ingress, including through
Cloudflare. This is an operating assumption, not a network audit or a claim
about every installation. A public source repository and an internet-accessible
runtime are different exposure decisions.

Product research may substantially change the user journeys and package
boundaries. A repository-wide cleanup before those decisions would spend effort
on code that may be replaced. Waiting for product maturity to establish trust
boundaries would compound risk and make later changes harder.

The previous SonarQube scope omitted `runtime/`, including Radhouse-owned code
for admission, browser control, credentials, terminal access and recovery.
Finding counts alone therefore do not describe the current system's risk.

## Decision

Establish a quality and security principle now: reduce real defects and debt as
far as practical, prioritizing consequences and enduring boundaries. Do not make
the smallest possible dashboard count the product objective.

First include all analyzable first-party runtime source, inventory the complete
findings, and qualify the boundaries around enabled capabilities. Fix confirmed
material defects in those boundaries before extending their authority. Continue
product discovery and unrelated product work while this bounded stage runs.
Afterward, reduce remaining debt through work on the affected code and a modest,
regular quality allocation. Architecture proposals are inputs to planning, not
permission to rewrite the application or split it into services.

Private deployment lowers exposure and urgency for some findings. It does not
excuse credential disclosure, incorrect authority, unsafe recovery, destructive
replay, private-data leaks, or a reachable severe dependency vulnerability.
Browsed pages, imported files, model output, dependencies and other LAN clients
remain relevant inputs and threats. Keep authority enforcement outside model
instructions, independent of whether a model recognizes a dangerous request.

Keep source, synthetic examples, decisions and sanitized validation public.
Keep credentials, live content, operational topology, raw security evidence and
unfixed exploit details in an appropriate private channel. Do not commit private
research conversation links or transcripts. Public availability is not a claim
of production readiness, multi-user isolation or a supported hosted service.

Use the existing SonarQube gate, profiles and new-code definition. No blanket
suppression, lowered gate, test deletion or exclusion of owned code is a remedy.
An individually verified false positive may receive an evidence-backed
disposition through the repository's separately authorized issue-review flow;
do not silently mark it fixed or accepted. Deferral must name an owner, reason,
trigger/date for review and any required containment. Unknown is not safe.

## Acceptance and escalation

The immediate stage is complete when the expanded baseline is attributable to
a merged SHA; material boundary findings have evidence-backed dispositions;
confirmed high/critical risks on enabled paths are fixed or the affected
capability is disabled; and recovery, privacy and authority checks pass for the
changed boundaries. A lower issue count alone does not satisfy this decision.

Before onboarding anyone else, adding public ingress, enabling broader tools,
introducing unattended consequential actions, changing data isolation, or
replacing an engine, reassess the threat model and qualify that changed scope.
Even a small group of trusted learning partners crosses the current owner-only
boundary. Research can continue before that qualification; onboarding cannot
borrow the owner-only assurance claim.

## Consequences and alternatives

The expanded scan may increase the count and reduce measured coverage without
any product regression. Track comparable baselines separately from scope changes.
Retain both overall and new-code findings. Test evidence must demonstrate
behavior and failure handling, not merely execute lines to raise a percentage.

An immediate zero-finding campaign would compete with product learning and
encourage low-value edits. An indefinite deferral would leave important unknowns
in the most privileged code. Bounded stabilization followed by continuous debt
reduction is the chosen middle course.

Execution: [implementation plan](../plans/2026-10-15-boundary-stabilization.md),
[security policy](../../SECURITY.md), [runtime ownership](../runtime-ownership.md),
and [ADR-0004](0004-replaceable-runtime-adapters.md).
