"""Author B/C from approved A, preserving geometry, materials and neutral pose.
Blender --background --python make_variants.py
"""
import bpy, math, json, hashlib
from pathlib import Path
from bpy_extras.object_utils import world_to_camera_view

OUT=Path(__file__).resolve().parent
KEEPER=OUT.parent/'v2'
SOURCE=KEEPER/'robot-avatar.blend'
BASE=(0,2,0)
FPS=24
END=120

def track(f,keys):
    if f<=keys[0][0]: return keys[0][1]
    for (fa,va),(fb,vb) in zip(keys,keys[1:]):
        if f<=fb:
            t=(f-fa)/(fb-fa)
            t=t*t*t*(t*(t*6-15)+10)
            if isinstance(va,tuple): return tuple(a+(b-a)*t for a,b in zip(va,vb))
            return va+(vb-va)*t
    return keys[-1][1]

def spring(f,start,amplitude):
    t=(f-start)/24
    if not 0<t<.95: return 0
    return amplitude*math.exp(-5*t)*math.sin(2*math.pi*3.3*t)*(1-t/.95)**2

CONFIG={
 'b-thoughtful':{
  'name':'B / Thoughtful', 'lead_frame':18,'blink_frame':73,'hero_frame':55,
  'description':'Looks slightly down, considers, gives a small nod, reconnects and softly blinks.',
  'pose':[(1,BASE),(23,BASE),(35,(6,3,-3.5)),(49,(6,3,-3.5)),
          (57,(10,3,-3.5)),(66,(3,2,-1.5)),(81,BASE),(121,BASE)],
  'gaze_x':[(1,0),(14,0),(18,-.17),(24,-.17),(35,-.10),(60,-.10),(64,-.10),(68,0),(121,0)],
  'gaze_z':[(1,.065),(14,.065),(18,-.24),(24,-.24),(35,-.13),(57,-.09),
            (63,-.10),(68,.065),(121,.065)],
  'dilate':[(1,1),(18,1),(35,.985),(65,.985),(81,1),(121,1)],
  'close':[(1,0),(70,0),(73,1),(74,1),(80,0),(121,0)],
  'lower':[(1,.045),(65,.045),(81,.13),(94,.13),(106,.045),(121,.045)],
  'upper':[(1,.02),(25,.02),(35,.055),(64,.055),(80,.02),(121,.02)],
  'springs_y':[(34,.09),(66,-.09)], 'springs_x':[(35,.09),(57,-.16),(78,.10)],
  'markers':[(1,'NEUTRAL'),(15,'EYES DOWN'),(24,'HEAD FOLLOWS'),(37,'CONSIDER'),
             (51,'SMALL NOD'),(65,'LOOK BACK'),(73,'SOFT BLINK'),(106,'NEUTRAL HOLD')],
  'previews':[('consider',38),('nod',57),('blink',73)]
 },
 'c-playful':{
  'name':'C / Playful','lead_frame':17,'blink_frame':82,'hero_frame':64,
  'description':'Glances the opposite way, double-takes, tilts playfully, then returns with an antenna bounce.',
  'pose':[(1,BASE),(22,BASE),(31,(0,4.8,-5)),(36,(0,4.8,-5)),
          (43,BASE),(50,BASE),(60,(-2,10,-8.5)),(65,(-1.5,8.5,-7.5)),
          (77,(-1.5,8.5,-7.5)),(95,(.5,1.4,.4)),(103,BASE),(121,BASE)],
  'gaze_x':[(1,0),(13,0),(17,-.30),(23,-.30),(31,-.19),(36,-.19),(40,.09),
            (43,0),(44,0),(47,-.34),(51,-.34),(63,-.20),(79,-.20),(85,0),(121,0)],
  'gaze_z':[(1,.065),(13,.065),(17,.11),(36,.11),(40,.065),(44,.065),
            (47,.16),(63,.12),(79,.12),(85,.065),(121,.065)],
  'dilate':[(1,1),(15,1),(23,1.025),(40,1),(45,1),(51,1.12),(69,1.06),
           (79,1.06),(90,1),(121,1)],
  'close':[(1,0),(80,0),(82,1),(83,1),(89,0),(121,0)],
  'lower':[(1,.045),(44,.045),(49,0),(78,0),(90,.15),(102,.15),(113,.045),(121,.045)],
  'upper':[(1,.02),(44,.02),(49,0),(78,0),(90,.02),(121,.02)],
  'springs_y':[(31,-.12),(59,-.34),(94,.23)], 'springs_x':[(60,.11),(95,-.08)],
  'markers':[(1,'NEUTRAL'),(14,'FIRST GLANCE'),(23,'HEAD FOLLOWS'),(38,'LOOK BACK'),
             (45,'DOUBLE TAKE / EYES FIRST'),(51,'PLAYFUL TILT'),(62,'ANTENNA BOUNCE'),
             (82,'BLINK'),(95,'RECONNECT'),(113,'NEUTRAL HOLD')],
  'previews':[('first-glance',31),('double-take',64),('blink',82)]
 }
}

