# Radhouse interface language

The interface should feel like a quiet home for capable tools: warm paper,
green ink, clear actions and room for the work itself. The house mark remains
the brand signature. Interface icons keep familiar meanings rather than turning
every control into a house. This extends [the brand](README.md) and the
[first useful action principle](../PRINCIPLES.md).

The assistant mark adapts our own Radhouse house-and-hearth geometry into a
monochrome outline: a shelter, a protective circle and a central point. The
owner rejected the robot glyph and suggested a logo-inspired direction. This
is the current review candidate, not owner approval of the finished family.
Keep it beside an explicit agent label in ownership and handoff controls.

## One small, original family

The SVG paths in `src/radhouse/chat/static/navigation.js` are the canonical
interface collection. They are original drawings contributed under the
repository's Apache-2.0 license; no library paths, font, package or external
request is used. A custom collection makes sense here because the small set can
share one geometry and state treatment without shipping a much larger library.
Do not copy document-format artwork into this family: those assets identify
file formats rather than interface actions.

- Draw on a 24 × 24 grid with a 1.7-unit stroke, round caps and round joins.
  Keep most geometry inside 3–21; directional marks can reach 2–22.
- Use 2-unit corners for small rectangular containers. Keep internal detail
  sparse and open; do not fill strokes or add a second accent colour.
- Render at 20px for actions, 21px in navigation and 17–18px in dense secondary
  controls. Optical sizing changes the rendered size, not the stroke geometry.
- Inherit `currentColor`. Use green `#315d4b` for selected and confirmed actions,
  muted ink `#526357` for secondary actions, paper `#fffef9` and soft green
  `#e9eee8` for surfaces. The small terracotta navigation dot `#a75c34` links the
  selection treatment to the hearth in the house mark.
- Keep a 44 × 44px hit area even when the glyph is 17px. The browser's tight
  navigation row has 40px-wide, 44px-tall targets on narrow screens; never go
  smaller. Keep visible labels on expanded navigation, handoff, shutdown and
  saved-login actions. Mobile sign-out and familiar browser controls can use
  icons with explicit accessible names.

## Action states and motion

| State | Treatment and meaning |
| --- | --- |
| Default | Muted glyph, stable size, quiet surface; the label names the action. |
| Hover | Soft background. Back/Go move 2px in their direction, Refresh turns 35°, clipboard lifts 2px. This hints at the action. |
| Pressed | Glyph contracts to 90% with an inset surface; primary controls deepen to `#244638`. This confirms the physical press. |
| Focus visible | 2px warm outline with 3px separation; the same affordances work by keyboard. |
| Selected | Green glyph and soft surface plus `aria-current="page"` and a warm dot in navigation. |
| Disabled | 42% opacity; hover and activation give no action hint. Native `disabled` remains authoritative. |
| Pending | `aria-busy="true"`, progress cursor and disabled input where the existing workflow requires it. Refresh rotates only during its actual request. |
| Success | Clipboard becomes a check and “Copied” only after `clipboard.writeText` resolves; polite text announces success. Reset after two seconds. |
| Failure | Clipboard shows “Copy unavailable”; browser actions retain the existing unconfirmed/rejected-action message. Never animate a false success. |

Hover transitions last 160ms. Click responses settle over 280–480ms: directional
push and recoil for Back/Go, a lift for Library/clipboard, opposite slider travel
for Settings, arrow travel for sign-out, a contraction for Close and one hearth
pulse for the agent mark. A copied check draws in over 300ms after success. These
effects run on the SVG alone; they never delay an action or move its hit target.
Honour `prefers-reduced-motion`: suppress transforms,
transitions and rotation while retaining colour, labels and status changes.
Tooltips on pointer hover or keyboard focus supplement accessible names; touch
users must be able to identify consequential actions without a tooltip.
Do not put tooltips or SVG titles into the accessible name of a control.

## Browser composition

The first row is Back, Refresh, editable address, Go and a view toggle. The
second is concise ownership and connection status with labelled Take control /
Return to agent and Close browser. The live page occupies the full inner width
with no 420px desktop height cap. Keep its real aspect ratio and letterboxing:
visual redesign must not change frame-to-page coordinate mapping.

Typing and saved logins sit below the viewport. Longer explanations are reserved
for pending handoff, a finishing reply or unconfirmed input. The normal ownership
explanation remains available to assistive technology. On mobile the ownership
strip wraps, address controls stay on one row, and page-input controls wrap
below the viewport. The navigation drawer preserves its modal focus trap and
Escape/backdrop dismissal. Desktop keeps expanded labels and the user's collapse
preference. Chat keeps a stable composer and generous copy targets.

Presentation must preserve inert launch until explicit Open, status-only
reconnection, retained URL drafts, action acknowledgement and no uncertain
replay, authenticated tab/lease/frame binding, browser-only pause, same-page
handoff, native vault restrictions and positive Close. Existing APIs and runtime
permissions remain the authority. Hiding the view stops reading frames; it does
not close the browser. Close is always labelled and distinct from Hide.

## Use and inspect

```js
RadhouseIcons.decorate(button, "clipboard", "Copy answer");
RadhouseIcons.decorate(back, "back", "Back", {compact: true});
RadhouseIcons.busy(refresh, requestPending);
```

Load `navigation.js` before consumers and `navigation.css` after base styles.
The BrowserView and formatter retain text-only fallbacks for standalone hosts.
The family lives with the existing shared shell to avoid adding an asset API or
component framework.

Open [interface-preview.html](interface-preview.html) directly, or serve the
repository with an ordinary static preview server. It reuses the production
icons, formatter, CSS and BrowserView DOM with an explicitly labelled synthetic
page and an in-memory request adapter. It launches no Chromium or production
requests. Inspect at desktop width, 390px and 320px; try Open, handoff, Close,
copy, keyboard focus and reduced motion. This fixture demonstrates presentation;
the existing browser-session journey validates real Chromium input and handoff.

## Review and validation

This design slice starts from the verified production source `7ac0630` on a
separate `codex/icon-browser-design` branch. It is a visual review candidate;
the owner has not approved the complete icon family or motion. No production
activation is part of this slice. SonarQube sprints and GitHub review-comment
cycles remain paused.

Run the relevant browser checks with the existing Playwright installation:

```sh
node tests/interface-browser.mjs
node tests/browser-session-browser.mjs
node tests/chat-browser-view-browser.mjs
node tests/navigation-browser.mjs
node tests/browser-view-browser.mjs
node tests/browser-login-removal-browser.mjs
```

`RADHOUSE_PLAYWRIGHT_MODULE` can point to an existing Playwright `index.mjs` when
the isolated checkout has no local dependencies. `RADHOUSE_DESIGN_EVIDENCE`
saves the specimen and clipboard screenshots;
`RADHOUSE_BROWSER_SCREENSHOTS` saves desktop/mobile real-CDP journey screenshots.
The tests use disposable synthetic accounts/pages. The interface check covers
delayed and denied clipboard writes, confirmation timing, keyboard focus,
distinct hover/click animations, reduced motion, 390/320px layouts and touch
targets. The existing journeys cover native input, uncertain-input recovery,
vault handling, browser ownership, handoff, positive Close and frame lifecycle.
Targeted Python API/authentication/brand checks also passed (65 tests on
2026-10-08); browser fixtures do not qualify a deployed runtime.
