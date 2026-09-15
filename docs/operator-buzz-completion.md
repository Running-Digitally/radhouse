# Official Buzz conversations and Radhouse web review

Status: official-client acceptance completed, 15 September 2026. Packages 1A,
1B and 3 passed for the bounded single-Researcher pilot described below. The
earlier custom desktop pilot is historical proof and remains superseded as the
default product path. Full V1 fleet, installation and wider-role qualification
remain separate release work.

## Product decision and verified baseline

Buzz is the ordinary conversation surface. Researcher is a standard signed Buzz
identity in an owner-only private conversation. Radhouse owns task identity,
execution, guidance, review, publication and authority. Its web interface owns
detailed evidence, protected review and administration. No embedded Radhouse
panel, private native HTTP bridge, vendored UI or custom Agents-directory code
is required in a Buzz client.

Radhouse source baseline is main `0cc970ec59859701c12a920ce8ccdd26838a1271`.
PR #7 already merged the durable guidance controller and the maintained desktop
patch before this redirect. Supersede that patch through a new reviewed product
change; do not rewrite history or remove retained recovery material. The new
steering desktop build was never installed.

The actual official desktop release is `desktop-v0.5.23`, commit
`b9392d9d78744df365f9276e1ffe8c1baa5ea903`. The former patch used newer source
`092c6a7277698bd373ccbc1d008fc1507094ae74` with the same displayed version; those
pins are not interchangeable. The retained official macOS bundle passes deep
strict signing checks, Gatekeeper's Notarized Developer ID assessment and its
stapled notarization ticket. It is signed by Block, Inc., team `EYF346PHUG`, and
its executable matches the originally retained digest. Restoration on Lisa
preserves the previous patched application and all application data.

The restored official desktop visibly displays Researcher's standard profile,
exact agent public key, owner association, private two-member conversation,
existing history and ordinary message composer. A local Agents-directory card
is not an acceptance requirement. No upstream desktop change is needed for
this verified conversation path. Offline presence is accurate: the server-side
HTTP adapter does not hold Buzz's WebSocket presence lease.

The upstream mobile code has standard kind-0 profile/owner verification,
kind-10100 agent recognition and private-DM membership/rendering paths. That is
source evidence, not proof of a particular installed iOS or Android binary.
At the exact desktop-release source pin, 249 focused mobile tests passed with
the unchanged upstream lockfile enforced, covering profiles, private channels,
membership, replies and reconnect. No source or mobile-client patch was needed.
The owner confirmed Researcher's private conversation opens in both official
iPhone and Android clients, and explicitly waived installed-version inventory.
The official-client preflight is complete. No phone installation, login, permission change,
push configuration or network grant is included. The existing mobile push
production gate remains separate.

## Conversation behavior

- A first message creates one durable task. Explicit separate work can use the
  existing `New task:` form; no model infers permissions or routes commands.
- With one active task, an ordinary message is guidance for that exact task.
  Multiple active tasks require an explicit reply. Freeze routing before the
  command effect and reuse the signed event identity on delivery recovery.
- With no active task, a later message follows the most recently selected
  completed work and snapshots its result as context. An explicit reply always
  selects its own task. Determine recency from durable owner task-selection
  messages, not random task UUIDs or delayed bot progress. Never reopen a run.
- Short tools-disabled tasks finish with their natural single response. Guidance
  does not force another response, reset the budget or silently enable tools.
- Researcher posts bounded progress, a concise result preview and a task-specific
  web-review link. Full work remains in Radhouse. Truncated previews are labelled.
- The existing `status` request is read-only and can return a fresh review link
  for the selected completed task. It creates neither a task nor a model call.
- After protected web publication, post one correlated publication-status event
  into the same private conversation. Restart or replay must not duplicate it.

## Durable guidance contract retained

Hermes queues identified guidance after a completed tool batch and includes it
in the next ordinary model request. The existing max-turns limit governs that
request. The reviewed overlay adds zero model calls for steering.

