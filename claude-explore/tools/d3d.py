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
# 'postscale' is a REJECTED hypothesis, kept switchable because it looked good:
# `Brutus de Milo`'s prisms carry the most non-uniform POSN scales in the corpus
# (0.089, 0.172, 0.068) and are the only object whose SLIC cutting is badly
# wrong, so "the plane is authored in the space the object is DRAWN in" fit the
# symptom exactly. Measured against the app's own VRML export it is WORSE --
# it destroys solids outright (Brutus 1/9 vs 1/15). Leave it on 'prescale'.
SLIC_SPACE = 'prescale'   # 'prescale' | 'postscale' -- which space the plane is in
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
        # POLY[14:30] -- FOUR fp16.16, the in-plane offset of EACH END of the
        # sweep: (du, dv) at `za`, then (du, dv) at `zb`. An offset moves that
        # cap sideways, so the extrusion leans instead of running straight.
        #
        # This was previously read as THREE values (a single far-end offset)
        # plus "a small signed int16 of unknown meaning" at [26:28] -- which was
        # really the integer half of the fourth value -- and the vertex count as
        # a u32 at [28:32], which swallowed that value's FRACTIONAL half.
        #
        # The count is a u16 at [30:32]. Nine prisms prove it: their POLY length
        # is impossible under the u32 reading (`Curtis` declared 196612 vertices
        # in a 64-byte chunk, `Bedroom with Porch` 2,696,019,971) and exact under
        # the u16 one. All 4212 prisms satisfy len == 32 + 8*u16[30].
        self.skew_a = (iff.fp(b, 14), iff.fp(b, 18))    # offset of the za cap
        self.skew_b = (iff.fp(b, 22), iff.fp(b, 26))    # offset of the zb cap
        self.skew = (self.skew_a[0], self.skew_a[1], 0.0)   # back-compat
        self.mid = b[14:30]
        n = iff.u16(b, 30)
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
                if RING_Z == 'uniform':
                    t = k / n
                    out.append((za + (zb - za) * t, math.sqrt(max(0.0, 1 - (1 - t) ** 2))))
                else:
                    th = (k / n) * (math.pi / 2)
                    out.append((za + (zb - za) * (1 - math.cos(th)), math.sin(th)))
        elif p == SPHERE:
            # `nseg` counts bands per QUARTER turn, not per profile. ROUNDED is a
            # quarter turn in `n` bands; SPHERE is a HALF turn, so it takes 2n at
            # the same angular step.
            #
            # Two things say so. (1) Shape: with only n bands an odd-nseg sphere
            # never reaches full radius -- nseg=5 peaks at sin(72 deg) = 0.951 and
            # nseg=3 at 0.866, so every "sphere" came out a narrow barrel. With 2n
            # a ring lands exactly on the equator and the scale reaches 1.0.
            # (2) Face numbering: four families of SURF records name faces beyond
            # the end of the n-band numbering and land exactly inside the 2n one --
            # (nseg 3, n 4) names 24 against a cap at 25; (5, 4) names 40 against
            # 41; (5, 9) names 91, the cap itself; (5, 16) names 161 and 162, the
            # cap and its first SLIC face.
            out = []
            m = 2 * n
            for k in range(m + 1):
                if RING_Z == 'uniform':
                    # rings spaced evenly ALONG the sweep, radius from the circle
                    t = k / m
                    out.append((za + (zb - za) * t, math.sqrt(max(0.0, 1 - (2 * t - 1) ** 2))))
                else:
                    th = (k / m) * math.pi
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


def face_boundary(tris):
    """The outline of a face, from its triangles: edges used once, chained.

    A face's triangles come from the fan/quad builder and then from SLIC
    clipping, so the outline is not known up front -- but an interior edge is
    shared by two triangles and a boundary edge by one.
    -> list of vertex indices in order, or None if it is not a single loop.
    """
    use = {}
    for t in tris:
        for a, b in ((t[0], t[1]), (t[1], t[2]), (t[2], t[0])):
            use[(a, b)] = use.get((a, b), 0) + 1
    edges = [e for e, n in use.items() if n == 1 and use.get((e[1], e[0]), 0) == 0]
    if not edges:
        return None
    nxt = {}
    for a, b in edges:
        if a in nxt:
            return None                      # a vertex leaving twice: not a simple loop
        nxt[a] = b
    start = edges[0][0]
    loop, cur = [start], nxt.get(start)
    while cur is not None and cur != start and len(loop) <= len(nxt):
        loop.append(cur)
        cur = nxt.get(cur)
    return loop if cur == start and len(loop) == len(nxt) else None


