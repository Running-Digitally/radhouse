# Viewer decoder recovery

Historical investigation. The [4 November closeout and troubleshooting guide](2026-11-04-browser-reliability-lessons.md)
supersedes this report's pending live-acceptance statements, preserves the limits
of the decoder diagnosis and records the later lifecycle/layout corrections.

## Evidence and scope

The Android simulator intermittently rendered a black preview after returning
browser control to the agent. Sanitized counters showed authentication and
incoming video chunks succeeded, while the configured H.264 decoder accumulated
queued work without output or an error callback. Restarting the viewer process
could recover; repeated handbacks could fail again. This establishes a silent
decoder stall, not its underlying browser-engine cause.

The pinned Selkies source already detects this condition, but explicitly skips
shared viewers. Radhouse deliberately uses that viewer role, including for its
separately fenced human-input connection. The owned preparation adaptation now
allows its existing decoder retry for visible, unpaused viewers. If both decoder
choices fail, the viewer stops and reports an actionable reconnect state. It
does not reload indefinitely, modify encoder settings or grant input authority.

## Review and validation

- Upstream archive identity remains the digest in `runtime/selkies/source-lock.json`.
  Each altered anchor must match exactly once; upstream drift fails preparation.
- The regression harness executes the actual patched upstream watchdog and
  fallback functions through the actual metrics-timer callback, with synthetic
  clock and output conditions. It covers
  recovery, exhausted retries, hidden, paused, quiet, unsupported and configuring
  streams. The stream-client build preserves the existing clipboard adaptations.
- The initial merged-main Sonar query returned no unresolved findings for
  `runtime/selkies/prepare.py`. The Python preparation test was not exposed as an
  issue component; the JavaScript regression test is analyzed.
- PR #136 merged as `0a3e691a61c3e4030d9c6e853fc8b4359a778412`.
  Its exact-main scan processed successfully, with 2,490 tests and four browser
  checks passing and fixture cleanup complete. The overall gate remains ERROR:
  68.7% new coverage, 0.88014% new duplication, 668 new-period issues and 766
  all-code issues. Overall coverage is 72.1%.
- The sole new finding, `10773fbf-253d-4123-ad62-3fb0945334df`
  (`javascript:S9073`), concerns a combined regression assertion. The follow-up
  splits it into independent assertions; closure requires the next main scan.
  No rule, exclusion, quality gate or issue disposition is changed.

Final live acceptance remains required before the owner phone release.

Raw simulator counters, screenshots and operational deployment identities remain
in the private release evidence, outside public Git. No page text, addresses,
credentials or input payloads are included in the diagnostic counters.

This change handles the observed failure mode. It does not establish that the
underlying WebCodecs implementation is repaired; physical-phone acceptance is
still necessary after the owner builds are published.

## Timer follow-up

Live acceptance after the first deployment still reproduced a stalled Android
viewer while iOS displayed the same page. Review found a second shared-viewer
return in `sendClientMetrics`, before its watchdog call. Testing only the
watchdog function missed this unreachable call path.

The follow-up moves the local watchdog call before that return, leaving the
shared-viewer metrics and control restrictions intact. The regression harness
now invokes the actual pinned timer callback. It fails against the first patch
(zero decoder resets instead of two) and passes all seven scenarios with the
caller fix. Final live acceptance is still pending; unit success alone does not
establish engine recovery.

The first scan attempt of PR #137's merged commit stopped before submission:
one synthetic browser-login integration case failed; fixture cleanup completed.
The unchanged-main retry remains subject to the same full verification gate.
