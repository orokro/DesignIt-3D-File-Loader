import sys, os, glob
sys.path.insert(0, os.path.dirname(__file__))
import d3d, render, wlb, iff

mode, src, out = sys.argv[1], sys.argv[2], sys.argv[3]
kw = {}
for a in sys.argv[4:]:
    k, v = a.split('='); kw[k] = float(v) if k in ('azim','elev') else v

items = []
if mode == 'dir':
    for f in sorted(glob.glob(os.path.join(src, '*.VVR'))):
        items.append((os.path.basename(f)[:-4], d3d.scene_meshes(f)))
elif mode == 'wlb':
    for name, it in wlb.items(src):
        ms = []
        d3d.collect(it, __import__('numpy').eye(4), ms)
        items.append((name, ms))
elif mode == 'file':
    items.append((os.path.basename(src), d3d.scene_meshes(src)))

sheet = render.grid(items, cols=int(kw.pop('cols', 4)), **kw)
sheet.save(out)
print(out, sheet.size, len(items), 'items')
