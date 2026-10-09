ROBOT AVATAR / GENERIC IDLE PROOF OF CONCEPT

Purpose
An actual editable Blender 3D bust, interpreted from the supplied robot portrait,
rendered into a small video that can be shown as an avatar in a web application.
The prototype prioritizes the silhouette, warm eyes and readable motion at
48-128 CSS pixels. It is an approximate likeness, not an exact reconstruction.

Review
Open index.html in a browser. It compares the reference to the animation and
shows the clip at 48, 80 and 128 CSS pixels, with circle and rounded-square crops.
It includes pause/play, reduced-motion handling and still-image posters.
The page works directly from its folder; an HTTP server is optional.

Deliverables
robot-avatar.blend       Self-contained 3D model, materials, lights and idle keys.
robot-idle-256.mp4        H.264 web export, 256x256, four seconds, 24 fps, silent.
robot-idle-256.webm       VP9 alternative with the same framing and timing.
robot-idle-master.mp4    384x384 higher-quality review export.
robot-poster-128.png     Still fallback for small avatars.
robot-poster-256.png     Still fallback for retina 128px avatars.
robot-still.png          768x768 larger still render.
robot-blink.png          Closed-eye pose check.
robot-side.png           View with the head turned, demonstrating 3D depth.
validation.json         Model controls, loop-boundary and framing checks.
delivery.json           Verified media properties and file sizes.
reference.png           The user-supplied reference, for comparison only.
build_robot.py           Rebuilds the model using Blender's built-in Python API.
render_robot.py          Renders still, preview or the idle frame sequence.
validate_robot.py        Checks controls/framing and renders diagnostic poses.

Controls and animation
CTRL_Robot              Moves the whole character.
CTRL_Body               Moves the torso and its attached head.
CTRL_Head               Local X: nod; Y: tilt; Z: turn.
CTRL_Gaze_L / R         Local X and Z move each pupil.
CTRL_Blink_L / R        Local Z scale: 1 open, .035 closed illuminated slit.
CTRL_Antenna            Secondary antenna movement.
CTRL_Shoulder_L / R     Separate rigid shoulders for future gestures.

The supplied idle animation uses small head rotations, a slow glance, an
electronic blink and a very small antenna movement. The eyes are rigid displays;
the blink squeezes the illuminated lens and pupil inside a stationary socket.
The reference did not define blinking, so this behavior is an interpretation.

Frames 1-96 are exported at 24 fps. Frame 97 repeats frame 1 and is deliberately
excluded. The validation script checks that the control transforms match exactly
at frames 1 and 97. It also checks the antenna stays inside the circular crop.

Making another state
Duplicate the blend file, retain the same camera, crop, lighting and materials,
and replace the existing per-control actions. The animated properties have keys
every frame: editing one current pose alone does not create a new state clip.
Future states such as listening, thinking or celebrating are NOT included yet.
If clips need smooth cross-state changes, use a shared neutral boundary pose or
a short crossfade. Independent loops do not guarantee seamless state changes.

Suggested app usage
Use muted loop playsinline video with WebM and MP4 sources, and a PNG poster.
Use a 256px source for up to 128 CSS px at 2x device pixel ratio.
Pause video when hidden, show the poster for reduced-motion preferences, and
only preload the active/likely next states. Use CSS border-radius for the crop.
The current clips have an opaque sage background. They do not contain alpha.
No live Blender or WebGL runtime is needed in the web app.

Reproduction (macOS, using the installed Blender application)
/Applications/Blender.app/Contents/MacOS/Blender --background --factory-startup --python build_robot.py
/Applications/Blender.app/Contents/MacOS/Blender --background robot-avatar.blend --python render_robot.py -- still
/Applications/Blender.app/Contents/MacOS/Blender --background robot-avatar.blend --python render_robot.py -- loop
/Applications/Blender.app/Contents/MacOS/Blender --background robot-avatar.blend --python validate_robot.py

All materials are procedural. No downloaded models, external textures, add-ons,
or rigging dependencies are needed. Tested with installed Blender 5.2.1 LTS.
The model is a bust; its back and hidden details are simple interpretations.
No feet, hands, full-body walking rig or talking mouth have been designed.
The web application itself has not been modified by this proof of concept.