def triangulate_with_holes(outer, holes):
    """Ear-clip a polygon that has holes, by BRIDGING each hole into the outline.

    The format has no boolean subtraction: the ONLY way to make an opening
    through a surface is a fully transparent decal (see surface_features). To
    render that as a real hole the face has to be retriangulated around it.

    Bridge construction is the standard one: take the hole's rightmost vertex,
    cast a ray to +u, find the nearest outer edge it crosses, and splice the two
    loops together at the best visible outer vertex. The result is one simple
    (degenerate but valid) polygon that ordinary ear clipping handles.

    `outer` and `holes` are lists of (u, v). -> index triples into
    `outer + holes[0] + holes[1] + ...`.
    """
    def area(p):
        return sum(p[i][0] * p[(i + 1) % len(p)][1] - p[(i + 1) % len(p)][0] * p[i][1]
                   for i in range(len(p))) / 2

    poly = [list(outer)] + [list(h) for h in holes]
    # outer counter-clockwise, holes clockwise
    if area(poly[0]) < 0:
        poly[0].reverse()
    for i in range(1, len(poly)):
        if area(poly[i]) > 0:
            poly[i].reverse()

    # index bookkeeping so the caller can map back to its own vertices
    idx = [list(range(len(outer)))]
    base = len(outer)
    for h in holes:
        idx.append(list(range(base, base + len(h))))
        base += len(h)
    if area(list(outer)) < 0:
        idx[0].reverse()
    for i, h in enumerate(holes, 1):
        if area(list(h)) > 0:
            idx[i].reverse()

    def seg_hits(p, q, ring, skip):
        """Does the bridge p-q cross any edge of the current ring?"""
        def o(a, b, c):
            v = (b[0]-a[0])*(c[1]-a[1]) - (b[1]-a[1])*(c[0]-a[0])
            return 0 if abs(v) < 1e-9 else (1 if v > 0 else -1)
        for i in range(len(ring)):
            j = (i + 1) % len(ring)
            if i in skip or j in skip:
                continue
            a, b = ring[i], ring[j]
            o1, o2, o3, o4 = o(p, q, a), o(p, q, b), o(a, b, p), o(a, b, q)
            if o1 != o2 and o3 != o4 and o1 and o2 and o3 and o4:
                return True
        return False

    ring, ridx = poly[0], idx[0]
    # Bridge the RIGHTMOST hole first: after a splice the ring contains the
    # previous hole's vertices, and a later bridge that lands on one of those
    # can produce a self-intersecting ring. Two holes in one face then loses a
    # cut entirely (199 of an expected 175 square inches, in the unit test).
    rest = sorted(range(1, len(poly)), key=lambda i: -max(p[0] for p in poly[i]))
    for hi in rest:
        hole, hidx = poly[hi], idx[hi]
        m = max(range(len(hole)), key=lambda i: hole[i][0])
        hp = hole[m]
        order = sorted(range(len(ring)),
                       key=lambda j: (ring[j][0]-hp[0])**2 + (ring[j][1]-hp[1])**2)
        bj = None
        for j in order:
            if ring[j][0] < hp[0] - 1e-9:
                continue
            if not seg_hits(hp, ring[j], ring, {j}):
                bj = j
                break
        if bj is None:
            bj = order[0]
        ring = ring[:bj + 1] + hole[m:] + hole[:m + 1] + ring[bj:]
        ridx = ridx[:bj + 1] + hidx[m:] + hidx[:m + 1] + ridx[bj:]
    # Ear clipping with its own containment test. The shared `triangulate` is
    # not usable here: bridging DUPLICATES two vertices, so points sit exactly
    # on the ear's edges, its inside-test counts those as contained, and every
    # ear is blocked -- it returns zero triangles.
    n = len(ring)
    if n < 3:
        return []
    live = list(range(n))
    cross = lambda o, a, b: (a[0]-o[0])*(b[1]-o[1]) - (a[1]-o[1])*(b[0]-o[0])

    def strictly_inside(p, a, b, c):
        if (abs(p[0]-a[0]) < 1e-9 and abs(p[1]-a[1]) < 1e-9) or \
           (abs(p[0]-b[0]) < 1e-9 and abs(p[1]-b[1]) < 1e-9) or \
           (abs(p[0]-c[0]) < 1e-9 and abs(p[1]-c[1]) < 1e-9):
            return False                      # a bridge duplicate, not an intruder
        d1, d2, d3 = cross(a, b, p), cross(b, c, p), cross(c, a, p)
        return (d1 > 1e-9 and d2 > 1e-9 and d3 > 1e-9) or \
               (d1 < -1e-9 and d2 < -1e-9 and d3 < -1e-9)

    out, guard = [], 0
    while len(live) > 3 and guard < 4 * n * n:
        guard += 1
        cut = False
        for k in range(len(live)):
            i0, i1, i2 = live[k-1], live[k], live[(k+1) % len(live)]
            a, b, c = ring[i0], ring[i1], ring[i2]
            if cross(a, b, c) <= 1e-12:
                continue
            if any(strictly_inside(ring[j], a, b, c) for j in live if j not in (i0, i1, i2)):
                continue
            out.append((i0, i1, i2))
            live.pop(k)
            cut = True
            break
        if not cut:
            break
    if len(live) == 3:
        out.append((live[0], live[1], live[2]))
    return [(ridx[a], ridx[b], ridx[c]) for a, b, c in out]


TEXTURES = {}           # {id: {'name','w','h','rgb','tile'}} for the file being built
DRAW_TEXTURES = True    # sample assigned textures when rendering


def prism_uvs(prsm, verts, faces, fids, poly):
    """Per-triangle UVs for a textured prism.

    A prism is textured as a whole (`PLTX`) or per face (`SUTX`), and each face
    needs its OWN frame, so the UVs are stored per triangle rather than per
    vertex. Coordinates are inches along the face's own u/v axes divided by the
    tile size from TXST -- so the texture repeats at its authored physical size
    instead of being stretched once across whatever face it lands on.
    -> (per-triangle texture id, [(3,2) uv per triangle]) or (None, None)
    """
    import textures as _tx
    whole = None
    pl = prsm.kid('PLTX')
    if pl is not None:
        whole = _tx._tex_id(pl)
    perface = {}
    for surf in prsm.kids('SURF'):
        su = surf.kid('SUTX')
        if su is not None:
            t = _tx._tex_id(su)
            if t is not None:
                perface[iff.u16(surf.hdr, 0)] = t
    if whole is None and not perface:
        return None, None
    appn = app_face_normals(poly)
    sweep = axis_matrix(poly.axis) @ np.array([0.0, 0.0, 1.0])
    byface = {}
    for i, f in enumerate(fids):
        byface.setdefault(f, []).append(i)
    uv = [None] * len(faces)
    tids = [None] * len(faces)
    for fid, tri_i in byface.items():
        # A per-face SUTX OVERRIDES the prism's PLTX, and a prism may carry
        # several different textures at once -- 13 of the 229 textured prisms
        # in the corpus do. Taking one id for the whole prism painted the rest
        # with the wrong bitmap or left them bare.
        tid = perface.get(fid, whole)
        if tid is None:
            continue
        ent = TEXTURES.get(tid)
        if ent is None or 'w' not in ent:
            continue
        tu, tv = ent.get('tile') or (64.0, 64.0)
        tu = tu if tu > 0.01 else 64.0
        tv = tv if tv > 0.01 else 64.0
        wu, wv = ent.get('wrap', (True, True))
        fr = face_frame(verts, [faces[i] for i in tri_i], sweep=sweep, normal=appn.get(fid))
        if fr is None:
            continue
        _, u, v, _, _ = fr
        # A NON-REPEATING texture is fitted ONCE across the face rather than
        # measured in inches per tile: `School Bk Depos 2` is a photograph of
        # the whole building and `CloudScape 1.0` a whole sky, and neither has
        # a physical tile size to be measured in. Per axis, because the flags
        # are per axis -- though the corpus only ever uses (1,1) or (0,0).
        idx = sorted({i for t in (faces[i] for i in tri_i) for i in t})
        V = np.asarray(verts)
        if not wu or not wv:
            us = [float(V[i] @ u) for i in idx]
            vs = [float(V[i] @ v) for i in idx]
            u0, du = min(us), (max(us) - min(us)) or 1.0
            v0, dv = min(vs), (max(vs) - min(vs)) or 1.0
        # V RUNS DOWN THE PICTURE, so it has to be flipped against the frame.
        # The face frame's v axis is world-UP for a vertical face (v = n x u
        # with u = Zup x n), so the top of a wall is v = 1; but row 0 of a
        # decoded bitmap is the TOP of the image. Sampling row = v * h then puts
        # the top of the picture at the bottom of the wall, and `DEALEY`'s
        # depository and every cloudscape in the corpus rendered upside down.
        # Only V: u already points to the viewer's right on the outside of the
        # face, so the image is flipped, NOT rotated 180.
        for i in tri_i:
            t = faces[i]
            uv[i] = np.array([[
                (float(V[j] @ u) / tu) if wu else ((float(V[j] @ u) - u0) / du),
                (-float(V[j] @ v) / tv) if wv else (1.0 - (float(V[j] @ v) - v0) / dv),
            ] for j in t])
            tids[i] = tid
    if all(x is None for x in uv):
        return None, None
    return tids, uv


