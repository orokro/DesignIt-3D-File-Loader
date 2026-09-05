/**
 * Design-It! 3-D geometry: IFF chunks -> triangle meshes.
 *
 * Everything visible in the application is a PRSM: a 2D polygon swept along an
 * axis with a profile function. There is no mesh format in the file.
 */
import { fp, u16, u32 } from './iff.js';
import { clipMesh } from './clip.js';
import { textureTable, assignments } from './textures.js';

export const STRAIGHT = 1, POINTED = 2, DIAMOND = 3, ROUNDED = 4, SPHERE = 5;
export const PROFILE_NAME = { 1: 'straight', 2: 'pointed', 3: 'diamond', 4: 'rounded', 5: 'sphere' };

export const options = {
  applySlic: true,      // SLIC planes cut the prism
  slicKeepNeg: false,   // keep n.p + d >= 0
  drawSurf: true,       // build SURF/FEAT decoration overlays
  drawTextures: true,   // sample the file's own TXTB bitmaps
  // How an opening gets made. 'mask' rasterises the holes into a per-face
  // stencil the renderer punches with alphaTest; 'geom' retriangulates the face
  // around them; 'off' leaves it solid. See d3d.HOLE_MODE for why 'geom' loses:
  // REEVES has a wall with 82 windows and bridging destroys 86% of it.
  holeMode: 'mask',     // 'mask' | 'geom' | 'off'
  maskPxPerInch: 2,
  maskMax: 512,
  applySkew: true,      // POLY's oblique-sweep offset
  faceFrame: 'azim',    // 'azim' | 'world' -- a face's 2D axes; mirrors d3d.FACE_FRAME
  drawHoles: false,     // draw alpha==0 FEATs (hole cutters) as solid decoration
};

// ---- small vector helpers ----
const sub = (a, b) => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
const add = (a, b) => [a[0] + b[0], a[1] + b[1], a[2] + b[2]];
const add3 = add;
const mul = (a, s) => [a[0] * s, a[1] * s, a[2] * s];
const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
const len = (a) => Math.hypot(a[0], a[1], a[2]);
const norm = (a) => { const l = len(a) || 1; return [a[0] / l, a[1] / l, a[2] / l]; };

export class Poly {
  constructor(chunk) {
    const b = chunk.data;
    this.pclass = b.getUint8(1);   // 1 custom, 2 rectangle, 3 regular n-gon
    this.axis = b.getUint8(2);     // sweep axis: 3 = Z, 2 = Y, 1 = X
    this.profile = b.getUint8(3);
    this.nseg = u16(b, 4);         // curve subdivision (1 for flat profiles)
    this.za = fp(b, 6);
    this.zb = fp(b, 10);
    // POLY[14:30] -- FOUR fp16.16: the in-plane offset of EACH end of the
    // sweep, (du, dv) at `za` then (du, dv) at `zb`. An offset slides that cap
    // sideways so the extrusion leans; neither has a component along the sweep,
    // so a lean can never change the prism's length.
    //
    // Previously read as THREE values plus "a signed int16 of unknown meaning"
    // at [26:28] -- the integer half of the fourth value -- with the vertex
    // count a u32 at [28:32] that swallowed its fractional half. The count is a
    // u16 at [30:32]: nine prisms have a POLY length impossible under the u32
    // reading (`Curtis` declared 196612 vertices in 64 bytes) and exact under
    // this one. Must match d3d.py's Poly.
    this.skewA = [fp(b, 14), fp(b, 18)];   // offset of the za cap
    this.skewB = [fp(b, 22), fp(b, 26)];   // offset of the zb cap
    this.skew = [this.skewA[0], this.skewA[1], 0];   // back-compat
    let n = u16(b, 30);
    n = Math.max(0, Math.min(n, Math.floor((b.byteLength - 32) / 8)));
    this.verts = [];
    for (let i = 0; i < n; i++) this.verts.push([fp(b, 32 + i * 8), fp(b, 36 + i * 8)]);
  }

  /**
   * (z, scale) pairs along the sweep.
   *
   * Two independent things are encoded here:
   *  - The taper direction. A profile's SMALL end sits at `za`, the first of
   *    the two stored sweep bounds, not at whichever end is higher. 124 of 213
   *    pointed prisms have za < zb; treating the apex as always-uppermost turns
   *    those upside down (Basketball Goal, Toilet, Barbecue Grill).
   *  - The ring ORDER, which fixes the face numbering SURF indexes into.
   *    Rings run from the HIGH end of the sweep to the low one.
   */
  rings() {
    const za = this.za, zb = this.zb;
    const n = Math.max(1, this.nseg);
    let out;
    switch (this.profile) {
      case POINTED: out = [[za, 0], [zb, 1]]; break;
      case DIAMOND: out = [[za, 0], [(za + zb) / 2, 1], [zb, 0]]; break;
      case ROUNDED:
        // Rings are spaced EVENLY ALONG THE SWEEP with the radius taken from the
        // circle -- not evenly by angle. Angle-spacing bunches rings at the
        // poles, which bulges the shape and squeezes the end bands to slivers.
        // Confirmed against the application. Must match d3d.py's rings().
        out = [];
        for (let k = 0; k <= n; k++) {
          const t = k / n;
          out.push([za + (zb - za) * t, Math.sqrt(Math.max(0, 1 - (1 - t) * (1 - t)))]);
        }
        break;
      case SPHERE: {
        // `nseg` counts bands per QUARTER turn: ROUNDED is a quarter turn in n
        // bands, so a SPHERE (a half turn) takes 2n at the same angular step.
        // With only n an odd-nseg sphere never reaches full radius -- nseg=5
        // peaks at 0.951 -- and four families of SURF face ids overflow the
        // numbering. Must match d3d.py's rings().
        out = [];
        const m = 2 * n;
        for (let k = 0; k <= m; k++) {
          const t = k / m;
          out.push([za + (zb - za) * t, Math.sqrt(Math.max(0, 1 - (2 * t - 1) * (2 * t - 1)))]);
        }
        break;
      }
      default: out = [[za, 1], [zb, 1]];
    }
    if (out[0][0] < out[out.length - 1][0]) out.reverse();
    return out;
  }
}

/**
 * Map local (u, v, w) -- polygon x, polygon y, sweep -- into object space.
 * The three axis values are a cyclic permutation, not a rotation.
 */
export function axisMap(axis, u, v, w) {
  if (axis === 3) return [u, v, w];
  if (axis === 2) return [v, w, u];
  return [w, u, v];
}

/**
 * POSN -> a 3x4 affine matrix.
 *
 * Fields 3-5 are three EULER ANGLES in radians, stored (ry, rx, rz) and applied
 * in that same order: R = Ry @ Rx @ Rz.
 *
 * They are NOT an axis-angle rotation vector. A single-axis rotation reads the
 * same either way and a mirrored pair negates the same two components under
 * both, so the common case cannot tell them apart. The distribution of the
 * COMPOUND values can: 159 parts carry exactly (180, 0, 180) degrees and a whole
 * family carries (180, 0, theta) for a dozen different theta. A rotation vector
 * built from two round turns does not land on round components, let alone pin
 * one field at exactly 180 across a family; "flip it, then turn it" does.
 *
 * A POSN is 48 bytes with all twelve fields but 24 bytes -- 1003 across the
 * corpus -- when the scale is identity and was omitted. Those short records
 * still carry a real position and often a real rotation; rejecting them as if
 * they were 2D FEAT POSNs dropped every one of those parts at the model origin.
 */
