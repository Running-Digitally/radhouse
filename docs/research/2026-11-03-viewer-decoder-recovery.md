# Viewer decoder recovery

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
  fallback functions with synthetic clock and output conditions. It covers
  recovery, exhausted retries, hidden, paused, quiet, unsupported and configuring
  streams. The stream-client build preserves the existing clipboard adaptations.
- The latest processed merged-main Sonar query returned no unresolved findings
  for `runtime/selkies/prepare.py`. Test files are not exposed as issue components.
  A new main scan and final live acceptance remain required before release.

Raw simulator counters, screenshots and operational deployment identities remain
in the private release evidence, outside public Git. No page text, addresses,
credentials or input payloads are included in the diagnostic counters.

This change handles the observed failure mode. It does not establish that the
underlying WebCodecs implementation is repaired; physical-phone acceptance is
still necessary after the owner builds are published.
