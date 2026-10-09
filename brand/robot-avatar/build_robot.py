"""Build a reusable robot avatar, with independent rigid controls and an idle clip.

Run with Blender --background --factory-startup --python build_robot.py.
Only Blender's built-in Python API is required. Coordinates: front is -Y, up is Z.
"""
import bpy
import math
from mathutils import Vector
from pathlib import Path

OUT = Path(__file__).resolve().parent
TAU = 2 * math.pi
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete(use_global=False)
scene = bpy.context.scene

def rgb(hexval):
    s = hexval.lstrip('#')
    c = [int(s[i:i+2], 16) / 255 for i in (0, 2, 4)]
    return tuple(x / 12.92 if x <= .04045 else ((x+.055)/1.055)**2.4 for x in c) + (1,)

def material(name, color, metal=0, rough=.4):
    m = bpy.data.materials.new(name)
    m.diffuse_color = rgb(color)
    m.use_nodes = True
    p = m.node_tree.nodes.get('Principled BSDF')
    p.inputs['Base Color'].default_value = rgb(color)
    p.inputs['Metallic'].default_value = metal
    p.inputs['Roughness'].default_value = rough
    return m

def worn(name, base, exposed, metal, scale=80):
    m = material(name, base, metal, .38)
    n, l = m.node_tree.nodes, m.node_tree.links
    p = n.get('Principled BSDF')
    coord = n.new('ShaderNodeTexCoord')
    noise = n.new('ShaderNodeTexNoise')
    noise.inputs['Scale'].default_value = scale
    noise.inputs['Detail'].default_value = 2.5
    l.new(coord.outputs['Generated'], noise.inputs['Vector'])
    ramp = n.new('ShaderNodeValToRGB')
    ramp.color_ramp.elements[0].position = .66
    ramp.color_ramp.elements[0].color = rgb(base)
    ramp.color_ramp.elements[1].position = .77
    ramp.color_ramp.elements[1].color = rgb(exposed)
    l.new(noise.outputs['Fac'], ramp.inputs[0])
    l.new(ramp.outputs['Color'], p.inputs['Base Color'])
    bump = n.new('ShaderNodeBump')
    bump.inputs['Strength'].default_value = .16
    bump.inputs['Distance'].default_value = .016
    l.new(noise.outputs['Fac'], bump.inputs['Height'])
    l.new(bump.outputs['Normal'], p.inputs['Normal'])
    return m

orange = worn('Enamel | warm persimmon', '#CD5933', '#64513A', .18)
ivory = worn('Enamel | warm porcelain', '#E9D6AD', '#8D704D', .12, 105)
teal = worn('Ear caps | deep petrol', '#285155', '#B68A48', .58, 60)
brass = worn('Brass | warm aged edges', '#B28B4D', '#604329', .82, 95)
dark = material('Joints | charcoal', '#25251F', .65, .35)
amber = material('Face recess | smoked amber', '#432817', .45, .25)
socket = material('Eye sockets | bronze', '#71411D', .78, .22)
pupil_mat = material('Pupils | warm black glass', '#171510', .18, .12)
cream = material('Lens | warm illuminated cream', '#FFE3AD', .12, .3)
p = cream.node_tree.nodes.get('Principled BSDF')
p.inputs['Emission Color'].default_value = rgb('#FFD997')
p.inputs['Emission Strength'].default_value = 1.15
catchlight = material('Eye catchlights', '#FFF2CC', .0, .1)
p = catchlight.node_tree.nodes.get('Principled BSDF')
p.inputs['Emission Color'].default_value = rgb('#FFF1CE')
p.inputs['Emission Strength'].default_value = 1.8

def finish(obj, name, mat=None, parent=None):
    obj.name = name
    if mat: obj.data.materials.append(mat)
    if parent: obj.parent = parent
    if obj.type == 'MESH':
        for poly in obj.data.polygons: poly.use_smooth = True
    return obj

def ctrl(name, loc=(0,0,0), parent=None):
    o = bpy.data.objects.new(name, None)
    scene.collection.objects.link(o)
    o.location = loc
    o.empty_display_type = 'SPHERE'
    o.empty_display_size = .12
    if parent: o.parent = parent
    return o

