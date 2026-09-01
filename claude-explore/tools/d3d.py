"""Design-It! 3-D geometry model: VVR/WLB chunks -> triangle meshes."""
import sys, os, math
sys.path.insert(0, os.path.dirname(__file__))
import iff
import numpy as np
import clip as _clip

# POLY byte 3 -> extrusion profile
SLIC_MODE = 'clip'  # 'off' | 'clip' | 'hinge' -- see findings/slic.md
SLIC_FILTER = None  # optional fn(index, nrec, eslc_row) -> bool
SLIC_KEEP_NEG = False

STRAIGHT, POINTED, DIAMOND, ROUNDED, SPHERE = 1, 2, 3, 4, 5
PROFILE_NAME = {1: 'straight', 2: 'pointed', 3: 'diamond', 4: 'rounded', 5: 'sphere'}

# POLY byte 2 -> which world axis the prism extrudes along.
# 3 = Z (upright), 2 = Y, 1 = X.  Verified against the _F / _R gallery renders.
AXIS_NAME = {1: 'X', 2: 'Y', 3: 'Z'}


class Poly:
    def __init__(self, chunk):
        b = chunk.data
        self.raw = b
        self.pclass = b[1]          # 1 custom, 2 rectangle, 3 regular n-gon
        self.axis = b[2]            # 1=X 2=Y 3=Z
        self.profile = b[3]         # see constants above
        self.nseg = iff.u16(b, 4)   # curve subdivision (1 for flat profiles)
        self.za = iff.fp(b, 6)
        self.zb = iff.fp(b, 10)
        self.mid = b[14:28]
        n = iff.u32(b, 28)
        self.declared_n = n
        n = max(0, min(n, (len(b) - 32) // 8))   # guard against 2D POLYs read as 3D
        self.verts = [(iff.fp(b, 32 + i * 8), iff.fp(b, 36 + i * 8)) for i in range(n)]

    def rings(self):
        """(z, scale) pairs from one end of the extrusion to the other."""
        z0, z1 = min(self.za, self.zb), max(self.za, self.zb)
        p, n = self.profile, max(1, self.nseg)
        if p == STRAIGHT:
            return [(z0, 1.0), (z1, 1.0)]
        if p == POINTED:
            return [(z0, 1.0), (z1, 0.0)]
        if p == DIAMOND:
            return [(z0, 0.0), ((z0 + z1) / 2, 1.0), (z1, 0.0)]
        if p == ROUNDED:
            out = []
            for k in range(n + 1):
                th = (k / n) * (math.pi / 2)
                out.append((z0 + (z1 - z0) * math.sin(th), math.cos(th)))
            return out
        if p == SPHERE:
            out = []
            for k in range(n + 1):
                th = (k / n) * math.pi
                out.append((z0 + (z1 - z0) * (1 - math.cos(th)) / 2, math.sin(th)))
            return out
        return [(z0, 1.0), (z1, 1.0)]


def axis_matrix(axis):
    """Map local (u, v, w) -- polygon x, polygon y, extrusion -- into object space.

    The three POLY b[2] values are a cyclic permutation of the axes, i.e. the
    same prism definition pointed along Z, Y or X:
        3 -> (X,Y,Z) = (u,v,w)     upright   (BASIC / ADVANCED galleries)
        2 -> (X,Y,Z) = (v,w,u)     along Y   (_F galleries)
        1 -> (X,Y,Z) = (w,u,v)     along X   (_R galleries)
    Derived from the Dining Chair / Coffee Table part layouts, where leg,
    stretcher and armrest extents only make sense under this mapping.
    """
    if axis == 3:
        return np.array([[1., 0., 0.],
                         [0., 1., 0.],
                         [0., 0., 1.]])
    if axis == 2:
        return np.array([[0., 1., 0.],
                         [0., 0., 1.],
                         [1., 0., 0.]])
    return np.array([[0., 0., 1.],
                     [1., 0., 0.],
                     [0., 1., 0.]])


def posn_matrix(chunk):
    d = chunk.data
    if len(d) < 48:                       # 2D (FEAT) POSN, not a 3D transform
        return np.eye(4), None
    v = [iff.fp(d, i * 4) for i in range(12)]
    pos, rot, scl = v[0:3], v[3:6], v[9:12]
    cx, cy, cz = (math.cos(a) for a in rot)
    sx, sy, sz = (math.sin(a) for a in rot)
    Rx = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]])
    Ry = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
    Rz = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]])
    R = Rz @ Ry @ Rx
    M = np.eye(4)
    M[:3, :3] = R @ np.diag(scl)
    M[:3, 3] = pos
    return M, v


def triangulate(poly2d):
    """Ear clipping for a simple polygon. Returns index triples."""
    n = len(poly2d)
    if n < 3:
        return []
    idx = list(range(n))
    area = sum(poly2d[i][0] * poly2d[(i + 1) % n][1] - poly2d[(i + 1) % n][0] * poly2d[i][1]
               for i in range(n))
    if area < 0:
        idx.reverse()

    def cross(o, a, b):
        return ((a[0] - o[0]) * (b[1] - o[1])) - ((a[1] - o[1]) * (b[0] - o[0]))

    def inside(p, a, b, c):
        d1 = cross(a, b, p); d2 = cross(b, c, p); d3 = cross(c, a, p)
        neg = (d1 < 0) or (d2 < 0) or (d3 < 0)
        pos = (d1 > 0) or (d2 > 0) or (d3 > 0)
        return not (neg and pos)

    tris, guard = [], 0
    while len(idx) > 3 and guard < 4 * n * n:
        guard += 1
        for k in range(len(idx)):
            i0, i1, i2 = idx[k - 1], idx[k], idx[(k + 1) % len(idx)]
            a, b, c = poly2d[i0], poly2d[i1], poly2d[i2]
            if cross(a, b, c) <= 0:
                continue
            if any(inside(poly2d[j], a, b, c) for j in idx if j not in (i0, i1, i2)):
                continue
            tris.append((i0, i1, i2))
            idx.pop(k)
            break
        else:
            break
    if len(idx) == 3:
        tris.append(tuple(idx))
    return tris


