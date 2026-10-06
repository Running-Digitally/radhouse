# Radhouse: a private agent, a place of your own

6 October 2026. Local review at http://127.0.0.1:8931/?analytics=preview.

## Owner direction

Keep the hero's message, make its visual more creative, and draw from sati.sh
and Running Digitally. Give the vision more prominence: a private, always-on,
open-source agent designed around security, privacy and clear boundaries.
Make the smaller beginning and current build sections shorter and improve
their appearance.

## Design and content

Both [sati.sh](https://sati.sh/) and
[Running Digitally](https://runningdigitally.com/) were inspected in the browser.
Their mixed sans/italic serif headings, warm paper, tilted physical objects and
deliberate reveals inform this revision. No artwork or assets were copied.

The previous diagram is replaced with a notebook: a stitched margin, layered
pages, cloth-colored cover, bookmark and a small garden sketch tie the visual
to the continuing conversation. The notebook stays fixed across all four
stages. A time marker and day/night scene change when the visitor steps away;
a small paper note holds the follow-up when they return. The notes leave the
earlier question and reply readable. Motion is finite and user-triggered.
The scene has a changing accessible description and the existing keyboard
controls. The hero headline and explanatory copy retain their meaning.

“Always there. Still yours.” introduces the vision. Three principles describe
ownership of the environment and data, enforced limits on files/tools/network
access with inspectable permissions, and open-source code that can be adapted.
These are explicitly the principles guiding the build, not a security audit or
a claim that the early pilot already implements the entire vision.

The owner's reference products are linked in a short positioning paragraph:

- [Grok Bot](https://x.ai/bot).
- [Meta's Muse](https://about.fb.com/news/2026/09/introducing-muse-personal-ai-agent/).
- [OpenAI's Dots](https://help.openai.com/en/articles/20001529-dots-privacy-security-and-safety-faqs).

Official sources were checked for names and category context. The page presents
Radhouse's direction without claiming measured security superiority, equivalent
features or affiliation with those products.

The previous two large build sections become one compact, pale-green note with
two columns. A single native disclosure preserves the recorded pilot scope,
tools-disabled state, attachment and streaming work still to qualify, and the
distinction between self-hosting the app and sending data to a model provider.
The earlier [web scope receipt](REVIEW-2026-10-06-WEB-ONLY.md) retains the source
and deployment evidence behind those statements.

## Checks

Evidence is saved under ignored `outputs/review-20261006-vision/`:

- All four stages at actual widths 320, 390, 521, 600, 800, 801, 1101 and
  1440. No horizontal page overflow, one exposed reading panel, stable scene
  and overall interaction height at each width. A narrow-width panel height
  issue was corrected and both affected widths rechecked.
- The returning and away notes do not cover either conversation entry.
- Left/Right, Home/End, Tab and Enter navigation, next-action focus retention
  and updated live announcements. The pilot disclosure opens by keyboard at
  width 390 without overflow.
- Reduced-motion fixture: zero transition durations and automatic scrolling.
  Ordinary scene: no CSS animation, only finite transitions of at most 650 ms.
- Unenhanced fixture: no scripts, hidden inactive controls, prose explanation
  and 18 usable navigation/reading links.
- Unique IDs and valid references; local assets and safe external-link
  attributes; exact source/served hashes and security headers; public links;
  normal desktop, narrow and full-page screenshots.

Four analytics-policy tests and three brand tests pass. JavaScript syntax and
Git whitespace checks pass. The vision section is included in existing section
and outbound-link analytics; the approved capture/privacy policy is unchanged.
Nine public destinations returned HTTP 200 to the link checker. Grok Bot and
the Dots help page returned 403 to that automated client; both were successfully
retrieved through the web tool and supplied the linked primary-source content.

Reduced-motion and no-JavaScript checks use isolated source-backed fixtures.
Physical phones, other browser engines and screen-reader speech are untested.
Private PostHog dashboard verification remains pending the earlier permission
request. This revision does not depend on that access.

Only `site/` changed. The 23 unrelated dirty/untracked files remain byte-identical
to the initial snapshot. Branch `fix/project-deploy-after-cancelled-review`,
HEAD `64c75cd8b6676226a148fb2efd83c30bc531daff`. No public deployment, commit,
push, pull request or branch switch.
