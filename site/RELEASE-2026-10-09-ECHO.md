# Public Echo reactions

Requested 9 October 2026 (Toronto). The owner asked the public website to use
the same Echo videos and neutral → random 2–6 second wait → random A/B/C motion
→ neutral photograph cycle. Work starts from current remote main at
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

`echo.js` shuffles all three clips, prevents immediate repeats, decodes the next
clip behind the neutral image, and plays it once after each random rest. The
neutral photograph stays visible until playback starts and returns immediately
when the clip ends. Videos are silent, inline, decorative and without looping.
Echo appears consistently in the Visuals card, gallery thumbnail, large gallery
portrait and static disclosure. Card and gallery Pause/Play controls affect all
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
- The focused Chrome walkthrough observed B, C, A playing once each after
  separate 3,000 ms rests, with a neutral image between clips and no repeats.
- Boundary random values verify rests at 2,000 ms and just below 6,000 ms.
- Pause/resume, portrait replacement, close cleanup, Escape focus return,
  reduced motion and offscreen suspension pass. Media failure and autoplay
  rejection retain the neutral image; no-JavaScript disclosure uses that image.
- Page and gallery have no horizontal overflow at 320, 390, 700 and 1280 px.
  Desktop card and gallery, and narrow gallery were visually inspected.
- The walkthrough reports zero page errors. Media copies match their originals
  exactly, including the approved A hashes.

Self-review found no blocking issues. It checked timer cancellation, late play
promises, shuffled selection after interrupted rests, gallery cleanup, video
geometry, decorative semantics, same-origin media policy and static fallbacks.
Physical phones and other browser engines are untested.

## Publication

The prior Cloudflare version is `9361ae8b`, independently observed as Ready at
100% on the existing `radhouserunningdigitallycom` Worker. Its attached custom
domain is `radhouse.runningdigitally.com`; it has zero bindings.
The baseline source and current public files are checked against the prior
manifest before upload. Rollback source is retained in
`/private/tmp/radhouse-public-before-echo-20261009.tar`.

The new `release-manifest.json` freezes the deployable `public/` folder. Upload
only that folder, then verify all served files, response headers, 404 bodies and
live Echo playback on the Worker endpoint and public domain. Publication
verification will be appended after the deployment completes.
