# Radhouse interface language

Warm paper, green ink, clear actions and playful details that express what the
control does. The house-and-hearth mark remains the brand signature. This extends
[the brand](README.md) and the [first useful action principle](../PRINCIPLES.md).
The icon family and motion remain a review candidate: the owner has not approved
the other icons by saying they were okay in screenshots. Review motion in the
[interactive showcase](interface-preview.html).

## One original family

`src/radhouse/chat/static/navigation.js` contains the canonical SVG geometry and
motion. These original drawings are contributed under the repository's
Apache-2.0 license. No icon package, font, copied library artwork or external
request is needed. Named SVG parts keep motion tied to the glyph's meaning.

- Draw on a 24 × 24 grid with a 1.7-unit round stroke, round joins and currentColor.
  Most geometry fits inside 3–21; directional marks can reach 2–22. Agent chimney
  effects extend above the grid, with space reserved around the glyph.
- Render at 20px for actions, 21px in navigation, and 17–18px in dense controls.
  The showcase enlarges the same SVGs; it has no separate animation implementation.
- Green `#315d4b` marks selected and confirmed actions; muted ink `#526357`,
  paper `#fffef9`, soft green `#e9eee8`, and terracotta `#a75c34` form the palette.
- Keep 44 × 44px hit areas. The browser navigation row allows 40px-wide,
  44px-tall targets on narrow screens. Never move a hit target during animation.
- Keep labels on handoff, closure and saved-login actions. Familiar compact
  controls have accessible names and supplementary hover/focus tooltips.
- Visible clipboard actions say **Copy**. Accessible names preserve **Copy answer**
  or **Copy code** so their context remains clear.

Refresh is a clean single arc and corner arrow. The key has a round bow, a small
hole and distinct stepped teeth. Browser has an active tab, navigation dot,
address field and page lines. Keyboard has individually drawn keys.

## Meaningful motion

Hover and keyboard focus preview the action. Click gives a fuller gesture.
Touch skips hover; activation still plays the click response. Effects run once
per interaction; ongoing loops are reserved for actual pending refreshes and
agent states. Actions run immediately and never wait for animation.

| Icon | Hover / keyboard focus | Click |
| --- | --- | --- |
| Menu | Write three lines in sequence | Fan the lines open and return |
| Chat | Write message lines | Trace the bubble, then write its lines |
| Library | Write folder content lines | Lift the tab, then write the contents |
| Copy | Write clipboard lines | A duplicate sheet peels away |
| Browser | Load page lines | Trace the active tab and address field before the page |
| Refresh | Re-ink the arc and tip | Full reload sweep; actual pending requests keep turning |
| Key | Trace the hole and teeth | Insert, turn, withdraw |
| Infrastructure | Blink LEDs and buzz two racks | Longer activity burst and vent strokes |
| Keyboard | Type four individual keys | Eight-key phrase, followed by the space bar |
| Eye | Natural blink | Close, hold, reopen and blink again |
| Check | Draw the short leg, pause, finish the long stroke | Replay the deliberate hand-drawn stroke |
| Close | Gather into a point and return with a small star | Collapse to a point, vanish in a star, redraw; no rotation |
| Settings | Opposite slider adjustments | Wider adjustment and return |
| Back / Go | Trace shaft and travel in the action's direction | Greater directional travel |
| Sign out | Trace the exit arrow | Arrow leaves the doorway and returns |
| Send | Draw the flight path | Plane flies away and a new plane arrives |
| Attach | Thread the paperclip | Full loop, then inner strand |
| Take control | Contact pulse at the pointer tip | Larger contact pulse |
| Warning | Trace the warning mark and pulse its dot | Two dot pulses |
| Terminal | Prompt, blinking cursor and a short typed command | Longer typing sequence |
| Share terminal context | Write output lines | Output packet travels toward the conversation |
| About You | Write saved-memory lines | Trace the read-only note and its contents |

Hover gestures take about 330–700ms; clicks take about 580–900ms. Staggered strokes
and pauses create character without translating the entire icon back and forth.
Surface transitions take 160ms. Focus uses a 2px warm outline with 3px separation.
Selected navigation includes `aria-current="page"`, a green surface and warm dot.
Disabled controls remain native disabled controls with 42% opacity and no motion.

Copy becomes a check with **Copied** only after `clipboard.writeText` resolves.
A polite live region announces success; denied writes show **Copy unavailable**.
Feedback resets after two seconds and keyboard focus is retained. The specimen's
check sample demonstrates geometry; the real copy control verifies acknowledgement.

## A stateful Radhouse agent

The house, chimney, hearth ring and central point adapt our own logo into one
recognizable agent mark. State is passed explicitly with `setAgentState`.

