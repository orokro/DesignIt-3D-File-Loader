"""Decal PLACEMENT oracle, scored against the ink of the app's own preview.

Containment (decalfit.py) only asks whether a decoration falls off its face. It
cannot tell a decal sitting in the right place from one sitting in the wrong
place on the same face -- and 92 of the 113 objects that discriminate between
two candidate coordinate origins come out EXACTLY tied under it, because their
faces are centred on the prism origin and the two rules coincide there.

But VRIF previews are line art: the application draws the decoration outlines.
So the interior ink of a preview IS ground truth for where the decorations go.

Method, per clip:
  * render our geometry twice at preview resolution, with and without SURF/FEAT
    decorations, and difference them -- that is exactly our decal region;
  * take the boundary of that region, which is what the app would have stroked;
  * take the preview's ink, minus the pixels that belong to the OUTER silhouette
    edge, leaving only interior detail;
  * score how much of each lands within one pixel of the other (F1).

One pixel of slop is deliberate: the preview is 50x50 for objects a metre wide,
so a decal edge is a pixel or two and exact coincidence is too much to ask.
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
import numpy as np
from PIL import Image
import render, vrif, d3d, score


def _grow(m):
    g = m.copy()
    g[1:, :] |= m[:-1, :]; g[:-1, :] |= m[1:, :]
    g[:, 1:] |= m[:, :-1]; g[:, :-1] |= m[:, 1:]
    return g


def _boundary(m):
    e = m.copy()
    e[1:, :] &= m[:-1, :]; e[:-1, :] &= m[1:, :]
    e[:, 1:] &= m[:, :-1]; e[:, :-1] &= m[:, 1:]
    return m & ~e


def _mask(meshes, size, azim, elev):
    im = render.render(meshes, size=(size, size), azim=azim, elev=elev, ortho=True)
    return np.array(im)


def clip_score(item, size=100, azim=-90.0, elev=0.0):
    """-> F1 in [0,1], or None if the clip has no decorations or no preview."""
    v = item.kid('VRIF')
    if v is None:
        return None
    ink = score.vrif_mask(v.data)
    if ink is None:
        return None
    solid = score.fill(ink)

    keep = d3d.DRAW_SURF
    try:
        d3d.DRAW_SURF = True
        with_d = []
        d3d.collect(item, np.eye(4), with_d)
        d3d.DRAW_SURF = False
        without = []
        d3d.collect(item, np.eye(4), without)
    finally:
        d3d.DRAW_SURF = keep
    if not with_d or len(with_d) == len(without):
        return None

    # Frame BOTH renders on the undecorated geometry so the decals cannot move
    # the camera and flatter themselves.
    a = _mask(without, size, azim, elev)
    b = _mask(with_d, size, azim, elev)
    ours = np.any(a != b, axis=-1)
    if not ours.any():
        return None
    ours = _boundary(ours)

    # Preview: ink that is not part of the outer silhouette edge.
    interior = ink & ~_boundary(solid) & ~_grow(~solid)
    if not interior.any():
        return None

    n = 48
    def to_n(m, ref):
        ys, xs = np.nonzero(ref)
        if not len(xs):
            return None
        sub = m[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
        return np.array(Image.fromarray(sub.astype(np.uint8) * 255).resize((n, n), Image.BILINEAR)) > 64

    A = to_n(ours, np.any(a != np.array(render.BG, np.uint8), axis=-1))
    B = to_n(interior, solid)
    if A is None or B is None or not A.any() or not B.any():
        return None
    prec = (A & _grow(B)).sum() / A.sum()
    rec = (B & _grow(A)).sum() / B.sum()
    return float(2 * prec * rec / (prec + rec)) if (prec + rec) else 0.0


def gallery(paths, names=None):
    import wlb
    out = []
    for p in paths:
        try:
            items = wlb.items(p)
        except Exception:
            continue
        for name, it in items:
            if names is not None and name not in names:
                continue
            try:
                s = clip_score(it)
            except Exception:
                s = None
            if s is not None:
                out.append((s, name, os.path.basename(p)))
    return out
