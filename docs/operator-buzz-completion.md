# Everyday operator workflow and native Buzz parity

Status: implemented and isolated qualification passed; private deployment and
native-client acceptance remain open. This
packet owns the implementation plan and acceptance gaps for packages 1 and 3.
It is not a release or live-deployment receipt.

## Outcome and existing authority

The owner requested completion of the everyday operator experience and the
equivalent Buzz task/review experience. Preserve the accepted contracts in
`boundary-experience.md`, `work-model.md`, `integrations/buzz.md`, and
`vs1b-pilot.md`. This is D2 software work. Local implementation and disposable
tests proceed; connecting a private installation and privileged host changes
remain distinct decisions. On 2026-09-13 the owner explicitly approved:
"Implement the minimal desktop patch" against the pinned Buzz source.

Product source baseline: `b7082be874ce802e8aa13fe4fa77a1657fd76546`.
Buzz compatibility source: `092c6a7277698bd373ccbc1d008fc1507094ae74`.

## Delivery slices

1. Complete the work-home read/action journey: choose an authorized project and
   assigned ready bot, retain an unsent draft through refresh, submit exactly
   once after a lost response, show task progress/history, select an eligible
   publication audience, refresh human assurance without losing work, download
   the result, and start a second assignment. Verify API and browser behavior.
2. Add selected input files and task-scoped follow-up handling through explicit
   runtime capabilities. Received and applied instructions must be distinct.
   An unsupported runtime must report a real gap rather than silently starting
   another task or claiming an instruction was applied. Access requests may
   never create an effective resource grant merely by updating a UI record.
3. Add the Buzz identity/command boundary using verified signed commands,
   current person/key/conversation bindings, controller-owned fresh human
   assurance, source-event deduplication and the existing service transactions.
   Read/event delivery uses authorized snapshots; Hermes remains reachable only
   through the controller coordinator.
4. Qualify the native Buzz client path and both-direction task/review flows.
   Finish with duplicate/reconnect/revocation/changed-audience/changed-content
   negatives and a complete unfamiliar-operator walkthrough.

## Program boundaries

`web/src/{api,app,contract,types,view-model}.ts` owns presentation and checked
transport values. `application/service.py` owns access-filtered workspace and
task queries, admission and review. `application/ports.py` and
`storage/postgres.py` own bounded queries through the existing transaction.
`auth/local.py` owns session validity and fresh password/TOTP assurance.
`api/app.py` maps authenticated requests to those services. The UI never
calculates grants and never sends a replacement model route.

```text
human action -> checked client request with stable command identity
  -> authentication + current project/conversation binding
  -> shared service transaction -> durable task/review/publication
  -> authorized work-home/events response

lost response -> retain original command identity -> retry same request
stale revision -> refresh current state -> explicit human retry
expired assurance -> inline fresh sign-in -> re-read exact review
revoked access -> deny read/action and remove protected display
```

Fresh assurance must not create another user session or revive revoked access.
Project selection lists only current active memberships/bindings. History and
result reads remain filtered by current bot and project grants. Publication
audiences come from the server and are rechecked in the commit transaction.

## Native Buzz integration decision

Verified source evidence:

- `desktop/src/features/workflows/ui/WorkflowApprovalCard.tsx` explicitly renders
  "Approval actions are not yet available in Desktop."
- `crates/buzz-relay/src/api/workflows.rs` exposes structured reads of relay-owned
  approvals, not an external protected-decision hook.
- `crates/buzz-acp/src/acp.rs` auto-approves ACP permission requests; using that
  harness would violate the accepted human decision and single execution owner.

Approved smallest client change: a Radhouse task panel in the existing Buzz
desktop channel/thread surface, configured for one explicit controller origin.
Reuse the client's native key signer; bind the exact community/channel/thread,
method/body and event identity; ask for fresh human assurance in the native
panel when required. Show exact action, artifact content/digest, audience and
expiry before commit. The panel calls the Radhouse controller directly and
never the Buzz workflow approval or ACP execution path. Keep private keys in
Buzz's existing custody and do not export Radhouse credentials into chat.

Ship the integration as a reviewable patch against the pinned upstream source,
with application/rollback checks, native transport tests and shared-component
browser tests. Selecting and
operating a patched desktop client creates an ongoing upstream-compatibility
obligation and requires an explicit owner decision. Official mobile clients
would remain unchanged; this would prove desktop parity only. Mobile protected
reviews and official mobile push must remain accurately classified.

Selected input is deliberately bounded to four UTF-8 reference files and 64 KiB
in total. A follow-up creates a new explicitly admitted task and includes a
snapshot of the selected previous result; active guidance stays on the existing
run without resetting budget or changing the immutable dispatch input. Hermes
0.21.1 acknowledges receipt of guidance but does not provide a per-instruction
application receipt. The UI reports that limitation instead of asserting it was
applied. Non-idempotent controls commit their receipt before transport and are
never automatically replayed after a lost reply or controller restart.

