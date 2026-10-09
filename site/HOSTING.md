# Radhouse public site hosting

Updated 6 October 2026. Owner: Satish. The owner approved the reviewed redesign,
Personal PostHog verification, GitHub merge and Cloudflare public rollout.
The frozen artifact is recorded in `release-manifest.json`. The owner requested
the live-browser feature update on 7 October; its bounded source and publication
scope is recorded in `RELEASE-2026-10-08-BROWSER.md` (UTC preparation date).

The owner requested a further current-build update on 8 October (Toronto).
[Its release receipt](RELEASE-2026-10-08-WORKSPACE.md) records the browser-control
evidence, activated workspace status, platform icons, character gallery and
publication checks.

## Hosting contract

| Concern | Value |
| --- | --- |
| Public URL | `https://radhouse.runningdigitally.com/` |
| Hosting | Cloudflare Workers Static Assets |
| Existing Worker | `radhouserunningdigitallycom` |
| Worker URL | `https://radhouserunningdigitallycom.connect-a95.workers.dev/` |
| Source root | `site/` |
| Build command | none |
| Upload root | contents of `site/public/`, with `index.html` at root |
| Access | public and unauthenticated |

The Worker name is corrected from this document's earlier proposed `radhouse`
name. The current name and endpoint are recorded in the infrastructure placement
reference, `Homelab-Documentation/configuration/cloudflare/radhouse-website-hosting.md`,
and the parent release handoff. The Cloudflare dashboard was independently inspected on 6 October in the
owner's existing account. It names the same Worker and links its custom domain
to `radhouse.runningdigitally.com`. Its existing static-file uploader supplies
routine content releases.

Radhouse is independent of the `runningdigitally` Worker. It is not a Pages
project, an OpenAI Site or a homelab origin. Routine releases don't require
changes to DNS, access, bindings or any other Worker.

## Validate the artifact

There is no compilation. HTML, CSS, JavaScript, SVGs, PNG screenshots, WebP portraits and the pinned, licensed
PostHog SDK are committed as the deployable artifact. Run the targeted checks
in [README.md](README.md), review desktop and narrow layouts and exercise
keyboard, reduced-motion, disclosures, error recovery and external links.
Serve with `python3 site/preview.py` to test the actual security headers.

Only the exact public hostname collects production analytics. A loopback
preview requires `?analytics=preview`; that parameter is removed from captured
URLs. The Worker endpoint does not collect production events. PostHog uses
https://posthog.sati.sh, Radhouse-specific browser persistence and production/
preview labels. See README for masking and collection details.

The prior claim of no third-party requests describes the old production page.
The refresh adds owner-approved public analytics and replay. `_headers` allows
scripts only from the site and connections only to the personal PostHog host;
there is no inline-script allowance. No application secrets, API credentials,
database, runtime variables or application server are needed.

## Release

1. Freeze the reviewed `public/` directory and record a per-file SHA-256 manifest.
2. Sign in to Cloudflare and open the existing `radhouserunningdigitallycom`
   Worker. Confirm its custom domain is `radhouse.runningdigitally.com`.
3. Retain the current deployment ID for rollback.
4. Direct-upload all contents of `public/` as a new deployment, preserving the
   relative paths, including `characters/`, `vendor/`, `_headers` and `404.html`.
5. Verify the Worker endpoint first, then the custom domain. Compare every
   served artifact to the frozen manifest, including the response headers.
6. Check public interactions, anonymous project links, 404 status, PostHog
   events with `site=radhouse.runningdigitally.com` and `environment=production`,
   in personal project 1. Session replay viewing requires separate authorization;
   it is not a prerequisite for checking tagged ingestion.

No deploy configuration is added, and no second Worker should be created. The
owner authorized committing this review, opening a draft PR, merging it, and
performing the public Cloudflare rollout. Upload the artifact from merged source.

## Rollback

Promote the previous known-good deployment in this Worker's deployment history
when available. If the static uploader does not expose its prior deployment ID,
retain a verified archive of the pre-release public files and restore it through
the same uploader. Keep the same custom domain, DNS, bindings and access. Verify
both endpoints and served hashes again after rollback.

## DNS cache troubleshooting

If an endpoint cannot resolve, compare public and local resolver answers before
changing anything. Negative resolver caches can persist after first attachment.
Don't create a local DNS override or alter the public route as a content-release
workaround. Any resolver or host action belongs to a separate diagnosed issue.