root = ctrl('CTRL_Robot')
body = ctrl('CTRL_Body', parent=root)
head = ctrl('CTRL_Head', (0,0,2.06), body)
head['instructions'] = 'Rotate locally: X nod, Y tilt, Z turn. Rigid head parts follow.'

def sphere(name, loc, scale, mat, parent=None):
    bpy.ops.mesh.primitive_uv_sphere_add(segments=64, ring_count=32, location=loc)
    o = bpy.context.object
    o.scale = scale
    return finish(o, name, mat, parent)

def box(name, loc, scale, radius, mat, parent=None):
    bpy.ops.mesh.primitive_cube_add(size=1, location=loc)
    o = bpy.context.object
    o.dimensions = scale
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    mod = o.modifiers.new('Soft manufactured corners', 'BEVEL')
    mod.width = radius
    mod.segments = 8
    mod = o.modifiers.new('Weighted corner normals', 'WEIGHTED_NORMAL')
    return finish(o, name, mat, parent)

def cylinder(name, loc, radius, depth, mat, parent=None, axis='Z'):
    bpy.ops.mesh.primitive_cylinder_add(vertices=64, radius=radius, depth=depth, location=loc)
    o = bpy.context.object
    if axis == 'Y': o.rotation_euler[0] = math.pi / 2
    if axis == 'X': o.rotation_euler[1] = math.pi / 2
    bevel = o.modifiers.new('Soft machined rim', 'BEVEL')
    bevel.width = min(.045, depth*.2)
    bevel.segments = 3
    o.modifiers.new('Weighted normals', 'WEIGHTED_NORMAL')
    return finish(o, name, mat, parent)

def torus(name, loc, radius, tube, mat, parent=None, axis='Y'):
    bpy.ops.mesh.primitive_torus_add(major_segments=80, minor_segments=12,
        location=loc, major_radius=radius, minor_radius=tube)
    o = bpy.context.object
    if axis == 'Y': o.rotation_euler[0] = math.pi/2
    if axis == 'X': o.rotation_euler[1] = math.pi/2
    return finish(o, name, mat, parent)

def roundrect(w, h, r, steps=16):
    points = []
    for cx, cz, start in [(w/2-r,h/2-r,0),(-w/2+r,h/2-r,90),
                           (-w/2+r,-h/2+r,180),(w/2-r,-h/2+r,270)]:
        for i in range(steps):
            a = math.radians(start + i*90/steps)
            points.append((cx+r*math.cos(a),cz+r*math.sin(a)))
    return points

def loft(name, profiles, centerz, mat, parent, cap=False):
    verts = [(x,y,z+centerz) for w,h,r,y in profiles for x,z in roundrect(w,h,r)]
    count = len(roundrect(*profiles[0][:3]))
    faces = []
    for j in range(len(profiles)-1):
        for i in range(count):
            k=(i+1)%count
            faces.append((j*count+i,j*count+k,(j+1)*count+k,(j+1)*count+i))
    if cap: faces.append(tuple(reversed(range((len(profiles)-1)*count,len(verts)))))
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    o = bpy.data.objects.new(name,mesh)
    scene.collection.objects.link(o)
    finish(o,name,mat,parent)
    bpy.context.view_layer.objects.active=o
    o.select_set(True)
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.mesh.normals_make_consistent(inside=False)
    bpy.ops.object.mode_set(mode='OBJECT')
    o.select_set(False)
    return o

def line(name, points, thickness, mat, parent):
    c = bpy.data.curves.new(name,'CURVE')
    c.dimensions='3D'
    c.resolution_u=16
    c.bevel_depth=thickness
    c.bevel_resolution=3
    s=c.splines.new('POLY')
    s.points.add(len(points)-1)
    for p,co in zip(s.points,points): p.co=(*co,1)
    o=bpy.data.objects.new(name,c)
    scene.collection.objects.link(o)
    return finish(o,name,mat,parent)

