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
a,b=matrices(1),matrices(145)
err=max(abs(x-y) for k in a for x,y in zip(a[k],b[k]))
assert err<1e-6,err
tip=bpy.data.objects['Antenna | finial']
max_radius=0
for frame in range(1,145):
    s.frame_set(frame)
    p=world_to_camera_view(s,s.camera,tip.matrix_world.translation)
    max_radius=max(max_radius,sqrt((p.x-.5)**2+(p.y-.5)**2))
crop_radius=max_radius+.115/s.camera.data.ortho_scale
assert crop_radius<.5, crop_radius
def custom_state(frame):
    s.frame_set(frame)
    return {o.name:{key:o[key] for key in ('upper_lid','lower_lid') if key in o} for o in controls}
assert custom_state(1)==custom_state(145)
s.frame_set(80)
for side in ('L','R'):
    eye=bpy.data.objects['CTRL_Blink_'+side]
    assert eye['upper_lid']==1 and eye['lower_lid']==1
    assert bpy.data.objects['Eye '+side+' | upper lid'].data.shape_keys.key_blocks['Closed'].value==1
    assert bpy.data.objects['Eye '+side+' | lower lid'].data.shape_keys.key_blocks['Closed'].value==1
    assert all(abs(v-1)<1e-6 for v in eye.scale), 'Blink must not squash the eye'
s.frame_set(27)
assert bpy.data.objects['CTRL_Gaze_L'].location.x>.15
assert abs(bpy.data.objects['CTRL_Head'].rotation_euler.z)<1e-6, 'Eyes should lead the head'
stats={'objects':len(bpy.data.objects),'mesh_objects':sum(o.type=='MESH' for o in bpy.data.objects),
       'controls':[o.name for o in controls], 'frames':144, 'fps':24, 'duration_seconds':6,
       'loop_boundary_max_transform_error':err,'antenna_center_max_circle_radius':max_radius,
       'external_images':[i.filepath for i in bpy.data.images if i.source=='FILE'],
       'circle_radius_including_antenna_tip':crop_radius,
       'blink_shutters_preserve_eye_scale':True,'gaze_leads_head':True,
       'blender_version':bpy.app.version_string}
(out/'validation.json').write_text(json.dumps(stats,indent=2)+'\n')
print('VALIDATION',json.dumps(stats))
s.render.resolution_x=s.render.resolution_y=512
s.cycles.samples=48
for mode,frame in [('blink',80),('curious',46),('smile',94),('side',1)]:
    s.frame_set(frame)
    if mode=='side':
        h=bpy.data.objects['CTRL_Head']
        h.animation_data.action=None
        h.rotation_euler.z=radians(28)
    s.render.filepath=str(out/('robot-'+mode+'.png'))
    bpy.ops.render.render(write_still=True)