def _fill_polygon(mask, poly, w, h):
    """Punch one polygon to 0 in `mask`, even-odd, pixel centres.

    Each polygon is rasterised INDEPENDENTLY and OR-ed in. Throwing every
    polygon's crossings into one list and applying even-odd across the lot
    would make two overlapping holes cancel back to solid -- and overlapping
    decorations are ordinary here: a bezel round a screen, a frame round a
    picture. Independent passes are also what let a hole sit inside a hole
    without any winding bookkeeping.
    """
    n = len(poly)
    if n < 3:
        return
    ys = [p[1] for p in poly]
    y0 = max(0, int(math.floor(min(ys) - 0.5)))
    y1 = min(h - 1, int(math.ceil(max(ys) + 0.5)))
    for y in range(y0, y1 + 1):
        yc = y + 0.5
        xs = []
        for i in range(n):
            ax, ay = poly[i]
            bx, by = poly[(i + 1) % n]
            if (ay <= yc) != (by <= yc):
                xs.append(ax + (yc - ay) / (by - ay) * (bx - ax))
        if not xs:
            continue
        xs.sort()
        for i in range(0, len(xs) - 1, 2):
            a = int(math.ceil(xs[i] - 0.5))
            b = int(math.floor(xs[i + 1] - 0.5))
            if b < a:
                continue
            a = max(a, 0); b = min(b, w - 1)
            if b >= a:
                mask[y, a:b + 1] = 0


def face_masks(prsm, verts, faces, fids, poly):
    """Per-face opening stencils, and the UVs that address them.

    A face carrying transparent (alpha 0) or translucent (alpha 128)
    decorations gets a small bitmap in its OWN 2D frame: 255 where the face is
    solid, 0 where an opening has been punched. The geometry is left completely
    untouched -- which is the whole point, see HOLE_MODE.

    Translucent decorations punch the stencil too. The face has to be OPEN
    there so what lies behind the wall shows through; the pane itself is then
    drawn back into the opening as its own translucent mesh by
    `surface_features`, which is why the stencil only ever needs to be binary.

    -> ({fid: {'w','h','a','uv'}}, per-triangle uv list) or ({}, None)
    """
    holes = {}
    for surf in prsm.kids('SURF'):
        fid = iff.u16(surf.hdr, 0)
        for feat in surf.kids('FEAT'):
            col = feat.kid('COLR')
            if col is None or len(col.data) < 4 or col.data[0] not in (0, 128):
                continue
            p2 = feat_polygon(feat)
            if not p2 or len(p2) < 3:
                continue
            holes.setdefault(fid, []).append((p2, feat_transform(feat)))
    if not holes or fids is None:
        return {}, None

    appn = app_face_normals(poly)
    sweep = axis_matrix(poly.axis) @ np.array([0.0, 0.0, 1.0])
    byface = {}
    for i, f in enumerate(fids):
        byface.setdefault(f, []).append(i)

    out = {}
    uv = [None] * len(faces)
    V = np.asarray(verts)
    for fid, cuts in holes.items():
        tri_i = byface.get(fid)
        if not tri_i:
            continue
        tris = [faces[i] for i in tri_i]
        fr = face_frame(V, tris, sweep=sweep, normal=appn.get(fid))
        if fr is None:
            continue
        corner, u, v, _, _ = fr
        idx = sorted({i for t in tris for i in t})
        us = [float(V[i] @ u) for i in idx]
        vs = [float(V[i] @ v) for i in idx]
        u0, u1 = min(us), max(us)
        v0, v1 = min(vs), max(vs)
        du, dv = u1 - u0, v1 - v0
        if du < 1e-6 or dv < 1e-6:
            continue
        w = int(min(MASK_MAX, max(8, round(du * MASK_PX_PER_INCH))))
        h = int(min(MASK_MAX, max(8, round(dv * MASK_PX_PER_INCH))))
        mask = np.full((h, w), 255, np.uint8)
        cu, cv = float(corner @ u), float(corner @ v)
        for p2, tr in cuts:
            tx, ty, th, sx, sy = tr
            ct, st = math.cos(th), math.sin(th)
            px = []
            for (x, y) in p2:
                a = cu + ct * (x * sx) - st * (y * sy) + tx
                b = cv + st * (x * sx) + ct * (y * sy) + ty
                px.append(((a - u0) / du * w, (b - v0) / dv * h))
            _fill_polygon(mask, px, w, h)
        if not (mask == 0).any():
            continue                      # every opening missed the face
        out[fid] = {'w': w, 'h': h, 'a': mask.tobytes()}
        for i in tri_i:
            uv[i] = np.array([[(float(V[j] @ u) - u0) / du,
                               (float(V[j] @ v) - v0) / dv] for j in faces[i]])
    return out, (uv if out else None)


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

    # An oblique sweep. Each CAP carries its own in-plane offset -- `skew_a` at
    # `za`, `skew_b` at `zb` -- and a ring between them takes the linear blend.
    # Neither offset has a component along the sweep, so a lean can never change
    # the prism's length; reading the fourth value as a third VECTOR component
    # did exactly that, stretching the `Picnic Table`'s legs 42 inches (two down
    # through the floor, two up through the table top) instead of crossing them,
    # and sliding the `Lawnmower Man`'s handle stays off into the air.
    sa = poly.skew_a if SKEW_MODE != 'off' else (0.0, 0.0)
    sb = poly.skew_b if SKEW_MODE != 'off' else (0.0, 0.0)
    span = poly.zb - poly.za

    def shift(z):
        if sa == (0.0, 0.0) and sb == (0.0, 0.0):
            return 0.0, 0.0, 0.0
        t = 0.0 if span == 0.0 else (z - poly.za) / span
        return (sa[0] + (sb[0] - sa[0]) * t,
                sa[1] + (sb[1] - sa[1]) * t,
                0.0)

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

    # How many CAPS this profile has, and whether one sits at the HIGH end of the
    # sweep. Read straight out of the application: 0x57fb returns the cap count
    # by profile byte -- straight 2, pointed 1, rounded 1, diamond 0, sphere 0 --
    # and 0x5929 gives the high cap index 0, choosing by `za <= zb` when there is
    # only one. See claude-explore/DISASSEMBLY.md.
    ncap = (2 if poly.profile == STRAIGHT
            else 1 if poly.profile in (POINTED, ROUNDED) else 0)
    has_high = ncap == 2 or (ncap == 1 and poly.za <= poly.zb)
    has_low = ncap == 2 or (ncap == 1 and not has_high)
    # THE SIDE FACES ARE 1-BASED ONLY WHEN THERE IS A HIGH CAP TO BE FACE 0.
    # 0x59c5 computes `n*band + edge` and adds one ONLY if the high cap exists.
    # Straight prisms always have two caps, which is why the galleries -- almost
    # all boxes -- never showed this. Sphere and diamond have NO caps, so their
    # sides start at 0 and we were adding a spurious +1 to every one of them.
    first = 1 if has_high else 0

    def side_id(r, i):
        if FACE_BASE == 'side0':
            return r * n + ((i + 1) % n)
        if FACE_ORDER == 'end':
            # A side face is named by the vertex its edge ARRIVES at, plus one:
            # edge v_j -> v_j+1 is face (j+1)+1. Face 1 is therefore the edge
            # that closes the polygon back onto vertex 0.
            return first + r * n + ((i + 1) % n)
        return first + r * n + (n - 1 - i)

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

    # base faces = caps + sides (0x56f4 = 0x573b + cut faces; 0x573b = caps +
    # sides). The high cap is index 0; the low cap is the LAST base face.
    nbase = ncap + nband * n
    cap0, cap1 = ((nband * n, nband * n + 1) if FACE_BASE == 'side0'
                  else (0, nbase - 1))
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
            if SLIC_SPACE == 'postscale':
                # If the plane were authored in the space the object is DRAWN in
                # -- after POSN's scale -- then n.(S p) + d = (S n).p + d, so the
                # pre-scale normal is the component-wise product with the scale.
                _ps = prsm.kid('POSN')
                if _ps is not None and len(_ps.data) >= 48:
                    _sc = np.array([iff.fp(_ps.data, 36), iff.fp(_ps.data, 40), iff.fp(_ps.data, 44)])
                    if np.all(np.abs(_sc) > 1e-9):
                        nn = nn * _sc
            if not np.any(np.abs(nn) > 1e-9):
                continue
            erow = ([iff.fp(es.data, 2 + i * 40 + j * 4) for j in range(10)]
                    if es is not None and len(es.data) >= 2 + (i + 1) * 40 else None)
            if SLIC_FILTER is not None and not SLIC_FILTER(i, nrec, erow):
                continue
            if SLIC_MODE == 'clip':
                verts, faces, fids = _clip.clip_mesh(
                    verts, faces, nn, dd, keep_negative=SLIC_KEEP_NEG,
                    ids=fids, new_id=nbase + i)
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
    if HOLE_MODE == 'geom':
        verts, faces, fids = _cut_holes(prsm, verts, faces, fids, poly)
    verts, faces = _compact(verts, faces)
    return verts, faces, poly, fids


