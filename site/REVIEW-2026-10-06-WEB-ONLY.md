# Radhouse public page: one private web conversation

Historical visual revision. The pilot evidence remains relevant; the
[current vision revision](REVIEW-2026-10-06-VISION.md) changes the presentation
and gives the long-term vision more weight.

6 October 2026. Local review candidate at
http://127.0.0.1:8931/?analytics=preview.
This supersedes the assignment illustration in
[the previous receipt](REVIEW-2026-10-06-INTENT.md).

## Accepted scope and evidence

The owner asked to remove Buzz integration and supplied the chat
**private product-scope review**, session
`private-session-id`, started 5 October 2026 at
12:56 PM EDT in `/path/to/private-workspace`.
The session retrieval skill verified its title, workspace and transcript
metadata. Recent and older visible turns were read through the app's thread
reader. The owner's accepted first slice is opening Radhouse, talking to one
assistant, closing the browser and returning later to the same conversation.

Grounding was checked against these local sources, read without editing them:

- `private-installation-record`.
- `private-installation-record`
  and its `deployment-proof.json` artifact.
- README, ROADMAP, PRINCIPLES, chat UI and service in
  `/private/tmp/radhouse-hermes-first-20261005`, branch
  `codex/radhouse-minimal-web`, source
  `2e7abde5b074ddeb1b71ba2466485c8006d94710`.

The later completed deployment record establishes the small private text pilot:
two real Hermes replies, including recall after the web app restarted, pinned
to that source on 5 October. It supersedes the branch README's earlier statement
that deployment was pending. The public page says what this recorded check
establishes; no live private runtime probe was performed for this website review.
It makes no claim about current runtime health, general release, or qualification
of every file format, image/audio path or tool. Private infrastructure details
from the change record are absent from the public artifact.

## Page and interaction

The headline and copy now introduce one assistant and a continuing private web
conversation. Buzz, agent assignments, fleet management and publication review
are absent from the page. Reading links point at the smaller build's exact source
and its branch, rather than older integration notes on main.

The hand-authored SVG uses the existing cream, green and clay palette. Every
movement explains the accepted journey:

| Stage | Visible meaning |
| --- | --- |
| Talk | An ordinary question is ready in the private browser window. |
| Reply | The message travels once; the exchange joins the saved conversation. |
| Away | The browser disappears. The earlier exchange and context stay in place. |
| Return | The browser returns with the earlier answer and a follow-up ready to write. |

The retained conversation has the same position across Reply, Away and Return.
One explanatory panel and one next action appear at a time. There is no autoplay
or ambient animation. The example sends no message and is explicitly labelled
as an illustration. The prior article's principle of purposeful, inspectable
detail is retained without borrowing its artwork.

The progress section reports the recorded pilot and distinguishes it from future
work. Native disclosures explain that saving an original does not establish
that the assistant has read it, that the live connection has tools disabled, and
that selective access, live image/document/audio checks and streaming/Stop remain
work to qualify.

## Verification and limits

Current evidence is under ignored `outputs/review-20261006-web-only/`:

- Layout: all four stages at actual widths 319, 390, 521, 600, 800, 1101,
  1280 and 1440, with no page/panel overflow or stage height change. Message
  text fits its boundaries and the saved conversation stays fixed.
- Keyboard: Left/Right, Home/End, Tab and Enter; one panel visible, focus retained
  on the next action, and a polite stage announcement. The three native
  disclosures also open by keyboard at width 390 without horizontal overflow.
- Motion: initial state has no animation, message delivery runs once for 0.7
  seconds, and reply appearance is finite. The source-backed reduced-motion
  fixture has no animation, zero transition duration and automatic scrolling.
- Unenhanced fixture: no scripts, inactive controls hidden, one initial panel,
  complete prose fallback and 16 reading/navigation links.
- Source: unique HTML/SVG IDs, resolving ARIA/anchor targets, present local
  assets, safe external-link attributes and absence of obsolete scope claims.
- Exact source/served hashes, security headers, custom 404 and public reading
  link responses are recorded alongside normal desktop and narrow screenshots.

The existing three brand tests and four analytics-policy tests pass, together
with JavaScript syntax and Git whitespace checks. Analytics now names the event
`conversation_example_step_selected`, recording stage and selection source.
The approved ingestion/privacy policy is unchanged.

Fixtures exercise source branches without changing OS preferences or disabling
browser JavaScript globally. Physical phones, Safari/Firefox and screen-reader
speech are untested. Private PostHog ingestion/replay inspection remains pending
the earlier dashboard permission request; this revision does not depend on it.

Only `site/` changed. All 23 unrelated dirty/untracked files match the initial
hash snapshot. The active branch remains
`fix/project-deploy-after-cancelled-review` at
`64c75cd8b6676226a148fb2efd83c30bc531daff`.
There was no public deployment, commit, push, PR or branch switch.
