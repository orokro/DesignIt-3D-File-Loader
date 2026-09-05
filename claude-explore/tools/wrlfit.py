"""GROUND-TRUTH oracle: our reconstruction vs the application's own VRML export.

Every other oracle in this project is indirect -- a 50x50 silhouette, a bounding
box, a "does the decal fit" test -- and each one has, at least once, scored the
right answer and the wrong answer identically. This one is not indirect: the
application itself wrote out the vertices it believes the file describes.

Pairs come from two places:
  * the Virtus VRML disc, which SHIPS 19 .WRL files beside their .VVR sources
    (dated 1996, exported by Virtus themselves)
  * `D3D/2026_New_Exports/WRL Exports/`, exported by the user on demand

CONVENTIONS, all learned the hard way:
  * VRML units are METRES; divide by 0.0254 for our inches.
  * VRML is Y-UP. The permutation is recovered per file, not assumed.
  * Compare bounding-box centres, NEVER vertex means. The app tessellates
    unevenly, and a vertex mean invented a 6.5-inch displacement of the
    `Printer w/stand` body that does not exist.
  * Fit the rigid offset by RANSAC over candidate solid pairings. A least
    squares or median fit is dragged off by whichever solids actually disagree,
    which is precisely the population you are trying to measure.
"""
import os, re, sys, glob, itertools
import numpy as np

INCH = 0.0254


def parse_wrl(path):
    """-> list of Nx3 vertex arrays, one per IndexedFaceSet, in METRES."""
    txt = open(path, 'r', errors='replace').read()
    out = []
    for m in re.finditer(r'Coordinate3\s*\{\s*point\s*\[(.*?)\]\s*\}', txt, re.S):
        pts = re.findall(r'-?\d+\.?\d*(?:[eE][-+]?\d+)?', m.group(1))
        if len(pts) >= 9:
            out.append(np.array([float(x) for x in pts], float).reshape(-1, 3))
    return out


def solids_ours(path_or_item):
    import d3d
    d3d.DRAW_SURF = False
    if isinstance(path_or_item, str):
        ms = d3d.scene_meshes(path_or_item)
    else:
        ms = []
        d3d.collect(path_or_item, np.eye(4), ms)
    return [m[0] for m in ms if len(m[0])]


def _bb(v):
    return (v.max(0) + v.min(0)) / 2, v.max(0) - v.min(0)


def align(app, ours, cap=14):
    """Find (perm, signs, translation) mapping app-space onto ours, by RANSAC.

    Only the `cap` largest solids propose candidate offsets -- a scene has
    hundreds of solids and the naive all-pairs search is O(n^2) per orientation,
    which simply never finishes on `BEACHCBN`. The largest solids are also the
    most reliable anchors, and the inlier count is still evaluated against
    EVERY solid.
    -> (inliers, perm, signs, t)
    """
    oc = np.array([_bb(v)[0] for v in ours])
    oe = np.array([_bb(v)[1] for v in ours])
    big_a = sorted(range(len(app)), key=lambda i: -np.prod(_bb(app[i])[1]))[:cap]
    big_o = sorted(range(len(ours)), key=lambda j: -np.prod(oe[j]))[:cap]
    best = None
    for perm in itertools.permutations(range(3)):
        ae_p = np.array([_bb(v[:, perm])[1] for v in app])
        ac_p = np.array([_bb(v[:, perm])[0] for v in app])
        for sgn in itertools.product((1, -1), repeat=3):
            S = np.array(sgn, float)
            ac = ac_p * S
            for i in big_a:
                for j in big_o:
                    if np.abs(ae_p[i] - oe[j]).sum() > 0.3:
                        continue
                    t = oc[j] - ac[i]
                    # vectorised: nearest our-solid for every app solid at once
                    d = (np.abs((ac + t)[:, None, :] - oc[None, :, :]).sum(2)
                         + np.abs(ae_p[:, None, :] - oe[None, :, :]).sum(2))
                    inl = int((d.min(1) < 0.5).sum())
                    if best is None or inl > best[0]:
                        best = (inl, perm, S, t)
    return best


