# Radhouse browser-feature homepage update

Prepared 8 October 2026 UTC from reviewed main
`bfb66f309cfb9e7bc4b872c7c7b68acbc7866342`, in an isolated checkout. The owner
asked for a separate agent to update the live homepage with the browser feature.
The original checkout's unrelated dirty brand, site and application work is
preserved. This is a bounded D1 site presentation and content release; it changes
neither the private application nor its browser-control contract.

## Scope and acceptance

The private pilot now provides selective reads from large attached documents
and a live view of the same browser the assistant uses. The owner confirmed
that their 50 MB PDF and browser tests both worked as expected. The homepage
replaces its obsolete tools-disabled notes with these available capabilities.

A small browser illustration uses the existing paper, green and serif styling.
Its native disclosure demonstrates Hide/Show by hiding only the illustration.
It explicitly says that no live session is connected on the public page.
Human mouse/keyboard takeover and return of control are labelled planned;
neither an implemented lock, login handover nor an action timeline is claimed.
The existing vision, conversation notebook, brand, security headers and approved
public analytics policy are preserved. Existing project links now use main.

Changes are limited to `site/public/index.html`, `site/public/styles.css`, the
public-file release manifest, their site documentation and minimal root README/
ROADMAP current-status corrections. Those companion documents now agree with
the advertised pilot, while preserving the requirement to qualify other
installations. No extra Worker,
DNS, access, bindings, VM or privileged runtime change is part of this release.

## Verification and release gate

JavaScript syntax, all four existing analytics-policy tests, all three brand
consistency tests and Git whitespace checks pass. Browser checks cover native
Enter/Space Hide/Show, the no-JavaScript fixture and reduced-motion fixture.
Closing the disclosure sets its content visibility to hidden and retains the
illustration disclaimer. Widths 320, 390, 800 and 1280 have no horizontal page,
feature-panel or disclosure-heading overflow. Desktop and narrow screenshots
are retained in the task's temporary evidence. HTML IDs, ARIA/anchor references,
local assets and safe external-link attributes are verified.

The first GitHub Codex cycle on `34873fa2c7976dbdf4ce8f87a6b92103900c25aa`
found two P2 issues: insufficient contrast in the new small eyebrow, and a
contradictory current-build README destination. The eyebrow now uses `#934826`
on `#f3efe5` (5.72:1); other new small-text colors reach at least 4.88:1.
The README's stale tools-disabled and unqualified-deployment statements are
corrected using the verified private-pilot evidence. A new exact-head GitHub
Codex review is required after these corrections.

The second cycle on `f38cd24e432fd1801d0c7dba09e76465a2d33b25` found the README's
remaining pre-deployment setup paragraph and the linked roadmap's old selective-
access qualification sequence. The setup instruction now explicitly applies to
other installations; the roadmap records delivered, qualified and active pilot
progress and distinguishes remaining qualification from the live browser view.
The complete README/roadmap and homepage link destinations were checked for
contradictory current-state claims before the next exact-head review.

Publication requires the GitHub Codex review cycle to complete for the exact
source head, then a normal merge. Upload `public/` from that merged source to
the existing `radhouserunningdigitallycom` Worker. Verify all served public files
against `release-manifest.json`, the unchanged security headers and actual 404
status; then check the live browser section and native Hide/Show in the browser.
If review is unavailable, retain the prepared preview and do not report a public
deployment as complete.

## Destination and rollback

The existing Cloudflare account's dashboard was inspected. It identifies Worker
`radhouserunningdigitallycom`, custom domain `radhouse.runningdigitally.com`,
worker URL `radhouserunningdigitallycom.connect-a95.workers.dev`, zero bindings
and static-file upload deployment. The known-good active version begins
`2e42913b`; full deployment identity is retained with the task's publishing
receipt when exposed by the dashboard.

All eleven previously served public files match the committed 6 October release
manifest, including the actual 404 response. `_headers` is verified through its
applied response policy. The unchanged pre-release `site/public/` archive is
retained at `/private/tmp/radhouse-homepage-rollback-20261008.tar`, SHA-256
`837205a99262c09063da25fab4096030475633a7aa8aa5926a4a2260e7779fca`.
Use the previous deployment or upload that archive through the same uploader
if verification fails. Keep the same domain, access and bindings.
