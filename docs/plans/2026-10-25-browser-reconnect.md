# Browser reconnect after transport retirement

Date: 25 October 2026. Design depth: D1. Status: implemented; live fault recovery and human input acceptance passed.

After a stream fails, its browser can be positively retired while the Hermes
native driver remains alive. Status then repeatedly rejects the dead generation
until the independent idle reaper removes that driver. Reconnecting should finish
that known teardown promptly and return to the ordinary idle/Open browser UI.
It must not infer retirement from a timeout or replay a navigation or input.

The Selkies adapter owns stream shutdown and positive browser retirement. After
that proof, the Hermes bridge uses Hermes's existing verified daemon reaper
for the exact retained native identity, independently confirm process exit and
retire the controller binding. Failed identity or exit verification retains the
blocked generation. Reconnect may retry cleanup; it never allocates a browser.
Explicit Open retains its existing ownership and readiness checks.

Affected contracts: `runtime/selkies/platform.py` lifecycle/cleanup,
`runtime/selkies/space_platform.py` lost-reply reconciliation and
`runtime/hermes/bridge.py` native process retirement. The SPACE guest lease,
credential policy, egress rules, browser actions and durable chat stay unchanged.
Both adapters must be deployed together from a frozen tested revision.

Regression tests cover an orphaned driver, mismatched identity, failed exit
proof, interrupted guest retirement, repeated reconnect and successful fresh
Open after cleanup. Installed acceptance reproduced a bounded transport loss using a synthetic
browser and verified video, Private/Observe controls, handback, chat continuity,
foreground streamed keyboard input and final process cleanup. Private
topology and execution receipts belong in Homelab.

The dated Sonar index reports 25 open bridge findings and 15 platform findings.
The existing analysis credential returned HTTP403 for issue-detail reads during
this pass. Counts alone cannot identify applicable issue keys or prove closure;
retain that limitation and review actual touched code for scoped improvements.
No issue suppression, gate change or unrelated complexity rewrite is authorized
by this repair.

Validation at source `e8d2b703d588bbcbd7da57a9a0af57ed36cd0241`: the owned
PostgreSQL fixture with pinned upstream Hermes source passed 2,081 tests with no
failures, errors or skips, plus three browser journeys. Coverage executed all
48 changed executable lines across the three runtime adapters. This is changed
line coverage, not a new Sonar quality-gate result. Public-source privacy passed.

Installed Linux qualification passed real frame progression, sandbox, origin,
view-only input and Chrome-control guards. A 20-second outage of the existing
SPACE gateway then retired the old native browser generation in 21.516 seconds
from observation start, approximately a second after connectivity returned.
The worker service did not restart and no live generation remained. The UI
returned to idle automatically; explicit Open created a new browser. A deployment
receipt permission error was corrected while admission remained held, before
these acceptance tests. Operational hashes and receipts remain in Homelab.

Post-recovery live acceptance confirmed Private snapshot denial, Observe snapshot
success, a separate actual navigation denial while the owner held control,
handback, agent navigation, browser video and explicit Close returning idle.
The tool records were checked independently of the model's wording. The selected
runtime passed final integrity/readiness checks with no active run, browser or
terminal. Foreground human keyboard input navigated the streamed browser to
`https://example.com/`; the live video confirmed its URL and Example Domain title.
Explicit Close again returned the UI and native runtime to idle, with the worker
process unchanged and saved memory preserved.

The fresh viewer initially displayed Connecting; one ordinary page reload
preceded successful video and keyboard input. This proves the usable input path
after reload, not uninterrupted first-open connection reliability. Investigate
viewer initialization if this observation recurs; the cause of the original
transport interruption remains unproven.