def _cut_holes(prsm, verts, faces, fids, poly):
    """Subtract every fully transparent FEAT from the face it sits on.

    A zero-alpha decoration is not decoration: it is an OPENING, and it is the
    only subtractive operation the format has. `BEACHCBN`'s convertible gets its
    open cockpit this way and the `Silo` its doorway. 468 of them corpus-wide.
    """
    holes = {}
    for surf in prsm.kids('SURF'):
        fid = iff.u16(surf.hdr, 0)
        for feat in surf.kids('FEAT'):
            col = feat.kid('COLR')
            # Both Transparent (0) and Translucent (128) open the face: a
            # translucent window must show what is BEHIND the wall, not blend
            # with the wall itself. The translucent pane is then drawn back into
            # the opening by surface_features.
            if col is None or len(col.data) < 4 or col.data[0] not in (0, 128):
                continue
            p2 = feat_polygon(feat)
            if not p2 or len(p2) < 3:
                continue
            holes.setdefault(fid, []).append((p2, feat_transform(feat)))
    if not holes:
        return verts, faces, fids
    byface = {}
    for i, (t, f) in enumerate(zip(faces, fids)):
        byface.setdefault(f, []).append(i)
    appn = app_face_normals(poly)
    sweep = axis_matrix(poly.axis) @ np.array([0.0, 0.0, 1.0])
    verts = list(verts)
    drop, add, addid = set(), [], []
    for fid, cuts in holes.items():
        tri_i = byface.get(fid)
        if not tri_i:
            continue
        tris = [faces[i] for i in tri_i]
        loop = face_boundary(tris)
        fr = face_frame(np.asarray(verts), tris, sweep=sweep, normal=appn.get(fid))
        if loop is None or fr is None:
            continue                          # not a simple loop: leave the face alone
        corner, u, v, nrm, _ = fr
        V = np.asarray(verts)
        outer = [(float(V[i] @ u), float(V[i] @ v)) for i in loop]
        cu, cv = float(corner @ u), float(corner @ v)
        hs = []
        for p2, tr in cuts:
            tx, ty, th, sx, sy = tr
            ct, st = math.cos(th), math.sin(th)
            hs.append([(cu + ct*(x*sx) - st*(y*sy) + tx,
                        cv + st*(x*sx) + ct*(y*sy) + ty) for (x, y) in p2])
        try:
            tt = triangulate_with_holes(outer, hs)
        except Exception:
            continue
        if not tt:
            continue
        plane = float(V[loop[0]] @ nrm)
        newidx = list(loop)
        for h in hs:
            for (a, b) in h:
                verts.append(u*a + v*b + nrm*plane)
                newidx.append(len(verts) - 1)
        for (a, b, c) in tt:
            add.append((newidx[a], newidx[b], newidx[c]))
            addid.append(fid)
        drop.update(tri_i)
    if not add:
        return np.asarray(verts), faces, fids
    keep = [i for i in range(len(faces)) if i not in drop]
    return (np.asarray(verts),
            [faces[i] for i in keep] + add,
            [fids[i] for i in keep] + addid)


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


