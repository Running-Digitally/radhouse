# Ongoing follow-up for confirmed commitments

Status: backend deployed, confirmed follow-up active and both owner phone builds
published; first scheduled private review and device acceptance are tracked below. Extends the
[accepted pilot](2026-11-02-native-proactive-assistance.md) under the owner's
3 November instruction to keep following confirmed commitments within the same
security boundaries.

## Behavior and native capability

Reuse the existing pinned Hermes hourly no-agent cron job and bounded AIAgent
worker. Hermes owns wakeups, recovery and execution; Radhouse owns commitment
state, authorized evidence, attention decisions and authenticated delivery. The
[native cron guide](https://github.com/NousResearch/hermes-agent/blob/818c13be1dc4fd28987e1e881a9408224afd4535/website/docs/user-guide/features/cron.md)
confirms recurring script jobs and pause/resume. No additional scheduler, model
provider, tool, memory source, webhook or external messaging destination is added.

A new explicit “Confirm and follow up” action starts an active commitment. Older
clients' “Confirm” continues to save only; a saved commitment can be explicitly
started from the updated controls. Follow-up retains the confirmed quotation and
private preparation after the original conversation window ages out. Only the
same bounded recent conversation and owner-entered progress notes can add new
evidence. The owner can add progress, snooze, complete or stop tracking. The agent
may ask whether work is complete; it cannot mark it complete or execute it.

The first review prepares useful private help. Subsequent reviews account for
new evidence and scheduled check-ins, even when the conversation is unchanged.
A progress check becomes eligible after one day; unanswered checks back off to
three days and then seven days. Quiet checks never send status pushes. Evidence
updates must cite an exact permitted owner quotation. The UI shows the latest
review, next check, progress and preparation, including budget/coverage gaps.
These are bounded periodic checks, not an exact-time alarm service.

## State, contracts and boundaries

- Migrate the private review store atomically from schema 1 to 2, retaining all
  existing suggestions and grants. Add follow-up state and delivery occurrences.
  Old code refuses schema 2; deployment requires a verified separate-store backup
  and a recovery plan that preserves post-migration owner decisions.
- Keep one running review at a time and the shared four-inference rolling-day cap.
  Alternate discovery with due follow-up batches when both need work. Review at
  most three active commitments per run; cap active/snoozed commitments at ten.
- Use a revision per commitment. Every owner edit invalidates in-flight work and
  pending notifications for that revision. Pause/revocation, binding changes,
  snooze, completion, newer conversation and expiry are checked before publication
  and again before delivery. Resume never revives an old pending occurrence.
- Model results have a strict schema and cannot modify state, dates, permissions,
  recipients or schedules. Each batch must account for exactly its selected items.
  Transient source snapshots are erased after success, failure or revocation.
- Preserve generic lock-screen content and the existing version-2 payload shape.
  A distinct occurrence ID permits a later meaningful update on the same item,
  while retries retain identity. Taps still open the current authenticated item.
  The shared two-notification rolling-day cap, consent, expiry and 22:00–08:00
  quiet hours remain unchanged.
- Preserve source isolation: no attachments, Library, browser, other conversations,
  autonomous messages to others or external-system changes. Saved commitment
  history is private application state, not permission to read new sources.

## Verification and rollout

Exercise migration/restart, legacy confirmation, explicit follow-up activation,
unchanged-input due work, progress, snooze/resume, terminal states, stale revisions,
binding revocation, injected output, exact citations, batch completeness, failed
reviews, shared budgets, deduplication and queued-delivery invalidation. Verify web
and mobile controls and repeated occurrence taps on the same commitment. Reuse
native scheduler qualification; real model usefulness and phone receipt remain
separate from synthetic tests. Record actual rollout and device acceptance only
after observing them. Keep private evidence in the existing operational dossier.

## Candidate qualification — 3 November

The existing local-model worker passed an actual synthetic follow-up prompt in
20.18 seconds, returning a strictly cited check-in with no additional tools or
private source reads. The full owned Docker/PostgreSQL and pinned native fixture
verification passed 2,413 tests without failures, errors or skips and cleaned up
its resources. Two subsequent callback/barrier regressions passed in the focused
67-test lifecycle/review run. The browser journey exercises explicit activation,
progress, snooze/resume, completion, global pause and text-safe rendering at both
viewport sizes; its screenshots were inspected. Mobile typecheck, lint, 137 Jest
and 15 tooling tests passed. The final merged backend verification passed all
2,415 tests without failures, errors or skips. The processed merged-main scan
closed all five new findings after the bounded cleanup. The backend's broader
quality gate still fails its existing backlog; the mobile merged-main gate passes.

Owner controls join the worker admission barrier so a held migration cannot admit
new progress or completion decisions. Oversized evidence fails visibly and erases
its snapshot; it is never truncated into a false claim of complete coverage.

## Deployment and remaining acceptance — 3 November

Backend PRs 125 and 126 merged the feature and scan cleanup; deployed source is
`4ea2344ba22c49a6382fbcb59e8a669e6a058306`. The held migration verified its
separate-store backup, preserved owner decisions, migrated to review schema 2,
and passed source and health verification before admission resumed. The existing
native worker and hourly job remain enabled without a source or schedule change.
The owner-requested activation was completed through the live authenticated UI
for the already-confirmed commitment; the unconfirmed suggestion remains undecided.

The first private follow-up is pending the unchanged shared review budget. Earlier
qualification consumed its four slots; the normal hourly job can claim new work
after the rolling window renews. No budget reset, extra inference or quiet-hours
override was applied. Synthetic model qualification is distinct from that pending
real review, and the earlier two-phone suggestion acceptance is distinct from a
future follow-up notification receipt.

Mobile PR 11 merged as `c77e38e511364cf88806e26ba5ad95faf98ceeee`.
Android 1.0 (7) is available in the existing internal track. iOS 1.0 (9) is
published to the existing Owner TestFlight group; App Store Connect reports
Testing with Owner assigned after the unchanged encryption declaration was saved.
Both builds retain the established notification consent and payload contracts.
New build installation and physical follow-up receipt are not yet asserted.