export function posnMatrix(chunk) {
  if (!chunk || chunk.data.byteLength < 24) return identity();
  const d = chunk.data;
  const v = [];
  const n = Math.min(d.byteLength >> 2, 12);
  for (let i = 0; i < n; i++) v.push(fp(d, i * 4));
  while (v.length < 9) v.push(0);      // short form: position + rotation only,
  while (v.length < 12) v.push(1);     // scale omitted because it is identity
  const R = eulerMatrix(v[3], v[4], v[5]);
  const S = [v[9], v[10], v[11]];
  const M = [[0, 0, 0, v[0]], [0, 0, 0, v[1]], [0, 0, 0, v[2]]];
  for (let r = 0; r < 3; r++) for (let c = 0; c < 3; c++) M[r][c] = R[r][c] * S[c];
  return M;
}

/** Ry @ Rx @ Rz, angles in radians -- the POSN field order. */
export function eulerMatrix(ry, rx, rz) {
  const cx = Math.cos(rx), sx = Math.sin(rx);
  const cy = Math.cos(ry), sy = Math.sin(ry);
  const cz = Math.cos(rz), sz = Math.sin(rz);
  const X = [[1, 0, 0], [0, cx, -sx], [0, sx, cx]];
  const Y = [[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]];
  const Z = [[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]];
  return mat3(mat3(Y, X), Z);
}

const identity = () => [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0]];
function mat3(A, B) {
  const C = [[0, 0, 0], [0, 0, 0], [0, 0, 0]];
  for (let i = 0; i < 3; i++) for (let j = 0; j < 3; j++) {
    let s = 0; for (let k = 0; k < 3; k++) s += A[i][k] * B[k][j];
    C[i][j] = s;
  }
  return C;
}
/** Compose two 3x4 affine matrices. */
export function compose(A, B) {
  const C = [[0, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0]];
  for (let i = 0; i < 3; i++) {
    for (let j = 0; j < 3; j++) {
      let s = 0; for (let k = 0; k < 3; k++) s += A[i][k] * B[k][j];
      C[i][j] = s;
    }
    let s = A[i][3];
    for (let k = 0; k < 3; k++) s += A[i][k] * B[k][3];
    C[i][3] = s;
  }
  return C;
}
export function apply(M, p) {
  return [
    M[0][0] * p[0] + M[0][1] * p[1] + M[0][2] * p[2] + M[0][3],
    M[1][0] * p[0] + M[1][1] * p[1] + M[1][2] * p[2] + M[1][3],
    M[2][0] * p[0] + M[2][1] * p[1] + M[2][2] * p[2] + M[2][3],
  ];
}

/** Ear clipping for a simple polygon. */
export function triangulate(pts) {
  const n = pts.length;
  if (n < 3) return [];
  let idx = [...Array(n).keys()];
  let a2 = 0;
  for (let i = 0; i < n; i++) {
    const j = (i + 1) % n;
    a2 += pts[i][0] * pts[j][1] - pts[j][0] * pts[i][1];
  }
  if (a2 < 0) idx.reverse();
  const cr = (o, a, b) => (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]);
  const inside = (p, a, b, c) => {
    const d1 = cr(a, b, p), d2 = cr(b, c, p), d3 = cr(c, a, p);
    const neg = d1 < 0 || d2 < 0 || d3 < 0, pos = d1 > 0 || d2 > 0 || d3 > 0;
    return !(neg && pos);
  };
  const tris = [];
  let guard = 0;
  while (idx.length > 3 && guard++ < 4 * n * n) {
    let clipped = false;
    for (let k = 0; k < idx.length; k++) {
      const i0 = idx[(k - 1 + idx.length) % idx.length], i1 = idx[k], i2 = idx[(k + 1) % idx.length];
      const a = pts[i0], b = pts[i1], c = pts[i2];
      if (cr(a, b, c) <= 0) continue;
      if (idx.some((j) => j !== i0 && j !== i1 && j !== i2 && inside(pts[j], a, b, c))) continue;
      tris.push([i0, i1, i2]);
      idx.splice(k, 1);
      clipped = true;
      break;
    }
    if (!clipped) break;
  }
  if (idx.length === 3) tris.push([idx[0], idx[1], idx[2]]);
  return tris;
}

/** Punch one polygon to 0 in `mask`, even-odd, pixel centres. Mirrors
 *  d3d._fill_polygon — each polygon is rasterised INDEPENDENTLY and OR-ed in,
 *  because throwing every polygon's crossings into one even-odd pass would make
 *  two overlapping holes cancel back to solid, and overlapping decorations are
 *  ordinary here (a bezel round a screen, a frame round a picture). */
function fillPolygon(mask, poly, w, h) {
  const n = poly.length;
  if (n < 3) return;
  let lo = Infinity, hi = -Infinity;
  for (const p of poly) { if (p[1] < lo) lo = p[1]; if (p[1] > hi) hi = p[1]; }
  const y0 = Math.max(0, Math.floor(lo - 0.5));
  const y1 = Math.min(h - 1, Math.ceil(hi + 0.5));
  for (let y = y0; y <= y1; y++) {
    const yc = y + 0.5;
    const xs = [];
    for (let i = 0; i < n; i++) {
      const [ax, ay] = poly[i], [bx, by] = poly[(i + 1) % n];
      if ((ay <= yc) !== (by <= yc)) xs.push(ax + (yc - ay) / (by - ay) * (bx - ax));
    }
    if (!xs.length) continue;
    xs.sort((p, q) => p - q);
    for (let i = 0; i + 1 < xs.length; i += 2) {
      let a = Math.ceil(xs[i] - 0.5), b = Math.floor(xs[i + 1] - 0.5);
      if (a < 0) a = 0;
      if (b > w - 1) b = w - 1;
      for (let x = a; x <= b; x++) mask[y * w + x] = 0;
    }
  }
}

/**
 * Per-face opening stencils, and the UVs that address them. Mirrors
 * d3d.face_masks.
 *
 * A face carrying transparent (alpha 0) or translucent (alpha 128) decorations
 * gets a small bitmap in its OWN 2D frame: 255 where the face is solid, 0 where
 * an opening has been punched. The geometry is left completely untouched.
 *
 * Translucent decorations punch the stencil too — the face has to be OPEN there
 * so what lies behind the wall shows through, and the pane itself is drawn back
 * into the opening as its own translucent mesh by surfaceFeatures. That is why
 * the stencil only ever needs to be binary.
 *
 * -> { masks: Map(fid -> {w, h, a}), uv: [per-triangle [[u,v]x3] | null] } | null
 */