def surf_colours(prsm):
    """SURF face-index -> RGB override. {} if the prism has none.

    A `SURF` can carry a `COLR` that RECOLOURS its face, and this was never
    implemented -- 548 of them across the galleries were being ignored.

    Its COLR is NOT laid out like a PRSM's. There is a 2-byte prefix first, and
    the length follows it:

        6 B    prefix 1 or 3, then ONE  (a, r, g, b)     96 records
       10 B    prefix 2,      then TWO  (a, r, g, b)    452 records

    A PRSM's own 8-byte COLR is the same two-record body with no prefix, and its
    two records almost always carry identical RGB -- which fits the application's
    two-sided-surface model, where a face can be coloured differently inside and
    out. The prefix looks like the same outside/inside/both selector `FEAT` uses,
    one-based: 1 and 3 take a single colour, 2 takes a pair.

    Reading a SURF COLR at the PRSM offsets picks up the prefix as part of the
    colour: `00 02 00 ff ff ff 00 ff ff ff` is white, but bytes 1-3 read it as
    (0x02, 0x00, 0xff), a dark blue.

    Each record is `(alpha, r, g, b)`, and with TWO of them the SECOND is the one
    you can see. Record 1's alpha is 0 in every one of the 18,038 PRSM colours
    and every two-record SURF colour in the corpus -- it is the INSIDE of the
    surface, which a solid never shows. Taking record 1's RGB is right only
    because the two records almost always agree:

        record 2 alpha 255, RGBs differ :   50   <- rendered with the WRONG colour
        record 2 alpha 255, RGBs agree  : 1945
        record 2 alpha 128, RGBs agree  :  127   <- translucent, drawn opaque
        record 2 alpha   0, RGBs agree  : 2348   <- see below

    The 50 are real: the `INDYCAR`'s two wing end plates are a mirrored pair, one
    `00 03 | ff ff ff ff` (white) and the other
    `00 02 | 00 ff 00 00 | ff ff ff ff` (inside red, OUTSIDE WHITE). Reading
    record 1 painted the second plate red while the application shows white.

    Because the RGBs agree everywhere except those 50, switching to record 2
    changes nothing else.

    OPEN: what a record-2 alpha of 0 means for a FACE. On a `FEAT` a zero alpha
    cuts a hole (see surface_features); if it does the same here, 2,348 faces
    should be invisible rather than painted. Not acted on -- their RGB matches
    record 1 in every case, so the current output is unchanged either way.
    """
    out = {}
    for surf in prsm.kids('SURF'):
        c = surf.kid('COLR')
        if c is None or len(c.data) < 6:
            continue
        d = c.data
        out[iff.u16(surf.hdr, 0)] = (d[7], d[8], d[9]) if len(d) >= 10 else (d[3], d[4], d[5])
    return out


def surf_alphas(prsm):
    """SURF face-index -> OPACITY of the visible record. 255 / 128 / 0.

    The glass in `GLASHOUS` is here: its four walls carry
    `00 02 | 00 ff ff ff | 80 ff ff ff` -- record 2 alpha 0x80, translucent
    white. The application calls the three states Opaque, Translucent (drawn as
    a checkerboard dither) and Transparent (a hole).
    """
    out = {}
    for surf in prsm.kids('SURF'):
        c = surf.kid('COLR')
        if c is None or len(c.data) < 6:
            continue
        d = c.data
        out[iff.u16(surf.hdr, 0)] = d[6] if len(d) >= 10 else d[2]
    return out


def prism_alpha(prsm):
    """A prism's own opacity: the second COLR record's alpha."""
    c = prsm.kid('COLR')
    return c.data[4] if c is not None and len(c.data) >= 8 else 255


def color_of(prsm):
    """A prism's own colour: the SECOND of its COLR's two (alpha, r, g, b)
    records. Record 1 is the inside face -- its alpha is 0 in all 18,038 of
    them -- and its RGB differs from record 2's on 8 prisms."""
    c = prsm.kid('COLR')
    if c is None or len(c.data) < 8:
        return (170, 170, 170)
    d = c.data
    return (d[5], d[6], d[7])


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
                base = color_of(k)
                over = surf_colours(k)
                tids, uv = (prism_uvs(k, v, f, fids, poly)
                            if (DRAW_TEXTURES and TEXTURES) else (None, None))

                def _tex(tid):
                    e = TEXTURES[tid]
                    return {'id': tid, 'name': e.get('name'), 'w': e['w'], 'h': e['h'],
                            'rgb': e['rgb'], 'wrap': e.get('wrap', (True, True))}
                al = surf_alphas(k)
                ba = prism_alpha(k)
                masks, muv = (face_masks(k, v, f, fids, poly)
                              if HOLE_MODE == 'mask' else ({}, None))
                # The TEXTURED flag is part of the grouping key. Within one
                # prism some faces can carry a SUTX and others none, and a GPU
                # cannot sample a bitmap for half a draw call -- so the two sets
                # become separate meshes rather than one mesh with holes in its
                # UV array. Splitting here keeps the JS port able to mirror this
                # exactly instead of painting the untextured faces with texel
                # (0, 0), which turned MYHOUSE2's white wall dark maroon.
                if (over or al or masks or uv) and fids is not None:
                    groups = {}
                    for i, fid in enumerate(fids):
                        # the texture ID is part of the key, not just a flag:
                        # one prism can wear several bitmaps
                        tflag = tids[i] if (uv and uv[i] is not None) else -1
                        # A STENCILLED face is its own group: the mask is in
                        # that one face's frame, so merging two masked faces
                        # into a draw call would address the wrong bitmap.
                        mkey = fid if (muv and muv[i] is not None) else -1
                        groups.setdefault(
                            (over.get(fid, base), al.get(fid, ba), tflag, mkey), []).append(i)
                    for key in sorted(groups):          # sorted: JS must match
                        col, a, tflag, mkey = key
                        gi = groups[key]
                        gt = dict(_tex(tflag), uv=[uv[i] for i in gi]) if tflag >= 0 else None
                        gm = (dict(masks[mkey], uv=[muv[i] for i in gi])
                              if mkey >= 0 and mkey in masks else None)
                        out.append((wv, [f[i] for i in gi], col, poly, gt, a, gm))
                else:
                    out.append((wv, f, base, poly, None, ba, None))
                if DRAW_SURF:
                    out.extend(surface_features(k, v, f, fids, W))
        collect(k, W, out, u)


