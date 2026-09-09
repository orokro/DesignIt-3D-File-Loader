"""Find duplicate clips and models across the corpus.

WHAT COUNTS AS A DUPLICATE

Only an object that is the same *as the app would present it*. That means:

  - same geometry in the same orientation, up to a translation. Several
    duplicates differ only by a leftover world offset -- `Chairs2::MR Ottoman`
    sits at (240, 1130) in one copy and at the origin in the other -- so
    everything is compared with its bounding box seated at the origin.
  - same colours, same per-face opacity, and the same textures. Design-It! and
    Kesign3D ship geometrically identical models where only the Kesign3D copy
    is textured; those are two different objects and both are kept. The texture
    enters the fingerprint by NAME plus a hash of its pixels, so the same
    bitmap matches across files while a missing one never does.

and explicitly NOT:

  - a rotation. `BASIC_F` / `BASIC_R` are the Front and Right working views of
    one primitive -- the same solid swept along a different axis. The app
    offers them as separate library entries, so we do too.
  - a reflection. `X1AL` / `X1AR` are left- and right-hand worksurfaces; ten of
    them are exact mirror pairs. Again, separate catalogue parts.

Both are still *detected* and reported as variants, because knowing that
`ADVNCE_F::Octagon Sphere` is `ADVNCE_R::Octagon Sphere` rotated is worth having
even when neither is deleted.

TESTS, cheapest first

  exact       hash (verts, tris, colour, alpha, texture) per mesh, sort the mesh
              hashes, hash again. Order- and position-independent.
  identity    for clips with equal triangle and mesh counts and equal surface
              area, a true Hausdorff distance at the identity transform,
              tolerance 0.30". Correspondence-free, so it survives
              re-tessellation and vertex renumbering.
  variants    the same Hausdorff over the 48 signed axis permutations, split
              into proper rotations and reflections. Reported, never merged.
  layout      web/src/pack.js ported, so a clip can be located by row and
              column -- which is how a hand-made mark list gets checked against
              what was actually standing next to it.

USAGE

    python dedupe.py scan    galleries3d|models|scenes
    python dedupe.py pairs   <bucket>
    python dedupe.py report  <bucket> [marks.txt]
    python dedupe.py suppress <bucket> [more buckets...]   -> data/dedupe.json

`data/manifest.json` supplies the file list and each file's `apps`; every
cross-library duplicate in galleries3d turned out to be one product re-releasing
another's library under a new name.
"""
import sys, os, json, hashlib, collections, itertools
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import iff, wlb, d3d

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
OUT = os.path.join(ROOT, 'claude-explore', 'out', 'dedupe')
TOL = 0.30          # inches; a Hausdorff distance under this is "the same"


def _h(*parts):
    x = hashlib.sha1()
    for p in parts:
        x.update(p if isinstance(p, bytes) else str(p).encode())
    return x.hexdigest()[:16]


def _texkey(tex, cache=None):
    """A texture's identity: WHICH bitmap, and HOW it is laid down.

    Not the TXID -- that is a per-file index. Not the pixels either, and this
    took two tries to get right. The products re-encode: OCEANFLR's `Tile 3.0`
    is quantised to six channel levels in the Kesign3D copy (0, 64, 128, 192,
    224, 255) and sixteen in the VirVRML one, the same picture at correlation
    0.976 without a byte in common. A mean-colour signature survived that but
    was brittle at its own bucket edges -- `Grasses 1.0` in the two White House
    copies landed either side of one, which kept two identical scenes apart.

    So: the name with VirVRML's `\xa58+\xa5128x64` suffix stripped, the pixel
    dimensions, and the TXST tile size. Tile size belongs in the identity
    because it is visible: OCEANFLR's two `Water-Pool 1.0` entries are the same
    128x64 bitmap at 60" and 32" per tile, and the two copies of that scene use
    them differently on the same face. That is a real difference, and it is the
    only thing keeping those two apart.
    """
    if not tex:
        return ''
    name = (tex.get('name') or '').split('\xa5')[0].strip()
    tile = tex.get('tile') or (0, 0)
    return (f'{name}|{tex.get("w")}x{tex.get("h")}'
            f'|{round(float(tile[0]), 2)}x{round(float(tile[1]), 2)}')