export function faceMasks(prsm, verts, faces, ids, poly) {
  if (!ids) return null;
  const holes = new Map();
  for (const surf of prsm.kids('SURF')) {
    const fid = u16(surf.hdr, 0);
    for (const feat of surf.kids('FEAT')) {
      const col = feat.kid('COLR');
      if (!col || col.data.byteLength < 4) continue;
      const a = col.data.getUint8(0);
      if (a !== 0 && a !== 128) continue;
      const p2 = featPolygon(feat);
      if (!p2 || p2.length < 3) continue;
      if (!holes.has(fid)) holes.set(fid, []);
      holes.get(fid).push([p2, featTransform(feat)]);
    }
  }
  if (!holes.size) return null;

  const appn = appFaceNormals(poly);
  const byFace = new Map();
  ids.forEach((f, i) => { if (!byFace.has(f)) byFace.set(f, []); byFace.get(f).push(i); });

  const masks = new Map();
  const uv = new Array(faces.length).fill(null);
  for (const [fid, cuts] of holes) {
    const triI = byFace.get(fid);
    if (!triI) continue;
    const tris = triI.map((i) => faces[i]);
    const fr = faceFrame(verts, tris, appn.get(fid));
    if (!fr) continue;
    const { origin, u, v } = fr;
    const idx = [...new Set(tris.flat())];
    let u0 = Infinity, u1 = -Infinity, v0 = Infinity, v1 = -Infinity;
    for (const i of idx) {
      const a = dot(verts[i], u), b = dot(verts[i], v);
      if (a < u0) u0 = a; if (a > u1) u1 = a;
      if (b < v0) v0 = b; if (b > v1) v1 = b;
    }
    const du = u1 - u0, dv = v1 - v0;
    if (du < 1e-6 || dv < 1e-6) continue;
    const w = Math.min(options.maskMax, Math.max(8, Math.round(du * options.maskPxPerInch)));
    const h = Math.min(options.maskMax, Math.max(8, Math.round(dv * options.maskPxPerInch)));
    const mask = new Uint8Array(w * h).fill(255);
    const cu = dot(origin, u), cv = dot(origin, v);
    for (const [p2, tr] of cuts) {
      const [tx, ty, th, sx, sy] = tr;
      const ct = Math.cos(th), st = Math.sin(th);
      fillPolygon(mask, p2.map(([x, y]) => [
        ((cu + ct * (x * sx) - st * (y * sy) + tx) - u0) / du * w,
        ((cv + st * (x * sx) + ct * (y * sy) + ty) - v0) / dv * h,
      ]), w, h);
    }
    let open = false;
    for (let i = 0; i < mask.length; i++) if (!mask[i]) { open = true; break; }
    if (!open) continue;                       // every opening missed the face
    masks.set(fid, { w, h, a: mask });
    for (const i of triI) {
      uv[i] = faces[i].map((j) => [(dot(verts[j], u) - u0) / du,
                                   (dot(verts[j], v) - v0) / dv]);
    }
  }
  return masks.size ? { masks, uv } : null;
}

/**
 * Build one PRSM. Returns {verts, faces, faceIds, poly} in object space.
 *
 * Face numbering, which SURF indexes into:
 *   0                  cap at the HIGH end of the sweep
 *   1 .. bands*n       side faces, band-major, polygon edges traversed BACKWARDS
 *   bands*n + 1        cap at the LOW end
 *   bands*n + 2 + j    face created by SLIC cut j
 */
/** The outline of a face, from its triangles: an interior edge is shared by two
 *  triangles, a boundary edge by one. -> ordered vertex indices, or null. */
export function faceBoundary(tris) {
  const use = new Map();
  const key = (a, b) => `${a},${b}`;
  for (const t of tris) {
    for (const [a, b] of [[t[0], t[1]], [t[1], t[2]], [t[2], t[0]]]) {
      use.set(key(a, b), (use.get(key(a, b)) || 0) + 1);
    }
  }
  const nxt = new Map();
  for (const [k, n] of use) {
    const [a, b] = k.split(',').map(Number);
    if (n !== 1 || use.get(key(b, a))) continue;
    if (nxt.has(a)) return null;
    nxt.set(a, b);
  }
  if (!nxt.size) return null;
  const start = nxt.keys().next().value;
  const loop = [start];
  let cur = nxt.get(start);
  while (cur !== undefined && cur !== start && loop.length <= nxt.size) {
    loop.push(cur);
    cur = nxt.get(cur);
  }
  return cur === start && loop.length === nxt.size ? loop : null;
}

/** Ear-clip a polygon with holes, bridging each hole into the outline.
 *  Mirrors d3d.triangulate_with_holes -- see there for why the shared
 *  `triangulate` cannot be reused (bridging duplicates vertices). */
export function triangulateWithHoles(outer, holes) {
  const area = (p) => {
    let a = 0;
    for (let i = 0; i < p.length; i++) {
      const j = (i + 1) % p.length;
      a += p[i][0] * p[j][1] - p[j][0] * p[i][1];
    }
    return a / 2;
  };
  const rings = [outer.slice()], idxs = [outer.map((_, i) => i)];
  let base = outer.length;
  for (const h of holes) {
    rings.push(h.slice());
    idxs.push(h.map((_, i) => base + i));
    base += h.length;
  }
  if (area(rings[0]) < 0) { rings[0].reverse(); idxs[0].reverse(); }
  for (let i = 1; i < rings.length; i++) {
    if (area(rings[i]) > 0) { rings[i].reverse(); idxs[i].reverse(); }
  }
  const orient = (a, b, c) => {
    const v = (b[0]-a[0])*(c[1]-a[1]) - (b[1]-a[1])*(c[0]-a[0]);
    return Math.abs(v) < 1e-9 ? 0 : (v > 0 ? 1 : -1);
  };
  const segHits = (p, q, ring, skip) => {
    for (let i = 0; i < ring.length; i++) {
      const j = (i + 1) % ring.length;
      if (i === skip || j === skip) continue;
      const a = ring[i], b = ring[j];
      const o1 = orient(p, q, a), o2 = orient(p, q, b);
      const o3 = orient(a, b, p), o4 = orient(a, b, q);
      if (o1 !== o2 && o3 !== o4 && o1 && o2 && o3 && o4) return true;
    }
    return false;
  };
  let ring = rings[0], ridx = idxs[0];
  // rightmost hole first -- see d3d.py
  const order = [...rings.keys()].slice(1)
    .sort((a, b) => Math.max(...rings[b].map((p) => p[0])) - Math.max(...rings[a].map((p) => p[0])));
  for (const hi of order) {
    const hole = rings[hi], hidx = idxs[hi];
    let m = 0;
    for (let i = 1; i < hole.length; i++) if (hole[i][0] > hole[m][0]) m = i;
    const hp = hole[m];
    const cand = [...ring.keys()].sort((a, b) =>
      ((ring[a][0]-hp[0])**2 + (ring[a][1]-hp[1])**2) - ((ring[b][0]-hp[0])**2 + (ring[b][1]-hp[1])**2));
    let bj = null;
    for (const j of cand) {
      if (ring[j][0] < hp[0] - 1e-9) continue;
      if (!segHits(hp, ring[j], ring, j)) { bj = j; break; }
    }
    if (bj === null) bj = cand[0];
    ring = ring.slice(0, bj + 1).concat(hole.slice(m), hole.slice(0, m + 1), ring.slice(bj));
    ridx = ridx.slice(0, bj + 1).concat(hidx.slice(m), hidx.slice(0, m + 1), ridx.slice(bj));
  }
  const n = ring.length;
  if (n < 3) return [];
  const live = [...Array(n).keys()];
  const same = (p, q) => Math.abs(p[0]-q[0]) < 1e-9 && Math.abs(p[1]-q[1]) < 1e-9;
  const inside = (p, a, b, c) => {
    if (same(p, a) || same(p, b) || same(p, c)) return false;
    const d1 = (b[0]-a[0])*(p[1]-a[1])-(b[1]-a[1])*(p[0]-a[0]);
    const d2 = (c[0]-b[0])*(p[1]-b[1])-(c[1]-b[1])*(p[0]-b[0]);
    const d3 = (a[0]-c[0])*(p[1]-c[1])-(a[1]-c[1])*(p[0]-c[0]);
    return (d1 > 1e-9 && d2 > 1e-9 && d3 > 1e-9) || (d1 < -1e-9 && d2 < -1e-9 && d3 < -1e-9);
  };
  const out = [];
  let guard = 0;
  while (live.length > 3 && guard < 4 * n * n) {
    guard++;
    let cut = false;
    for (let k = 0; k < live.length; k++) {
      const i0 = live[(k - 1 + live.length) % live.length], i1 = live[k],
            i2 = live[(k + 1) % live.length];
      const a = ring[i0], b = ring[i1], c = ring[i2];
      if ((b[0]-a[0])*(c[1]-a[1]) - (b[1]-a[1])*(c[0]-a[0]) <= 1e-12) continue;
      let bad = false;
      for (const j of live) {
        if (j === i0 || j === i1 || j === i2) continue;
        if (inside(ring[j], a, b, c)) { bad = true; break; }
      }
      if (bad) continue;
      out.push([i0, i1, i2]);
      live.splice(k, 1);
      cut = true;
      break;
    }
    if (!cut) break;
  }
  if (live.length === 3) out.push([live[0], live[1], live[2]]);
  return out.map(([a, b, c]) => [ridx[a], ridx[b], ridx[c]]);
}