def scene_meshes(path_or_chunk):
    r = iff.load(path_or_chunk) if isinstance(path_or_chunk, str) else path_or_chunk
    global TEXTURES
    try:
        import textures as _tx
        TEXTURES = _tx.table(r) if DRAW_TEXTURES else {}
    except Exception:
        TEXTURES = {}
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
FACE_ORDER = 'end'       # 'end' | 'rev' -- how SURF face ids map to profile edges
FACE_HAND = 'right'      # 'right' | 'raw' -- orient the face frame by its outward normal
# Curved profiles space their rings EVENLY ALONG THE SWEEP, taking the radius
# from the circle -- not evenly by angle. Both are legitimate spheres and differ
# only in where the rings land, but angle-spacing bunches them at the poles: it
# makes a head bulge like a barrel and squeezes the top band to a sliver, so the
# `INFANTRY` soldiers' helmets came out as a thin rim instead of a hat. The user
# confirmed the even-spaced silhouette against the application.
# No oracle can see this -- facefit scores the two identically (464 misfits, 202
# adrift, both ways) because face EXTENTS barely move. It took the eye.
RING_Z = 'uniform'       # 'uniform' | 'angle' -- how curved-profile rings are spaced
FACE_FRAME = 'azim'    # n x up: horizontal across the face, vertical up it
FACE_BASE = 'cap0'       # 'cap0' (cap first, sides 1-based) | 'side0' (sides first, 0-based)
FACE_HORIZ_TOL = 1e-6   # |up x n| below this counts the face as HORIZONTAL
DRAW_HOLES = False      # draw alpha==0 FEATs (hole cutters) as solid decoration

# How an opening gets made. 'mask' rasterises the holes into a per-face stencil
# and the renderer skips those pixels; 'geom' retriangulates the face around
# them; 'off' leaves the face solid.
#
# 'mask' is the default because 'geom' does not survive contact with the corpus.
# `REEVES` has a wall carrying EIGHTY-TWO windows: bridging each hole into the
# outer ring in turn means every later bridge has to thread past the vertices
# the earlier ones spliced in, the ring self-intersects, and the ear clipper
# hands back a shredded face. Audited, that wall drops from 254,674 sq in to
# 34,079 when it should lose only its windows and land at 209,079 -- 86% of the
# wall destroyed. Eight of the nine cut faces in the file are wrong by more
# than 2%. No amount of bridge-ordering care fixes the general case, and holes
# are allowed to OVERLAP (a bezel around a screen, a frame around a picture),
# which a single outer ring cannot represent at all.
#
# A stencil has none of those failure modes, and it is very probably what the
# application itself did: a 1993 scanline renderer with no depth buffer makes a
# hole by leaving spans unpainted, not by retriangulating. Note the Virtus VRML
# exporter does NOT cut either -- it writes the wall whole and lays a
# transparent quad on top, which is why its exports show no openings at all.
HOLE_MODE = 'mask'      # 'mask' | 'geom' | 'off'

MASK_PX_PER_INCH = 2.0  # stencil resolution
MASK_MAX = 512          # ... capped, per axis
SURF_OFFSET = 0.05      # inches to lift a decoration off its face, to beat z-fighting

# FEAT's 2-byte header selects which side of the surface is decorated.
#
# The value 1 is OUTSIDE, not inside. It accounts for 2048 of the 2520 gallery
# decorations; 2 is both (412) and 0 is rare (60). Reading 1 as "inside" pushes
# four decorations in five 0.05 in INTO their own prism, where the depth buffer
# hides them -- a bug that stayed invisible for as long as the placement bug
# above kept decals hanging off their faces in open air, and only surfaced the
# moment placement was fixed and they landed flush.
FEAT_INSIDE, FEAT_OUTSIDE, FEAT_BOTH = 0, 1, 2


def app_face_normals(poly):
    """Face normals the way the APPLICATION computes them, from `seg28:0x5a59`.

    For a side face the app takes the edge ARRIVING at vertex si and uses its
    raw perpendicular::

        di = (si == 0) ? vertexCount - 1 : si - 1
        normal = (vert[di].y - vert[si].y,  vert[si].x - vert[di].x,  0)

    -- un-normalised, with NO component along the sweep -- then permutes it by
    the sweep axis. The binary stores that as three **int16**, and the
    quantisation is not an implementation detail, it is the rule: a face whose
    perpendicular is (-137.3494, -0.2431) is stored as (-137, 0) and is
    therefore EXACTLY axis-aligned as far as the app is concerned.

    That is what decides whether a face counts as horizontal, and it has to be,
    because no angular tolerance can work: `STAWAGON`'s roof is 0.1 degrees off
    horizontal and wants the horizontal fallback, while `SPACSTAT`'s facets are
    0.6 degrees off and want the azimuth frame. Quantisation separates them
    exactly -- the roof's tilt comes from a 0.24 in edge offset that rounds to
    zero, the station's from a 12 in one that does not.

    -> {face_id: 3-vector, un-normalised, in object space}
    """
    A = axis_matrix(poly.axis)
    V = poly.verts
    n = len(V)
    if n < 3:
        return {}
    rings = poly.rings()
    nband = len(rings) - 1
    ncap = (2 if poly.profile == STRAIGHT
            else 1 if poly.profile in (POINTED, ROUNDED) else 0)
    has_high = ncap == 2 or (ncap == 1 and poly.za <= poly.zb)
    has_low = ncap == 2 or (ncap == 1 and not has_high)
    first = 1 if has_high else 0
    out = {}
    if has_high:
        out[0] = A @ np.array([0.0, 0.0, 1.0])
    if has_low:
        out[ncap + nband * n - 1] = A @ np.array([0.0, 0.0, -1.0])
    for band in range(nband):
        for j in range(n):
            a, b = V[(j - 1) % n], V[j]
            nx, ny = int(b[1] - a[1]), int(a[0] - b[0])    # int16 truncation
            if nx == 0 and ny == 0:
                continue                                   # edge under 1 unit
            out[first + band * n + j] = A @ np.array([float(nx), float(ny), 0.0])
    return out


