"""Render a saved variant: Blender -b robot-b-thoughtful.blend -P render_variant.py."""
import bpy
from pathlib import Path
root=Path(__file__).resolve().parent
slug=Path(bpy.data.filepath).stem.removeprefix('robot-')
out=root/'frames'/slug
out.mkdir(parents=True,exist_ok=True)
s=bpy.context.scene
prefs=bpy.context.preferences.addons['cycles'].preferences
prefs.compute_device_type='METAL'
prefs.get_devices()
for device in prefs.devices: device.use=device.type=='METAL'
s.cycles.device='GPU'
s.render.resolution_x=s.render.resolution_y=384
s.render.resolution_percentage=100
s.cycles.samples=64
s.render.use_persistent_data=True
s.render.filepath=str(out/'frame-')
bpy.ops.render.render(animation=True)
print('VARIANT_RENDER_OK',slug,s.frame_end)