export function prismMesh(prsm) {
  const pc = prsm.kid('POLY');
  if (!pc || pc.data.byteLength < 32) return null;
  const poly = new Poly(pc);
  const base = poly.verts;
  if (base.length < 3) return null;
  const rings = poly.rings();
  const n = base.length;
  const nband = rings.length - 1;

  // An oblique sweep: each CAP carries its own in-plane offset -- skewA at `za`,
  // skewB at `zb` -- and a ring between them takes the linear blend.
  const sa = options.applySkew === false ? [0, 0] : poly.skewA;
  const sb = options.applySkew === false ? [0, 0] : poly.skewB;
  const span = poly.zb - poly.za;
  const flat = sa[0] === 0 && sa[1] === 0 && sb[0] === 0 && sb[1] === 0;
  const shift = (z) => {
    if (flat) return [0, 0, 0];
    const t = span === 0 ? 0 : (z - poly.za) / span;
    return [sa[0] + (sb[0] - sa[0]) * t, sa[1] + (sb[1] - sa[1]) * t, 0];
  };

  const verts = [], ringIdx = [];
  for (const [z, s] of rings) {
    const [dx, dy, dz] = shift(z);
    if (s === 0) { ringIdx.push([verts.length]); verts.push([dx, dy, z + dz]); }
    else {
      const start = verts.length;
      for (const [x, y] of base) verts.push([x * s + dx, y * s + dy, z + dz]);
      ringIdx.push([...Array(n).keys()].map((i) => start + i));
    }
  }

  // winding of the stored polygon decides which way the side quads face
  let sarea = 0;
  for (let i = 0; i < n; i++) {
    const j = (i + 1) % n;
    sarea += base[i][0] * base[j][1] - base[j][0] * base[i][1];
  }
  const ccw = sarea > 0;

  // A side face is named by the vertex its edge ARRIVES at, plus one: edge
  // v_j -> v_j+1 is face (j+1)+1, and face 1 is the edge that closes the
  // polygon back onto vertex 0. Must match d3d.py's side_id.
  // Cap count by profile, straight from the application (0x57fb): straight 2,
  // pointed 1, rounded 1, diamond 0, sphere 0; and with one cap, 0x5929 puts it
  // at the HIGH end when za <= zb. See claude-explore/DISASSEMBLY.md.
  const ncap = poly.profile === STRAIGHT ? 2
             : (poly.profile === POINTED || poly.profile === ROUNDED) ? 1 : 0;
  const hasHigh = ncap === 2 || (ncap === 1 && poly.za <= poly.zb);
  // The side faces are 1-based ONLY when a high cap exists to be face 0:
  // 0x59c5 computes n*band + edge and adds one only in that case. Sphere and
  // diamond have no caps, so their sides start at 0. Must match d3d.py.
  const first = hasHigh ? 1 : 0;
  const sideId = (r, i) => first + r * n + ((i + 1) % n);
  const faces = [], fids = [];
  for (let r = 0; r < nband; r++) {
    const lo = ringIdx[r], hi = ringIdx[r + 1];   // lo is the HIGHER end
    if (lo.length === 1) {
      for (let i = 0; i < n; i++) {
        const j = (i + 1) % n;
        faces.push(ccw ? [lo[0], hi[j], hi[i]] : [lo[0], hi[i], hi[j]]); fids.push(sideId(r, i));
      }
    } else if (hi.length === 1) {
      for (let i = 0; i < n; i++) {
        const j = (i + 1) % n;
        faces.push(ccw ? [lo[i], hi[0], lo[j]] : [lo[i], lo[j], hi[0]]); fids.push(sideId(r, i));
      }
    } else {
      for (let i = 0; i < n; i++) {
        const j = (i + 1) % n;
        faces.push(ccw ? [lo[i], hi[j], lo[j]] : [lo[i], lo[j], hi[j]]); fids.push(sideId(r, i));
        faces.push(ccw ? [lo[i], hi[i], hi[j]] : [lo[i], hi[j], hi[i]]); fids.push(sideId(r, i));
      }
    }
  }
  const nbase = ncap + nband * n;         // caps + sides; the low cap is the last
  const cap0 = 0, cap1 = nbase - 1;
  // triangulate() normalises to CCW in polygon space: the high cap faces
  // +sweep as written, the low cap is the reverse
  const tris = triangulate(base);
  if (ringIdx[0].length > 1) for (const [x, y, z] of tris) { faces.push([ringIdx[0][x], ringIdx[0][y], ringIdx[0][z]]); fids.push(cap0); }
  const last = ringIdx[ringIdx.length - 1];
  if (last.length > 1) for (const [x, y, z] of tris) { faces.push([last[x], last[z], last[y]]); fids.push(cap1); }

  // Winding is consistent by construction; a negative signed volume just means
  // the shell came out inside-out, so flip it wholesale. This replaces a
  // per-face centroid test, which mis-orients faces on long or concave prisms.
  let vol = 0;
  for (const [i0, i1, i2] of faces) {
    const A = verts[i0], B = verts[i1], C = verts[i2];
    vol += (A[0] * (B[1] * C[2] - B[2] * C[1]) + A[1] * (B[2] * C[0] - B[0] * C[2]) + A[2] * (B[0] * C[1] - B[1] * C[0])) / 6;
  }
  if (vol < 0) for (let k = 0; k < faces.length; k++) { const f = faces[k]; faces[k] = [f[0], f[2], f[1]]; }

  let V = verts.map(([u, v, w]) => axisMap(poly.axis, u, v, w));
  let F = faces, ids = fids;

  // SLIC planes are in OBJECT space, applied in order
  const sl = prsm.kid('SLIC');
  if (options.applySlic && sl && sl.data.byteLength > 2) {
    const nrec = Math.floor((sl.data.byteLength - 2) / 16);
    for (let i = 0; i < nrec; i++) {
      const o = 2 + i * 16;
      const nn = [fp(sl.data, o), fp(sl.data, o + 4), fp(sl.data, o + 8)];
      const dd = fp(sl.data, o + 12);
      if (!nn.some((x) => Math.abs(x) > 1e-9)) continue;
      const r = clipMesh(V, F, nn, dd, { keepNegative: options.slicKeepNeg, ids, newId: nbase + i });
      V = r.verts; F = r.faces; ids = r.ids;
      if (!F.length) break;
    }
  }
  if (options.holeMode === 'geom') ({ V, F, ids } = cutHoles(prsm, V, F, ids, poly));
  ({ verts: V, faces: F } = compact(V, F));
  return { verts: V, faces: F, faceIds: ids, poly };
}

