"""Render the existing blend: -- still | preview | loop | blink | side."""
import bpy, sys
from pathlib import Path
from math import radians
OUT=Path(__file__).resolve().parent
mode=sys.argv[sys.argv.index('--')+1] if '--' in sys.argv else 'preview'
s=bpy.context.scene
s.render.resolution_percentage=100
if mode=='loop':
    (OUT/'frames').mkdir(exist_ok=True)
    s.render.resolution_x=s.render.resolution_y=384
    s.cycles.samples=24
    s.render.filepath=str(OUT/'frames'/'idle-')
    s.render.use_persistent_data=True
    bpy.ops.render.render(animation=True)
else:
    s.render.resolution_x=s.render.resolution_y=768 if mode=='still' else 512
    s.cycles.samples=64 if mode=='still' else 24
    s.frame_set(56 if mode=='blink' else 1)
    if mode=='side':
        h=bpy.data.objects['CTRL_Head']
        h.rotation_euler[2]=radians(28)
    s.render.filepath=str(OUT/('robot-'+mode+'.png'))
    bpy.ops.render.render(write_still=True)
print('ROBOT_RENDER_OK',mode)
