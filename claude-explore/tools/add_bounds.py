"""Second pass: add world bounds + triangle counts to scene/model entries.

Split out from build_data.py because building meshes for every scene is slow
and the file layout is useful without it.
"""
import os, sys, json, time
sys.path.insert(0, os.path.dirname(__file__))
import build_data, d3d

MAN = '../data/manifest.json'
budget = float(sys.argv[1]) if len(sys.argv) > 1 else 90.0

man = json.load(open(MAN))
t0 = time.time()
done = skipped = 0
for rec in man['files']:
    if rec['bucket'].split('/')[0] not in ('scenes', 'models', 'exports', 'misc'):
        continue
    if 'bounds' in rec or 'parseError' in rec or not rec['path'].upper().endswith('.VVR'):
        continue
    if time.time() - t0 > budget:
        skipped += 1
        continue
    bb = build_data.scene_bbox(os.path.join('../data', rec['path']))
    if bb:
        rec['bounds'] = bb
    done += 1
json.dump(man, open(MAN, 'w'), indent=1)
print(f'bounds added for {done} files, {skipped} still pending ({time.time()-t0:.0f}s)')
