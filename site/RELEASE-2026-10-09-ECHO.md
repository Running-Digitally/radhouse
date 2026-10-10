# Public Echo centerpiece

Requested 9 October 2026 (Toronto). The owner asked the public website to use
the approved Echo videos, continuously playing random A/B/C videos with no
wait, between two smaller static robot companions. The reviewed Visuals card
uses the same icon, numbered label, heading and body structure as the other
three workspace cards, with a compact identity preview below the copy.
Only Hearthside, Kiln Club and Signal Station remain in the public preview.
Work starts from remote main at
`e360876896d5eee4d88ba2642d9aeef0ec66947f` in an isolated checkout.

## Assets and behavior

Seven files in `public/characters/` are byte-identical copies of the approved
`brand/robot-avatar/` media:

| Public file | Source |
| --- | --- |
| `echo-neutral.png` | `v2/robot-poster-256.png` |
| `echo-a.mp4`, `echo-a.webm` | `v2/robot-idle-256.mp4`, `v2/robot-idle-256.webm` |
| `echo-b.mp4`, `echo-b.webm` | `variants/robot-b-thoughtful-256.mp4`, `variants/robot-b-thoughtful-256.webm` |
| `echo-c.mp4`, `echo-c.webm` | `variants/robot-c-playful-256.mp4`, `variants/robot-c-playful-256.webm` |

These copies total 388,002 bytes. A is six seconds; B and C are five seconds.
The original A assets and source Blender scenes are unchanged.

The fourth workspace card has the shared header structure: icon, `04 / Identity`,
`Visuals.` heading and description. A compact preview row shows the 72 px Echo
video between static 24 px Beacon and Orbit portraits, with its name alongside.
Hearthside and Kiln Club each have one small portrait and a theme link beneath.
The quiet footer pairs the design-preview label with the Pause/Play control.
Narrow containers wrap the preview label and reduce theme swatches to fit.
Paper Trails is removed from the card, gallery and static disclosure, leaving
three collections and ten characters. Opening Signal Station selects Echo
directly in the gallery.

`echo.js` shuffles all three clips, prevents immediate repeats and preloads each
reaction. The next clip starts as soon as the current one ends; the outgoing
final frame stays visible until the incoming video is playing. Each video plays
once, with the player continuously selecting the next reaction. Videos are
silent, inline and decorative. The neutral photograph appears during initial
loading, pauses and unavailable media. Echo animates in the card and large
gallery portrait; gallery thumbnails and the disclosure remain static.
Card and gallery Pause/Play controls affect all
Echo players. Reduced motion, the existing appearance preference, offscreen
portraits and hidden documents suspend automatic playback. Gallery dismissal
or selecting another character releases the corresponding player. Load errors,
autoplay rejection and prolonged buffering leave the neutral photograph.

The public policy adds only `media-src 'self'` for these local files. Existing
analytics configuration, script/connect destinations and other headers retain
their prior settings. Publication targets the existing Radhouse static Worker.

## Validation and self-review

- JavaScript syntax and Git whitespace checks pass.
- Four analytics policy tests and three canonical brand tests pass.
- The focused Chrome walkthrough observed continuous B, C, A, B playback,
  including the shuffle boundary, with no immediate repeats. All handoffs were
  below 3 ms in the initial revised run; the check requires less than 250 ms.
- Each transition retains one visible video frame; there is no neutral flash
  or rest phase between reactions. Both companion portraits remain static.
- Pause/resume, portrait replacement, close cleanup, Escape focus return,
  reduced motion and offscreen suspension pass. Media failure and autoplay
  rejection retain the neutral image; no-JavaScript disclosure uses that image.
- Page and gallery have no horizontal overflow at 320, 390, 700, 1000, 1001 and
  1280 px, including both sides of the four-column breakpoint. Desktop and
  narrow card and gallery were visually inspected. All four desktop cards have
  aligned card edges, category labels and headings; only three theme links and
  gallery choices remain.
- The walkthrough reports zero page errors. Media copies match their originals
  exactly, including the approved A hashes.

Self-review found no blocking issues. It checked buffering watchdog cancellation,
late play promises, shuffled selection after interruptions, gallery cleanup,
video geometry, decorative semantics, same-origin media policy and static fallbacks.
Physical phones and other browser engines are untested.

## Local review and publication

The updated local preview is at `http://127.0.0.1:8934/#characters`. PR #86 is
open at https://github.com/Running-Digitally/radhouse/pull/86. The owner requested
local design review before merging or publishing. This update has not been
merged or deployed.

The prior Cloudflare version is `9361ae8b`, independently observed as Ready at
100% on the existing `radhouserunningdigitallycom` Worker. Its attached custom
domain is `radhouse.runningdigitally.com`; it has zero bindings.
The baseline source and current public files are checked against the prior
manifest before upload. Rollback source is retained in
`/private/tmp/radhouse-public-before-echo-20261009.tar`.

The new `release-manifest.json` freezes the deployable `public/` folder. After
design review and release authorization, upload
only that folder, then verify all served files, response headers, 404 bodies and
live Echo playback on the Worker endpoint and public domain. Publication
verification will be appended after the deployment completes.
