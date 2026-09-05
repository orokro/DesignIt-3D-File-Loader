"""Face-assignment oracle: does each decoration FIT on the face it claims?

The fourth oracle, and the one that finally settled `SURF`'s face numbering.

A `FEAT` outline is laid out in the 2D frame of ONE face of its prism, so its
extent in that frame must lie inside the face's own extent. Unlike decalfit.py,
which only asks whether a decal escapes its prism's bounding BOX, this asks
which individual FACE the outline actually fits on -- so it can tell "painted on
the 0.5-inch chamfer instead of the 20-inch top" from "painted correctly".

That distinction is what exposed the numbering bug. The old rule numbered side
faces by walking the profile's edges BACKWARDS; the true rule names a side face
after the vertex its edge ARRIVES at. On a rectangular prism the two rules
differ only by swapping OPPOSITE faces, which is invisible to every oracle that
measures bounding boxes and nearly invisible to the eye -- the decal is still on
a face of the right size, just the far side of the object. It showed up as the
`Lectern`'s pages on its underside and the `Microwave, undercabinet`'s control
panel on its back. On prisms with an odd or irregular profile the two rules
diverge properly, and there the decal lands in mid-air: the `Bar Sink`'s basin.

    misfits, FACE_ORDER='rev' (old): 126 / 2532
    misfits, FACE_ORDER='end' (new):  22 / 2532

CAUTION: a decal that "fits" is not proof it is on the RIGHT face -- opposite
faces of a box fit equally well. Use this to find failures, not to confirm
successes; for that, render against the VRIF preview.
"""
import sys, os, glob, math, json, collections
sys.path.insert(0, os.path.dirname(__file__))
import numpy as np
import iff, d3d, wlb

SLACK = 0.6      # inches of tolerance, matching decalfit.py


def face_fit(verts, tris, poly2, tr):
    """Lay the outline out on this face; -> max overhang in inches (<0 = slack)."""
    fr = d3d.face_frame(verts, tris)
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


def scan(paths, slack=SLACK):
    """-> (n_misfit, n_total, rows) where a row describes one decoration."""
    rows = []
    for p in paths:
        try:
            items = wlb.items(p)
        except Exception:
            continue
        gal = os.path.basename(p)
        for name, it in items:
            def walk(node):
                for k in node.children:
                    if k.tag not in ('PRSM', 'PGRP'):
                        continue
                    if k.tag == 'PRSM' and k.kids('SURF'):
                        m = d3d.prsm_mesh(k)
                        if m:
                            verts, faces, poly, fids = m
                            byface = {}
                            for t, fid in zip(faces, fids):
                                byface.setdefault(fid, []).append(t)
                            for s in k.kids('SURF'):
                                fid = iff.u16(s.hdr, 0)
                                for f in s.kids('FEAT'):
                                    p2 = d3d.feat_polygon(f)
                                    if not p2 or len(p2) < 3:
                                        continue
                                    tr = d3d.feat_transform(f)
                                    fits = []
                                    for cand, tris in byface.items():
                                        o = face_fit(verts, tris, p2, tr)
                                        if o is not None:
                                            fits.append((round(o, 3), cand))
                                    if not fits:
                                        continue
                                    fits.sort()
                                    here = dict((c, o) for o, c in fits).get(fid)
                                    rows.append(dict(
                                        gal=gal, name=name, n=len(poly.verts),
                                        nband=len(poly.rings()) - 1,
                                        nslic=len(k.kids('SLIC')),
                                        nfaces=len(byface), fid=fid,
                                        best=fits[0][1], bestover=fits[0][0],
                                        fidover=here,
                                        fits=[c for o, c in fits if o <= slack]))
                    walk(k)
            try:
                walk(it)
            except Exception:
                pass
    bad = [r for r in rows if r['fidover'] is None or r['fidover'] > slack]
    return len(bad), len(rows), rows


if __name__ == '__main__':
    pats = [a for a in sys.argv[1:] if '=' not in a] or ['data/galleries3d/*.WLB']
    for a in sys.argv[1:]:
        if a.startswith('order='):
            d3d.FACE_ORDER = a.split('=', 1)[1]
    files = [p for pat in pats for p in sorted(glob.glob(pat))
             if not os.path.basename(p).startswith('ID')]
    bad, tot, rows = scan(files)
    print(f'FACE_ORDER={d3d.FACE_ORDER}  '
          f'decorations that do not fit their stored face: {bad}/{tot} '
          f'({100 * bad / max(tot, 1):.2f}%)')
    miss = [r for r in rows if r['fidover'] is None or r['fidover'] > SLACK]
    for name, k in collections.Counter(r['name'] for r in miss).most_common(20):
        r = next(x for x in miss if x['name'] == name)
        print(f'  {k:4d}  {name[:32]:32s} {r["gal"][:12]:12s} '
              f'n={r["n"]} bands={r["nband"]} slic={r["nslic"]} '
              f'fid={r["fid"]} best={r["best"]}')