def snapshot():
    bpy.context.view_layer.update()
    result={o.name:[v for row in o.matrix_world for v in row] for o in bpy.data.objects}
    for side in ('L','R'):
        eye=bpy.data.objects['CTRL_Blink_'+side]
        result['lid properties '+side]=[eye['upper_lid'],eye['lower_lid']]
    return result

def difference(a,b):
    assert a.keys()==b.keys()
    return max(abs(x-y) for name in a for x,y in zip(a[name],b[name]))

reports={}
for slug,cfg in CONFIG.items():
    bpy.ops.wm.open_mainfile(filepath=str(SOURCE))
    s=bpy.context.scene
    s.frame_set(1)
    neutral=snapshot()
    for obj in bpy.data.objects:
        if obj.animation_data and obj.animation_data.action:
            obj.animation_data_clear()
    s.timeline_markers.clear()
    head=bpy.data.objects['CTRL_Head']; antenna=bpy.data.objects['CTRL_Antenna']
    gazes=[bpy.data.objects['CTRL_Gaze_'+side] for side in ('L','R')]
    eyes=[bpy.data.objects['CTRL_Blink_'+side] for side in ('L','R')]
    pupils=[bpy.data.objects['Eye '+side+' | pupil'] for side in ('L','R')]
    radii=[p['base_radius'] for p in pupils]
    s.render.fps=FPS; s.frame_start=1; s.frame_end=END
    for frame in range(1,END+2):
        head.rotation_euler=tuple(math.radians(v) for v in track(frame,cfg['pose']))
        head.keyframe_insert(data_path='rotation_euler',frame=frame,group=cfg['name']+' / head')
        gx=track(frame,cfg['gaze_x']); gz=track(frame,cfg['gaze_z'])
        dilate=track(frame,cfg['dilate']); closed=track(frame,cfg['close'])
        upper=track(frame,cfg['upper']); lower=track(frame,cfg['lower'])
        for i,(gaze,r,pupil,eye) in enumerate(zip(gazes,radii,pupils,eyes)):
            gaze.location.x=gx*r+(.005 if i==0 else -.005)
            gaze.location.z=gz*r
            gaze.keyframe_insert(data_path='location',frame=frame,group=cfg['name']+' / focus')
            pupil.scale=(r*.455*dilate,.021,r*.47*dilate)
            pupil.keyframe_insert(data_path='scale',frame=frame,group=cfg['name']+' / pupil')
            eye['upper_lid']=upper+(1-upper)*closed
            eye['lower_lid']=lower+(1-lower)*closed
            eye.keyframe_insert(data_path='["upper_lid"]',frame=frame,group=cfg['name']+' / blink')
            eye.keyframe_insert(data_path='["lower_lid"]',frame=frame,group=cfg['name']+' / blink')
        antenna.rotation_euler.y=.12+sum(spring(frame,start,amp) for start,amp in cfg['springs_y'])
        antenna.rotation_euler.x=sum(spring(frame,start,amp) for start,amp in cfg['springs_x'])
        antenna.keyframe_insert(data_path='rotation_euler',frame=frame,group=cfg['name']+' / antenna')
    for obj in (head,antenna,*eyes,*gazes,*pupils):
        obj.animation_data.action.name=cfg['name']+' / '+obj.name
    for frame,name in cfg['markers']+[(END,'END / NEUTRAL')]: s.timeline_markers.new(name,frame=frame)
    s['Clip']=cfg['name']; s['Description']=cfg['description']
    s['Export']=f'Frames 1-{END} at {FPS} fps; {END/FPS:.1f} seconds. Frame {END+1} repeats 1.'
    s['Shared neutral']='Every object transform and both lid controls match approved A at the first and last exported frames.'
    # Prove transition poses against the actual keeper, including pupils and eyelids.
    errors={}
    for f in (1,END,END+1):
        s.frame_set(f); errors[str(f)]=difference(neutral,snapshot())
    assert max(errors.values())<1e-6,errors
    tip=bpy.data.objects['Antenna | finial']
    max_circle=0
    for f in range(1,END+1):
        s.frame_set(f)
        p=world_to_camera_view(s,s.camera,tip.matrix_world.translation)
        max_circle=max(max_circle,math.hypot(p.x-.5,p.y-.5)+.115/s.camera.data.ortho_scale)
        for gaze,r in zip(gazes,radii):
            assert math.hypot(gaze.location.x,gaze.location.z)+r*.61<r, 'Iris leaves aperture'
    assert max_circle<.5,max_circle
    s.frame_set(cfg['lead_frame'])
    assert abs(gazes[0].location.x)>.06 and abs(head.rotation_euler.z)<1e-6
    s.frame_set(cfg['blink_frame'])
    assert all(eye['upper_lid']==1 and eye['lower_lid']==1 for eye in eyes)
    s.frame_set(1)
    for text in bpy.data.texts:
        if text.name.startswith('README'):
            text.clear()
            text.write(cfg['name']+'\n'+cfg['description']+'\n\n'+s['Export']+'\n'
                'Geometry, materials and camera are inherited unchanged from approved A.\n'
                'CTRL_Head X nod / Y tilt / Z turn. CTRL_Gaze_L/R local X/Z.\n'
                'CTRL_Blink_L/R upper_lid and lower_lid 0 open to 1 closed.\n'
                'Replace per-control actions for new clips. Keep the shared neutral boundary.\n')
    path=OUT/f'robot-{slug}.blend'
    bpy.ops.wm.save_as_mainfile(filepath=str(path))
    reports[slug]={'name':cfg['name'],'description':cfg['description'],'blend':path.name,
        'duration_seconds':END/FPS,'fps':FPS,'frames':END,'neutral_match_errors':errors,
        'antenna_circle_radius_max':max_circle,'gaze_leads_head':True,'iris_inside_aperture':True,
        'markers':cfg['markers'],'hero_frame':cfg['hero_frame']}
    s.render.resolution_x=s.render.resolution_y=512
    s.cycles.samples=48
    for label,frame in cfg['previews']:
        s.frame_set(frame)
        s.render.filepath=str(OUT/f'{slug}-{label}.png')
        bpy.ops.render.render(write_still=True)

expected=json.loads((OUT/'keeper-manifest.json').read_text())
assert all(hashlib.sha256((KEEPER/name).read_bytes()).hexdigest()==digest for name,digest in expected.items())
(OUT/'validation.json').write_text(json.dumps({'keeper_unchanged':True,'clips':reports},indent=2)+'\n')
print('VARIANTS_VALIDATED',json.dumps(reports))