/** Subtract every fully transparent FEAT from the face it sits on.
 *  A zero-alpha decoration is an OPENING -- the only subtractive operation the
 *  format has. Mirrors d3d._cut_holes. */
function cutHoles(prsm, V, F, ids, poly) {
  const holes = new Map();
  for (const surf of prsm.kids('SURF')) {
    const fid = u16(surf.hdr, 0);
    for (const feat of surf.kids('FEAT')) {
      const col = feat.kid('COLR');
      // Both Transparent (0) and Translucent (128) open the face: a translucent
      // window must show what is BEHIND the wall, not blend with the wall
      // itself. The pane is then drawn back into the opening by surfaceFeatures.
      const fa = col && col.data.byteLength >= 4 ? col.data.getUint8(0) : 255;
      if (!col || col.data.byteLength < 4 || (fa !== 0 && fa !== 128)) continue;
      const p2 = featPolygon(feat);
      if (!p2 || p2.length < 3) continue;
      if (!holes.has(fid)) holes.set(fid, []);
      holes.get(fid).push([p2, featTransform(feat)]);
    }
  }
  if (!holes.size) return { V, F, ids };
  const byFace = new Map();
  F.forEach((t, i) => {
    const k = ids[i];
    if (!byFace.has(k)) byFace.set(k, []);
    byFace.get(k).push(i);
  });
  const appn = appFaceNormals(poly);
  const verts = V.slice(), drop = new Set(), add = [], addId = [];
  for (const [fid, cuts] of holes) {
    const triI = byFace.get(fid);
    if (!triI) continue;
    const tris = triI.map((i) => F[i]);
    const loop = faceBoundary(tris);
    const fr = faceFrame(verts, tris, appn.get(fid));
    if (!loop || !fr) continue;
    const { origin, u, v, nrm } = fr;
    const outer = loop.map((i) => [dot(verts[i], u), dot(verts[i], v)]);
    const cu = dot(origin, u), cv = dot(origin, v);
    const hs = cuts.map(([p2, tr]) => {
      const [tx, ty, th, sx, sy] = tr;
      const ct = Math.cos(th), st = Math.sin(th);
      return p2.map(([x, y]) => [cu + ct * (x * sx) - st * (y * sy) + tx,
                                 cv + st * (x * sx) + ct * (y * sy) + ty]);
    });
    let tt;
    try { tt = triangulateWithHoles(outer, hs); } catch (e) { continue; }
    if (!tt.length) continue;
    const plane = dot(verts[loop[0]], nrm);
    const newIdx = loop.slice();
    for (const h of hs) {
      for (const [a, b] of h) {
        verts.push(add3(add3(mul(u, a), mul(v, b)), mul(nrm, plane)));
        newIdx.push(verts.length - 1);
      }
    }
    for (const [a, b, c] of tt) { add.push([newIdx[a], newIdx[b], newIdx[c]]); addId.push(fid); }
    for (const i of triI) drop.add(i);
  }
  if (!add.length) return { V: verts, F, ids };
  const keep = F.map((_, i) => i).filter((i) => !drop.has(i));
  return { V: verts, F: keep.map((i) => F[i]).concat(add),
           ids: keep.map((i) => ids[i]).concat(addId) };
}

/**
 * Drop vertices no face refers to.
 *
 * The clipper appends the vertices it creates and stops referencing the ones it
 * cut away. Harmless for drawing -- nothing indexes them -- but poisonous for
 * anything that measures: a clipped prism's array still held the geometry that
 * was removed, so its bounding box was the box of the UNCUT prism. That inflated
 * the manifest bounds and the explorer's ground placement, which is why cut
 * objects hovered above the floor instead of resting on it.
 */
function compact(verts, faces) {
  const used = new Set();
  for (const f of faces) for (const i of f) used.add(i);
  if (used.size === verts.length) return { verts, faces };
  const order = [...used].sort((a, b) => a - b);
  const remap = new Map(order.map((o, n) => [o, n]));
  return { verts: order.map((i) => verts[i]), faces: faces.map((f) => f.map((i) => remap.get(i))) };
}

/**
 * SURF face-index -> RGB override. A SURF can carry a COLR that RECOLOURS its
 * face; 548 of them across the galleries were previously ignored.
 *
 * Its COLR is NOT laid out like a PRSM's -- there is a 2-byte prefix first:
 *     6 B   prefix 1 or 3, then ONE (a,r,g,b)     96 records
 *    10 B   prefix 2,      then TWO (a,r,g,b)    452 records
 * so `00 02 00 ff ff ff 00 ff ff ff` is white, not the dark blue you get by
 * reading bytes 1-3 as a PRSM colour. The prefix looks like the same
 * outside/inside/both selector FEAT uses, one-based.
 */
export function surfColours(prsm) {
  const out = new Map();
  for (const surf of prsm.kids('SURF')) {
    const c = surf.kid('COLR');
    if (!c || c.data.byteLength < 6) continue;
    // Each record is (alpha, r, g, b) and with TWO of them the SECOND is the
    // visible one: record 1 is the INSIDE of the surface and its alpha is 0 in
    // every two-record colour in the corpus. The RGBs agree except on 50 faces
    // -- INDYCAR's wing end plate is one, inside red and outside white, and
    // reading record 1 painted it red where the app shows white.
    const d = c.data;
    out.set(u16(surf.hdr, 0), d.byteLength >= 10
      ? [d.getUint8(7), d.getUint8(8), d.getUint8(9)]
      : [d.getUint8(3), d.getUint8(4), d.getUint8(5)]);
  }
  return out;
}

/**
 * The texture table of the file currently being walked. A gallery holds one
 * TXTB for the whole .WLB, so a clip built on its own still has to be told
 * about it -- see setTextures / loadClip.
 */
export let TEXTURES = new Map();
export function setTextures(t) { TEXTURES = t || new Map(); }

/**
 * Per-TRIANGLE UVs for a textured prism.
 *
 * A prism is textured as a whole (PLTX) or per face (SUTX), and every face has
 * its own frame, so the UVs cannot live on the vertices -- two faces sharing a
 * corner want different coordinates there. They are INCHES along the face's own
 * u/v axes divided by the tile size from TXST, so a brick wall repeats at its
 * authored physical size instead of being stretched once across whatever face
 * it lands on.
 * -> { id, uv: [ [[u,v],[u,v],[u,v]] | null, ... ] } or null
 */
