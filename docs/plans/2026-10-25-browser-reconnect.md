# Browser reconnect after transport retirement

Date: 25 October 2026. Design depth: D1. Status: implementation in progress.

After a stream fails, its browser can be positively retired while the Hermes
native driver remains alive. Status then repeatedly rejects the dead generation
until the independent idle reaper removes that driver. Reconnecting should finish
that known teardown promptly and return to the ordinary idle/Open browser UI.
It must not infer retirement from a timeout or replay a navigation or input.

The Selkies adapter owns stream shutdown and positive browser retirement. After
that proof, the Hermes bridge will use Hermes's existing verified daemon reaper
for the exact retained native identity, independently confirm process exit and
retire the controller binding. Failed identity or exit verification retains the
blocked generation. Reconnect may retry cleanup; it never allocates a browser.
Explicit Open retains its existing ownership and readiness checks.

Affected contracts: `runtime/selkies/platform.py` lifecycle/cleanup and
`runtime/hermes/bridge.py` native process retirement. The SPACE guest lease,
credential policy, egress rules, browser actions and durable chat stay unchanged.
Both adapters must be deployed together from a frozen tested revision.

Regression tests will cover an orphaned driver, mismatched identity, failed exit
proof, interrupted guest retirement, repeated reconnect and successful fresh
Open after cleanup. Installed acceptance will reproduce a bounded transport loss
using only a synthetic browser, then verify human video/input, Private/Observe
controls, handback, chat continuity and final process/listener cleanup. Private
topology and execution receipts belong in Homelab.

The dated Sonar index reports 25 open bridge findings and 15 platform findings.
The existing analysis credential returned HTTP403 for issue-detail reads during
this pass. Counts alone cannot identify applicable issue keys or prove closure;
retain that limitation and review actual touched code for scoped improvements.
No issue suppression, gate change or unrelated complexity rewrite is authorized
by this repair.