Runtime permission responses are exact request/run/digest decisions with fresh
human assurance. Deny is available; allow-once additionally requires an exact
operator-configured command in that bot's existing grant. No session/permanent
approval, new external resource grant, or runtime permission bypass is added.

### Native transport and authority contract

The native transport is a bounded Rust command in the pinned desktop client.
Build-time configuration pins one HTTPS controller and one relay origin/key.
The command rejects a different active community, uses the current native
signing key, forbids redirects and non-operator routes, and bounds request size,
response size and elapsed time. It signs the exact HTTP method, URL, body and
channel plus a separately signed, fixed relay membership query. Cookies remain
in native process memory, scoped to the current identity/community; neither
cookies nor keys are returned to JavaScript or written to disk.

The controller keeps its existing local-auth cookie, Origin and CSRF checks
unchanged. `/buzz` adds signature verification, an exact configured channel
mapping, a fresh relay query for the authoritative relay-signed kind-39002
membership snapshot, and the current Radhouse person/key binding. Each request
uses a fresh relay nonce; the controller signature binds that membership proof,
so relay replay rejection also rejects duplicate signed ingress. Application
command identities still permit safe retries signed as new requests.

Login also checks the verified key's expected Radhouse principal before issuing
a session. Protected decisions require the same current local MFA assurance as
the web interface. There is no bearer-token or CSRF-bypass path. A revoked key,
member, bot grant, project membership or local session fails closed.

The desktop mounts the same locally bundled work-home components inside its
channel panel. It does not load remote executable UI. Every visible task and
publication refreshes from the shared controller, and reconnect obtains a full
authorized snapshot. Only the configured channel conversation is admitted;
no inferred thread, DM, mobile, or room-wide publication authority is added.

### Database compatibility and rollback

Schema version 2 marks the extended task snapshot contract. The owner initializer
accepts only the exact version-1 checksum or exact current checksum, applies the
ordered upgrade in one transaction, and keeps existing tasks and publications.
The runtime role retains DML-only access. Version-1 controller/auth binaries are
fenced by the metadata version before they can process new task snapshots.

Before a private upgrade, stop API/coordinator writers and retain a verified
database backup plus the previous application/configuration pins. Before new
work is admitted, a rollback can restore that snapshot and previous binary.
After new tasks or decisions are admitted, prefer disabling the optional Buzz
mount or stopping the affected worker while retaining version-2 data for a
forward fix. Restoring an older database would lose newer work and requires an
explicit decision; it is never an automatic application rollback.

## Verification and completion

Use a disposable local PostgreSQL instance, fake runtime/provider, synthetic
users and signed events. No private credentials or live model calls are needed
for development. Test the complete UI against the actual API, including lost
responses, multi-tab sessions, stale content, read-only users and revoked grants.
Then qualify the selected native client and relay composition before accepting
the private rollout. Passing synthetic API tests alone does not complete either
package.

### Executed local evidence — 2026-09-13

- `RADHOUSE_BROWSER_CHANNEL=chrome .venv/bin/python scripts/vs0.py verify`:
  248 tests, zero failures/errors/skips; both simulated channel directions,
  fresh-process recovery, exactly one run per completed task, and unknown
  runtime evidence retained without redispatch. Owned Docker fixture cleanup
  completed. The source was the baseline plus this implementation diff.
- `npm --prefix web test`: build and all eight client tests pass. The browser
  walkthrough exercises selected files, a completed result, native-signed
  protected publication, return to web and a follow-up containing the prior
  result. It uses real PostgreSQL/API with synthetic keys and runtime; it is not
  an installed Tauri-client test. The resulting work-home screenshot was reviewed.
- Pinned Buzz: TypeScript, Biome, Rust checks/Clippy, desktop builds, 6,488
  JavaScript tests and 2,098 unchanged mobile tests pass. The complete desktop
  native suite passes serially (3,176 tests, 19 existing ignored tests), including
  all three new transport tests. Default parallel `just ci` exposed the existing
  global login-shell-counter test failure under concurrency; that test passes alone and the complete
  native workspace passes with `RUST_TEST_THREADS=1`. No test was disabled and no
  source allowlist was broadened to hide the failure. Default parallel CI is
  therefore not recorded as green.
- The exact exported desktop patch applies to a fresh pinned checkout, passes
  reverse-application checks and returns the checkout to a clean state. Its
  manifest pins the patch and the canonical shared-component content digests.

Private acceptance still needs a healthy relay, verified relay public key,
existing-person/channel binding, native TLS and configured desktop build,
Linux/Python dependency installation, schema upgrade/backup proof and a real
operator walkthrough in both directions. The approved patch does not close
official mobile push, mobile reviews, OIDC, invitation/recovery administration
or the wider full-V1 release requirements.
