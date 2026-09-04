"""Design-It! 3-D geometry model: VVR/WLB chunks -> triangle meshes."""
import sys, os, math, struct
sys.path.insert(0, os.path.dirname(__file__))
import iff
import numpy as np
import clip as _clip

# POLY byte 3 -> extrusion profile
SLIC_MODE = 'clip'  # 'off' | 'clip' | 'hinge' -- see findings/slic.md
SLIC_FILTER = None  # optional fn(index, nrec, eslc_row) -> bool
SLIC_KEEP_NEG = False
SKEW_MODE = 'near'  # 'off' | 'far' | 'near' -- POLY's oblique-sweep offset

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
        # POLY[14:26] -- three fp16.16 that offset the far end of the sweep, so
        # the extrusion leans instead of running straight. Non-zero on 5.1 % of
        # prisms. b[26:28] is a small signed int16 whose meaning is unknown.
        self.skew = (iff.fp(b, 14), iff.fp(b, 18), iff.fp(b, 22))
        self.mid = b[14:28]
        n = iff.u32(b, 28)
        self.declared_n = n
        n = max(0, min(n, (len(b) - 32) // 8))   # guard against 2D POLYs read as 3D
        self.verts = [(iff.fp(b, 32 + i * 8), iff.fp(b, 36 + i * 8)) for i in range(n)]

    def rings(self):
        """(z, scale) pairs along the sweep.

        Two independent things are encoded here:

        * The taper direction. A profile's SMALL end sits at `za` -- the first
          of the two stored sweep bounds -- not at whichever end happens to be
          higher. 124 of 213 pointed prisms have za < zb, and treating the apex
          as always-uppermost turns those upside down (the Basketball Goal, the
          Toilet and the Barbecue Grill all have one).
        * The ring ORDER, which fixes the face numbering SURF indexes into.
          Rings are emitted from the HIGH end of the sweep to the low one.
        """
        za, zb = self.za, self.zb
        p, n = self.profile, max(1, self.nseg)
        if p == POINTED:
            out = [(za, 0.0), (zb, 1.0)]
        elif p == DIAMOND:
            out = [(za, 0.0), ((za + zb) / 2, 1.0), (zb, 0.0)]
        elif p == ROUNDED:
            out = []
            for k in range(n + 1):
                th = (k / n) * (math.pi / 2)
                out.append((za + (zb - za) * (1 - math.cos(th)), math.sin(th)))
        elif p == SPHERE:
            out = []
            for k in range(n + 1):
                th = (k / n) * math.pi
                out.append((za + (zb - za) * (1 - math.cos(th)) / 2, math.sin(th)))
        else:
            out = [(za, 1.0), (zb, 1.0)]
        if out[0][0] < out[-1][0]:
            out.reverse()
        return out



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
    """POSN -> a 3x4 affine matrix.

    Fields 3-5 are three EULER ANGLES in radians, stored (ry, rx, rz) -- the
    first two are SWAPPED relative to the obvious order -- and applied in the
    order they are stored: R = Ry @ Rx @ Rz. That self-consistency is the point:
    the writer lays the angles down in application order.

    They are NOT an axis-angle rotation vector, though the corpus fights hard to
    look like one -- a single-axis rotation reads identically either way, and a
    mirrored pair negates the same two components under both models, so neither
    the common case nor the obvious mirror test discriminates. What settles it is
    the distribution of COMPOUND values: 159 parts carry exactly (180, 0, 180)
    degrees and a whole family carries (180, 0, theta) for theta in
    {-175, -135, -90, -65, -45, 45, 56, 90, 135, 170, ...}. A rotation vector
    composed from two round turns essentially never lands on round components,
    let alone pins one field at exactly 180 across a family -- but "flip it over,
    then turn it" does, which is what a modelling UI actually offers.

    A POSN is 48 bytes when it carries all twelve fields, but 24 bytes -- 1003 of
    them across the corpus -- when the scale is identity and the writer omitted
    it. Those short records still carry a real position, and 131 carry a real
    rotation. Rejecting anything under 48 bytes (the guard that keeps 2D FEAT
    POSNs out) silently collapsed every one of them to the identity, dumping the
    part at the model origin. That is why Brutus's arms fanned out from his
    chest: they are short-form records, so they lost their offsets and their
    shoulder rotations at once.

    Measured on the detached-part oracle (see detach.py, which counts prisms
    whose world AABB touches no other prism -- far sharper than silhouette IoU
    for this): 3312 gallery parts give 24 isolated under this reading, 38 under
    the rotation-vector reading, and 60-160 under every other axis assignment.
    Sign flips and applying scale after rotation instead of before both make it
    worse, so R @ diag(scale) with all-positive angles is the floor.
    """
    d = chunk.data
    if len(d) < 24:                       # 2D (FEAT) POSN, not a 3D transform
        return np.eye(4), None
    v = [iff.fp(d, i * 4) for i in range(min(len(d) // 4, 12))]
    while len(v) < 9:                     # SHORT FORM (24 B): position + rotation
        v.append(0.0)                     # only; scale was omitted as identity
    while len(v) < 12:
        v.append(1.0)
    pos, scl = v[0:3], v[9:12]
    R = euler_matrix(v[3], v[4], v[5])
    M = np.eye(4)
    M[:3, :3] = R @ np.diag(scl)
    M[:3, 3] = pos
    return M, v


def euler_matrix(ry, rx, rz):
    """Ry @ Rx @ Rz, angles in radians -- the POSN field order.

    Measured against the other five orders on the 36 gallery objects that carry
    a compound rotation: yxz 0.7882 mean silhouette IoU, xyz 0.7837, yzx 0.7858,
    zyx 0.7502. yxz also ties for the fewest detached parts (26).
    """
    cx, sx = math.cos(rx), math.sin(rx)
    cy, sy = math.cos(ry), math.sin(ry)
    cz, sz = math.cos(rz), math.sin(rz)
    X = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]])
    Y = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
    Z = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]])
    return Y @ X @ Z


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

    # An oblique sweep: POLY's skew vector displaces the far end, and every ring
    # takes its share in proportion to how far along the sweep it sits.
    sk = poly.skew if SKEW_MODE != 'off' else (0.0, 0.0, 0.0)
    span = poly.zb - poly.za

    def shift(z):
        if span == 0.0 or sk == (0.0, 0.0, 0.0):
            return 0.0, 0.0, 0.0
        t = (z - poly.za) / span
        if SKEW_MODE == 'near':
            t = 1.0 - t
        return t * sk[0], t * sk[1], t * sk[2]

    verts, ringidx = [], []
    for z, s in rings:
        dx, dy, dz = shift(z)
        if s == 0.0:
            ringidx.append([len(verts)])
            verts.append(np.array([dx, dy, z + dz]))
        else:
            start = len(verts)
            for (x, y) in base:
                verts.append(np.array([x * s + dx, y * s + dy, z + dz]))
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
    # winding of the stored polygon decides which way the side quads face
    sarea = sum(base[i][0] * base[(i + 1) % n][1] - base[(i + 1) % n][0] * base[i][1]
                for i in range(n))
    ccw = sarea > 0

    def side_id(r, i):
        return 1 + r * n + (n - 1 - i)

    for r in range(nband):
        lo, hi = ringidx[r], ringidx[r + 1]      # lo is the HIGHER end of the sweep
        if len(lo) == 1:
            for i in range(n):
                j = (i + 1) % n
                t = (lo[0], hi[j], hi[i]) if ccw else (lo[0], hi[i], hi[j])
                faces.append(t); fids.append(side_id(r, i))
        elif len(hi) == 1:
            for i in range(n):
                j = (i + 1) % n
                t = (lo[i], hi[0], lo[j]) if ccw else (lo[i], lo[j], hi[0])
                faces.append(t); fids.append(side_id(r, i))
        else:
            for i in range(n):
                j = (i + 1) % n
                t1 = (lo[i], hi[j], lo[j]) if ccw else (lo[i], lo[j], hi[j])
                t2 = (lo[i], hi[i], hi[j]) if ccw else (lo[i], hi[j], hi[i])
                faces.append(t1); fids.append(side_id(r, i))
                faces.append(t2); fids.append(side_id(r, i))

    cap0, cap1 = 0, nband * n + 1
    # triangulate() normalises to CCW in polygon space, so the high cap faces
    # +sweep as written and the low cap is the reverse
    tris = triangulate(base)
    if len(ringidx[0]) > 1:
        for (x, y, z) in tris:
            faces.append((ringidx[0][x], ringidx[0][y], ringidx[0][z])); fids.append(cap0)
    if len(ringidx[-1]) > 1:
        for (x, y, z) in tris:
            faces.append((ringidx[-1][x], ringidx[-1][z], ringidx[-1][y])); fids.append(cap1)

    verts = np.array(verts)
    # Consistent winding by construction; a negative signed volume just means
    # the whole shell came out inside-out, so flip it wholesale. This replaces
    # a per-face centroid test, which mis-orients faces on long or concave
    # prisms -- the escalator side panel in DEPARTME.VVR was one.
    vol = 0.0
    for (i0, i1, i2) in faces:
        vol += float(np.dot(verts[i0], np.cross(verts[i1], verts[i2]))) / 6.0
    if vol < 0:
        faces = [(i0, i2, i1) for (i0, i1, i2) in faces]

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
    verts, faces = _compact(verts, faces)
    return verts, faces, poly, fids


