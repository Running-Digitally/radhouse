# SPACE browser pilot integration

Date: 2026-10-22. Updated: 2026-10-23. Status: implementation; deployment is not yet verified.
Design depth: D2. Implements the owner-approved browser-first slice of DW-5.

## Outcome and scope

The existing chat and viewer use the same browser inside one retained SPACE
microVM. Chat, Hermes, Library data, the credential vault and the authoritative
browser controller remain on their current servers. Existing local browser
packages and configuration remain available for explicit rollback. The first
pilot keeps the microVM running; it does not require memory snapshots, agent
migration, multiple owners or automatic fallback after ambiguous operations.

The existing seven native page tools and saved-login operations retain their
controller reservations. No model-facing shell, evaluation, CDP or management
API is added. Browser file behaviour must be compared with the current release;
this slice must not present operator file transfer as Library integration.

This slice preserves the local worker's temporary-profile behavior: Close
retires the browser and removes that generation's cookies, history and cache.
It does not complete DW-2 Library transfers or DW-3 durable browser profiles.
Those remain explicit roadmap items, including their privacy and backup design.

## Boundary and call path

```text
authenticated chat / browser viewer
  -> existing web session and owner checks
  -> existing Hermes browser controller and vault
       -> pinned page-only native driver
            -> fixed local CDP tunnel -> authenticated remote browser service
       -> existing take / observe / handback state machine
            -> acknowledged guest input freeze / drain / grant
       -> authenticated fixed stream relay -> guest Selkies

remote browser service inside SPACE
  -> non-root sandboxed Chromium + private X display
  -> existing Selkies input allowlist and held-input cleanup
  -> public-only egress proxy outside the microVM
SPACE host gateway
  -> fixed sandbox / port, scoped SPACE attachment credential
```

The guest owns browser execution, not user authorization. The controller sends
short-lived grants and renews them while its current authority remains valid.
The guest checks the grant at input injection and expires streams and input when
renewal stops. A controller-side critical section freezes guest input and awaits
drain before inspecting sensitive fields or admitting subsequent agent work.
An unacknowledged freeze, revoke, drain, launch or stop keeps the browser fenced;
there is no retry of uncertain effects and no automatic local replacement.

The existing controller stays authoritative instead of introducing a second
controller database. The vault never moves into the guest. Trusted native driver
traffic crosses the fixed CDP tunnel; this endpoint is never returned to the
viewer or model. Service credentials are separate from SPACE management and
viewer credentials. All remote connections use verified TLS and fixed origins.

## Modules and contracts

- `runtime/selkies/space_protocol.py`: closed request/response shapes, identifiers,
  bounded frames, grant expiry and sanitized errors.
- `runtime/selkies/space_client.py`: authenticated requests and one fixed CDP
  tunnel; process-like browser handle with explicit uncertain outcomes.
- `runtime/selkies/space_guest.py`: browser/display lifecycle, guest input fence,
  scoped stream and CDP transport; no caller-selected paths or command execution.
- `runtime/selkies/space_platform.py`: existing controller integration and remote
  critical-section acknowledgements. Reuses the current platform observation,
  ownership and handback logic.
- `runtime/selkies/space_gateway.py`: host-side TLS relay to one sandbox port.
  It keeps the management credential outside the guest, renews acknowledged
  port attachments and never retries an uncertain browser mutation.
- `runtime/selkies/space_bootstrap.py`: fixed guest startup after systemd has
  killed the prior service cgroup. It verifies that only the bootstrap and its
  ancestors remain, then retires stale launch records and temporary profiles.
  A surviving process, child cgroup or unexpected profile path blocks startup.
- `runtime/selkies/platform.py`: explicit manifest selection between the current
  local worker and SPACE; unchanged default and public browser API.
- Private deployment helpers: pinned guest package, SPACE
  lifecycle intent/receipts, public-only egress, service startup and rollback.

Every request binds the configured installation and launch generation. Mutable
control operations carry a unique request identity; the service rejects stale
generations and conflicting launch identities. It never interprets browser
content as configuration. Tokens, credential-bearing expressions, URLs and
input contents are excluded from logs and operational receipts.