# Head shell is actual depth geometry, with an open face and an invented plain rear.
cz=1.32
shell = loft('Head | rounded orange housing',[
    (3.00,1.87,.42,-.835),(3.13,2.00,.48,-.89),
    (3.42,2.25,.59,-.855),(3.72,2.54,.73,-.68),
    (3.86,2.68,.79,-.40),(3.88,2.70,.80,.05),
    (3.79,2.61,.77,.51),(3.53,2.35,.67,.75),
    (3.24,2.06,.56,.83)],cz,orange,head,True)
loft('Face | inset bronze bezel',[
    (3.00,1.87,.42,-.845),(3.055,1.925,.445,-.885),
    (3.09,1.96,.46,-.86),(3.045,1.915,.435,-.82)],cz,brass,head)
loft('Face | inner black gasket',[
    (2.945,1.815,.40,-.81),(3.00,1.87,.42,-.845)],cz,dark,head)
box('Face | amber backplate',(0,-.57,cz),(2.99,.30,1.86),.35,amber,head)

# Transparent cover: a thin convex rounded rectangle, not a painted image.
glass = material('Face cover | lightly amber glass','#FFF1D9',0,.105)
gp=glass.node_tree.nodes.get('Principled BSDF')
gp.inputs['Transmission Weight'].default_value=1
gp.inputs['IOR'].default_value=1.22
cover_profiles=[(2.98,1.85,.42,-.86),(2.80,1.67,.40,-.925),
                (2.35,1.37,.35,-.972),(1.50,.87,.22,-1.004),(.02,.012,.005,-1.014)]
cover=loft('Face | transparent convex cover',cover_profiles,cz,glass,head,True)
solid=cover.modifiers.new('Thin face glass','SOLIDIFY')
solid.thickness=.016

eyes=[]
gazes=[]
for side,x,z,r in [('L',-.77,cz+.14,.49),('R',.77,cz-.075,.39)]:
    cylinder('Eye '+side+' | dark socket',(x,-.766,z),r+.074,.12,dark,head,'Y')
    torus('Eye '+side+' | outer bronze ring',(x,-.815,z),r+.036,.043,socket,head)
    torus('Eye '+side+' | fine brass trim',(x,-.86,z),r+.005,.014,brass,head)
    blink=ctrl('CTRL_Blink_'+side,(x,-.837,z),head)
    blink['instructions']='Scale local Z from 1 (open) to 0.035 (closed display).'
    sphere('Eye '+side+' | luminous lens',(0,0,0),(r,.061,r),cream,blink)
    gaze=ctrl('CTRL_Gaze_'+side,(-.045,-.061,.025),blink)
    gaze['instructions']='Move local X/Z for gaze. Keep inside the luminous lens.'
    sphere('Eye '+side+' | pupil',(0,0,0),(r*.42,.039,r*.43),pupil_mat,gaze)
    sphere('Eye '+side+' | highlight',(-r*.115,-.038,r*.145),(r*.066,.012,r*.066),catchlight,gaze)
    eyes.append(blink)
    gazes.append(gaze)

# Ear drums remain rigidly attached to the head.
for s in [-1,1]:
    cylinder('Ear | neck '+str(s),(s*1.95,.03,cz),.43,.20,dark,head,'X')
    cylinder('Ear | brass seat '+str(s),(s*2.015,.03,cz),.55,.10,brass,head,'X')
    sphere('Ear | teal cap '+str(s),(s*2.105,.03,cz),(.23,.46,.52),teal,head)
    cylinder('Ear | center button '+str(s),(s*2.32,.03,cz),.17,.10,brass,head,'X')

antenna=ctrl('CTRL_Antenna',(1.17,.12,cz+1.26),head)
antenna.rotation_euler[1]=.12
cylinder('Antenna | socket',(0,0,.055),.155,.20,teal,antenna)
torus('Antenna | brass collar',(0,0,.16),.105,.018,brass,antenna,'Z')
cylinder('Antenna | mast',(0,0,.47),.042,.65,brass,antenna)
sphere('Antenna | finial',(0,0,.81),(.115,.115,.115),brass,antenna)
line('Head | fine center seam',[(0,-.838,cz+.99),(0,-.71,cz+1.18),
    (0,-.40,cz+1.335),(0,.05,cz+1.353),(0,.51,cz+1.31)],.009,socket,head)

