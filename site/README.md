# Radhouse public site

The source for https://radhouse.runningdigitally.com/, separate from `web/`,
the authenticated operator application. The October refresh was approved for
public rollout on Cloudflare. Its frozen files are in `release-manifest.json`;
[release preparation](RELEASE-2026-10-06.md) records the verified analytics target
and release scope.

The page leads with the vision: a private, always-on, open-source agent with
clear security boundaries, running on infrastructure the owner controls.
The private pilot is a compact development note below the vision. Browser
now describes qualified owner control, return and saved logins. A separate
workspace section describes Terminal, About You and model controls activated
in the private pilot on 8 October. Agent Identity remains a design preview, presented in
one compact Visuals card with the same icon, numbered label, heading and copy
structure as the other workspace cards. A small Echo preview row places Beacon
and Orbit as static portraits on either side, with Hearthside and Kiln Club
links beneath. Paper Trails has been removed from the public preview. Each theme
opens the ten-character popup gallery; working identity settings are the
next private-app step. [The update receipt](RELEASE-2026-10-08-WORKSPACE.md) records the evidence.
Echo uses the approved Blender neutral photograph and A/B/C reactions in the
Visuals card and featured gallery portrait. Silent A/B/C clips play continuously
in shuffled order without pauses or immediate repeats. All three clips preload,
and the previous final frame remains visible until the next clip starts.
Gallery thumbnails remain static. Pause/Play controls, reduced motion, hidden tabs and offscreen
portraits suspend playback; unavailable media retains the neutral photograph.
[The Echo release receipt](RELEASE-2026-10-09-ECHO.md) records sources and checks.
The hero keeps its original message and uses a tactile conversation notebook.
Talk, Reply, Away and Return move the scene from day to night and back while
the notebook stays in place. This is an illustration, not a live agent or a
product screenshot. Future capabilities are framed as the direction of the
build; current limitations sit in the pilot's native disclosure.

The browser feature section reflects the deployed private pilot: one shared
live view of the assistant's browser and Hide/Show controls. Its native disclosure
shows the owner's real Google search screenshot for Running Digitally, unchanged
and at its original aspect ratio. Hide/Show works without JavaScript; the caption
identifies it as a preview. The page explains qualified
human takeover, return and page sharing. The pilot note also describes selective
access to large attached documents.

## Preview

From the repository root:

```sh
python3 site/preview.py
```

Open http://127.0.0.1:8931/ for the ordinary preview, or
http://127.0.0.1:8931/?analytics=preview to explicitly enable preview analytics.
The server binds only to loopback and applies `public/_headers`, including the
production content security policy. It serves the actual error page with 404
status for missing paths.

`/__qa/reduced-motion` forces the source's reduced-motion CSS branch,
without changing the operating system.
`/__qa/no-js` serves the unenhanced HTML with its fallback explanation.
These preview-only fixtures aren't in `public/` and aren't uploaded.

## Files and checks

`public/` is the complete deployable artifact: HTML, CSS, conversation interaction,
analytics policy/loader, platform glyphs, character portraits and gallery,
brand SVGs, headers, error page and vendored PostHog SDK/license. No build or dependency installation is required.

```sh
node --check site/public/journey.js
node --check site/public/analytics.js
node --check site/public/platform-icons.js
node --check site/public/gallery.js
node --check site/public/echo.js
node --test site/test/analytics.test.mjs
.venv/bin/python -m pytest tests/test_brand_assets.py -q
git diff --check -- site
```

The focused video/gallery browser check uses the existing Playwright runtime;
no site dependencies or build are needed:

```sh
RADHOUSE_PLAYWRIGHT_MODULE=/absolute/path/to/playwright/index.mjs \
RADHOUSE_BROWSER_CHANNEL=chrome \
RADHOUSE_BROWSER_ORIGIN=http://127.0.0.1:8931 \
node site/test/echo-walkthrough.mjs
```

The conversation example has a single next action and four keyboard-accessible stages.
Its tabs use Left/Right, Home/End and normal Tab navigation. Enter advances the
next action, retaining focus; the changed state is announced in a polite live
region. One reading panel is exposed at a time. Reduced motion removes the clock,
paper and day/night transitions while preserving the completed state. Static project
links, the first illustration and a full prose fallback work without enhancement.

The character gallery uses a native modal dialog, collection and portrait
buttons, previous/next controls and short character stories. Escape and backdrop
click close it; focus returns to the collection link. Arrow keys and Home/End
select within each button group. Three native disclosures expose all portraits
without JavaScript. Reduced motion removes gallery and glyph animation.

The platform glyph module is copied exactly from the qualified app source,
excluding the app navigation bootstrap. Thirteen original character PNGs are
resized to 640px WebP previews (695,498 bytes total); canonical artwork stays
untouched. [The asset receipt](ASSETS-2026-10-08-GALLERY.json) pins sources and
hashes. The gallery shows the accepted identity design, with no claim that
working identity settings have shipped.

Brand assets remain byte-identical copies of `../brand/`. The
[logo refinement](REVIEW-2026-10-06-LOGO.md) updates the canonical SVGs and their
website and operator-app copies together. See the
[vision review receipt](REVIEW-2026-10-06-VISION.md)
for the visual references, vision copy, checks and limits. The earlier
[web scope review](REVIEW-2026-10-06-WEB-ONLY.md) records the pilot evidence. The
[assignment review](REVIEW-2026-10-06-INTENT.md) preserves the article reference
and rationale. The original [house review](REVIEW-2026-10-06.md) is historical.
Current screenshots and browser records are under ignored
`outputs/review-20261006-vision/` and `outputs/review-20261006-logo/`.

## Analytics

The public browser ingestion configuration comes from the approved personal
PostHog integration on Running Digitally and sati.sh, project 1 at
https://posthog.sati.sh. Its project token and received Radhouse preview events
were confirmed in that project on 6 October. Filter by
`site=radhouse.runningdigitally.com` and `environment=production` for the public
site. It is separate from RiseWithMe analytics.

Production requires the exact hostname `radhouse.runningdigitally.com`.
Loopback requires explicit `?analytics=preview`; other hostnames, private
paths, DNT/GPC and the `radhouse-analytics-disabled` preference disable capture.
Browser persistence and consent keys are specific to Radhouse, with cross-
subdomain cookies disabled. No account identity is supplied.

Replay masks inputs and sensitive markers and blocks private content, editable
regions and iframes. Console recording, request bodies/headers, copied text and
network timing are disabled. The page has no input forms. URL credentials,
fragments and non-campaign parameters are removed from telemetry. Product
example, navigation, outbound links, disclosures, section views, reading depth
and web vitals complement pageviews, heatmaps and session replay.

`vendor/posthog-1.436.1.js` is the full, no-external SDK from the already
installed `posthog-js` 1.436.1 package used by the accepted RD preview. Only the
missing source-map directive was removed. It is covered by the adjacent Apache
license. Its SHA-256 is
`2c14307d97092d9587b5fdde4858437a8c970682d2c35a6158a3fb0afa6ccb96`.
Update it deliberately from the same pinned package, preserve the license,
and repeat the analytics and browser checks. No Matomo integration is present.

## Hosting

See [HOSTING.md](HOSTING.md). Upload only `public/` to the existing Cloudflare
Worker after the design is reviewed and release is authorized.
