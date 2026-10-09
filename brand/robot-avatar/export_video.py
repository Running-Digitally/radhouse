"""Encode the rendered frame sequence and verify delivered web video files."""
from pathlib import Path
import json, subprocess, shutil
out=Path(__file__).resolve().parent
ffmpeg=shutil.which('ffmpeg')
ffprobe=shutil.which('ffprobe')
frames=sorted((out/'frames').glob('idle-*.png'))
assert len(frames)==96, len(frames)
assert all((out/'frames'/f'idle-{f:04d}.png').is_file() for f in range(1,97))
def run(args):
    subprocess.run(args,check=True)
base=[ffmpeg,'-v','error','-y','-framerate','24','-start_number','1','-i',str(out/'frames'/'idle-%04d.png'),'-frames:v','96','-an']
tags=['-color_primaries','bt709','-color_trc','bt709','-colorspace','bt709','-color_range','tv']
for name,size,crf in [('robot-idle-256.mp4',256,'23'),('robot-idle-master.mp4',384,'18')]:
    run(base+['-vf',f'scale={size}:{size}:flags=lanczos:out_color_matrix=bt709,format=yuv420p',
        '-c:v','libx264','-preset','slow','-crf',crf,'-movflags','+faststart']+tags+[str(out/name)])
run(base+['-vf','scale=256:256:flags=lanczos:out_color_matrix=bt709,format=yuv420p',
    '-c:v','libvpx-vp9','-b:v','0','-crf','33','-deadline','good','-cpu-used','2','-row-mt','1']+tags+[str(out/'robot-idle-256.webm')])
for size in (128,256):
    run([ffmpeg,'-v','error','-y','-i',str(frames[0]),'-vf',f'scale={size}:{size}:flags=lanczos',
         '-frames:v','1','-update','1',str(out/f'robot-poster-{size}.png')])
media=[]
for filename in ['robot-idle-256.mp4','robot-idle-256.webm','robot-idle-master.mp4']:
    path=out/filename
    result=json.loads(subprocess.check_output([ffprobe,'-v','error','-count_frames','-show_entries',
        'stream=codec_name,codec_type,width,height,pix_fmt,avg_frame_rate,nb_read_frames:format=duration',
        '-of','json',str(path)]))
    v=result['streams'][0]
    assert len(result['streams'])==1 and v['codec_type']=='video'
    assert int(v['nb_read_frames'])==96
    assert abs(float(result['format']['duration'])-4)<.002
    media.append({'file':filename,'bytes':path.stat().st_size,**result})
(out/'delivery.json').write_text(json.dumps({'state':'generic_idle','loop':True,'alpha':False,
    'display_sizes_css_px':[48,80,128],'media':media},indent=2)+'\n')
print(json.dumps(media,indent=2))
