ROBOT AVATAR / VERSION 2 / CURIOUS IDLE

Changes from the first proof of concept
- Rounder ivory eye surfaces, warm brown irises, deep pupils and two catchlights.
- Slight pupil dilation on noticing something.
- Separate curved upper/lower lids that close over the full-size eyes.
- Fast coordinated gaze shifts followed by slower head motion and held poses.
- Short damped antenna motion after a head movement, with quiet intervals.
- Six seconds instead of four, including a clear rest before repeating.

Timing (24 frames per second)
1-24: looks at the viewer, holds steady.
25-30: quick glance toward a shared offscreen target.
31-46: head follows; antenna wobbles and settles.
47-71: curious held pose.
72-86: return glance and blink, with fast closing and slower reopening.
87-119: reconnects with the viewer, slight lower-lid lift, settles.
120-144: quiet attentive hold.
Frame 145 matches frame 1 and is excluded from export.

Files
robot-avatar.blend: editable 3D scene and animation.
robot-idle-256.mp4 / .webm: six seconds, 256x256, 24 fps, silent web assets.
robot-idle-master.mp4: 384x384 higher-quality review version.
robot-poster-128.png / -256.png: static fallbacks.
robot-still.png: larger still; robot-curious.png / -blink.png / -smile.png / -side.png: pose checks.
validation.json: checks for loop, crop, eye-first timing and eyelid controls.
delivery.json: verified codec, duration, frame count and size of each export.
build_robot.py, render_robot.py, validate_robot.py, export_video.py: reproduction scripts.

Controls
CTRL_Head: local X nod, Y tilt, Z turn.
CTRL_Gaze_L/R: local X/Z moves each iris, pupil and catchlights.
CTRL_Blink_L/R: upper_lid and lower_lid properties, 0 open through 1 closed.
Eye L/R | pupil: scale X/Z for dilation; leave Y thickness unchanged.
CTRL_Antenna: rotation, with brief damped motion in the current clip.
CTRL_Body / CTRL_Robot / CTRL_Shoulder_L/R: rigid body and shoulder controls.

All animated properties have baked per-frame keys. To make a new state, duplicate
the scene and replace the actions rather than changing only the current pose.
Keep lighting, camera and framing fixed across state exports. Smooth switching
between different clips requires matching transition poses or a brief crossfade.

Review the parent folder's index-v2.html for reference / v1 / v2 comparison and the
new animation at 48, 80 and 128 CSS pixels. Pause/play, replay and crop controls
are provided. The first version and index-v1.html remain in the parent folder.

Rebuild, from this folder:
/Applications/Blender.app/Contents/MacOS/Blender --background --factory-startup --python build_robot.py
/Applications/Blender.app/Contents/MacOS/Blender --background robot-avatar.blend --python render_robot.py -- still
/Applications/Blender.app/Contents/MacOS/Blender --background robot-avatar.blend --python render_robot.py -- loop
/Applications/Blender.app/Contents/MacOS/Blender --background robot-avatar.blend --python validate_robot.py
python3 export_video.py

Blender 5.2.1 LTS was used. Rendering needs no external models, textures or add-ons.
FFmpeg is needed only to encode web video. The background is opaque sage, with
no alpha channel. It is a stylized bust based on one portrait, not an exact copy.
No talking mouth, walking rig or additional app-state clips have been developed.