def prsm_mesh(prsm):
    """Build (verts Nx3 in local object space, faces list) for one PRSM."""
    pc = prsm.kid('POLY')
    if pc is None:
        return None
    poly = Poly(pc)
    base = poly.verts
    if len(base) < 3:
        return None
    rings = poly.rings()
    A = axis_matrix(poly.axis)

    verts, ringidx = [], []
    for z, s in rings:
        if s == 0.0:
            ringidx.append([len(verts)])
            verts.append(np.array([0.0, 0.0, z]))
        else:
            start = len(verts)
            for (x, y) in base:
                verts.append(np.array([x * s, y * s, z]))
            ringidx.append(list(range(start, start + len(base))))

    faces = []
    n = len(base)
    for r in range(len(rings) - 1):
        lo, hi = ringidx[r], ringidx[r + 1]
        if len(lo) == 1:                       # fan from apex up to ring
            for i in range(n):
                faces.append((lo[0], hi[i], hi[(i + 1) % n]))
        elif len(hi) == 1:                     # fan from ring to apex
            for i in range(n):
                faces.append((lo[i], lo[(i + 1) % n], hi[0]))
        else:
            for i in range(n):
                j = (i + 1) % n
                faces.append((lo[i], lo[j], hi[j]))
                faces.append((lo[i], hi[j], hi[i]))
    # caps
    tris = triangulate(base)
    if len(ringidx[0]) > 1:
        for (a, b, c) in tris:
            faces.append((ringidx[0][a], ringidx[0][c], ringidx[0][b]))
    if len(ringidx[-1]) > 1:
        for (a, b, c) in tris:
            faces.append((ringidx[-1][a], ringidx[-1][b], ringidx[-1][c]))
    verts = (A @ np.array(verts).T).T     # local (u,v,w) -> object space

    # SLIC planes are expressed in OBJECT space, not the polygon's local frame:
    # they intersect the prism 96.7% of the time there versus 76.2% locally.
    sl, es = prsm.kid('SLIC'), prsm.kid('ESLC')
    if SLIC_MODE != 'off' and sl is not None and len(sl.data) > 2:
        nrec = (len(sl.data) - 2) // 16
        for i in range(nrec):
            o = 2 + i * 16
            nn = np.array([iff.fp(sl.data, o), iff.fp(sl.data, o + 4), iff.fp(sl.data, o + 8)])
            dd = iff.fp(sl.data, o + 12)
            if not np.any(np.abs(nn) > 1e-9):
                continue
            erow = ([iff.fp(es.data, 2 + i * 40 + j * 4) for j in range(10)]
                    if es is not None and len(es.data) >= 2 + (i + 1) * 40 else None)
            if SLIC_FILTER is not None and not SLIC_FILTER(i, nrec, erow):
                continue
            if SLIC_MODE == 'clip':
                verts, faces = _clip.clip_mesh(verts, faces, nn, dd,
                                               keep_negative=SLIC_KEEP_NEG)
                if not faces:
                    break
            elif SLIC_MODE == 'hinge' and es is not None:
                e = [iff.fp(es.data, 2 + i * 40 + j * 4) for j in range(10)]
                rot = e[3:6]
                if not any(abs(r) > 1e-6 for r in rot):
                    continue
                cx, cy, cz = (math.cos(a) for a in rot)
                sx, sy, sz = (math.sin(a) for a in rot)
                R = (np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]])
                     @ np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
                     @ np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]]))
                ln = np.linalg.norm(nn) or 1.0
                pivot = -dd * nn / (ln * ln)
                m = (verts @ nn + dd) > 0
                if m.any():
                    verts = verts.copy()
                    verts[m] = (R @ (verts[m] - pivot).T).T + pivot
    return verts, faces, poly


def color_of(prsm):
    c = prsm.kid('COLR')
    if c is None or len(c.data) < 8:
        return (170, 170, 170)
    d = c.data
    return (d[1], d[2], d[3])


COMPOSE = False   # see findings/hierarchy.md -- child POSN appears to be absolute


def collect(node, M, out):
    """Walk PRSM/PGRP tree accumulating world-space meshes."""
    for k in node.children:
        if k.tag not in ('PRSM', 'PGRP'):
            continue
        ps = k.kid('POSN')
        L, _ = posn_matrix(ps) if ps else (np.eye(4), None)
        W = (M @ L) if COMPOSE else L
        if k.tag == 'PRSM':
            m = prsm_mesh(k)
            if m:
                v, f, poly = m
                vh = np.hstack([v, np.ones((len(v), 1))])
                wv = (W @ vh.T).T[:, :3]
                out.append((wv, f, color_of(k), poly))
        collect(k, W, out)


def scene_meshes(path_or_chunk):
    r = iff.load(path_or_chunk) if isinstance(path_or_chunk, str) else path_or_chunk
    out = []
    roots = r.find_all('ROOT')
    if roots:
        for root in roots:
            collect(root, np.eye(4), out)
    else:
        collect(r, np.eye(4), out)
    return out