Retain `hermes-guidance-v1`: exact run/control/input-SHA256 correlation;
monotonic receipts; independent delivery and application outcomes; at-most-once
POST; GET-only reconciliation through terminal tasks, pause/resume and retained
expiry; durable recovery of accepted, applied, too-late, not-applied and unknown
outcomes. New guidance retains its authenticated source channel/event before
the runtime POST. Standard Buzz replies bind outcomes to that exact input; if
a web mirror is still pending, child delivery waits for its signed parent.
In the UI, accepted means queued. Applied means a model response
completed for a request containing the guidance, not guaranteed obedience.

The optional capability remains `runs_steering_receipts` version 1, durable,
with `checkpoint=after_tool_batch`, `max_extra_model_calls=0` and
`applied_evidence=completed_provider_response`. New guidance requires that
capability. Missing receipts and uncertain provider completion remain unknown;
never resend to manufacture confirmation. Existing no-tools enforcement and
exact permission/MFA controls remain unchanged.

The retained Hermes overlay is based on `c67fb3378943dc6454b5680f3fc17919facd8fad`
and locally committed at `27e563d0af4a7fac6bf654db67444b026ecf0d71`. It passed 249
distinct local cases; the frozen VM260 rollout has four helper regression cases.
The approved isolated Linux qualification also passed all 249 cases without
changing live runtime state. Source deployment, journal migration and live
inference remain pending.

## Authenticated web-review locator

Use a short-lived signed locator, not an authentication credential. Reuse the
existing Researcher signing identity and the existing authentication service;
add no key, service, broker or PostgreSQL schema solely for navigation.

The proposed version-1 locator contains the task, immutable result digest,
project, exact conversation link and binding revision, agent identity, intended
principal, issue time and expiry. Use a fixed 15-minute lifetime. Sign canonical
bytes with the existing Schnorr implementation under a review-link-specific
domain separator; a review signature must not be usable as a Nostr event or
NIP-98 authorization. Encode only bounded validated fields. No task contents,
password, session cookie, MFA data or return-to URL belongs in the locator.

Deliver an HTTPS URL under the configured Radhouse origin, with the locator in
`/app/#review=...`. The fragment keeps it out of HTTP request URLs and referrers.
The browser submits it to a same-origin, CSRF-protected resolver after normal
sign-in/MFA. Verify exact signature, purpose, fields, lifetime, audience, current
configured agent/link/binding, task ownership, project access and result digest.
Derive the authorized web binding from current server state. A locator alone
must never read a task, create a session, prepare a review or publish.

Return only the authorized task/project navigation target. Keep that target
through sign-in and assurance refresh; focus the exact task in the web review.
Every subsequent read and protected operation retains its existing independent
ACL/binding, fresh-assurance, result-digest and publication checks. The resolver
is read-only. Reopening a valid locator with the same authenticated audience is
navigation, not a replayable bearer grant.

Expired, tampered, wrong-audience, stale-binding and changed-result links fail
closed with a clear message. Work remains available through the ordinary
permitted web home; a signed `status` request can issue a fresh locator. Persist
the original completion message/link before relay delivery and never rewrite
an already signed outbox event on reconnect. A stale delayed delivery does not
justify replaying work or creating another publication.

The current Radhouse web ingress admits Lisa. Mobile foreground conversation
support does not grant phones a new web-review route. Preserve the existing
private network and firewall boundaries.

## Affected components and implementation slices

This is D2 structural integration work. Complete the official-client preflight
before dependent implementation, then deliver these end-to-end slices:

1. Server conversation and link slice: add the domain-separated locator service,
   compose it with existing configured agent keys and web origin, and add an
   authenticated resolver in `api/app.py`/schemas. Update
   `application/conversations.py` and `storage/conversations.py` for durable
   conversation focus and read-only status links. Update
   `channels/buzz_conversations.py` for bounded completion previews and stable
   publication-status messages. Publication needs its own undelivered selector:
   publishing currently does not increment task state revision.
2. Web slice: resolve the URL fragment after normal authentication, preserve the
   target through assurance refresh, select the exact authorized project/task,
   and reuse the existing review/publication actions. Ordinary conversation
   remains in Buzz; the web surface supports history/evidence and administration.