export function prismUVs(prsm, verts, faces, ids, poly) {
  if (!TEXTURES.size || !ids) return null;
  const { whole, faces: perface } = assignments(prsm, u16);
  if (whole === null && !perface.size) return null;
  const appn = appFaceNormals(poly);
  const byFace = new Map();
  ids.forEach((f, i) => { if (!byFace.has(f)) byFace.set(f, []); byFace.get(f).push(i); });
  const uv = new Array(faces.length).fill(null);
  const tids = new Array(faces.length).fill(null);
  let any = false;
  for (const [fid, triI] of byFace) {
    // A per-face SUTX OVERRIDES the prism's PLTX, and a prism may wear several
    // bitmaps at once -- 13 of the 229 textured prisms in the corpus do. Taking
    // one id for the whole prism painted the rest wrong or left them bare.
    const tid = perface.has(fid) ? perface.get(fid) : whole;
    if (tid === null || tid === undefined) continue;
    const ent = TEXTURES.get(tid);
    if (!ent) continue;
    let [tu, tv] = ent.tile || [64, 64];
    if (!(tu > 0.01)) tu = 64;
    if (!(tv > 0.01)) tv = 64;
    const fr = faceFrame(verts, triI.map((i) => faces[i]), appn.get(fid));
    if (!fr) continue;
    for (const i of triI) {
      uv[i] = faces[i].map((j) => [dot(verts[j], fr.u) / tu, dot(verts[j], fr.v) / tv]);
      tids[i] = tid;
      any = true;
    }
  }
  return any ? { tids, uv } : null;
}

/**
 * SURF face-index -> OPACITY of the visible record: 255, 128 or 0.
 *
 * The glass in `GLASHOUS` is here: its walls carry
 * `00 02 | 00 ff ff ff | 80 ff ff ff` -- record 2 alpha 0x80, translucent
 * white. The application calls the three states Opaque, Translucent (drawn as a
 * checkerboard dither) and Transparent (an open face).
 *
 * Ground truth: the Virtus VRML exporter writes `transparency 0.0000 / 0.4980 /
 * 1.0000` per face, and the counts match exactly -- KITCHEN 1 open face,
 * BEACHCBN 1, DEALEY 3 open and 3 translucent. `JENSONIN`'s 272 open faces are
 * the window panes of a Victorian house, not unset defaults.
 */
export function surfAlphas(prsm) {
  const out = new Map();
  for (const surf of prsm.kids('SURF')) {
    const c = surf.kid('COLR');
    if (!c || c.data.byteLength < 6) continue;
    const d = c.data;
    out.set(u16(surf.hdr, 0), d.byteLength >= 10 ? d.getUint8(6) : d.getUint8(2));
  }
  return out;
}

/** A prism's own opacity: the second COLR record's alpha. */
export function prismAlpha(prsm) {
  const c = prsm.kid('COLR');
  return c && c.data.byteLength >= 8 ? c.data.getUint8(4) : 255;
}

/** A prism's colour: the SECOND of its COLR's two (alpha, r, g, b) records.
 *  Record 1 is the inside face -- alpha 0 in all 18,038 of them. */
export function colorOf(prsm) {
  const c = prsm.kid('COLR');
  if (!c || c.data.byteLength < 8) return [170, 170, 170];
  return [c.data.getUint8(5), c.data.getUint8(6), c.data.getUint8(7)];
}

// ---- SURF / FEAT ----

/**
 * A 2D frame for one face: drop the axis the normal is most aligned with,
 * keep the other two in ascending axis order, origin at the face's minimum
 * corner. Feature coordinates are expressed in this frame.
 */
/**
 * Face normals the way the APPLICATION computes them (`seg28:0x5a59`).
 *
 * For a side face the app takes the edge ARRIVING at vertex si and uses its raw
 * perpendicular -- un-normalised, with no component along the sweep -- then
 * permutes it by the sweep axis. The binary stores that as three INT16, and the
 * quantisation is the rule, not an implementation detail: a face whose
 * perpendicular is (-137.3494, -0.2431) stores as (-137, 0) and is therefore
 * exactly axis-aligned as far as the app is concerned.
 *
 * That is what decides whether a face counts as horizontal, and it has to be:
 * no angular tolerance can work, because STAWAGON's roof is 0.1 degrees off
 * horizontal and wants the horizontal fallback while SPACSTAT's facets are 0.6
 * degrees off and want the azimuth frame. Quantisation separates them exactly.
 *
 * -> Map of face id -> un-normalised object-space vector.
 */
export function appFaceNormals(poly) {
  const out = new Map();
  const V = poly.verts, n = V.length;
  if (n < 3) return out;
  const rings = poly.rings();
  const nband = rings.length - 1;
  const ncap = poly.profile === STRAIGHT ? 2
             : (poly.profile === POINTED || poly.profile === ROUNDED) ? 1 : 0;
  const hasHigh = ncap === 2 || (ncap === 1 && poly.za <= poly.zb);
  const hasLow = ncap === 2 || (ncap === 1 && !hasHigh);
  const first = hasHigh ? 1 : 0;
  if (hasHigh) out.set(0, axisMap(poly.axis, 0, 0, 1));
  if (hasLow) out.set(ncap + nband * n - 1, axisMap(poly.axis, 0, 0, -1));
  for (let band = 0; band < nband; band++) {
    for (let j = 0; j < n; j++) {
      const a = V[(j - 1 + n) % n], b = V[j];
      const nx = Math.trunc(b[1] - a[1]), ny = Math.trunc(a[0] - b[0]);
      if (nx === 0 && ny === 0) continue;          // edge under one unit
      out.set(first + band * n + j, axisMap(poly.axis, nx, ny, 0));
    }
  }
  return out;
}