def fingerprint(meshes):
    allv = np.vstack([np.asarray(m[0], float) for m in meshes])
    lo, hi = allv.min(0), allv.max(0)
    exact, shape, body = [], [], []
    tris = 0
    area = 0.0
    texs = []
    textured = 0
    for m in meshes:
        V = np.round(np.asarray(m[0], float) - lo, 2)
        F = np.asarray(m[1], dtype=np.int32)
        col = tuple(int(c) for c in m[2])
        tex = _texkey(m[4] if len(m) > 4 else None)
        alpha = int(m[5]) if len(m) > 5 and m[5] is not None else 255
        vb, fb = V.tobytes(), F.tobytes()
        shape.append(_h(vb, fb))
        body.append(_h(vb, fb, alpha))
        exact.append(_h(vb, fb, col, alpha, tex))
        if tex:
            textured += 1
            texs.append(tex)
        T = V[F]
        a = 0.5 * np.linalg.norm(np.cross(T[:, 1] - T[:, 0], T[:, 2] - T[:, 0]), axis=1)
        tris += len(F)
        area += float(a.sum())
    return {'exact': _h(json.dumps(sorted(exact))),
            'shape': _h(json.dumps(sorted(shape))),
            # `body` is geometry and opacity only -- no colour, no texture. It
            # has to drop colour as well, because painting a face changes the
            # colour UNDER the paint: APOLLO's sky face is (99,99,255) plain and
            # (255,255,255) once `CloudScape 1.0` goes on it, and SPLASHDN's sea
            # goes blue -> grey under `Water-Pool 1.0`. In every observed case
            # the ONLY meshes that differ between two copies are the ones that
            # gained a bitmap, so colour is an effect of the finish, not a
            # distinction from it.
            'body': _h(json.dumps(sorted(body))),
            'texs': sorted(texs),
            'tris': tris, 'meshes': len(meshes), 'area': round(area, 1),
            'textured': textured, 'texset': _h(json.dumps(sorted(texs))),
            'size': [round(float(x), 2) for x in (hi - lo)]}


# explore.html's ground-pad cull, ported. The fingerprint has to be taken on
# the geometry the VIEWER shows, not on what the file contains: `SHUTTLE__kesign3d`
# and `launch__3dwebbld` are the same 128-mesh model under differently-sized
# backdrop slabs, and comparing them with the slabs on says they are 2.4x
# different in extent. It also matters for textures -- all three bitmaps in
# SHUTTLE__kesign3d are ON the slabs, so the model itself is untextured.
CULL_FACTOR, CULL_FLOOR, CULL_GAP = 3, 1000, 4


def _foot(m):
    V = np.asarray(m[0], float)
    return float(max(np.ptp(V[:, 0]), np.ptp(V[:, 1]))) if len(V) else 0.0


def cull_pads(meshes):
    """Drop backdrop slabs: candidates are over CULL_FACTOR x the median (and
    over CULL_FLOOR inches); the cut goes at the largest ratio gap of at least
    CULL_GAP. Median-anchored so a file with no pad at all loses nothing."""
    idx = [i for i, m in enumerate(meshes) if len(m[0])]
    if len(idx) < 2:
        return meshes, 0
    foot = [_foot(meshes[i]) for i in idx]
    order = sorted(range(len(idx)), key=lambda k: -foot[k])
    desc = [foot[k] for k in order]
    limit = max(CULL_FLOOR, CULL_FACTOR * (desc[len(desc) >> 1] or 1))
    n = 0
    while n < len(desc) and desc[n] > limit:
        n += 1
    drop = set()
    if n and n < len(desc):
        cut, best = 0, 0.0
        for k in range(1, n + 1):
            r = desc[k - 1] / desc[k]
            if r > best and r >= CULL_GAP:
                best, cut = r, k
        for t in range(cut):
            drop.add(idx[order[t]])
    if not drop:
        return meshes, 0
    kept = [m for i, m in enumerate(meshes)
            if i not in drop and not (len(m) > 7 and m[7] and _foot(m) > CULL_FLOOR)]
    return kept, len(drop)


