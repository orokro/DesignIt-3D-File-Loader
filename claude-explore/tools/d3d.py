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
        """(z, scale) pairs along the sweep, ordered from the HIGH end to the low.

        The order matters because it fixes the face numbering that SURF's
        2-byte header indexes into. Verified against decorated caps whose
        correct side is unambiguous: the Safe's front panel, the Tractor's
        hubcap and the `PC, Compaq` monitor screen all land correctly this way
        and on the wrong face under the opposite order.
        """
        return list(reversed(self._rings_low_to_high()))

    def _rings_low_to_high(self):
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
    # The rotation triple is stored (ry, rx, rz), NOT (rx, ry, rz). The Fax
    # Machine settles it: its control panel carries 0.157 rad in field 4 and
    # its body is cut at a 9.03 deg slope in Y (plane normal 0, 2.323, -14.61,
    # atan = 0.1576). Only reading field 4 as rotation-about-X makes the panel
    # lie flush on that slope instead of cutting through it. Across the 87
    # gallery items that use fields 3 or 4 this lifts mean silhouette IoU from
    # 0.754 to 0.779, better on 54 items and worse on 24.
    pos, scl = v[0:3], v[9:12]
    rot = [v[4], v[3], v[5]]
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

    # Face numbering that SURF indexes into:
    #     0                    cap at the HIGH end of the sweep
    #     1 .. bands*n         side faces, band-major, edges traversed BACKWARDS
    #     bands*n + 1          cap at the LOW end of the sweep
    #     bands*n + 2 + k      face created by SLIC cut k
    # Derived from four objects whose correct face is unambiguous: the Paper
    # Shredder's paper tray and the Fax Machine's button panel (both must be
    # the top cap), the PC Compaq base (front panel + its two chamfers), and
    # the Compaq monitor screen (the front cap).
    faces, fids = [], []
    n = len(base)
    nband = len(rings) - 1

    def side_id(r, i):
        return 1 + r * n + (n - 1 - i)

    for r in range(nband):
        lo, hi = ringidx[r], ringidx[r + 1]
        if len(lo) == 1:                       # fan from apex up to ring
            for i in range(n):
                faces.append((lo[0], hi[i], hi[(i + 1) % n])); fids.append(side_id(r, i))
        elif len(hi) == 1:                     # fan from ring to apex
            for i in range(n):
                faces.append((lo[i], lo[(i + 1) % n], hi[0])); fids.append(side_id(r, i))
        else:
            for i in range(n):
                j = (i + 1) % n
                faces.append((lo[i], lo[j], hi[j])); fids.append(side_id(r, i))
                faces.append((lo[i], hi[j], hi[i])); fids.append(side_id(r, i))
    # caps
    tris = triangulate(base)
    cap0, cap1 = 0, nband * n + 1
    if len(ringidx[0]) > 1:
        for (a, b, c) in tris:
            faces.append((ringidx[0][a], ringidx[0][c], ringidx[0][b])); fids.append(cap0)
    if len(ringidx[-1]) > 1:
        for (a, b, c) in tris:
            faces.append((ringidx[-1][a], ringidx[-1][b], ringidx[-1][c])); fids.append(cap1)
    verts = np.array(verts)
    ctr = verts.mean(0)
    for k, (i0, i1, i2) in enumerate(faces):
        a, b, c = verts[i0], verts[i1], verts[i2]
        nrm = np.cross(b - a, c - a)
        if float(nrm @ ((a + b + c) / 3.0 - ctr)) < 0:
            faces[k] = (i0, i2, i1)          # keep winding outward
    verts = (A @ verts.T).T               # local (u,v,w) -> object space

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
                verts, faces, fids = _clip.clip_mesh(
                    verts, faces, nn, dd, keep_negative=SLIC_KEEP_NEG,
                    ids=fids, new_id=cap1 + 1 + i)
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
    return verts, faces, poly, fids


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
                v, f, poly, fids = m
                vh = np.hstack([v, np.ones((len(v), 1))])
                wv = (W @ vh.T).T[:, :3]
                out.append((wv, f, color_of(k), poly))
                if DRAW_SURF:
                    out.extend(surface_features(k, v, f, fids, W))
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


# ---------------------------------------------------------------------------
# SURF / FEAT -- 2D vector decorations placed on a prism face
# ---------------------------------------------------------------------------

DRAW_SURF = True
SURF_OFFSET = 0.05      # inches to lift a decoration off its face, to beat z-fighting