3. Remove the active custom-client dependency: stop mounting `/buzz` native HTTP
   routes in `cli.py`; supersede/remove `channels/buzz.py`, the embedded-client
   enrollment routes and web-only-to-native hooks. Remove the maintained patch
   payload from the active integration path, retaining a supersession pointer
   and immutable Git history. Keep the signed binding, owner-attestation
   verification, stored enrollment and `ConfiguredBuzzConversation` checks used
   by the server adapter. New enrollment is not silently enabled by weakening
   those checks; generic official setup remains a separately specified path.

No source change is proposed to official Buzz at this point. If exact official
mobile/client evidence demonstrates a generic missing feature, identify the
specific call path and propose the smallest upstream contribution. Never make
the private desktop patch the default workaround.

## Tests and review gates

Exercise real signed relay events and owned PostgreSQL, including first-message
admission, latest completed context, explicit replies, multiple active tasks,
delayed/duplicate delivery, lost acknowledgment, restart and revoked bindings.
Retain the already qualified natural-checkpoint/no-tools guidance regressions.

Test locator tampering, expiry, wrong principal/project/task/digest, revoked or
changed binding, disabled agent, absent/stale authentication/MFA, forged keys,
malformed/oversized input, no open redirect and no permission from possession.
Verify a login/assurance round trip selects the exact task, and that a successful
web publication yields one stable signed Buzz status event across replay.
Old native routes must be unavailable in the deployed API composition.

Use focused tests while iterating, then the required product verification and
browser gates. Read consequential authority and recovery code through review
cycles; local tests alone do not close the live acceptance. Preserve any failed
or uncertain observation accurately.

## Package 1 and 3 live acceptance

The bounded private proof completed these criteria with one useful ordinary
assignment and follow-up, one separately authenticated review-link check, and
one genuinely multi-step research assignment whose correlated guidance changed
a later model response. Duplicate prevention, reconnect, controller restart and
one durable publication-status event passed as separate checks. Deployment-
specific identities and receipts remain in the private operational evidence.

The milestone requires a useful Researcher assignment reliably completed from an
unmodified official Buzz client. Keep packages open until demonstrated; a local
test pass or nominal runtime completion is insufficient. Official desktop
identity/conversation visibility and owner-confirmed mobile foreground access
are already established. The custom desktop fork remains superseded.

Package 1 has two internal milestones. **1A** proves one durable assignment from
an official Buzz message, acknowledgement, meaningful progress and a useful
result. Then prove a contextual follow-up after completion, and verify the
short-lived task-specific link to authenticated/MFA web review separately.
**1B** proves exactly correlated live guidance during genuine successive research
turns. Keep the overall package open until both pass; assess 1A independently
and complete it before admitting the 1B proof. A nonempty fragment or nominal
runtime success does not demonstrate useful work.

Prove the following in order, with separate bounded checks:

1. Correct reply ancestry and empty-success reporting. Retain the failed
   walkthrough and its exact task/run/source-event evidence.
2. Qualify the existing Hermes/Nemo tool path independently of Buzz. Start with
   one useful question over one admitted reference. Distinguish provider response
   shape, runtime execution/persistence and controller integration failures.
   Require real tool execution and a nonempty useful answer; report missing
   evidence instead of interpreting an empty terminal status as success.
3. Use official Buzz for one useful assignment: one signed owner event creates
   one durable task, Researcher posts progress and a concise result, a subsequent
   message becomes a contextual follow-up, and its exact detailed review opens
   in authenticated Radhouse web. Short finished work stays finished.
4. Prove steering separately on substantive research. The question must require
   several admitted sources, evidence comparison, gap/contradiction analysis and
   a recommendation. Source selection and analysis should naturally require
   successive tool/model turns. Three immediate reads in one batch are not a
   sufficient substitute. Submit one guidance event while active and verify its
   exact task/control/input correlation, durable outcome and effect on a later
   model turn and the resulting recommendation.
5. Keep protected publication, authentication denials, deduplication, reconnect
   and idle-service restart recovery as separate checks. Reuse already-qualified
   safeguards and prior applicable evidence; do not overload one run with every
   property. Publication stays in the web interface and its status returns to
   Buzz. Retain exact task/run/control/result/publication identities.

