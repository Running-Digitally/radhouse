# Radhouse public website: workspace, platform icons and character gallery

Prepared 8 October 2026 (Toronto) from public `main` at
`2902155c5a2dd883b371649f00471f3f2190f35a`. The owner requested a review of
“Review Radhouse rework status” and “Assess worktree readiness” followed by
changes to the public website, then requested platform icons and a visual
popup gallery of avatars and themes. The latter linked chat covers RiseWithMe;
this release uses the Radhouse evidence only. The primary checkout has separate
unfinished work, so this update uses an isolated branch.

## Content and evidence

The current public page still labels human browser takeover as planned. The
Radhouse release branch at `bc2ed65` records browser control and saved-logins
activation on 8 October, with production Open/Go/reload/Close acceptance after
`7ac0630`. The page describes on-demand opening, human control, return after
the assistant reply, page sharing and the distinction between Hide and Close.
Library and selective document reads remain part of the pilot description.

PR77's owner-workspace release adds About You, Terminal, opt-in terminal context
and engine-driven model/thinking choices. Its source qualification recorded
1,072 tests and 11 browser journeys. Release qualification completed on
8 October for source revision `e8ce1e24ef01aa413a0d197a078374a06f972f0f`.
The verified activation supersedes the earlier pending-deployment status.
The workspace cards
say “New in the private pilot”. Thinking choices depend on the connected engine.
Read-only memory does not imply editing or proof that every saved note was used
in a reply. No private runtime operation is part of this website change.

The accepted Agent Identity design at `d221bec` supplies four collections:
Hearthside, Kiln Club, Paper Trails and Signal Station, with thirteen characters.
One compact Visuals card sits alongside the workspace features. Its four
groups each show three 44px portraits and open the matching collection in the
existing native popup, with all thirteen characters and short stories. The
large standalone heading and four separate collection cards are removed.
The card is labelled a design preview; working identity settings remain the
next private-app step. The mobile address/search bar and
Send-during-reply research are omitted.

The site's action and feature icons reuse the exact `RadhouseIcons` module and
stylesheet from the qualified platform source at `bc2ed65`. The extraction
excludes the application navigation bootstrap. Original artwork is unchanged;
640px WebP previews total 695,498 bytes. Source revisions and original/export
hashes are pinned in `ASSETS-2026-10-08-GALLERY.json`.

Public “Read the pilot build” and release links point to `codex/browser-handover`,
which contains the qualified browser and workspace source. The older runtime
implementation in `main` is not changed by this content release.

## Scope and verification

Public HTML/CSS, two gallery/glyph scripts, thirteen portraits, the supplied
Google search screenshot, the 30-file release manifest, preview fixtures and site
documentation change. The notebook,
house SVGs, analytics and response headers retain their existing bytes. The
browser preview uses the owner's real Google search screenshot for Running
Digitally. The 2202 × 1170 PNG is copied unchanged (315,746 bytes), preserves its
aspect ratio and has descriptive alternative text. Native Hide/Show controls
remain available without JavaScript, with explanatory handover text below.

- JavaScript syntax checks pass; four analytics-policy and three brand tests pass.
- HTML IDs, ARIA/anchor references, local assets and external-link attributes pass.
- All 29 preview-served assets match the frozen manifest; applied security
  headers and the real missing-path 404 response pass.
- Browser checks cover all thirteen portrait selections, collection changes,
  previous/next wrapping, group arrow/Home/End navigation, native modal focus
  containment, Escape, backdrop dismissal and focus return to the opener.
- The compact card has four theme links, each with three 44px portraits. All
  four open their matching popup collection and return focus to the opener.
  Each of the twelve portraits has its own fixed hover area and playful
  lift/tilt response. Only the hovered portrait moves; its neighbours stay
  still. Theme links retain keyboard access to the popup. Reduced motion
  keeps resting transforms and removes transitions.
- Four static disclosures expose thirteen portraits without JavaScript.
  Reduced-motion checks confirm disabled glyph motion, no dialog animation,
  zero portrait transition and automatic scrolling.
- Widths 320, 390, 521, 700, 800 and 1280 have no page overflow. The narrow
  popup scrolls vertically with a sticky close button and no horizontal overflow.
- The Google screenshot loads at its original dimensions, stays within the
  card at desktop and phone widths, and Hide/Show responds to click and keyboard.
- Chrome reports no site console errors; extension warnings are unrelated.
  Desktop and phone screenshots are retained in the chat's visualization folder.

Physical phones, other browser engines and screen-reader speech are untested.
The existing privacy policy and analytics capture scope are unchanged.

## Publication

The new manifest is `release-manifest.json`. The public host and Worker are the
existing `radhouse.runningdigitally.com` and `radhouserunningdigitallycom`.
No DNS, access, bindings, VM or private application change is included.

Both public endpoints' eleven served baseline assets and real 404 body were
verified against public `main`. The pre-release archive is retained outside
Git at `/private/tmp/radhouse-public-pre-workspace-20261008.tar`, SHA-256
`4fcb24f6aea7f95490a7622d95f9eea5d3ac86a062b82458fc18df09b5e2454a`.
Retain the existing deployment identity before upload. Follow the existing
hosting contract: exact-source-head GitHub Codex review, normal merge, then
upload only `public/` from merged source. Verify both endpoints, served hashes,
headers, actual 404 status and visible browser interactions after publication.

PR79 holds the prepared update. Publication is pending Cloudflare sign-in and
the owner's answer to the request to post the required GitHub Codex review
comment. A login tab has been left for the owner. This preparation is not a
public deployment.