# FEAT's 2-byte header selects which side of the surface is decorated.
FEAT_OUTSIDE, FEAT_INSIDE, FEAT_BOTH = 0, 1, 2


def face_frame(verts, tris):
    """A 2D coordinate frame for one face of a prism.

    Drop the axis the face normal is most aligned with and keep the other two
    in ascending axis order; the origin is the minimum corner of the face in
    that projection. Verified against `PC, Compaq`: the keyboard's two key
    panels and the monitor's screen land in the right places under this rule.
    """
    idx = sorted({i for t in tris for i in t})
    P = verts[idx]
    # use the largest triangle of the face -- clipping can leave slivers whose
    # cross product is numerically useless
    best, nrm = 0.0, None
    for t in tris:
        a, b, c = verts[t[0]], verts[t[1]], verts[t[2]]
        cr = np.cross(b - a, c - a)
        ln = float(np.linalg.norm(cr))
        if ln > best:
            best, nrm = ln, cr / ln
    if nrm is None or best < 1e-9:
        return None
    # point the normal away from the solid so decorations sit on the outside
    if float(nrm @ (P.mean(0) - verts.mean(0))) < 0:
        nrm = -nrm
    drop = int(np.argmax(np.abs(nrm)))
    ax = [i for i in range(3) if i != drop]          # ascending order
    u = np.zeros(3); u[ax[0]] = 1.0
    v = np.zeros(3); v[ax[1]] = 1.0
    # keep the frame in the face plane
    u = u - nrm * (u @ nrm)
    nu = np.linalg.norm(u)
    if nu < 1e-9:
        return None
    u /= nu
    v = v - nrm * (v @ nrm) - u * (v @ u)
    nv = np.linalg.norm(v)
    if nv < 1e-9:
        return None
    v /= nv
    uu, vv = P @ u, P @ v
    origin = u * uu.min() + v * vv.min() + nrm * float(P[0] @ nrm)
    return origin, u, v, nrm


def feat_polygon(feat):
    """2D FEAT outline: 4-byte header (0, class, 0, vertexCount) then N x (x,y)."""
    pl = feat.kid('POLY')
    if pl is None or len(pl.data) < 4:
        return None
    b = pl.data
    n = b[3]
    if len(b) < 4 + n * 8:
        return None
    return [(iff.fp(b, 4 + i * 8), iff.fp(b, 8 + i * 8)) for i in range(n)]


def feat_transform(feat):
    """2D FEAT POSN: 6 x fp16.16 = (x, y, ?, ?, sx, sy)."""
    ps = feat.kid('POSN')
    if ps is None or len(ps.data) < 24:
        return (0.0, 0.0, 1.0, 1.0)
    d = ps.data
    return (iff.fp(d, 0), iff.fp(d, 4), iff.fp(d, 16) or 1.0, iff.fp(d, 20) or 1.0)


def surface_features(prsm, verts, faces, fids, W):
    """Build overlay meshes for every SURF decoration on this prism."""
    out = []
    if fids is None:
        return out
    byface = {}
    for t, fid in zip(faces, fids):
        byface.setdefault(fid, []).append(t)

    for surf in prsm.kids('SURF'):
        fid = iff.u16(surf.hdr, 0)
        tris = byface.get(fid)
        if not tris:
            continue
        fr = face_frame(verts, tris)
        if fr is None:
            continue
        origin, u, v, nrm = fr

        for feat in surf.kids('FEAT'):
            side = iff.u16(feat.hdr, 0) if feat.hdr else FEAT_OUTSIDE
            poly = feat_polygon(feat)
            if not poly or len(poly) < 3:
                continue
            tx, ty, sx, sy = feat_transform(feat)
            col = feat.kid('COLR')
            rgb = (col.data[1], col.data[2], col.data[3]) if col and len(col.data) >= 4 else (0, 0, 0)

            pts2 = [((x * sx) + tx, (y * sy) + ty) for (x, y) in poly]
            for sgn in ((1, -1) if side == FEAT_BOTH else (1,) if side != FEAT_INSIDE else (-1,)):
                off = nrm * (SURF_OFFSET * sgn)
                pv = np.array([origin + u * a + v * b + off for (a, b) in pts2])
                tri = triangulate([(p @ u, p @ v) for p in pv])
                if not tri:
                    continue
                vh = np.hstack([pv, np.ones((len(pv), 1))])
                wv = (W @ vh.T).T[:, :3]
                out.append((wv, tri, rgb, None))
    return out