def _record(rec, meshes, verts, max_span=None):
    """max_span mirrors explore.html's gallery-grid guard against stray oversize
    CLIPS; a scene or a model is meant to be huge, so it is not applied there."""
    if not meshes:
        rec['skip'] = 'empty'
        return False
    rec.update(fingerprint(meshes))
    if max_span and (rec['size'][0] > max_span or rec['size'][1] > max_span):
        rec['skip'] = 'oversize'
        return False
    A = np.vstack([np.asarray(m[0], float) for m in meshes])
    verts[rec['path']] = np.unique(np.round(A - A.min(0), 2), axis=0)
    return True


def scan(bucket):
    """Every object in a bucket, fingerprinted, addressed the way the viewer does.

    A gallery file holds many clips (`<file>::<clip>`, with the #2/#3 suffix
    explore.html uses for repeated names -- four galleries repeat one); a scene
    or model file is a single object addressed by its path alone.
    """
    man = json.load(open(os.path.join(ROOT, 'data', 'manifest.json')))
    files = [f for f in man['files'] if f['bucket'] == bucket]
    out, verts = [], {}
    for f in files:
        p = os.path.join(ROOT, 'data', f['path'])
        try:
            root = iff.load(p)
        except Exception as e:
            out.append({'file': f['path'], 'error': str(e)[:120]})
            continue
        try:
            import textures as _tx
            d3d.TEXTURES = _tx.table(root) if d3d.DRAW_TEXTURES else {}
        except Exception:
            d3d.TEXTURES = {}
        if bucket.startswith('galleries'):
            seen = {}
            for i, (name, chunk) in enumerate(wlb.items(p)):
                rec = {'file': f['path'], 'idx': i, 'name': name, 'apps': f['apps']}
                n = seen.get(name, 0) + 1
                rec['path'] = f'{f["path"]}::{name}' + ('' if n == 1 else f'#{n}')
                ms = []
                try:
                    d3d.collect(chunk, np.eye(4), ms)
                except Exception as e:
                    rec['error'] = str(e)[:120]
                    out.append(rec)
                    continue
                if _record(rec, ms, verts, max_span=4000):
                    seen[name] = n
                    rec['nth'] = n
                else:
                    rec.pop('path', None)
                out.append(rec)
        else:
            rec = {'file': f['path'], 'idx': 0, 'apps': f['apps'],
                   'name': f['path'].split('/')[-1], 'path': f['path']}
            try:
                ms = d3d.scene_meshes(root)
            except Exception as e:
                rec['error'] = str(e)[:120]
                out.append(rec)
                continue
            ms, rec['culled'] = cull_pads(ms)
            if not _record(rec, ms, verts):
                rec.pop('path', None)
            out.append(rec)
        print('  read', f['path'], flush=True)
    os.makedirs(OUT, exist_ok=True)
    json.dump(out, open(os.path.join(OUT, f'{bucket}.json'), 'w'))
    np.savez_compressed(os.path.join(OUT, f'{bucket}.npz'), **verts)
    return out, verts


def _mats():
    """The 48 signed permutation matrices: 24 rotations + 24 reflections."""
    out = []
    for perm in itertools.permutations(range(3)):
        for sgn in itertools.product((1, -1), repeat=3):
            M = np.zeros((3, 3))
            for i, p in enumerate(perm):
                M[i, p] = sgn[i]
            out.append((M, np.linalg.det(M) > 0))
    return out


MATS = _mats()


def _haus(A, B):
    # Hausdorff needs no correspondence and no equal point counts. Collapsing
    # duplicate vertices leaves the two sides with different totals often enough
    # (most of the modular L/R families) that requiring equality here silently
    # skipped the very pairs the reflection test exists for. The triangle-count,
    # mesh-count and area gate in pairs() is what keeps it honest.
    d = np.abs(A[:, None, :] - B[None, :, :]).max(2)
    return float(max(d.min(1).max(), d.min(0).max()))


def compare(a, b):
    """{'id', 'rot', 'ref'} Hausdorff distances.

    `id` is the one that decides a duplicate; `rot` and `ref` are the best
    proper-rotation and reflection alignments, reported so a variant can be
    named without being merged.
    """
    A = a - a.min(0)
    res = {'id': _haus(A, b - b.min(0)), 'rot': float('inf'), 'ref': float('inf')}
    for M, proper in MATS:
        B = b @ M.T
        B = B - B.min(0)
        v = _haus(A, B)
        key = 'rot' if proper else 'ref'
        if v < res[key]:
            res[key] = v
    return res


