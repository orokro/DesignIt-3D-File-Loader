"""Decal-containment oracle.

A FEAT decoration is a 2D shape painted on ONE face of a prism, so its world
box must sit inside that prism's world box. When it does not, the decal juts
into space -- the arrow-like spikes on `Jersey Cow`, the slab beside
`Bar Sink`, the panel that used to hang ten inches below the `Copy Machine`.

This is the third oracle in the project and the sharpest one for anything that
decorates a face. Silhouette IoU cannot see a decal at all at 50x50, and
detach.py only looks at prisms. Baseline after the two-coordinate-convention
fix: 124 of 2932 (4.2%), down from 346 (11.8%).
"""
import sys, os, glob
sys.path.insert(0, os.path.dirname(__file__))
import numpy as np
import iff, d3d, wlb

SLACK = 0.6      # inches; decals are lifted off their face on purpose


def scan(paths, slack=SLACK):
    """-> (n_outside, n_total, [(overhang_inches, clip_name, gallery), ...])"""
    bad = tot = 0
    worst = []
    for p in paths:
        try:
            items = wlb.items(p)
        except Exception:
            continue
        gal = os.path.basename(p)
        for name, it in items:
            def walk(node):
                nonlocal bad, tot
                for k in node.children:
                    if k.tag not in ('PRSM', 'PGRP'):
                        continue
                    ps = k.kid('POSN')
                    L, _ = d3d.posn_matrix(ps) if ps else (np.eye(4), None)
                    if k.tag == 'PRSM':
                        m = d3d.prsm_mesh(k)
                        if m:
                            v, f, poly, fids = m
                            vh = np.hstack([v, np.ones((len(v), 1))])
                            wv = (L @ vh.T).T[:, :3]
                            lo, hi = wv.min(0) - slack, wv.max(0) + slack
                            for fm in d3d.surface_features(k, v, f, fids, L):
                                tot += 1
                                fv = fm[0]
                                over = max(float((lo - fv.min(0)).max()),
                                           float((fv.max(0) - hi).max()))
                                if over > 0:
                                    bad += 1
                                    worst.append((round(over, 1), name, gal))
                    walk(k)
            try:
                walk(it)
            except Exception:
                pass
    worst.sort(reverse=True)
    return bad, tot, worst


if __name__ == '__main__':
    pats = sys.argv[1:] or ['data/galleries3d/*.WLB']
    files = [p for pat in pats for p in sorted(glob.glob(pat))
             if not os.path.basename(p).startswith('ID')]
    bad, tot, worst = scan(files)
    print(f'decals outside their own prism: {bad}/{tot} ({100 * bad / max(tot, 1):.2f}%)')
    seen = set()
    for o, n, g in worst:
        if n in seen:
            continue
        seen.add(n)
        print(f'  {o:7.1f} in  {n[:34]:34s} {g}')
        if len(seen) >= 15:
            break