export function faceFrame(verts, tris, normal) {
  const idx = [...new Set(tris.flat())].sort((a, b) => a - b);   // match d3d.py
  // Area-weighted sum over the whole face, not the single largest triangle:
  // one triangle's cross product carries enough float noise to flip the
  // dominant-axis test below on a face sitting at exactly 45 degrees.
  let best = 0, nbest = null;
  const acc = [0, 0, 0];
  for (const t of tris) {
    const cr = cross(sub(verts[t[1]], verts[t[0]]), sub(verts[t[2]], verts[t[0]]));
    acc[0] += cr[0]; acc[1] += cr[1]; acc[2] += cr[2];
    const l = len(cr);
    if (l > best) { best = l; nbest = [cr[0] / l, cr[1] / l, cr[2] / l]; }
  }
  const la = len(acc);
  let nrm = la > 1e-9 ? [acc[0] / la, acc[1] / la, acc[2] / la] : nbest;
  if (!nrm || best < 1e-9) return null;
  const ctr = [0, 0, 0];
  for (const v of verts) { ctr[0] += v[0] / verts.length; ctr[1] += v[1] / verts.length; ctr[2] += v[2] / verts.length; }
  const fc = [0, 0, 0];
  for (const i of idx) { fc[0] += verts[i][0] / idx.length; fc[1] += verts[i][1] / idx.length; fc[2] += verts[i][2] / idx.length; }
  if (dot(nrm, sub(fc, ctr)) < 0) nrm = mul(nrm, -1);
  // The app's own integer-quantised normal, used ONLY to choose the in-plane
  // direction below -- never as the face's plane. The face's vertices are
  // coplanar with respect to the TRUE normal, not the quantised one, so using
  // it as the plane makes the origin depend on which vertex you measure from.
  let nq = null;
  if (normal) {
    const ln = len(normal);
    if (ln > 1e-9) nq = mul(dot(normal, nrm) < 0 ? mul(normal, -1) : normal, 1 / ln);
  }

  // Break an exact tie towards the LOWEST axis index, so that two mirrored
  // faces get mirrored frames instead of transposed ones -- see d3d.py.
  let mx = Math.max(Math.abs(nrm[0]), Math.abs(nrm[1]), Math.abs(nrm[2]));
  let drop = 0;
  for (let i = 0; i < 3; i++) if (Math.abs(nrm[i]) >= mx - 1e-6) { drop = i; break; }
  const ax = [0, 1, 2].filter((i) => i !== drop);
  let u = [0, 0, 0]; u[ax[0]] = 1;
  let v = [0, 0, 0]; v[ax[1]] = 1;
  // The AZIMUTH frame: u = n x up, the horizontal direction lying in the face,
  // v the one going up it -- so a decoration's x runs ACROSS a wall and its y
  // runs UP it, at whatever angle the wall is turned. On a world-aligned face
  // this is identical to the world-axis pair above, which is why that rule
  // survived so long; on a facet turned 22.5 degrees it is not, which is why
  // exactly half of SPACSTAT's window rows flew off into space. A HORIZONTAL
  // face degenerates the cross product and keeps the world-axis pair.
  if (options.faceFrame === 'azim') {
    // `up x n`, NOT `n x up`. The two differ by a 180-degree turn about the
    // normal, and only this order reproduces the old world-axis frame -- hand
    // flip included -- on every axis-aligned face. Backwards, every decoration
    // lands on the right face upside down and at the wrong end of it, and no
    // containment oracle can see it: a 180-degree turn moves the origin to the
    // opposite corner and fits exactly as well.
    // 'azim_rev' is the wrong order, kept switchable for A/B measurement.
    const na = nq || nrm;
    const h = options.faceFrame === 'azim_rev' ? cross(na, [0, 0, 1]) : cross([0, 0, 1], na);
    if (len(h) > 1e-6) { u = norm(h); v = cross(nrm, u); }
  }
  u = sub(u, mul(nrm, dot(u, nrm)));
  if (len(u) < 1e-9) return null;
  u = norm(u);
  v = sub(sub(v, mul(nrm, dot(v, nrm))), mul(u, dot(v, u)));
  if (len(v) < 1e-9) return null;
  v = norm(v);
  // Make (u, v, nrm) RIGHT-HANDED. u and v come from fixed world axes, so the
  // two opposite faces of a box get the SAME pair while their normals point
  // opposite ways -- one frame right-handed, the other mirrored. A decoration
  // in the mirrored frame comes out backwards, which is why DEPARTME's two
  // escalators carry the same triangle and only one of them read correctly.
  if (dot(cross(u, v), nrm) < 0) u = mul(u, -1);
  let minU = Infinity, minV = Infinity, maxU = -Infinity, maxV = -Infinity;
  for (const i of idx) {
    const du = dot(verts[i], u), dv = dot(verts[i], v);
    minU = Math.min(minU, du); maxU = Math.max(maxU, du);
    minV = Math.min(minV, dv); maxV = Math.max(maxV, dv);
  }
  // Two in-plane origins: `origin` at the face's minimum corner, `middle` at its
  // centre. Which one a decoration wants is decided by its POSN translation --
  // see surfaceFeatures.
  const plane = mul(nrm, dot(verts[idx[0]], nrm));
  const origin = add(add(mul(u, minU), mul(v, minV)), plane);
  const middle = add(add(mul(u, (minU + maxU) / 2), mul(v, (minV + maxV) / 2)), plane);
  return { origin, u, v, nrm, middle };
}

/** 2D FEAT polygon: 4-byte header (0, class, 0, vertexCount) then N x (x, y). */
export function featPolygon(feat) {
  const pl = feat.kid('POLY');
  if (!pl || pl.data.byteLength < 4) return null;
  const b = pl.data;
  const n = b.getUint8(3);
  if (b.byteLength < 4 + n * 8) return null;
  const out = [];
  for (let i = 0; i < n; i++) out.push([fp(b, 4 + i * 8), fp(b, 8 + i * 8)]);
  return out;
}

/**
 * 2D FEAT POSN -> [tx, ty, rotation, sx, sy].
 *
 * Two lengths, and the SHORT one is a trap:
 *
 *     24 B   (x, y, rotation, ~0, sx, sy)      2194 records
 *     12 B   (x, y, rotation)                   338 records, scale implied 1
 *
 * Same omit-the-default trick the 3D POSN plays. Requiring 24 bytes returned
 * (0, 0) for every short record, so 338 decorations lost their placement and
 * piled up at their face's origin corner -- `Mac LC` and `Mac IIci` screens off
 * the side of the monitor while `Mac Quadra`, which carries full records, was
 * perfect. There is only ONE placement convention: the face's minimum corner,
 * offset by (tx, ty).
 */
export function featTransform(feat) {
  const ps = feat.kid('POSN');
  if (!ps || ps.data.byteLength < 12) return [0, 0, 0, 1, 1];
  const v = [];
  const n = Math.min(ps.data.byteLength >> 2, 6);
  for (let i = 0; i < n; i++) v.push(fp(ps.data, i * 4));
  while (v.length < 4) v.push(0);   // short form: rotation may be absent too
  while (v.length < 6) v.push(1);   // scale omitted because it is identity
  return [v[0], v[1], v[2], v[4] || 1, v[5] || 1];
}

export const FEAT_INSIDE = 0, FEAT_OUTSIDE = 1, FEAT_BOTH = 2;

