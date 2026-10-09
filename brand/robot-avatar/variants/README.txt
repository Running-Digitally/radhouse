ROBOT AVATAR / APPROVED A + THOUGHTFUL B + PLAYFUL C

A is the approved six-second Curious animation in ../v2, unchanged.
B and C are five seconds each, 24 fps, 256x256, silent, opaque sage background.
Both reuse A's exact model, eye materials, camera and lighting.

B / Thoughtful: downward glance, a considering pause, small nod, eye contact,
soft blink, return to neutral.
C / Playful: glance in the opposite direction, little double-take, head tilt,
antenna bounce, blink and return to neutral.

The first AND last exported frame of each variant match the approved neutral
pose. This is checked for all object transforms, pupil scales and eyelid values.
The matching pose allows holding a neutral frame between clips.

Assets
robot-b-thoughtful.blend / robot-c-playful.blend: editable source scenes.
robot-b-thoughtful-256.mp4 / .webm and robot-c-playful-256.mp4 / .webm: web clips.
../v2/robot-idle-256.mp4 / .webm: unchanged approved A.
../v2/robot-poster-256.png: shared still fallback.
manifest.json: all clip paths, durations and 2-6 second wait range.
validation.json: shared-pose, gaze, crop and iris checks.
keeper-manifest.json: SHA-256 hashes protecting the approved A assets.
delivery.json: verified video formats, sizes and durations.

Preview
The parent index.html plays the three clips in shuffled groups, with no immediate
repeat. It holds the neutral frame for a randomly chosen 2-6 seconds AFTER each
clip ends. Upcoming video is decoded behind the held frame before becoming
visible. Each clip plays once; video loop is disabled. The preview also offers
manual A/B/C selection, pause/resume, circular/square crops and 48/80/128px views.
Hidden tabs pause both movement and the rest countdown. Reduced-motion preference
starts paused; a manually selected clip plays once and pauses again.
player.mjs is the small standalone preview controller. Product integration has
not been performed. If a new clip is slow to load, the neutral frame is retained.

Reproduction
Run make_variants.py with Blender to generate both blend files and diagnostic
stills from ../v2/robot-avatar.blend. Then run render_all.py with Blender, and
export_variants.py with Python 3 and FFmpeg. Blender rendering uses the Mac Metal
device. No downloaded models, textures or add-ons are required.

The previous reference/v1/v2 comparison is preserved at ../index-v2.html.
