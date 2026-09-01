"""Clip a closed triangle mesh by a plane and re-cap the cut.

Sutherland-Hodgman per triangle (a half-space is convex, so each triangle
clips to one convex polygon), then the cut face is rebuilt from the vertices
that end up lying on the plane.

Capping from the on-plane vertex set -- rather than by stitching together the
edges we happened to create -- is what makes cuts through *existing* corners
work. A slab mitred corner to corner (the `PC, Compaq` keyboard) creates no new
vertices at two of its four cut corners, so edge-stitching produces a
degenerate sliver there.

The cut face is assumed convex, which holds for a plane through a convex prism.
A concave cross-section cut by a plane could wind incorrectly.
"""
import numpy as np

ON = 1e-6


def clip_mesh(verts, faces, n, d, keep_negative=True, eps=1e-9, ids=None, new_id=None):
    n = np.asarray(n, float)
    sgn = 1.0 if keep_negative else -1.0
    V = [np.asarray(v, float) for v in verts]
    dist = [sgn * (float(n @ v) + d) for v in V]
    nrm = n * sgn
    nl = np.linalg.norm(nrm) or 1.0
    scale = max(1.0, float(np.abs(np.asarray(dist)).max()))
    tol = ON * nl * scale

    if max(dist) <= tol:
        # the whole solid is on the kept side
        return (np.array(V), list(faces), list(ids)) if ids is not None else (np.array(V), list(faces))
    if min(dist) > tol:
        # the whole solid is on the discarded side
        return (np.array(V), [], []) if ids is not None else (np.array(V), [])

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

    out, out_ids, onplane = [], [], set()
    for ti, tri in enumerate(faces):
        fid = ids[ti] if ids is not None else None
        ds = [dist[k] for k in tri]
        if all(x > tol for x in ds):
            continue
        if all(x <= tol for x in ds):
            poly = list(tri)
        else:
            poly = []
            for i in range(3):
                a, b = tri[i], tri[(i + 1) % 3]
                da, db = dist[a], dist[b]
                if da <= tol:
                    poly.append(a)
                if (da <= tol) != (db <= tol):
                    poly.append(cut(a, b))
        if len(poly) < 3:
            for k in poly:
                if abs(dist[k]) <= tol:
                    onplane.add(k)
            continue
        for k in poly:
            if abs(dist[k]) <= tol:
                onplane.add(k)
        for k in range(1, len(poly) - 1):
            a, b, c = poly[0], poly[k], poly[k + 1]
            if _area(V, a, b, c) > 1e-12:
                out.append((a, b, c))
                out_ids.append(fid)

    cap = _cap(V, onplane, nrm / nl)
    out.extend(cap)
    out_ids.extend([new_id] * len(cap))
    if ids is None:
        return np.array(V), out
    return np.array(V), out, out_ids


def _area(V, a, b, c):
    return float(np.linalg.norm(np.cross(V[b] - V[a], V[c] - V[a]))) / 2.0


def _cap(V, onplane, nhat):
    """Fan-triangulate the cut face, wound to face along +nhat (out of the solid)."""
    idx = sorted(onplane)
    if len(idx) < 3:
        return []
    P = np.array([V[i] for i in idx])
    # deduplicate coincident vertices
    keep, seen = [], []
    for k, p in zip(idx, P):
        if not any(np.allclose(p, q, atol=1e-7) for q in seen):
            keep.append(k)
            seen.append(p)
    if len(keep) < 3:
        return []
    P = np.array(seen)
    ctr = P.mean(0)
    u = np.cross(nhat, [0.0, 0.0, 1.0])
    if np.linalg.norm(u) < 1e-6:
        u = np.cross(nhat, [0.0, 1.0, 0.0])
    u /= np.linalg.norm(u)
    w = np.cross(nhat, u)
    ang = np.arctan2((P - ctr) @ w, (P - ctr) @ u)
    order = [keep[i] for i in np.argsort(ang)]
    faces = []
    for k in range(1, len(order) - 1):
        a, b, c = order[0], order[k], order[k + 1]
        if _area(V, a, b, c) > 1e-12:
            faces.append((a, b, c))
    return faces