The pinned SPACE build drops private-address traffic before evaluating the
guest's configurable egress policy. A private proxy therefore needs a host-owned
exception for exactly its address and TCP port in this sandbox's namespace.
The rule must preserve source anti-spoofing and every other guardrail, and return
traffic to SPACE's transparent gateway rather than forwarding around it. Bind
startup reconciliation to the sandbox lease and pinned namespace identity;
do not relax a shared node-pool policy to make the browser work.

The host gateway's API key is organization-scoped within the isolated installation;
it is not a sandbox-scoped key. Only the fixed port attachment crosses the data
plane. The Radhouse-facing service exposes no sandbox-management or shell route.

## Verification and rollout

1. Synthetic protocol tests: wrong origin/credential/generation, lost replies,
   overlapping freeze, expired grants, input draining and closed endpoints.
2. Actual guest: Chromium sandbox proof, public HTTP(S) positive controls,
   private/metadata/DNS/redirect and guest-root bypass denials, scoped streams,
   pause-free operation and predictable service startup.
3. Radhouse end to end: one actual conversation and viewer, agent navigation,
   Private/Observe, takeover, handback, reconnect, close/reopen and stale-stream
   denial. Verify existing Library, saved-login and file behaviours separately.
4. Freeze source and configuration, retain current local-backend selection and
   consistent data evidence, deploy while idle, then repeat installed acceptance.
   On failed acceptance, select the retained local backend without restoring or
   overwriting chat, originals, native history or vault data.

The private Homelab change record owns target identities, live prerequisites,
authority, exact package/configuration pins, recovery receipts and deployment
status. This document does not claim that the integration is deployed.

## Qualification observed so far

Real-guest tests exercised public HTTPS, private/metadata denials, streamed video,
human mouse/keyboard input, frozen and revoked holders, and connection expiry.
The actual controller factory and all seven page-only native tools worked through
the TLS tunnel, including takeover and handback with a fresh native snapshot.
An attachment-renewal soak passed beyond five minutes. Privileged inspection
verified Chromium's nested user/PID/network namespaces and extra BPF filters;
fixed guest-root probes confirmed the tested proxy and direct-egress restrictions.
A controlled service crash reconciled the old generation, rejected its reuse and
allowed a fresh explicit launch. These results do not replace full host recovery,
installed UI acceptance, or rollback qualification.

The whole-host restart test failed recovery: the Kubernetes containers returned,
but SPACE placed the existing sandbox in terminal `failed` state. Admission
remained closed and the live backend was unchanged. A maintained immutable
browser template and an explicitly fenced replacement/recovery procedure are
required before deployment. Service-process recovery alone is insufficient.

## Recovery implementation

The host gateway journals launch identities before forwarding start, so a lost
response cannot erase execution ownership. This journal contains identifiers,
sandbox bindings and retirement facts, never page content or credentials. The
gateway cannot declare a VM dead. Its fixed host recovery procedure may retire
an old sandbox's journal rows only after a changed host boot identity proves
that its processes ended, with SPACE also confirming terminal failure.

On that bounded failure, startup creates one replacement from the pinned
credential-free template, injects the service credential, verifies the new lease
and exact proxy rule, then selects its attachment. Creation intent is durable;
an ambiguous create stops for reconciliation instead of creating another VM.
The gateway can acknowledge old-generation retirement without forwarding old
commands to the replacement. New work requires a fresh browser launch. No page
action is replayed, no old profile is restored, and no local fallback is selected.
A real host restart with a synthetic browser open passed automatic replacement,
positive old-launch retirement, stale-start and stale-WebSocket denial, and a
fresh sandboxed launch. Public HTTPS, video, input fencing and private-network
denials also passed on the recovered guest. Installed owner UI acceptance and
rollback qualification are still pending.

Installed qualification has exercised the actual native interpreter and
controller, then selected the candidate while idle. A signed-in Private-mode
test denied the agent's snapshot as intended. The original local selector was
restored and its live viewer rendered, preserving existing history and profile
configuration. Complete SPACE viewer acceptance remains open, so selection is
kept on the retained local backend while investigation continues. A late status
request after native retirement also exposed a stream allocation race; the
factory now rejects absent/retired browser handles before allocating resources
and captures the generation handle before asynchronous startup.

The full local Python run passed 1,673 tests and 20 subtests; 306 tests requiring
optional PostgreSQL or qualified native fixtures were skipped. The real Linux
browser/controller evidence above is separate from those local test results.