def face_frame(verts, tris, sweep=None, normal=None):
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
    # Area-weighted sum over the whole face, not the single largest triangle.
    # One triangle's cross product carries enough float noise to flip the
    # dominant-axis test below on a face that sits at exactly 45 degrees, and a
    # sum is both more accurate and cheaper to reason about. Keep the largest
    # triangle only as the degenerate fallback.
    acc = np.zeros(3)
    best, nbest = 0.0, None
    for t in tris:
        a, b, c = verts[t[0]], verts[t[1]], verts[t[2]]
        cr = np.cross(b - a, c - a)
        acc += cr
        ln = float(np.linalg.norm(cr))
        if ln > best:
            best, nbest = ln, cr / ln
    la = float(np.linalg.norm(acc))
    nrm = acc / la if la > 1e-9 else nbest
    if nrm is None or best < 1e-9:
        return None
    # The APP's own integer-quantised normal, used ONLY to choose the in-plane
    # DIRECTION below -- never as the face's plane.
    #
    # Substituting it for `nrm` outright is wrong and expensively so: the face's
    # vertices are coplanar with respect to the TRUE normal, not the quantised
    # one, so the plane offset then depends on WHICH vertex you measure it from.
    # Python sorted the face's vertex indices and the JS did not, and on
    # `APOLLO` -- 17,000 units across -- that put the two implementations 69
    # inches apart on the same decoration.
    nq = None
    if normal is not None:
        q = np.asarray(normal, float)
        ln = float(np.linalg.norm(q))
        if ln > 1e-9:
            nq = (-q if float(q @ nrm) < 0 else q) / ln
    # point the normal away from the solid so decorations sit on the outside
    if float(nrm @ (P.mean(0) - verts.mean(0))) < 0:
        nrm = -nrm
    # Which world axis to drop. A plane at exactly 45 degrees ties two axes, and
    # `argmax` then decides on whatever the last ulp of the cross product says --
    # so the `Jersey Cow`'s two flanks, which are mirror images of one another,
    # got TRANSPOSED frames: one kept (Y, Z), the other (X, Y). The spot painted
    # on the second flank was laid out along a 7-inch axis using a 59-inch
    # coordinate and flew off into space. Break the tie towards the lowest axis
    # index instead, so mirrored faces get mirrored frames.
    a_n = np.abs(nrm)
    drop = int(np.flatnonzero(a_n >= a_n.max() - 1e-6)[0])
    ax = [i for i in range(3) if i != drop]          # ascending order
    u = np.zeros(3); u[ax[0]] = 1.0
    v = np.zeros(3); v[ax[1]] = 1.0

    # `u` ALWAYS RUNS ALONG THE SWEEP on a side face.
    #
    # The world-axis rule alone is discontinuous: as a facet's normal swings past
    # 45 degrees the dropped axis changes, and with it WHICH of the two kept axes
    # ends up along the extrusion. Going round an octagonal cylinder the eight
    # facets therefore do not share a convention -- and on `SPACSTAT` exactly the
    # four whose `u` landed on the sweep placed their window rows correctly while
    # the other four threw them into space. 60 decorations of 120, a clean half.
    #
    # So keep the world-axis PAIR (it decides the in-plane direction) but fix the
    # ROLES: whichever of the two is more aligned with the sweep becomes `u`. A
    # cap face has no sweep component and is left alone.
    # The AZIMUTH frame: u = n x up, the horizontal direction in the face plane.
    #
    # Measured over all 15,643 side-face decorations, the app does not use a
    # world-axis PAIR at all. It builds the tangent frame from the normal the
    # way a design tool would: `u` is the horizontal direction lying in the
    # face, `v` is the one going up it -- so a decoration's x runs across the
    # wall and its y runs up it, whatever angle the wall is turned to. On a
    # world-aligned face that is indistinguishable from the world-axis rule,
    # which is why the old frame survived so long; on a facet turned 22.5
    # degrees it is not, which is why exactly half of `SPACSTAT`'s windows flew
    # off. When the face is HORIZONTAL the cross product degenerates and the
    # world-axis pair is used instead -- and the 42 decorations that rule gets
    # wrong under any edge/sweep story are precisely the degenerate ones.
    if FACE_FRAME.startswith('azim'):
        up = np.zeros(3)
        up[{'azimx': 0, 'azimy': 1}.get(FACE_FRAME.lower(), 2)] = 1.0
        # `up x n`, NOT `n x up`. Both are continuous round a cylinder, but they
        # differ by a 180-degree turn about the normal, and only this order
        # reproduces the old world-axis frame -- INCLUDING its right-hand flip
        # -- on every axis-aligned face. Getting it backwards put every
        # decoration in the corpus on the right face upside down and at the
        # wrong end of it, which no containment oracle can see: rotating a face
        # frame 180 degrees moves the origin to the opposite corner and the fit
        # is exactly as good. It took the user reading `VIRTUS` off the shuttle.
        # 'azim_rev' is the WRONG order, kept switchable on purpose: it is the
        # one A/B this codebase cannot do by editing the source, because the two
        # spellings are the same number of BYTES. Python's bytecode cache
        # invalidates on source mtime AND SIZE, so a same-length edit on a mount
        # with coarse mtime silently reuses the stale .pyc and both halves of
        # the comparison run the same code -- which is exactly what happened,
        # and it reported "0 decorations moved" for a change that moves 16,000.
        na = nrm if nq is None else nq
        h = np.cross(na, up) if FACE_FRAME == 'azim_rev' else np.cross(up, na)
        nh = float(np.linalg.norm(h))
        if nh > FACE_HORIZ_TOL:
            u = h / nh
            v = np.cross(nrm, u)
    if FACE_FRAME in ('sweep_u', 'sweep_v') and sweep is not None:
        w = np.asarray(sweep, float)
        du, dv = abs(float(u @ w)), abs(float(v @ w))
        if FACE_FRAME == 'sweep_u' and dv > du + 1e-9:
            u, v = v, u
        elif FACE_FRAME == 'sweep_v' and du > dv + 1e-9:
            u, v = v, u
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
    # Make (u, v, nrm) RIGHT-HANDED.
    #
    # u and v come from fixed world axes, so the two opposite faces of a box get
    # the SAME pair while their outward normals point opposite ways -- one frame
    # right-handed, the other left-handed. A decoration laid out in the mirrored
    # frame comes out backwards, which is why `DEPARTME`'s two escalators carry
    # the same triangle and only one of them reads correctly.
    if FACE_HAND == 'right' and float(np.cross(u, v) @ nrm) < 0:
        u = -u
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
    """2D FEAT POSN -> (tx, ty, rotation, sx, sy).

    Two lengths, and the SHORT one is a trap that cost most of a session:

        24 B   (x, y, rotation, ~0, sx, sy)      2194 records
        12 B   (x, y, rotation)                   338 records, scale implied 1

    This is the same omit-the-default trick the 3D POSN plays (see
    `posn_matrix`), and it bites the same way. Requiring 24 bytes here returned
    (0, 0) for every short record, so 338 decorations lost their placement and
    piled up at their face's origin corner -- `Mac LC` and `Mac IIci`'s screens
    off the side of the monitor, while `Mac Quadra` and the `Computer Desk` Macs,
    which carry full records, looked perfect. That split -- same object class,
    some right and some wrong -- is exactly the signature of a short-record bug,
    and I misread it as evidence for two different coordinate conventions and
    built an elaborate wrong rule on top of it. There is only ONE convention:
    the outline is measured from the face's minimum corner, offset by (tx, ty).

    Field 2 is a rotation in radians about the decoration's own origin --
    non-zero on 4.3 % of decals, with unmistakable values (pi, pi/2, -pi/2, pi/4,
    5.359, -0.2618). Field 3 is zero on 99.7 % of the long records and has no
    known meaning. Fields 4 and 5 are scale, exactly 1.0 on 94 % of them.
    """
    ps = feat.kid('POSN')
    if ps is None or len(ps.data) < 12:
        return (0.0, 0.0, 0.0, 1.0, 1.0)
    d = ps.data
    v = [iff.fp(d, i * 4) for i in range(min(len(d) // 4, 6))]
    while len(v) < 4:                     # short form: rotation may be absent too
        v.append(0.0)
    while len(v) < 6:                     # scale omitted because it is identity
        v.append(1.0)
    return (v[0], v[1], v[2], v[4] or 1.0, v[5] or 1.0)


def surface_features(prsm, verts, faces, fids, W):
    """Build overlay meshes for every SURF decoration on this prism."""
    out = []
    if fids is None:
        return out
    byface = {}
    for t, fid in zip(faces, fids):
        byface.setdefault(fid, []).append(t)

    pc = prsm.kid('POLY')
    sweep_dir = appn = None
    if pc is not None:
        _p = Poly(pc)
        sweep_dir = axis_matrix(_p.axis) @ np.array([0.0, 0.0, 1.0])
        appn = app_face_normals(_p)
    appn = appn or {}

    for surf in prsm.kids('SURF'):
        fid = iff.u16(surf.hdr, 0)
        tris = byface.get(fid)
        if not tris:
            continue
        fr = face_frame(verts, tris, sweep=sweep_dir, normal=appn.get(fid))
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
            # Byte 0 of a FEAT's COLR is OPACITY, and it takes exactly three
            # values corpus-wide: 255 opaque (18,805), 128 translucent (629) and
            # 0 fully transparent (468). A zero is not decoration at all -- the
            # authors used it to cut a HOLE through the face it sits on, which
            # is how `BEACHCBN`'s convertible gets its open cockpit and how the
            # `Silo` gets its doorway. Drawn opaque, that hole becomes a solid
            # white slab across the car's seats.
            alpha = col.data[0] if col and len(col.data) >= 4 else 255
            if alpha == 0 and not DRAW_HOLES:
                continue                      # a hole is cut, nothing is drawn

            ct, st = math.cos(th), math.sin(th)
            pts2 = [(ct * (x * sx) - st * (y * sy) + tx,
                     st * (x * sx) + ct * (y * sy) + ty) for (x, y) in poly]

            # ONE convention: the outline is measured from the face's MINIMUM
            # CORNER, offset by the FEAT's own (tx, ty).
            #
            # This was briefly split into two rules keyed on whether (tx, ty) was
            # zero, because 338 decorations only fit if placed some other way.
            # Those 338 turned out to be exactly the 338 short (12-byte) FEAT
            # POSNs whose translation was being discarded -- see feat_transform.
            # The lesson: when a rule needs an exception for a specific subset,
            # check whether the subset is defined by a parsing failure before
            # inventing semantics for it.
            origin = corner
            # Lift the decoration off its face by SURF_OFFSET INCHES, not by
            # SURF_OFFSET local units. A prism carries the object's UNIT scale
            # and its own POSN scale in W, so a fixed local offset shrinks by
            # whatever those come to -- 4x on a quarter-inch-unit object, 16x on
            # a sixteenth. That is what turned the `Microwave Oven`'s front into
            # z-fighting speckle the moment UNIT scaling was implemented.
            # A decoration can carry its OWN texture, through SFTX. 92 of them
            # do, and they are not a curiosity: `JENSONEX`'s half-timbered top
            # storey is 22 WOOD2-3E panels and 23 STONE2 ones, so with SFTX
            # unread the whole upper floor of the house rendered flat brown.
            ftex = _feat_texture(feat)

            wn = np.linalg.norm(W[:3, :3] @ nrm) or 1.0
            for sgn in ((1, -1) if side == FEAT_BOTH else (1,) if side != FEAT_INSIDE else (-1,)):
                off = nrm * (SURF_OFFSET * sgn / wn)
                pv = np.array([origin + u * a + v * b + off for (a, b) in pts2])
                tri = triangulate([(p @ u, p @ v) for p in pv])
                if not tri:
                    continue
                vh = np.hstack([pv, np.ones((len(pv), 1))])
                wv = (W @ vh.T).T[:, :3]
                gt = None
                if ftex is not None:
                    gt = dict(ftex, uv=[_feat_uv(ftex, pv, u, v, pts2, t) for t in tri])
                out.append((wv, tri, rgb, None, gt, alpha, None))
    return out


def _feat_texture(feat):
    """A decoration's own SFTX texture, as a mesh-tuple `tex` dict."""
    sf = feat.kid('SFTX')
    if sf is None:
        return None
    try:
        import textures as _tx
        tid = _tx._tex_id(sf)
    except Exception:
        return None
    e = TEXTURES.get(tid) if tid is not None else None
    if e is None or 'w' not in e:
        return None
    return {'id': tid, 'name': e.get('name'), 'w': e['w'], 'h': e['h'],
            'rgb': e['rgb'], 'wrap': e.get('wrap', (True, True)),
            'tile': e.get('tile') or (64.0, 64.0)}


def _feat_uv(tex, pv, u, v, pts2, tri):
    """UVs for one triangle of a textured decoration.

    A REPEATING texture is measured in the same face-frame inches the wall uses,
    so panelling on a decoration tiles in register with panelling on the surface
    under it. A NON-REPEATING one is fitted across the DECORATION's own extent,
    not the face's -- `VRLOGO`'s logo and the `Mountains 1.0` panel in `MYHOUSE`
    are pictures of themselves, and the face they sit on is irrelevant to them.
    """
    tu, tv = tex['tile']
    tu = tu if tu > 0.01 else 64.0
    tv = tv if tv > 0.01 else 64.0
    wu, wv_ = tex['wrap']
    if not wu or not wv_:
        us = [a for (a, _) in pts2]; vs = [b for (_, b) in pts2]
        u0, du = min(us), (max(us) - min(us)) or 1.0
        v0, dv = min(vs), (max(vs) - min(vs)) or 1.0
    out = []
    for j in tri:
        a, b = pts2[j]
        # V flipped, for the same reason as prism_uvs: row 0 of a bitmap is the
        # TOP of the picture and the frame's v axis points UP.
        out.append([(float(pv[j] @ u) / tu) if wu else ((a - u0) / du),
                    (-float(pv[j] @ v) / tv) if wv_ else (1.0 - (b - v0) / dv)])
    return np.array(out)
