"""Same geometry digest as web/parity.mjs, from the Python implementation."""
import sys, os, json, math
sys.path.insert(0, os.path.dirname(__file__))
import numpy as np, iff, d3d, wlb

d3d.SLIC_MODE = 'clip'; d3d.SLIC_KEEP_NEG = False; d3d.SLIC_FILTER = None; d3d.DRAW_SURF = os.environ.get('SURF') == '1'
d3d.FACE_FRAME = os.environ.get('FRAME', d3d.FACE_FRAME)
# The JS builds decoration overlays WITHOUT baking in the z-fight lift -- it
# hands the renderer `normal` and `side` and biases depth there instead. So a
# SURF=1 digest only compares like with like when the lift is off; leaving it
# on shows every decorated file as a volume-only difference (identical area,
# identical bounds) and hides any real placement bug in the noise.
if os.environ.get('SURF_OFFSET') is not None:
    d3d.SURF_OFFSET = float(os.environ['SURF_OFFSET'])


def digest(meshes):
    tris = area = vol = 0
    lo = np.full(3, np.inf); hi = np.full(3, -np.inf)
    for m in meshes:
        V = m[0]
        for (a, b, cc) in m[1]:
            A, B, C = V[a], V[b], V[cc]
            area += float(np.linalg.norm(np.cross(B - A, C - A))) / 2
            # signed volume is independent of how a surface happens to be tessellated
            vol += float(np.dot(A, np.cross(B, C))) / 6
            tris += 1
        if len(V):
            lo = np.minimum(lo, V.min(0)); hi = np.maximum(hi, V.max(0))
    r = lambda x: round(float(x), 3)
    return {'meshes': len(meshes), 'tris': tris, 'area': r(area), 'volume': r(vol),
            'lo': [r(x) for x in lo], 'hi': [r(x) for x in hi]}


out = {}
for rel in sys.argv[1:]:
    base = os.path.basename(rel)
    try:
        if rel.upper().endswith('.WLB'):
            for name, it in wlb.items(rel):
                ms = []
                d3d.collect(it, np.eye(4), ms)
                out[f'{base}::{name}'] = digest(ms)
        else:
            out[base] = digest(d3d.scene_meshes(rel))
    except Exception as e:
        out[base] = {'error': f'{type(e).__name__}: {e}'}
print(json.dumps(out))