def _compact(verts, faces):
    """Drop vertices no face refers to.

    The clipper appends the vertices it creates and simply stops referencing the
    ones it cut away, which is harmless for drawing -- nothing indexes them -- but
    poisonous for anything that measures. A clipped prism's vertex array still
    held the geometry that was removed, so its bounding box was the box of the
    UNCUT prism. That silently inflated the manifest's bounds, the detached-part
    oracle's boxes, and the explorer's ground placement, which is why cut objects
    hovered above the floor instead of resting on it.
    """
    used = sorted({i for f in faces for i in f})
    if len(used) == len(verts):
        return verts, faces
    remap = {o: n for n, o in enumerate(used)}
    return verts[used], [tuple(remap[i] for i in f) for f in faces]


def color_of(prsm):
    c = prsm.kid('COLR')
    if c is None or len(c.data) < 8:
        return (170, 170, 170)
    d = c.data
    return (d[1], d[2], d[3])


COMPOSE = False   # see findings/hierarchy.md -- child POSN appears to be absolute


INCH = 0.0254           # metres, the unit the geometry is normally authored in


def unit_scale(node):
    """UNIT -> how many inches one stored unit is worth.

    UNIT is an 8-byte IEEE-754 double giving METRES PER STORED UNIT, and it is
    NOT always an inch. 497 clips carry 0.0254 (1 in), but others carry 0.00635
    (1/4 in), 0.003175 (1/8 in), 0.0025400 (1/10 in), 0.0015875 (1/16 in) or
    0.01 (1 cm). Ignoring it renders those objects 4x, 8x, 10x or 16x too large.

    The check that it is a scale and not just a UI grid setting: `Bar Stool`
    carries 0.00635 and measures 48 x 48 x 104 raw, which is 12 x 12 x 26 inches
    once divided -- a bar stool. `Microwave Oven` gives 24 x 19.5 x 15.5,
    `Fridge, Vert. Black` 33 x 33 x 65, `Dishwasher, Brown` 30 x 32 x 32,
    `Queen Anne Desk` 32.5 x 21 x 35, `Pig` 60 x 24 x 35. Every one of those is
    the right size for the object it depicts, and absurd without the divide.

    UNIT appears on ROOT, VCLP, PGRP and even PRSM, but across 537 nested
    occurrences a child NEVER disagrees with its ancestor, so one lookup
    anywhere in the subtree is enough.
    """
    u = node.kid('UNIT') if node is not None else None
    if u is not None and len(u.data) == 8:
        return struct.unpack('>d', u.data)[0] / INCH
    return None


