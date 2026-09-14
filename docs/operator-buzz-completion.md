# Official Buzz conversations and Radhouse web review

Status: owner-selected architecture, 14 September 2026. Packages 1 and 3 remain
open under the acceptance below. The earlier custom desktop pilot is historical
proof; it is superseded as the default product path. Preserve its branches,
source, application rollback and evidence until official-client acceptance passes.

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
The owner's already-paired mobile app versions and foreground Researcher
visibility must be confirmed. No phone installation, login, permission change,
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
outcomes. In the UI, accepted means queued. Applied means a model response
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
Only an unprivileged VM260 identity check ran before this redirect. Linux
qualification, source deployment, journal migration and live inference remain
pending.

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

Use the restored unmodified official Buzz desktop and the existing private
Researcher/Hermes/Nemo binding. Verify mobile foreground identity/conversation
compatibility separately on the already admitted clients.

1. Verify the recognizable Researcher identity and exact owner-only private DM.
2. From official Buzz, reply to the retained completed short no-tools assignment
   with one deliberately longer multi-step follow-up. Verify exactly one new
   durable task/dispatch/run and an exact previous-result snapshot; the old run
   remains completed. Use the three prepared public references and existing
   bounded read-only tool authority.
3. Submit one correlated guidance message while that task is active. Verify
   queued-to-applied evidence, the later ordinary request, and the changed result.
   Expect one batch of three reads and final text on ordinary model turn two.
4. The unchanged Hermes budget finalizer permits at most two additional
   tool-free summary attempts after exhaustion, so the existing ceiling is four
   calls. It is not introduced for steering. Session call counts exclude those
   summaries: require a complete normalized transcript showing the expected
   tool/guidance/final-text ordering, or report uncertainty/fallback separately.
   No task or guidance retry, extra proof run or forced no-tools continuation.
5. Open the short-lived task-specific link from official Buzz, complete normal
   Radhouse authentication/MFA, review the exact result and publish once to the
   existing private owner audience. Verify the resulting status in Buzz.
6. Reconnect the official client and restart the admitted services while idle.
   Verify identical task/run/control/result/publication identities, retained
   guidance outcome and no additional dispatch, instruction or publication.

A timing miss or missing application evidence leaves steering acceptance open.
Do not silently repeat the assignment. Retain only sanitized IDs, digests,
counts and semantic checks in operational evidence, not task contents or secrets.
Keep private exposure, current firewall restrictions, signed identity checks,
MFA, DML-only runtime access, exact model binding and bounded tools. Do not
change VM250, public DNS, Cloudflare, mobile clients or unrelated infrastructure.