| State | Appearance |
| --- | --- |
| Ready | Still hearth and central point |
| Idle | Three little zzz drift from the chimney |
| Thinking | Curling chimney smoke and a breathing hearth point |
| Working | Chimney smoke and circulating ink around the hearth |
| Waiting | Gentle ellipsis inside the hearth |
| Paused | Still pause bars inside the hearth |
| Complete | Check inside the hearth |
| Error | Warning inside the hearth |

The empty conversation uses idle; saved replies awaiting dispatch use waiting;
a reply in progress uses the illustrative thinking cue; completed replies use
complete. Failure/interruption uses the attention cue. These presentation states
do not claim access to internal reasoning or VM utilization. Browser ownership
maps existing agent, takeover, paused and recovery states to working, waiting,
paused and error. Existing text remains the source of meaning and is available
to assistive technology. Decorative SVGs remain `aria-hidden`.

The showcase offers every state, a large selector and an illustrative journey.
Terminal, Share terminal context and About You are future icon studies only.
Their demo controls launch no VM session, send no terminal output and edit no
memory. The demo context switch starts off; Hide and Close illustrate their
separate meanings. Implementation of those features belongs to the next release.

## Appearance and reduced motion

**Settings → Appearance → Icon animation** enables or disables all icon motion,
including agent-state loops, hover, keyboard focus, click, success and pending
refresh. The same switch is available in the showcase. Default is on; the device's
`prefers-reduced-motion` setting always suppresses animation, even when the saved
switch is on. Static smoke, zzz, ellipsis, pause, check and warning cues remain
visible, as do control labels, colors and status updates.

The preference is local to this browser, stored as `on` / `off` under
`radhouse.appearance.icon-animation`, and synchronized across tabs with storage
events. Turning it off immediately cancels in-flight Web Animations and stops CSS
loops. Storage failure applies the choice to the current page and tells the user
it could not persist. This changes no server settings, permissions or account
configuration. Instance settings remain read only.

## Browser composition and behavior

Back, Refresh, editable address, Go and a view toggle occupy the first row.
Concise ownership and connection status sit beside labelled Take control,
Return to agent and Close browser actions. The live page occupies the full inner
width without the previous 420px desktop height cap. Real aspect ratio and
letterboxing preserve frame-to-page coordinate mapping.

Typing and saved logins sit below the viewport. Longer explanations appear for
pending handoff, a finishing reply or unconfirmed input; normal ownership text
stays available to assistive technology. The Eye control stays in the header so
it remains available when the view is hidden. On mobile, ownership wraps while
address controls remain on one row. Navigation retains modal focus, Escape,
backdrop dismissal and the user's collapse preference.

Preserve inert launch until explicit Open, status-only reconnection, retained
URL drafts, acknowledged actions without uncertain replay, authenticated
tab/lease/frame binding, browser-only pause, same-page handoff, native vault
restrictions and positive Close. Hiding stops frame reading and preserves the
browser. Close ends the browser session. APIs and runtime permissions remain
the authority; this design introduces no backend or credential changes.

## Use and validate

```js
RadhouseIcons.decorate(copy, "clipboard", "Copy", {accessibleLabel: "Copy answer"});
RadhouseIcons.decorate(back, "back", "Back", {compact: true});
RadhouseIcons.busy(refresh, requestPending);
RadhouseIcons.setAgentState(agent, "thinking");
settings.append(RadhouseIcons.appearanceControl());
```

Load `navigation.js` before consumers and `navigation.css` after base styles.
BrowserView and the formatter retain text fallbacks for standalone hosts.
Serve the repository with a static server and open `brand/interface-preview.html`.
The showcase uses production components with an in-memory browser adapter and
synthetic pixels. It launches no native browser or production API request.

Run the relevant checks with an existing Playwright installation; set
`RADHOUSE_PLAYWRIGHT_MODULE` to its `index.mjs` when this checkout has no dependencies:

```sh
node tests/interface-browser.mjs
node tests/navigation-browser.mjs
node tests/library-browser.mjs
node tests/browser-session-browser.mjs
node tests/chat-browser-view-browser.mjs
node tests/browser-view-browser.mjs
node tests/browser-login-removal-browser.mjs
```

The additional `minimal-chat-browser.mjs` integration is launched by
`test_minimal_chat_postgres.py` with an owned PostgreSQL/authentication fixture;
it cannot be run as a standalone static preview check.

Coverage includes semantic hover/click motion, typed keys, the nonrotating Close
star, agent states, acknowledged clipboard writes and keyboard focus, the real
Settings switch, persistence, cross-tab updates, storage denial, OS reduced
motion, 390/320px layout and touch targets. Existing browser journeys cover native
input, uncertainty, vault handling, ownership, handoff, positive Close and frame
lifecycle. Tests use disposable synthetic accounts/pages, without production
runtime claims. Do not capture screenshots unless requested.

This branch starts from verified production source `7ac0630` on
`codex/icon-browser-design`. It remains a design review candidate, without
production activation. SonarQube sprints and GitHub review-comment cycles remain
paused.
