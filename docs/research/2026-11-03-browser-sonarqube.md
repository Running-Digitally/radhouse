# Browser release: processed merged-main analysis

The analysis of `69ba707178d4d27b4253996b1a4669a45d46f93d` completed successfully
on 3 November 2026 (local time). The existing backend quality gate remains ERROR.
This is a processed analysis with failing conditions, not an upload or processing
failure. The Community Build launcher analyzed committed remote main.

| Measure | Result | Existing gate |
| --- | ---: | --- |
| New-code coverage | 68.7% | At least 80%; fails |
| New-code duplication | 0.88226% | At most 3%; passes |
| New-code issues | 667 | Zero; fails |
| Overall coverage | 72.1% | Reported |
| Overall duplication | 1.0% | Reported |
| All-code issues | 765 | Reported |

The new-code period still starts at the previous project version on 7 October;
these counts are not the number of issues introduced by this browser change.
No gate, profile, disposition or first-party exclusion was changed.

The scanner's clean merged-main verification passed 2,488 tests, with no failures,
errors or skips, four JavaScript checks, owned synthetic coverage and complete
fixture cleanup. The tested source fingerprint is
`8afb41301b47fe6abaf06c9f70e659d98b0ee82c8cf8e070f4dcfdf07a6b6ec0`.

The preceding analysis of `c34ce37f336d994583986f93eebda3af27472f9d` confirmed
five addressed findings closed: three browser-service complexity findings and
two ASCII-equivalent regular-expression findings. The portrait follow-up
confirmed eight additional closures: three in `sandbox.py`, four in
`space_guest.py` and one in `qualification.py`. All-code findings decreased from
773 to 765 in that follow-up, with no new finding in its touched files.

Remaining open touched-file counts are three in `sandbox.py`, eight in
`platform.py`, eight in `space_guest.py` and six in `qualification.py`.
The stylesheet and lifecycle regression file have none. Their exact issue keys
and source-based deferral reasons are recorded in the
[bounded browser review](2026-11-03-browser-research-review.md). Broader security
coordination refactors, asynchronous callback contracts, mutation-safe collection
snapshots and X11 readiness checks remain explicit follow-up work. These findings
were not accepted, suppressed or marked false-positive on the server.

This result establishes source and analysis evidence. Live native viewing,
active chat preview and owner-channel publication have separate acceptance
checks; a successful source scan does not establish those outcomes.
