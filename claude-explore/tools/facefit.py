"""Face-assignment oracle: does each decoration FIT on the face it claims?

Scans the WHOLE corpus -- galleries, scenes AND models. It originally scanned
only `data/galleries3d`, which is 2,532 of the corpus's 19,902 decorations, or
13%. Every score quoted from it before that was a score on an eighth of the
data, and adding a Models tab to the explorer promptly exposed the rest.
**If you add an oracle, point it at everything.**

A `FEAT` outline is laid out in the 2D frame of ONE face of its prism, so its
extent in that frame must lie inside the face's own extent. Unlike decalfit.py,
which only asks whether a decal escapes its prism's bounding BOX, this asks
which individual FACE the outline fits on -- so it can tell "painted on the
0.5-inch chamfer instead of the 20-inch top" from "painted correctly".

READ THE HISTOGRAM, NOT THE HEADLINE COUNT. A decoration is allowed to overhang
its face: `CAPECOD`'s windows are a 28x50 frame on a 24x46 wall panel, so they
overhang by exactly 2 inches by design, 110 times. Overhangs under a few inches
are trim; the ones worth chasing are the decorations adrift by tens of inches.

CAUTION: a decal that "fits" is not proof it is on the RIGHT face -- opposite
faces of a box fit equally well, and so does a MIRRORED layout. Use this to find
failures, not to confirm successes; for that, render against the VRIF preview.
"""
import sys, os, glob, math, collections
sys.path.insert(0, os.path.dirname(__file__))
import numpy as np
import iff, d3d, wlb

SLACK = 0.6      # inches; matches decalfit.py
ADRIFT = 15.0    # inches; beyond this it is not trim, it is a bug


def face_fit(verts, tris, poly2, tr, sweep=None):
    """Lay the outline out on this face; -> max overhang in inches (<0 = slack)."""
    fr = d3d.face_frame(verts, tris, sweep=sweep)
    if fr is None:
        return None
    corner, u, v, nrm, middle = fr
    tx, ty, th, sx, sy = tr
    ct, st = math.cos(th), math.sin(th)
    pts = [(ct * (x * sx) - st * (y * sy) + tx,
            st * (x * sx) + ct * (y * sy) + ty) for (x, y) in poly2]
    ii = sorted({i for t in tris for i in t})
    P = verts[ii]
    fu, fv = P @ u, P @ v
    du = [corner @ u + a for a, _ in pts]
    dv = [corner @ v + b for _, b in pts]
    return float(max(fu.min() - min(du), max(du) - fu.max(),
                     fv.min() - min(dv), max(dv) - fv.max()))


def _scan_item(item, name, bucket, rows):
    def walk(node):
        for k in node.children:
            if k.tag not in ('PRSM', 'PGRP'):
                continue
            if k.tag == 'PRSM' and k.kids('SURF'):
                m = d3d.prsm_mesh(k)
                if m:
                    verts, faces, poly, fids = m
                    swp = d3d.axis_matrix(poly.axis) @ np.array([0.0, 0.0, 1.0])
                    byface = {}
                    for t, fid in zip(faces, fids):
                        byface.setdefault(fid, []).append(t)
                    nb = len(poly.rings()) - 1
                    n = len(poly.verts)
                    sl = k.kid('SLIC')
                    nrec = (len(sl.data) - 2) // 16 if sl is not None and len(sl.data) > 2 else 0
                    maxid = nb * n + 1 + nrec
                    for s in k.kids('SURF'):
                        fid = iff.u16(s.hdr, 0)
                        tris = byface.get(fid)
                        for f in s.kids('FEAT'):
                            p2 = d3d.feat_polygon(f)
                            if not p2 or len(p2) < 3:
                                continue
                            if tris is None:
                                rows.append(dict(bucket=bucket, name=name, fid=fid, over=None,
                                                 cause=('face id beyond the numbering' if fid > maxid
                                                        else 'face removed by clipping')))
                                continue
                            o = face_fit(verts, tris, p2, d3d.feat_transform(f), sweep=swp)
                            if o is None:
                                continue
                            rows.append(dict(bucket=bucket, name=name, fid=fid, over=o, cause=None))
            walk(k)
    try:
        walk(item)
    except Exception:
        pass


def corpus(data='data'):
    """-> one row per decoration across galleries, scenes and models."""
    rows = []
    for p in sorted(glob.glob(os.path.join(data, 'galleries3d', '*.WLB'))):
        if os.path.basename(p).startswith('ID'):
            continue
        try:
            items = wlb.items(p)
        except Exception:
            continue
        for name, it in items:
            _scan_item(it, name, 'gallery', rows)
    for bucket in ('scenes', 'models'):
        for p in sorted(glob.glob(os.path.join(data, bucket, '*.VVR'))):
            try:
                r = iff.load(p)
            except Exception:
                continue
            for root in (r.find_all('ROOT') or [r]):
                _scan_item(root, os.path.basename(p), bucket, rows)
    return rows


if __name__ == '__main__':
    for a in sys.argv[1:]:
        if a.startswith('frame='):
            d3d.FACE_FRAME = a.split('=', 1)[1]
    rows = corpus()
    print(f'FACE_FRAME={d3d.FACE_FRAME}   decorations: {len(rows)}')
    for b in ('gallery', 'scenes', 'models'):
        sub = [r for r in rows if r['bucket'] == b]
        bad = [r for r in sub if r['over'] is None or r['over'] > SLACK]
        if sub:
            print(f'  {b:8s} over {SLACK} in: {len(bad):5d} / {len(sub):5d}  ({100*len(bad)/len(sub):5.2f}%)')
    print('\n  overhang histogram (a few inches is trim, not a bug):')
    for lo, hi, label in ((SLACK, 2.5, '0.6 - 2.5 in'), (2.5, 6, '2.5 - 6 in'),
                          (6, ADRIFT, f'6 - {ADRIFT:g} in'), (ADRIFT, 50, '15 - 50 in'),
                          (50, float('inf'), 'over 50 in')):
        k = sum(1 for r in rows if r['over'] is not None and lo < r['over'] <= hi)
        print(f'    {label:>14}: {k:5d}')
    miss = [r for r in rows if r['over'] is None]
    print(f'    {"no such face":>14}: {len(miss):5d}')
    adrift = [r for r in rows if r['over'] is not None and r['over'] > ADRIFT]
    print(f'\n  ADRIFT (over {ADRIFT:g} in) -- the real problem: {len(adrift)}')
    for n, c in collections.Counter(r['name'] for r in adrift).most_common(12):
        print(f'    {c:5d}  {n}')
    if miss:
        print('\n  naming a face that does not exist:')
        for cause, c in collections.Counter(r['cause'] for r in miss).most_common():
            print(f'    {c:5d}  {cause}')
