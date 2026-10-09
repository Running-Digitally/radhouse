import bpy, json
from pathlib import Path
from math import radians, sqrt
from mathutils import Vector
from bpy_extras.object_utils import world_to_camera_view
out=Path(__file__).resolve().parent
s=bpy.context.scene
controls=[o for o in bpy.data.objects if o.name.startswith('CTRL_')]
def matrices(frame):
    s.frame_set(frame)
    return {o.name:[x for row in o.matrix_world for x in row] for o in controls}
a,b=matrices(1),matrices(97)
err=max(abs(x-y) for k in a for x,y in zip(a[k],b[k]))
assert err<1e-6,err
tip=bpy.data.objects['Antenna | finial']
max_radius=0
for frame in range(1,97):
    s.frame_set(frame)
    p=world_to_camera_view(s,s.camera,tip.matrix_world.translation)
    max_radius=max(max_radius,sqrt((p.x-.5)**2+(p.y-.5)**2))
assert max_radius+.115/s.camera.data.ortho_scale<.5, max_radius
stats={'objects':len(bpy.data.objects),'mesh_objects':sum(o.type=='MESH' for o in bpy.data.objects),
       'controls':[o.name for o in controls], 'frames':96, 'fps':24, 'duration_seconds':4,
       'loop_boundary_max_transform_error':err,'antenna_center_max_circle_radius':max_radius,
       'external_images':[i.filepath for i in bpy.data.images if i.source=='FILE'],
       'blender_version':bpy.app.version_string}
(out/'validation.json').write_text(json.dumps(stats,indent=2)+'\n')
print('VALIDATION',json.dumps(stats))
s.render.resolution_x=s.render.resolution_y=512
s.cycles.samples=24
for mode,frame in [('blink',56),('side',1)]:
    s.frame_set(frame)
    if mode=='side':
        h=bpy.data.objects['CTRL_Head']
        h.animation_data.action=None
        h.rotation_euler.z=radians(28)
    s.render.filepath=str(out/('robot-'+mode+'.png'))
    bpy.ops.render.render(write_still=True)
