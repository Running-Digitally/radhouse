# Robot avatar prototype

A reusable Blender robot bust with three short, silent reactions for small web
profile pictures. This is a standalone proof of concept; it is not wired into
the Radhouse application.

## Start here

- `index.html`: the current three-reaction preview, including 48, 80 and 128 px views.
- `v2/`: the approved **A · Curious** design and six-second animation.
- `variants/`: **B · Thoughtful** and **C · Playful**, five seconds each.
- `variants/manifest.json`: shared poster, asset paths, durations and idle wait range.
- `variants/player.mjs`: the preview playback controller.

All web clips are 256 × 256 at 24 fps, with H.264 MP4 and VP9 WebM alternatives.
The background is opaque sage. Each reaction returns to the same neutral pose,
so the player can hold still for a random 2–6 seconds after playback, then choose
the next reaction from a shuffled group without an immediate repeat. The preview
pauses in hidden tabs and starts paused when reduced motion is requested.

The avatar uses modeled ivory eyes, brown irises, dark pupils, catchlights,
separate eyelids, gaze-first head movements and small antenna follow-through.
The approved A assets are protected by `variants/keeper-manifest.json` hashes.

## Preview locally

From this directory:

```sh
python3 -m http.server 8873 --bind 127.0.0.1
```

Open <http://127.0.0.1:8873/>. If the port is already occupied, use another port.
Serve over HTTP because the preview loads its manifest as a module resource.

`index-v2.html` preserves the original reference / first model / approved model
comparison. `index-v1.html`, the root-level Blender model, scripts, videos and
`README.txt` describe the initial four-second experiment. Use **v2** and
**variants** for the approved three-reaction set.

## Edit or rebuild

Open `v2/robot-avatar.blend`, `variants/robot-b-thoughtful.blend`, or
`variants/robot-c-playful.blend` in Blender. The scenes are self-contained; no
external models, textures or add-ons are needed. The Python scripts preserve
reproducible geometry, materials and animation. Detailed controls and original
build commands are in `v2/README.txt` and `variants/README.txt`.

Production used Blender 5.2.1 LTS with Apple Metal, Python 3 and FFmpeg/FFprobe.
The render scripts select Metal; choose an available render device if running on
another platform. With `blender` on PATH, rebuild B and C from the approved A:

```sh
blender --background --factory-startup --python variants/make_variants.py
blender --background --factory-startup --python variants/render_all.py
python3 variants/export_variants.py
```

Rendered PNG sequences, Blender backup files and local server/render logs are
excluded from Git. Rebuilding outputs can differ across Blender versions and
hardware; the committed clips retain the approved appearance.

## Validation and scope

The included validation reports check shared neutral transforms and eyelid
controls, eye-first timing, iris bounds, blink closure, and circular framing.
The export reports verify codecs, resolution, frame counts and durations. The
first and last **poses** match; video compression can introduce small pixel
variations. Prior browser review verified the automatic shuffled sequence and
random rests. Manual buttons in the latest player were not confirmed during
that review; this limitation is recorded in `variants/delivery.json`.

This is a rigid portrait rig with editable eyes, lids, head and antenna. Talking,
walking and application-state integration are outside this prototype.
