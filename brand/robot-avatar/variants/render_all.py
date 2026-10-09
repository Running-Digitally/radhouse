import bpy,runpy
from pathlib import Path
out=Path(__file__).resolve().parent
for slug in ('b-thoughtful','c-playful'):
    bpy.ops.wm.open_mainfile(filepath=str(out/f'robot-{slug}.blend'))
    runpy.run_path(str(out/'render_variant.py'),run_name='__main__')
