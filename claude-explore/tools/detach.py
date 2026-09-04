"""Detached-part oracle.

Silhouette IoU is blind to a part that is rotated into the wrong place, because
a 50x50 preview forgives a lot. But real assemblies are CONNECTED: a chair's
legs touch its seat, a printer's paper touches the printer. So count the parts
that touch nothing.

Metric per object: fraction of prisms whose (slightly grown) world AABB
intersects no other prism's. Lower is better. Unlike IoU this is a direct,
local read on exactly the bug the user reports -- "floating detached pieces".
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
import numpy as np
import iff, d3d, wlb

TOL = 0.75   # inches of slack; parts that merely abut still count as touching


def part_boxes(item):
    """One AABB per PRSM (feature decals excluded -- they ride on their face)."""
    boxes = []
    def walk(node, M):
        for k in node.children:
            if k.tag not in ('PRSM', 'PGRP'):
                continue
            ps = k.kid('POSN')
            L, _ = d3d.posn_matrix(ps) if ps else (np.eye(4), None)
            W = (M @ L) if d3d.COMPOSE else L
            if k.tag == 'PRSM':
                m = d3d.prsm_mesh(k)
                if m:
                    v = m[0]
                    vh = np.hstack([v, np.ones((len(v), 1))])
                    wv = (W @ vh.T).T[:, :3]
                    boxes.append((wv.min(0), wv.max(0)))
            walk(k, W)
    walk(item, np.eye(4))
    return boxes


def isolated(boxes, tol=TOL):
    n = len(boxes)
    if n < 2:
        return 0, n
    lo = np.array([b[0] for b in boxes]) - tol
    hi = np.array([b[1] for b in boxes]) + tol
    touch = (lo[:, None, :] <= hi[None, :, :]).all(2) & (hi[:, None, :] >= lo[None, :, :]).all(2)
    np.fill_diagonal(touch, False)
    return int((~touch.any(1)).sum()), n


def score_item(item):
    return isolated(part_boxes(item))


def gallery_scan(paths, minparts=3):
    """-> list of (name, path, n_isolated, n_parts) sorted worst first."""
    rows = []
    for p in paths:
        try:
            its = wlb.items(p)
        except Exception:
            continue
        for name, it in its:
            try:
                k, n = score_item(it)
            except Exception:
                continue
            if n >= minparts:
                rows.append((name, os.path.basename(p), k, n))
    rows.sort(key=lambda r: (-r[2] / max(r[3], 1), -r[2]))
    return rows
