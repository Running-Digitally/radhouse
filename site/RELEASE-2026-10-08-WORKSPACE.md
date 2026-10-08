# Radhouse public website: browser control and workspace progress

Prepared 8 October 2026 (Toronto) from public `main` at
`2902155c5a2dd883b371649f00471f3f2190f35a`. The owner requested a review of
“Review Radhouse rework status” and “Assess worktree readiness” followed by
changes to the public website. The latter chat covers RiseWithMe; this release
uses the Radhouse evidence only. The primary checkout has separate unfinished
work, so this update uses an isolated branch.

## Content and evidence

The current public page still labels human browser takeover as planned. The
Radhouse release branch at `bc2ed65` records browser control and saved-logins
activation on 8 October, with production Open/Go/reload/Close acceptance after
`7ac0630`. The page now describes on-demand opening, human control, return after
the assistant reply, page sharing and the distinction between Hide and Close.
Library and selective document reads remain part of the pilot description.

PR77's owner-workspace release adds About You, Terminal, opt-in terminal context
and engine-driven model/thinking choices. Its 1,072 local source tests and 11
browser journeys passed. At preparation, deployment qualification is still in
progress; these cards explicitly say “Prepared for the next pilot release”.
Thinking choices are conditional on the connected engine. Read-only memory does
not imply editing or proof that every saved note was used in a reply.

The accepted Agent Identity design (`d221bec`, `docs/design/agent-identity.md`)
is mentioned separately as taking shape. It is a documentation mock awaiting
working settings. No operational identity controls are claimed by this page.
The mobile address/search bar and Send-during-reply research are omitted.

Public “Read the pilot build” and release links point to `codex/browser-handover`,
which contains the relevant qualified browser and prepared workspace source.
The older implementation in `main` is not changed by this content release.

## Scope and verification

Only public HTML/CSS, the 12-file release manifest and site documentation change.
The notebook, house assets, scripts, analytics policy and response headers remain
unchanged. The browser illustration remains a native Hide/Show disclosure; it
connects to no private browser or agent. The new handover sequence is explanatory
text, not a set of working runtime controls.

- JavaScript syntax checks pass; four analytics-policy and three brand tests pass.
- HTML IDs, ARIA/anchor references, local assets and external-link attributes pass.
- All eleven preview-served assets match the frozen manifest; the applied
  security headers and real missing-path 404 response pass.
- Browser checks cover keyboard Enter/Space Hide/Show, the no-script fallback,
  and the reduced-motion fixture (automatic scrolling and zero transitions).
- Widths 320, 390, 521, 800 and 1280 have no page overflow. The 521px inspection
  prompted a readability repair: workspace cards stack through 700px.
- Desktop and phone screenshots are retained in the chat's visualization folder.

Physical phones, other browser engines and screen-reader speech are untested.
The existing privacy policy and analytics capture scope are unchanged.

## Publication

The new manifest is `release-manifest.json`. The public host and Worker are the
existing `radhouse.runningdigitally.com` and `radhouserunningdigitallycom`.
No DNS, access, bindings, VM or private application change is included.
Retain the verified pre-release public archive and deployment identity before
upload. Follow the existing hosting contract: review, merge, then upload only
`public/` from merged source. Verify both endpoints, served hashes, headers,
actual 404 status and visible browser interactions after publication.

Publication is pending Cloudflare sign-in. A login tab has been left for the
owner. Do not describe this preparation as a public deployment.