def compare(vvr, wrl, item=None):
    app = [v / INCH for v in parse_wrl(wrl)]
    ours = solids_ours(item if item is not None else vvr)
    if not app or not ours:
        return None
    got = align(app, ours)
    if got is None:
        return None
    inl, perm, S, t = got
    ac = np.array([_bb(v[:, perm])[0] * S + t for v in app])
    ae = np.array([_bb(v[:, perm])[1] for v in app])
    oc = np.array([_bb(v)[0] for v in ours])
    oe = np.array([_bb(v)[1] for v in ours])
    used, rows = set(), []
    for i in np.argsort([-e.max() for e in ae]):
        bj, bd = None, 1e18
        for j in range(len(ours)):
            if j in used:
                continue
            d = np.linalg.norm(ac[i] - oc[j]) + np.abs(ae[i] - oe[j]).sum()
            if d < bd:
                bd, bj = d, j
        if bj is None:
            continue
        used.add(bj)
        rows.append({'centre': float(np.linalg.norm(ac[i] - oc[bj])),
                     'size': float(np.abs(ae[i] - oe[bj]).sum()),
                     'appExt': ae[i], 'ourExt': oe[bj],
                     'appC': ac[i], 'ourC': oc[bj]})
    return {'appSolids': len(app), 'ourSolids': len(ours), 'rows': rows,
            'perm': perm, 'signs': S, 'inliers': inl,
            'matched': sum(1 for r in rows if r['centre'] < 0.5 and r['size'] < 0.5)}


if __name__ == '__main__':
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    pairs = []
    # 3D Website Builder ships its own WRL exports beside the .WSB sources, so
    # it is more ground truth on the same terms -- pair on the stem, whichever
    # scene extension sits next to it.
    roots = ['D3D/2026_New_Exports/VirVRML', 'D3D/2026_New_Exports/3DWebBld']
    seen = set()
    for root in roots:
        for w in sorted(glob.glob(f'{root}/**/*.[wW][rR][lL]', recursive=True)):
            stem = os.path.splitext(os.path.basename(w))[0].upper()
            for d in (os.path.dirname(w), os.path.dirname(os.path.dirname(w))):
                hit = [p for p in glob.glob(os.path.join(d, '*'))
                       if os.path.splitext(os.path.basename(p))[0].upper() == stem
                       and os.path.splitext(p)[1].upper() in ('.VVR', '.WSB')]
                if hit and (stem, root) not in seen:
                    seen.add((stem, root))
                    pairs.append((hit[0], w))
                    break
    print(f'{len(pairs)} VVR/WRL ground-truth pairs\n')
    print(f'{"object":22s} {"app":>4} {"ours":>5} {"exact":>6} {"worst centre":>13} {"worst size":>11}')
    tot = ex = 0
    bad = []
    for v, w in pairs:
        try:
            r = compare(v, w)
        except Exception as e:
            print(f'{os.path.basename(v)[:22]:22s}  ERROR {type(e).__name__}: {e}')
            continue
        if r is None:
            print(f'{os.path.basename(v)[:22]:22s}  no alignment')
            continue
        wc = max((x['centre'] for x in r['rows']), default=0)
        ws = max((x['size'] for x in r['rows']), default=0)
        tot += len(r['rows']); ex += r['matched']
        print(f'{os.path.basename(v)[:22]:22s} {r["appSolids"]:4d} {r["ourSolids"]:5d} '
              f'{r["matched"]:3d}/{len(r["rows"]):<3d} {wc:11.2f} in {ws:9.2f} in')
        if r['matched'] < len(r['rows']):
            bad.append((os.path.basename(v), r))
    print(f'\nsolids matching the application exactly: {ex} / {tot}  ({100*ex/max(tot,1):.1f}%)')
