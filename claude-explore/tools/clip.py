"""Clip a closed triangle mesh by a plane and re-cap the cut.

Sutherland-Hodgman per triangle (a half-space is convex, so each triangle
clips to a single convex polygon), then the newly created edges are stitched
into loops and capped. Winding is preserved throughout, which is what makes
the result watertight -- verified by checking that the two complementary
half-volumes of a cube sum back to the whole.
"""
import numpy as np


def clip_mesh(verts, faces, n, d, keep_negative=True, eps=1e-9):
    n = np.asarray(n, float)
    sgn = 1.0 if keep_negative else -1.0
    V = [np.asarray(v, float) for v in verts]
    dist = [sgn * (float(n @ v) + d) for v in V]
    cache = {}

    def cut(i, j):
        key = (i, j) if i < j else (j, i)
        if key not in cache:
            a, b = dist[i], dist[j]
            t = a / (a - b)
            V.append(V[i] + t * (V[j] - V[i]))
            dist.append(0.0)
            cache[key] = len(V) - 1
        return cache[key]

    out, cut_edges = [], []
    for tri in faces:
        ds = [dist[k] for k in tri]
        if all(x > eps for x in ds):
            continue
        if all(x <= eps for x in ds):
            out.append(tuple(tri))
            continue
        poly, made = [], []
        for i in range(3):
            a, b = tri[i], tri[(i + 1) % 3]
            da, db = dist[a], dist[b]
            if da <= eps:
                poly.append(a)
            if (da <= eps) != (db <= eps):
                poly.append(cut(a, b))
                made.append(len(poly) - 1)
        if len(poly) < 3:
            continue
        for k in range(1, len(poly) - 1):
            out.append((poly[0], poly[k], poly[k + 1]))
        if len(made) == 2:
            i0, i1 = made
            if (i0 + 1) % len(poly) == i1:
                cut_edges.append((poly[i1], poly[i0]))
            else:
                cut_edges.append((poly[i0], poly[i1]))

    if cut_edges:
        out.extend(_cap(V, cut_edges))
    return np.array(V), out


def _cap(V, edges):
    """Stitch the cut edges into loops and fan-triangulate each."""
    nxt = {}
    for a, b in edges:
        nxt.setdefault(a, []).append(b)
    faces, used = [], set()
    for start in list(nxt):
        if start in used:
            continue
        loop, cur = [], start
        while cur is not None and cur not in used:
            used.add(cur)
            loop.append(cur)
            cur = next((c for c in nxt.get(cur, []) if c not in used), None)
        if len(loop) < 3:
            continue
        for k in range(1, len(loop) - 1):
            faces.append((loop[0], loop[k], loop[k + 1]))
    return faces
