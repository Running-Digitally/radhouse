"""Encode and verify B/C, and publish a manifest with unchanged approved A."""
from pathlib import Path
import json, subprocess, hashlib
OUT=Path(__file__).resolve().parent
ROOT=OUT.parent
def run(args): subprocess.run(['ffmpeg','-v','error','-y',*args],check=True)
tags=['-color_primaries','bt709','-color_trc','bt709','-colorspace','bt709','-color_range','tv']
reports={}
for slug in ('b-thoughtful','c-playful'):
    frames=OUT/'frames'/slug
    assert all((frames/f'frame-{i:04d}.png').exists() for i in range(1,121))
    base=['-framerate','24','-start_number','1','-i',str(frames/'frame-%04d.png'),'-frames:v','120','-an']
    media=[]
    for ext,codec in [('mp4',['-c:v','libx264','-preset','slow','-crf','20','-movflags','+faststart']),
                      ('webm',['-c:v','libvpx-vp9','-b:v','0','-crf','28','-deadline','good','-cpu-used','2','-row-mt','1'])]:
        target=OUT/f'robot-{slug}-256.{ext}'
        run(base+['-vf','scale=256:256:flags=lanczos:out_color_matrix=bt709,format=yuv420p']+codec+tags+[str(target)])
        info=json.loads(subprocess.check_output(['ffprobe','-v','error','-count_frames','-show_entries',
            'stream=codec_name,codec_type,width,height,avg_frame_rate,nb_read_frames:format=duration','-of','json',str(target)]))
        v=info['streams'][0]
        assert len(info['streams'])==1 and v['codec_type']=='video'
        assert v['width']==256 and v['height']==256 and int(v['nb_read_frames'])==120
        assert abs(float(info['format']['duration'])-5)<.002
        media.append({'file':target.name,'bytes':target.stat().st_size,**info})
    reports[slug]=media

expected=json.loads((OUT/'keeper-manifest.json').read_text())
assert all(hashlib.sha256((ROOT/'v2'/name).read_bytes()).hexdigest()==digest for name,digest in expected.items())
(OUT/'delivery.json').write_text(json.dumps({'keeper_a_unchanged':True,'media':reports},indent=2)+'\n')
manifest={
 'poster':'v2/robot-poster-256.png','wait_min_seconds':2,'wait_max_seconds':6,
 'clips':[
  {'id':'a','name':'A · Curious','description':'A quick glance, a curious tilt, and a blink back to you.',
   'mp4':'v2/robot-idle-256.mp4','webm':'v2/robot-idle-256.webm','blend':'v2/robot-avatar.blend','duration':6},
  {'id':'b','name':'B · Thoughtful','description':'A downward glance, a considering pause, and a gentle nod.',
   'mp4':'variants/robot-b-thoughtful-256.mp4','webm':'variants/robot-b-thoughtful-256.webm','blend':'variants/robot-b-thoughtful.blend','duration':5},
  {'id':'c','name':'C · Playful','description':'A little double-take, an opposite tilt, and an antenna bounce.',
   'mp4':'variants/robot-c-playful-256.mp4','webm':'variants/robot-c-playful-256.webm','blend':'variants/robot-c-playful.blend','duration':5}
 ]}
(OUT/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
print(json.dumps({k:[{'file':m['file'],'bytes':m['bytes']} for m in v] for k,v in reports.items()},indent=2))
