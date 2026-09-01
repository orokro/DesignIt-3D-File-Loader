"""Objective fidelity metric: silhouette IoU against the app's own VRIF preview.

The VRIF thumbnail carries a 1-bit mask bitmap -- the exact silhouette the
application drew. We render our reconstruction from the same direction, crop
both silhouettes to their bounding box, normalise to a common size and compare.
Cropping makes the score scale- and position-invariant, so it measures shape
agreement only.
"""
import sys, os, struct
sys.path.insert(0, os.path.dirname(__file__))
import numpy as np
from PIL import Image
import wlb, vrif, d3d, render


def vrif_mask(data):
    maps = []
    for tag, body in vrif._chunks(data, 30, len(data)):
        if tag == b'CGRP':
            for t2, b2 in vrif._chunks(body, 4, len(body)):
                if t2 == b'BMAP':
                    maps.append(vrif._bmap(b2))
    if len(maps) < 2:
        return None
    w, h, depth, stride, cmap, dat = maps[1]
    if dat is None or depth != 1:
        return None
    return np.array(vrif._unpack(w, h, depth, stride, dat), bool)


def fill(mask):
    """VRIF previews are line art, not filled shapes. Flood the background in
    from the border; whatever is unreachable (plus the ink itself) is the
    silhouette. Works because the outline stroke is closed."""
    h, w = mask.shape
    out = np.zeros((h, w), bool)
    stack = []
    for x in range(w):
        stack += [(0, x), (h - 1, x)]
    for y in range(h):
        stack += [(y, 0), (y, w - 1)]
    seen = np.zeros((h, w), bool)
    while stack:
        y, x = stack.pop()
        if y < 0 or x < 0 or y >= h or x >= w or seen[y, x] or mask[y, x]:
            continue
        seen[y, x] = True
        stack += [(y + 1, x), (y - 1, x), (y, x + 1), (y, x - 1)]
    return ~seen


def render_mask(meshes, size=50, azim=-90.0, elev=0.0):
    im = render.render(meshes, size=(size, size), azim=azim, elev=elev, ortho=True)
    a = np.array(im)
    return ~np.all(a == np.array(render.BG, np.uint8), axis=-1)


def norm(mask, n=48):
    ys, xs = np.nonzero(mask)
    if len(xs) == 0:
        return None
    sub = mask[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    return np.array(Image.fromarray(sub.astype(np.uint8) * 255).resize((n, n), Image.BILINEAR)) > 127


def iou(a, b):
    if a is None or b is None:
        return None
    u = (a | b).sum()
    return float((a & b).sum() / u) if u else None


def score_gallery(path, azim=-90.0, elev=0.0, limit=None):
    out = []
    for name, it in wlb.items(path):
        v = it.kid('VRIF')
        if not v:
            continue
        vm = vrif_mask(v.data)
        gm = norm(fill(vm)) if vm is not None else None
        ms = []
        d3d.collect(it, np.eye(4), ms)
        if not ms or gm is None:
            continue
        s = iou(gm, norm(render_mask(ms, 100, azim, elev)))
        if s is not None:
            out.append((s, name))
        if limit and len(out) >= limit:
            break
    return out


VIEWS = [(a, e) for a in range(-180, 180, 30) for e in (-30, 0, 30)]


def best_view_score(meshes, gm, views=VIEWS, size=64):
    """VRIF previews are posed per item, not from one fixed camera, so score
    an item by the best-matching view rather than a single projection."""
    best = 0.0
    for a, e in views:
        s = iou(gm, norm(render_mask(meshes, size, a, e)))
        if s and s > best:
            best = s
    return best


def gallery_best(path, names=None, views=VIEWS, size=64):
    import numpy as np
    out = []
    for name, it in wlb.items(path):
        if names is not None and name not in names:
            continue
        v = it.kid('VRIF')
        if not v:
            continue
        vm = vrif_mask(v.data)
        if vm is None:
            continue
        gm = norm(fill(vm))
        ms = []
        d3d.collect(it, np.eye(4), ms)
        if not ms or gm is None:
            continue
        out.append((best_view_score(ms, gm, views, size), name))
    return out
