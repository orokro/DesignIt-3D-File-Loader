import sys, os, json, glob, hashlib
sys.path.insert(0, os.path.join(os.environ['HOME'], 'mnt/DesignIt-3D-File-Loader/claude-explore/tools'))
os.chdir(os.path.join(os.environ['HOME'], 'mnt/DesignIt-3D-File-Loader'))
import numpy as np, wlb, d3d

def h(*parts):
    x = hashlib.sha1()
    for p in parts: x.update(p if isinstance(p, bytes) else str(p).encode())
    return x.hexdigest()[:16]

def fingerprints(meshes):
    allv = np.vstack([np.asarray(m[0], float) for m in meshes])
    lo = allv.min(0); hi = allv.max(0)
    exact, shape, iso = [], [], []
    tris = 0; area = 0.0
    for m in meshes:
        V = np.asarray(m[0], float) - lo
        F = np.asarray(m[1], dtype=np.int64)
        col = tuple(int(c) for c in m[2])
        vb = np.round(V, 2).tobytes(); fb = F.astype(np.int32).tobytes()
        shape.append(h(vb, fb))
        exact.append(h(vb, fb, col))
        T = V[F]                                    # (n,3,3)
        e = np.sort(np.round(np.linalg.norm(np.stack([
            T[:,1]-T[:,0], T[:,2]-T[:,1], T[:,0]-T[:,2]], 1), axis=2), 2), axis=1)
        a = np.round(0.5*np.linalg.norm(np.cross(T[:,1]-T[:,0], T[:,2]-T[:,0]), axis=1), 2)
        tris += len(F); area += float(a.sum())
        iso.extend((float(a[i]), tuple(e[i])) for i in range(len(F)))
    iso_h = h(json.dumps(sorted(iso)))
    cols = sorted(tuple(int(c) for c in m[2]) for m in meshes)
    return {
        'exact': h(json.dumps(sorted(exact))),
        'shape': h(json.dumps(sorted(shape))),
        'iso':   h(iso_h, json.dumps(cols)),
        'isoNC': iso_h,
        'tris': tris, 'meshes': len(meshes), 'area': round(area, 1),
        'size': [round(float(x), 2) for x in (hi - lo)],
    }

out = []
files = sorted(glob.glob('data/galleries3d/*'))
for fi, p in enumerate(files):
    base = os.path.basename(p)
    rel = 'galleries3d/' + base
    skip_file = base.startswith('ID')       # explore.html filters these out
    try: its = wlb.items(p)
    except Exception as e:
        out.append({'file': rel, 'error': str(e)}); continue
    seen = {}
    for idx, (name, chunk) in enumerate(its):
        rec = {'file': rel, 'idx': idx, 'name': name, 'fileHidden': skip_file}
        try:
            ms = []
            d3d.collect(chunk, np.eye(4), ms)
        except Exception as e:
            rec['error'] = str(e)[:120]; out.append(rec); continue
        if not ms:
            rec['skip'] = 'empty'; out.append(rec); continue
        fp = fingerprints(ms)
        rec.update(fp)
        if fp['size'][0] > 4000 or fp['size'][1] > 4000:
            rec['skip'] = 'oversize'; out.append(rec); continue
        n = seen.get(name, 0) + 1; seen[name] = n
        rec['path'] = f'{rel}::{name}' + ('' if n == 1 else f'#{n}')
        rec['nth'] = n
        out.append(rec)
    print(f'{fi+1}/{len(files)} {base} {len(its)}', flush=True)

json.dump(out, open(os.path.join(os.environ['HOME'], 'dd/clips.json'), 'w'))
print('DONE', len(out))