/** Overlay meshes for the decorations on a prism's faces. */
export function surfaceFeatures(prsm, mesh) {
  const out = [];
  if (!mesh.faceIds) return out;
  const byFace = new Map();
  mesh.faces.forEach((t, i) => {
    const k = mesh.faceIds[i];
    if (!byFace.has(k)) byFace.set(k, []);
    byFace.get(k).push(t);
  });
  const pc = prsm.kid('POLY');
  const appn = pc ? appFaceNormals(new Poly(pc)) : new Map();
  for (const surf of prsm.kids('SURF')) {
    const fid = u16(surf.hdr, 0);
    const tris = byFace.get(fid);
    if (!tris) continue;
    const fr = faceFrame(mesh.verts, tris, appn.get(fid));
    if (!fr) continue;
    let layer = 0;
    for (const feat of surf.kids('FEAT')) {
      const side = feat.hdr ? u16(feat.hdr, 0) : FEAT_OUTSIDE;
      const poly = featPolygon(feat);
      if (!poly || poly.length < 3) continue;
      const [tx, ty, th, sx, sy] = featTransform(feat);
      const col = feat.kid('COLR');
      const rgb = col && col.data.byteLength >= 4
        ? [col.data.getUint8(1), col.data.getUint8(2), col.data.getUint8(3)] : [0, 0, 0];
      // Byte 0 of a FEAT's COLR is OPACITY, and corpus-wide it takes exactly
      // three values: 255 opaque (18,805), 128 translucent (629), 0 fully
      // transparent (468). A zero is not decoration -- the authors used it to
      // cut a HOLE through the face, which is how BEACHCBN's convertible gets
      // its open cockpit and the Silo its doorway. Drawn opaque it becomes a
      // white slab across the car's seats.
      const alpha = col && col.data.byteLength >= 4 ? col.data.getUint8(0) : 255;
      if (alpha === 0 && !options.drawHoles) continue;
      const ct = Math.cos(th), st = Math.sin(th);
      const pts2 = poly.map(([x, y]) => [ct * (x * sx) - st * (y * sy) + tx,
                                         st * (x * sx) + ct * (y * sy) + ty]);
      // ONE convention: the face's MINIMUM CORNER, offset by the FEAT's own
      // (tx, ty). A brief two-rule split was chasing 338 decorations that only
      // fitted some other way -- they were exactly the 338 short (12-byte) FEAT
      // POSNs whose translation was being discarded. See featTransform.
      const base = fr.origin;
      const pv = pts2.map(([a, b]) => add(add(base, mul(fr.u, a)), mul(fr.v, b)));
      const tri = triangulate(pv.map((p) => [dot(p, fr.u), dot(p, fr.v)]));
      if (!tri.length) continue;
      // Decorations stack: a roundel is concentric FEATs on ONE face, all
      // mutually coplanar. `layer` is their paint order within the SURF, so the
      // renderer can give each its own depth bias instead of letting them fight.
      out.push({ verts: pv, faces: tri, color: rgb, alpha, side, normal: fr.nrm,
                 isFeature: true, layer: layer++ });
    }
  }
  return out;
}

/**
 * Walk a PRSM/PGRP tree collecting world-space meshes.
 * Child transforms are ABSOLUTE -- a group's POSN is never composed onto them.
 */
const INCH = 0.0254;   // metres, the unit the geometry is normally authored in

/**
 * UNIT -> how many inches one stored unit is worth.
 *
 * UNIT is an 8-byte IEEE-754 double giving METRES PER STORED UNIT, and it is NOT
 * always an inch. 497 clips carry 0.0254 (1 in) but others carry 0.00635 (1/4
 * in), 0.003175 (1/8 in), 0.00254 (1/10 in), 0.0015875 (1/16 in) or 0.01 (1 cm).
 * Ignoring it renders those objects 4x, 8x, 10x or 16x too large. `Bar Stool` is
 * the clearest proof: 48 x 48 x 104 raw, 12 x 12 x 26 inches once divided.
 *
 * UNIT appears on ROOT, VCLP, PGRP and PRSM, but across 537 nested occurrences a
 * child never disagrees with its ancestor.
 */
export function unitScale(node) {
  const u = node && node.kid ? node.kid('UNIT') : null;
  if (u && u.data.byteLength === 8) return u.data.getFloat64(0, false) / INCH;
  return null;
}

export function collect(node, out = [], unit = null) {
  const here = unitScale(node);
  if (here !== null) unit = here;
  for (const k of node.children) {
    if (k.tag !== 'PRSM' && k.tag !== 'PGRP') continue;
    const kf = unitScale(k);
    const u = kf !== null ? kf : unit;
    let W = posnMatrix(k.kid('POSN'));
    if (u !== null && Math.abs(u - 1) > 1e-12) {
      W = W.map((row) => row.map((x) => x * u));
    }
    if (k.tag === 'PRSM') {
      const m = prismMesh(k);
      if (m) {
        const world = m.verts.map((p) => apply(W, p));
        const base = colorOf(k);
        const over = surfColours(k);
        const alph = surfAlphas(k);
        const balpha = prismAlpha(k);
        // UVs are measured in the prism's OWN space, before W is applied, so
        // they are the same whatever the object's placement or unit scale.
        const tx = options.drawTextures
          ? prismUVs(k, m.verts, m.faces, m.faceIds, m.poly) : null;
        const mk = options.holeMode === 'mask'
          ? faceMasks(k, m.verts, m.faces, m.faceIds, m.poly) : null;
        const texOf = (tid) => {
          const e = TEXTURES.get(tid);
          return e ? { id: tid, name: e.name, w: e.w, h: e.h, rgba: e.rgba } : null;
        };
        if ((over.size || alph.size || tx || mk) && m.faceIds) {   // tx: any UVs at all
          const groups = new Map();
          m.faces.forEach((tri, i) => {
            const fid = m.faceIds[i];
            const col = over.get(fid) || base;
            const a = alph.has(fid) ? alph.get(fid) : balpha;
            // A STENCILLED face is its own group: the mask is in that one
            // face's frame, so merging two masked faces into a draw call would
            // address the wrong bitmap.
            const mf = mk && mk.uv[i] ? fid : -1;
            // The TEXTURED flag is part of the key: within one prism some faces
            // carry a SUTX and others none, and a GPU cannot sample a bitmap for
            // half a draw call. Without the split the untextured faces sample
            // texel (0, 0) -- which painted MYHOUSE2's white wall dark maroon.
            // the texture ID is part of the key, not just a flag
            const tf = tx && tx.uv[i] ? tx.tids[i] : -1;
            const key = col.join(',') + ',' + a + ',' + tf + ',' + mf;
            if (!groups.has(key)) groups.set(key, { color: col, alpha: a, tf, mf, faces: [], idx: [] });
            groups.get(key).faces.push(tri);
            groups.get(key).idx.push(i);
          });
          // sorted: Python groups the same way, so the two stay comparable
          for (const key of [...groups.keys()].sort((a, b) => {
            const A = a.split(',').map(Number), B = b.split(',').map(Number);
            return A[0] - B[0] || A[1] - B[1] || A[2] - B[2] || A[3] - B[3]
                || A[4] - B[4] || A[5] - B[5];
          })) {
            const g = groups.get(key);
            const gm = g.mf >= 0 && mk.masks.has(g.mf)
              ? Object.assign({}, mk.masks.get(g.mf), { uv: g.idx.map((i) => mk.uv[i]) })
              : null;
            out.push({ verts: world, faces: g.faces, color: g.color, alpha: g.alpha,
                       poly: m.poly, isFeature: false,
                       tex: g.tf >= 0 ? texOf(g.tf) : null,
                       uv: g.tf >= 0 ? g.idx.map((i) => tx.uv[i]) : null,
                       mask: gm });
          }
        } else {
          out.push({ verts: world, faces: m.faces, color: base, alpha: balpha,
                     poly: m.poly, isFeature: false, tex: null, uv: null, mask: null });
        }
        if (options.drawSurf) {
          for (const f of surfaceFeatures(k, m)) {
            f.verts = f.verts.map((p) => apply(W, p));
            f.normal = apply([[W[0][0], W[0][1], W[0][2], 0], [W[1][0], W[1][1], W[1][2], 0], [W[2][0], W[2][1], W[2][2], 0]], f.normal);
            out.push(f);
          }
        }
      }
    }
    collect(k, out, u);
  }
  return out;
}

/** All meshes for a parsed file (a scene, or one gallery clip). */
export function sceneMeshes(root) {
  setTextures(options.drawTextures ? textureTable(root) : null);
  const roots = root.findAll('ROOT');
  const out = [];
  if (roots.length) for (const r of roots) collect(r, out);
  else collect(root, out);
  return out;
}