# Bust: no inferred full body is needed for the avatar crop.
sphere('Body | ivory torso',(0,.10,.48),(1.34,.71,1.40),ivory,body)
cylinder('Neck | dark spindle',(0,0,1.91),.34,.68,dark,body)
for z,r in [(1.64,.63),(1.79,.47),(1.96,.435),(2.105,.39)]:
    cylinder('Neck | brass collar %.2f'%z,(0,0,z),r,.13,brass,body)
for s in [-1,1]:
    shoulder=ctrl('CTRL_Shoulder_'+('L' if s<0 else 'R'),(s*1.29,.10,.71),body)
    cylinder('Shoulder | bearing '+str(s),(s*.08,0,0),.52,.24,dark,shoulder,'X')
    cylinder('Shoulder | brass collar '+str(s),(s*.20,0,0),.57,.12,brass,shoulder,'X')
    sphere('Shoulder | cream cap '+str(s),(s*.43,0,-.04),(.38,.53,.64),ivory,shoulder)
    cylinder('Arm | small joint '+str(s),(s*.43,.03,-.65),.235,.35,brass,shoulder)
    sphere('Arm | upper sleeve '+str(s),(s*.46,.03,-.90),(.28,.32,.46),ivory,shoulder)
cylinder('Chest | brass badge seat',(0,-.60,.77),.245,.08,brass,body,'Y')
cylinder('Chest | dial inset',(0,-.652,.77),.183,.03,socket,body,'Y')
dial=box('Chest | dial handle',(0,-.69,.77),(.07,.075,.29),.025,brass,body)
dial.rotation_euler[1]=-.14
for x in [-.39,.39]:
    cylinder('Chest | screw',(x,-.596,.77),.038,.025,brass,body,'Y')

# Soft sage studio. No external texture dependencies.
backmat=material('Backdrop | muted sage','#9CA995',0,.95)
box('Backdrop',(0,3.3,3.0),(200,.12,200),.02,backmat)
world=bpy.data.worlds.new('Soft neutral studio')
scene.world=world
world.use_nodes=True
world.node_tree.nodes['Background'].inputs['Color'].default_value=(.55,.60,.55,1)
world.node_tree.nodes['Background'].inputs['Strength'].default_value=.45

def area(name,loc,power,size,color,target):
    data=bpy.data.lights.new(name,'AREA')
    data.energy=power
    data.shape='DISK'
    data.size=size
    data.color=color
    o=bpy.data.objects.new(name,data)
    scene.collection.objects.link(o)
    o.location=loc
    o.rotation_euler=(Vector(target)-o.location).to_track_quat('-Z','Y').to_euler()
    return o

area('Key | large warm softbox',(-4,-5,7.5),650,4.5,(1,.85,.69),(0,0,2.6))
area('Fill | soft neutral',(4,-3,4.5),390,4,(.82,.9,1),(0,0,3))
area('Rim | upper edge',(1.5,2,7.2),720,3,(1,.89,.69),(0,0,3))
area('Front | eye readability',(-.5,-6,2.6),55,3,(1,.88,.7),(0,0,3))

bpy.ops.object.camera_add(location=(.18,-12.7,4.65))
cam=bpy.context.object
cam.name='Camera | avatar portrait'
cam.rotation_euler=(Vector((0,0,2.96))-cam.location).to_track_quat('-Z','Y').to_euler()
cam.data.type='ORTHO'
cam.data.ortho_scale=6.05
cam.data.lens=65
scene.camera=cam