def collect(node, M, out, unit=None):
    """Walk PRSM/PGRP tree accumulating world-space meshes."""
    here = unit_scale(node)
    if here is not None:
        unit = here
    for k in node.children:
        if k.tag not in ('PRSM', 'PGRP'):
            continue
        kf = unit_scale(k)
        u = kf if kf is not None else unit
        ps = k.kid('POSN')
        L, _ = posn_matrix(ps) if ps else (np.eye(4), None)
        W = (M @ L) if COMPOSE else L
        if u is not None and abs(u - 1.0) > 1e-12:
            W = np.diag([u, u, u, 1.0]) @ W
        if k.tag == 'PRSM':
            m = prsm_mesh(k)
            if m:
                v, f, poly, fids = m
                vh = np.hstack([v, np.ones((len(v), 1))])
                wv = (W @ vh.T).T[:, :3]
                out.append((wv, f, color_of(k), poly))
                if DRAW_SURF:
                    out.extend(surface_features(k, v, f, fids, W))
        collect(k, W, out, u)


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
    # `plane` is the face's plane with NO in-plane shift, so a decoration whose
    # coordinates are already prism-local can be laid down directly on it;
    # `origin` additionally moves to the face's minimum corner. Which one a
    # given FEAT wants is decided by its POSN translation -- see
    # surface_features.
    plane = nrm * float(P[0] @ nrm)
    origin = u * uu.min() + v * vv.min() + plane
    middle = u * ((uu.min() + uu.max()) / 2) + v * ((vv.min() + vv.max()) / 2) + plane
    return origin, u, v, nrm, middle


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
    """2D FEAT POSN: 6 x fp16.16 = (x, y, ROTATION, ~0, sx, sy).

    Field 2 is a rotation in radians about the decoration's own origin, and it
    was ignored for a long time. It is non-zero on 4.3 % of decals (134 of 3113)
    and the values are unmistakable: pi, pi/2, -pi/2, pi/4, 5.359 (307 deg),
    -0.2618 (-15 deg). Field 3 is zero on 99.7 % of records and has no known
    meaning. Fields 4 and 5 really are scale -- exactly 1.0 on 94 % of them.

    Drawing a rotated decal unrotated leaves it the right size in the right
    place but facing the wrong way, which reads as a misprinted panel rather
    than a misplaced one, so it hid behind the louder placement bugs.
    """
    ps = feat.kid('POSN')
    if ps is None or len(ps.data) < 24:
        return (0.0, 0.0, 0.0, 1.0, 1.0)
    d = ps.data
    return (iff.fp(d, 0), iff.fp(d, 4), iff.fp(d, 8),
            iff.fp(d, 16) or 1.0, iff.fp(d, 20) or 1.0)


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
        corner, u, v, nrm, middle = fr

        for feat in surf.kids('FEAT'):
            side = iff.u16(feat.hdr, 0) if feat.hdr else FEAT_OUTSIDE
            poly = feat_polygon(feat)
            if not poly or len(poly) < 3:
                continue
            tx, ty, th, sx, sy = feat_transform(feat)
            col = feat.kid('COLR')
            rgb = (col.data[1], col.data[2], col.data[3]) if col and len(col.data) >= 4 else (0, 0, 0)

            ct, st = math.cos(th), math.sin(th)
            pts2 = [(ct * (x * sx) - st * (y * sy) + tx,
                     st * (x * sx) + ct * (y * sy) + ty) for (x, y) in poly]

            # Two coordinate conventions, and the POSN translation says which.
            # With a non-zero (tx, ty) the outline is measured from the face's
            # minimum corner; with (0, 0) it is already in the prism's own local
            # coordinates and must be laid on the bare face plane instead.
            # The split is exact across the corpus: of 2182 decorations with a
            # translation, 2064 fit the corner frame and NONE fit only the
            # local-coordinate frame; of 338 without one, 309 fit local
            # coordinates and NONE fit only the corner frame. Using the corner
            # frame for all of them is what threw the Copy Machine's front panel
            # ten inches below the machine and left a floating slab beside the
            # Bar Sink.
            origin = corner if (abs(tx) > 1e-6 or abs(ty) > 1e-6) else middle
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