Before the 1B research run, make the exact assignment text, source paths and
permitted tools, natural checkpoint sequence, exact guidance message and when
to send it, expected useful result, ordinary model-turn limit, maximum physical
provider requests and stop conditions reviewable.
The permitted tool names are an execution boundary, not prompt advice. When an
owner brief says `Use only search_files and read_file`, Radhouse records that
exact ordered set with the task and requires Hermes' durable
`runs_allowed_tools` exact-subset capability before dispatch. Hermes advertises
and accepts only those configured tools for that run; an unavailable capability,
unknown name or conflicting replay fails closed. Reference content cannot set or
widen this restriction. Source-path compliance remains separately verified from
the durable tool transcript.
Count all provider requests, including thinking continuation, truncated tool-call
recovery and finalizer requests. The current two-turn setting is not itself a
hard wire-call cap: truncated-argument retries occur within a turn. Use an exact
qualified cap before claiming a maximum; any necessary budget increase requires
an explicit owner decision. Do not add artificial delays, busywork, forced model
calls for completed responses, fallback providers or broader tools.

A short task that closes before guidance receives a contextual follow-up. A
failed or inconclusive research proof remains open; do not silently repeat it.
Keep queued/applied/too-late/unknown outcomes honest and preserve unsent or
uncertain guidance. Retain only sanitized IDs, digests, counts and semantic
checks in operational evidence. Preserve private exposure, firewall restrictions,
MFA, signed identity, DML-only runtime access and the Hermes/Nemo binding. No
VM250 mutation, client fork, model switch or unrelated access is included.

## Official-client walkthrough corrections, 14 September

The first official-client follow-up retained the correct completed parent and
created one task/run, but did not pass acceptance. The official client used a
reply-only NIP-10 marker. The adapter incorrectly treated that reply as a new
thread root, and the relay rejected its acknowledgement and progress events.
Hermes separately exhausted two thinking-only responses without tools or a
final result, yet reported completion. No guidance or publication was sent.
The coordinator is held and the original task and signed outbox remain intact.

This bounded D1 correction changes two existing call paths, without schema,
client, authority or model changes:

- In `BuzzConversationCycle._prepare_outbox`, derive a reply parent's root from
  its root marker, otherwise its reply marker. Without a reply marker the parent
  is top-level, including legacy root-only events. Preserve the
  immediate parent ID. A transport fixture must enforce the relay's ancestry
  rule for a reply-only follow-up, then verify one task and stable signed
  acknowledgement/result events after reconnect and lost acknowledgement.
- In `Service._finish_work`, treat an absent or whitespace-only completed result
  as an unverified runtime outcome, using the existing attention/reconciliation
  state. Do not close successfully, publish, redispatch or create another model
  call. Verify this through the normal service and durable dispatch path.

Hermes owns its separate correction to unfinished/empty run status. These
changes do not rewrite the retained failed walkthrough, regenerate signed
outbox rows, or authorize another proof task. Any delivery repair must first
prove the rejected event IDs absent at the relay and preserve their provenance;
an unknown delivery remains immutable. Live acceptance remained open until the
subsequent bounded proof summarized above passed.

### Retained rejected deliveries

The ancestry fix cannot rewrite three already signed, rejected replies. A
bounded D1 recovery extends the existing transport → egress → outbox selector:
only the relay's HTTP 400 `/events` response with the exact JSON error
`invalid: root tag does not match thread ancestry` is a permanent delivery
rejection. Retain its event, signature, message and delivery IDs unchanged,
with `delivered=false` and `buzz_thread_ancestry_rejected`. Egress records that
outcome and continues; subsequent cycles omit only that known permanent error.
All authentication, uncertain-delivery, missing-parent and other failures keep
their existing stop/retry behavior. Parse the error within existing response
size/time bounds. No schema, new queue, re-signing or fabricated acknowledgement.

Tests must demonstrate exact error classification, preserved signed bytes and
failure evidence, later valid delivery, and no retry after reconnect. Task/run
identity and work dispatch remain independent of this delivery-only correction.