# One exact-period 4-second clip. Frame 97 equals frame 1, and is excluded on export.
scene.render.fps=24
scene.frame_start=1
scene.frame_end=96
for frame in range(1,98):
    t=(frame-1)/96
    ease=math.sin(TAU*t)
    head.rotation_euler=(math.radians(2+1.9*math.sin(TAU*t+.3)),
                         math.radians(7+4.2*ease),
                         math.radians(-3+3.0*math.sin(TAU*t-.4)))
    head.keyframe_insert(data_path='rotation_euler',frame=frame,group='Idle | head')
    head.location.z=2.06+.018*math.sin(TAU*t)
    head.keyframe_insert(data_path='location',frame=frame,group='Idle | head')
    for i,gaze in enumerate(gazes):
        gaze.location.x=-.045+.071*math.sin(TAU*t-.5)
        gaze.location.z=.025+.025*math.sin(TAU*t+.6)
        gaze.keyframe_insert(data_path='location',frame=frame,group='Idle | gaze')
    # A quick electronic blink with stationary sockets, no invented organic eyelids.
    blink_amount={54:.75,55:.24,56:.035,57:.035,58:.24,59:.72}.get(frame,1)
    for eye in eyes:
        eye.scale.z=blink_amount
        eye.keyframe_insert(data_path='scale',frame=frame,group='Idle | blink')
    antenna.rotation_euler[1]=.12+.018*math.sin(TAU*t-.7)
    antenna.keyframe_insert(data_path='rotation_euler',frame=frame,group='Idle | antenna')

for o in (head,*gazes,*eyes,antenna):
    if o.animation_data and o.animation_data.action:
        o.animation_data.action.name='Idle / '+o.name
for frame,name in [(1,'IDLE LOOP START'),(49,'GLANCE'),(56,'BLINK'),(96,'LOOP END; 97 duplicates 1')]:
    scene.timeline_markers.new(name,frame=frame)

scene.render.engine='CYCLES'
scene.cycles.samples=48
scene.cycles.use_denoising=True
scene.cycles.max_bounces=8
scene.cycles.transmission_bounces=6
scene.cycles.transparent_max_bounces=6
prefs=bpy.context.preferences.addons['cycles'].preferences
try:
    prefs.compute_device_type='METAL'
    prefs.get_devices()
    for d in prefs.devices: d.use=(d.type=='METAL')
    scene.cycles.device='GPU'
except Exception:
    scene.cycles.device='CPU'
scene.render.resolution_x=768
scene.render.resolution_y=768
scene.render.resolution_percentage=100
scene.render.image_settings.file_format='PNG'
scene.render.image_settings.color_mode='RGB'
scene.render.film_transparent=False
scene.view_settings.view_transform='AgX'
scene.view_settings.look='AgX - Medium High Contrast'
scene.render.filepath=str(OUT/'robot-still.png')
scene['Purpose']='Small web avatar POC. Reuse camera/materials/controls for future state clips.'
scene['Source']='exec-e7c9d5b8-2c04-454e-89b8-0c673555e6fa.png; interpreted from one portrait.'
scene['Limitations']='Bust only. Rear is an interpretation. Not an image-identical reconstruction.'
scene['Export']='Idle: frames 1-96 at 24 fps. Frame 97 is duplicate loop boundary; exclude it.'
scene['Future states']='Duplicate the blend or create new actions on head/gaze/blink controls.'
scene.frame_set(1)
bpy.ops.object.select_all(action='DESELECT')
head.select_set(True)
bpy.context.view_layer.objects.active=head
for screen in bpy.data.screens:
    for ar in screen.areas:
        if ar.type=='VIEW_3D':
            ar.spaces.active.region_3d.view_perspective='CAMERA'
            ar.spaces.active.shading.type='MATERIAL'
note=bpy.data.texts.new('README | Robot avatar controls')
note.write('Robot avatar proof of concept\n\nReal 3D bust, procedurally built from the supplied portrait.\n'
    'CTRL_Head: rotate X (nod), Y (tilt), Z (turn).\n'
    'CTRL_Gaze_L/R: move local X/Z for eye direction.\n'
    'CTRL_Blink_L/R: scale local Z 1 = open; .035 = closed display.\n'
    'CTRL_Antenna and CTRL_Shoulder_L/R: future secondary animation.\n'
    'Idle loop: frames 1-96 at 24 fps. Frame 97 matches frame 1 and is excluded.\n'
    'Duplicate this file or replace per-control actions for new app states.\n'
    'Camera, lighting and framing should remain consistent across state exports.\n'
    'All materials are procedural; no external assets or add-ons required.\n'
    'Reconstruction is approximate. Only the bust is modeled.\n')
bpy.ops.wm.save_as_mainfile(filepath=str(OUT/'robot-avatar.blend'))
print('ROBOT_BUILD_OK',len(bpy.data.objects),'objects',str(OUT/'robot-avatar.blend'))