def pairs(recs, verts, tol=TOL, cap=60):
    """(duplicates, rotated variants, reflected variants) beyond the exact hash."""
    dup, rot, ref = [], [], []
    buck = collections.defaultdict(list)
    for r in recs:
        if 'path' in r and 'exact' in r:
            buck[(r['tris'], r['meshes'], r['textured'])].append(r)
    for v in buck.values():
        if not 2 <= len(v) <= cap:
            continue
        for a, b in itertools.combinations(v, 2):
            if a['exact'] == b['exact']:
                continue
            if abs(a['area'] - b['area']) > max(2.0, 0.002 * a['area']):
                continue
            # geometry alone is not identity: Design-It! and Kesign3D ship the
            # same model where only one copy is textured, and OCEANFLR differs
            # by a single bitmap. The exact hash already accounts for this; the
            # tolerance path has to as well or it re-merges what that separated.
            if a['texset'] != b['texset']:
                continue
            c = compare(verts[a['path']], verts[b['path']])
            row = (a['path'], b['path'], round(min(c.values()), 2))
            if c['id'] <= tol:
                dup.append(row)
            elif c['rot'] <= tol:
                rot.append(row)
            elif c['ref'] <= tol:
                ref.append(row)
    return dup, rot, ref


def objects(recs, dup):
    """Union exact hashes with the identity-matched pairs -> path -> object id."""
    par = {}

    def find(x):
        par.setdefault(x, x)
        while par[x] != x:
            par[x] = par[par[x]]
            x = par[x]
        return x

    def uni(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            par[ra] = rb

    E = {r['path']: r['exact'] for r in recs if 'path' in r and 'exact' in r}
    for e in E.values():
        find(e)
    for a, b, _ in dup:
        uni(E[a], E[b])
    return {p: find(e) for p, e in E.items()}


def layout(recs, bucket, gap=30, aisle=70, hide_id=False):
    """web/src/pack.js, in Python: {row: [(x, path), ...]} left to right."""
    man = json.load(open(os.path.join(ROOT, 'data', 'manifest.json')))
    order = [f['path'] for f in man['files'] if f['bucket'] == bucket
             and not (hide_id and f['path'].split('/')[-1].startswith('ID'))]
    by = collections.defaultdict(list)
    for r in recs:
        if 'path' in r and 'exact' in r:
            by[r['file']].append(r)
    items = [r for p in order for r in sorted(by[p], key=lambda r: r['idx'])]
    L = [{'w': max(r['size'][0], 1), 'd': max(r['size'][1], 1), 'r': r} for r in items]
    if not L:
        return {}
    L.sort(key=lambda o: (-o['d'], -o['w']))          # stable, as JS sort is
    total = sum((o['w'] + gap) * (o['d'] + aisle) for o in L)
    rowWidth = max(total ** 0.5, L[0]['w'] * 1.2)
    x = y = rowDepth = 0.0
    row = 0
    rows = collections.defaultdict(list)
    for o in L:
        if x > 0 and x + o['w'] > rowWidth:
            y += rowDepth + aisle
            x = 0.0
            rowDepth = 0.0
            row += 1
        rows[row].append((x + o['w'] / 2, o['r']['path']))
        x += o['w'] + gap
        rowDepth = max(rowDepth, o['d'])
    for k in rows:
        rows[k].sort()
    return dict(rows)


def _redundant_files(good, obj, prefer_original=True):
    """Whole files every one of whose objects also lives somewhere else.

    Hiding a library outright beats hiding 21 of its 27 clips: the gallery keeps
    coherent sets instead of swiss cheese, and the reason is one sentence rather
    than twenty-one. Greedy, worst offender first, re-checking each round so the
    last copy of an object is never hidden.
    """
    by = collections.defaultdict(list)
    for r in good:
        by[r['file']].append(r)
    S = {f: set(obj[r['path']] for r in v) for f, v in by.items()}
    apps = {f: v[0]['apps'] for f, v in by.items()}
    alive, dropped = set(by), []
    while True:
        cnt = collections.Counter()
        for f in alive:
            cnt.update(S[f])
        cand = [f for f in alive if S[f] and all(cnt[o] > 1 for o in S[f])]
        if not cand:
            break

        def score(f):
            base = f.split('/')[-1]
            reissue = apps[f] == ['3dwebbld']
            w = reissue if prefer_original else not reissue
            return (-int('__' in base), -int(w), len(apps[f]), -len(by[f]), base)

        cand.sort(key=score)
        f = cand[0]
        alive.discard(f)
        dropped.append(f)
    return set(dropped)


def _finish_pairs(good, obj):
    """Copies of one object that differ ONLY in how much of it is textured.

    Design-It! and Kesign3D ship the same model where only the Kesign3D copy
    carries bitmaps; VirVRML does it again. Geometry, colours and opacity are
    identical -- `body` is the fingerprint with the textures taken back out --
    and one side's texture set is a strict subset of the other's. That is not
    two objects, it is one object at two levels of finish, and the gallery only
    needs to show the finished one.

    A DIFFERENT texture set is not a subset and never matches: OCEANFLR's two
    copies both carry seven bitmaps and differ by which water goes on one face,
    so both stay.

    Returns {path to hide: path that supersedes it}.
    """
    by = collections.defaultdict(list)
    for r in good:
        by[r['body']].append(r)
    out = {}
    for v in by.values():
        if len(v) < 2:
            continue
        for a in v:
            sa = collections.Counter(a.get('texs') or [])
            for b in v:
                if a is b or obj[a['path']] == obj[b['path']]:
                    continue
                sb = collections.Counter(b.get('texs') or [])
                if sa != sb and not (sa - sb):          # a's textures ⊂ b's
                    out[a['path']] = b['path']
                    break
    return out


def _redundant_files(good, obj, prefer_original=True):
    """Whole files every one of whose objects also lives somewhere else.

    Hiding a library outright beats hiding 21 of its 27 clips: the gallery keeps
    coherent sets instead of swiss cheese, and the reason is one sentence rather
    than twenty-one. Greedy, worst offender first, re-checking each round so the
    last copy of an object is never hidden.
    """
    by = collections.defaultdict(list)
    for r in good:
        by[r['file']].append(r)
    S = {f: set(obj[r['path']] for r in v) for f, v in by.items()}
    apps = {f: v[0]['apps'] for f, v in by.items()}
    alive, dropped = set(by), []
    while True:
        cnt = collections.Counter()
        for f in alive:
            cnt.update(S[f])
        cand = [f for f in alive if S[f] and all(cnt[o] > 1 for o in S[f])]
        if not cand:
            break

        def score(f):
            base = f.split('/')[-1]
            reissue = apps[f] == ['3dwebbld']
            w = reissue if prefer_original else not reissue
            return (-int('__' in base), -int(w), len(apps[f]), -len(by[f]), base)

        cand.sort(key=score)
        f = cand[0]
        alive.discard(f)
        dropped.append(f)
    return set(dropped)


def survivors(recs, obj, prefer_original=True, finish=True):
    """One keeper per object; everything else is hidden. Nothing is deleted.

    Three stages. First the unfinished copies -- same geometry, fewer textures
    -- give way to the finished one. Then whole files whose every object
    survives elsewhere disappear as files, so the galleries keep coherent sets.
    Then one keeper per object among what is left.

    Within a stage the preference is: the product this project is about
    (Design-It!/Kesign3D) over 3DWebBld's re-release, then the file that is NOT
    a build_data.py collision rename (`__virvrml`, `__3dwebbld`), then the more
    legible name -- a real word beats `KWALCAB1::2` -- then the shortest path,
    for stability.
    """
    good = [r for r in recs if 'path' in r and 'exact' in r]
    unfinished = _finish_pairs(good, obj) if finish else {}
    good2 = [r for r in good if r['path'] not in unfinished]
    dead = _redundant_files(good2, obj, prefer_original)
    hide = list(unfinished) + [r['path'] for r in good2 if r['file'] in dead]
    rest = [r for r in good2 if r['file'] not in dead]

    def rank(r):
        base = r['file'].split('/')[-1]
        name = r.get('name', '')
        reissue = r['apps'] == ['3dwebbld']
        cryptic = len(name) <= 2 or name.strip().isdigit()
        return (int(reissue) if prefer_original else int(not reissue),
                int('__' in base), int(cryptic), -len(r['apps']),
                len(r['path']), r['path'])

    by = collections.defaultdict(list)
    for r in rest:
        by[obj[r['path']]].append(r)
    keep = {}
    for o, v in by.items():
        v = sorted(v, key=rank)
        keep[o] = v[0]['path']
        hide.extend(x['path'] for x in v[1:])
    return keep, sorted(set(hide)), sorted(dead), unfinished


def load(bucket, rebuild=False):
    cache = os.path.join(OUT, f'{bucket}.json')
    if rebuild or not os.path.exists(cache):
        return scan(bucket)
    recs = json.load(open(cache))
    Z = np.load(os.path.join(OUT, f'{bucket}.npz'))
    return recs, {k: Z[k] for k in Z.files}


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'report'
    buckets = sys.argv[2:] or ['galleries3d']

    if cmd == 'suppress':
        out = {'note': 'paths the viewer hides in unique-only mode; nothing is '
                       'deleted, and "show all" ignores this list',
               'hide': []}
        for b in [x for x in buckets if not x.endswith('.txt')]:
            recs, verts = load(b)
            dup, _, _ = pairs(recs, verts)
            obj = objects(recs, dup)
            _, hide, dead, unf = survivors(recs, obj)
            out['hide'].extend(hide)
            out.setdefault('hiddenFiles', []).extend(dead)
            print(f'{b}: hiding {len(hide)} paths, {len(dead)} whole files, '
                  f'{len(unf)} unfinished copies')
        out['hide'].sort()
        p = os.path.join(ROOT, 'data', 'dedupe.json')
        json.dump(out, open(p, 'w'), indent=1)
        print('wrote', p, len(out['hide']), 'paths')
        return

    bucket = buckets[0]
    recs, verts = load(bucket, rebuild=(cmd == 'scan'))
    if cmd == 'scan':
        return
    dup, rotv, refv = pairs(recs, verts)
    obj = objects(recs, dup)
    good = [r for r in recs if 'path' in r and 'exact' in r]
    g = collections.defaultdict(list)
    for r in good:
        g[obj[r['path']]].append(r['path'])
    print(f'{len(good)} objects -> {len(g)} distinct '
          f'({sum(len(v) - 1 for v in g.values())} redundant)')
    print(f'{len(dup)} duplicates the exact hash missed; variants kept as '
          f'distinct: {len(rotv)} rotated, {len(refv)} reflected')
    if cmd == 'pairs':
        for tag, rows in (('dup', dup), ('rot', rotv), ('ref', refv)):
            for a, b, d in rows:
                print(f'  {tag}  {a}  |  {b}   d={d}"')
        return
    keep, hide, dead, unf = survivors(recs, obj)
    byfile = collections.Counter(p.split('::')[0] for p in hide)
    print(f'\n{len(hide)} copies hidden: {len(dead)} whole files + '
          f'{len(hide) - sum(1 for r in good if r["file"] in dead)} individual clips')
    for f, n in byfile.most_common(30):
        tot = sum(1 for r in good if r['file'] == f)
        print(f'   {f.split("/")[-1]:26} {n:3} of {tot:3}'
              + ('   WHOLE LIBRARY' if f in dead else ''))
    if len(sys.argv) > 3 and sys.argv[-1].endswith('.txt'):
        marks = set(l.strip() for l in open(sys.argv[-1]) if l.strip())
        solo = [m for m in marks if len(g[obj.get(m, m)]) == 1]
        allm = [v for v in g.values() if len(v) > 1 and all(p in marks for p in v)]
        print(f'\nmarks: {len(marks)}; with no duplicate anywhere: {len(solo)}; '
              f'clusters marked to extinction: {len(allm)}')
        for m in sorted(solo):
            print('   no twin:', m)
        for v in allm:
            print('   would lose:', ' | '.join(v))


if __name__ == '__main__':
    main()
