/**
 * Design-It! 3-D geometry: IFF chunks -> triangle meshes.
 *
 * Everything visible in the application is a PRSM: a 2D polygon swept along an
 * axis with a profile function. There is no mesh format in the file.
 */
import { fp, u16, u32 } from './iff.js';
import { clipMesh } from './clip.js';

export const STRAIGHT = 1, POINTED = 2, DIAMOND = 3, ROUNDED = 4, SPHERE = 5;
export const PROFILE_NAME = { 1: 'straight', 2: 'pointed', 3: 'diamond', 4: 'rounded', 5: 'sphere' };

export const options = {
  applySlic: true,      // SLIC planes cut the prism
  slicKeepNeg: false,   // keep n.p + d >= 0
  drawSurf: true,       // build SURF/FEAT decoration overlays
};

// ---- small vector helpers ----
const sub = (a, b) => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
const add = (a, b) => [a[0] + b[0], a[1] + b[1], a[2] + b[2]];
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
    let n = u32(b, 28);
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
        out = [];
        for (let k = 0; k <= n; k++) {
          const th = (k / n) * (Math.PI / 2);
          out.push([za + (zb - za) * (1 - Math.cos(th)), Math.sin(th)]);
        }
        break;
      case SPHERE:
        out = [];
        for (let k = 0; k <= n; k++) {
          const th = (k / n) * Math.PI;
          out.push([za + (zb - za) * (1 - Math.cos(th)) / 2, Math.sin(th)]);
        }
        break;
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

/** POSN: 12 x fp16.16. The rotation triple is stored (ry, rx, rz). */
export function posnMatrix(chunk) {
  if (!chunk || chunk.data.byteLength < 48) return identity();
  const d = chunk.data;
  const v = [];
  for (let i = 0; i < 12; i++) v.push(fp(d, i * 4));
  const rx = v[4], ry = v[3], rz = v[5];
  const cx = Math.cos(rx), sx = Math.sin(rx);
  const cy = Math.cos(ry), sy = Math.sin(ry);
  const cz = Math.cos(rz), sz = Math.sin(rz);
  const Rz = [[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]];
  const Ry = [[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]];
  const Rx = [[1, 0, 0], [0, cx, -sx], [0, sx, cx]];
  const R = mat3(mat3(Rz, Ry), Rx);
  const S = [v[9], v[10], v[11]];
  const M = [[0, 0, 0, v[0]], [0, 0, 0, v[1]], [0, 0, 0, v[2]]];
  for (let r = 0; r < 3; r++) for (let c = 0; c < 3; c++) M[r][c] = R[r][c] * S[c];
  return M;
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

/**
 * Build one PRSM. Returns {verts, faces, faceIds, poly} in object space.
 *
 * Face numbering, which SURF indexes into:
 *   0                  cap at the HIGH end of the sweep
 *   1 .. bands*n       side faces, band-major, polygon edges traversed BACKWARDS
 *   bands*n + 1        cap at the LOW end
 *   bands*n + 2 + j    face created by SLIC cut j
 */
export function prismMesh(prsm) {
  const pc = prsm.kid('POLY');
  if (!pc || pc.data.byteLength < 32) return null;
  const poly = new Poly(pc);
  const base = poly.verts;
  if (base.length < 3) return null;
  const rings = poly.rings();
  const n = base.length;
  const nband = rings.length - 1;

  const verts = [], ringIdx = [];
  for (const [z, s] of rings) {
    if (s === 0) { ringIdx.push([verts.length]); verts.push([0, 0, z]); }
    else {
      const start = verts.length;
      for (const [x, y] of base) verts.push([x * s, y * s, z]);
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

  const sideId = (r, i) => 1 + r * n + (n - 1 - i);
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
  const cap0 = 0, cap1 = nband * n + 1;
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
      const r = clipMesh(V, F, nn, dd, { keepNegative: options.slicKeepNeg, ids, newId: cap1 + 1 + i });
      V = r.verts; F = r.faces; ids = r.ids;
      if (!F.length) break;
    }
  }
  return { verts: V, faces: F, faceIds: ids, poly };
}

export function colorOf(prsm) {
  const c = prsm.kid('COLR');
  if (!c || c.data.byteLength < 8) return [170, 170, 170];
  return [c.data.getUint8(1), c.data.getUint8(2), c.data.getUint8(3)];
}

// ---- SURF / FEAT ----

/**
 * A 2D frame for one face: drop the axis the normal is most aligned with,
 * keep the other two in ascending axis order, origin at the face's minimum
 * corner. Feature coordinates are expressed in this frame.
 */
export function faceFrame(verts, tris) {
  const idx = [...new Set(tris.flat())];
  let best = 0, nrm = null;
  for (const t of tris) {
    const cr = cross(sub(verts[t[1]], verts[t[0]]), sub(verts[t[2]], verts[t[0]]));
    const l = len(cr);
    if (l > best) { best = l; nrm = [cr[0] / l, cr[1] / l, cr[2] / l]; }
  }
  if (!nrm || best < 1e-9) return null;
  const ctr = [0, 0, 0];
  for (const v of verts) { ctr[0] += v[0] / verts.length; ctr[1] += v[1] / verts.length; ctr[2] += v[2] / verts.length; }
  const fc = [0, 0, 0];
  for (const i of idx) { fc[0] += verts[i][0] / idx.length; fc[1] += verts[i][1] / idx.length; fc[2] += verts[i][2] / idx.length; }
  if (dot(nrm, sub(fc, ctr)) < 0) nrm = mul(nrm, -1);

  let drop = 0;
  for (let i = 1; i < 3; i++) if (Math.abs(nrm[i]) > Math.abs(nrm[drop])) drop = i;
  const ax = [0, 1, 2].filter((i) => i !== drop);
  let u = [0, 0, 0]; u[ax[0]] = 1;
  let v = [0, 0, 0]; v[ax[1]] = 1;
  u = sub(u, mul(nrm, dot(u, nrm)));
  if (len(u) < 1e-9) return null;
  u = norm(u);
  v = sub(sub(v, mul(nrm, dot(v, nrm))), mul(u, dot(v, u)));
  if (len(v) < 1e-9) return null;
  v = norm(v);
  let minU = Infinity, minV = Infinity;
  for (const i of idx) { minU = Math.min(minU, dot(verts[i], u)); minV = Math.min(minV, dot(verts[i], v)); }
  const origin = add(add(mul(u, minU), mul(v, minV)), mul(nrm, dot(verts[idx[0]], nrm)));
  return { origin, u, v, nrm };
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

/** 2D FEAT POSN: 6 x fp16.16 = (x, y, ?, ?, sx, sy). */
export function featTransform(feat) {
  const ps = feat.kid('POSN');
  if (!ps || ps.data.byteLength < 24) return [0, 0, 1, 1];
  return [fp(ps.data, 0), fp(ps.data, 4), fp(ps.data, 16) || 1, fp(ps.data, 20) || 1];
}

export const FEAT_OUTSIDE = 0, FEAT_INSIDE = 1, FEAT_BOTH = 2;

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
  for (const surf of prsm.kids('SURF')) {
    const fid = u16(surf.hdr, 0);
    const tris = byFace.get(fid);
    if (!tris) continue;
    const fr = faceFrame(mesh.verts, tris);
    if (!fr) continue;
    let layer = 0;
    for (const feat of surf.kids('FEAT')) {
      const side = feat.hdr ? u16(feat.hdr, 0) : FEAT_OUTSIDE;
      const poly = featPolygon(feat);
      if (!poly || poly.length < 3) continue;
      const [tx, ty, sx, sy] = featTransform(feat);
      const col = feat.kid('COLR');
      const rgb = col && col.data.byteLength >= 4
        ? [col.data.getUint8(1), col.data.getUint8(2), col.data.getUint8(3)] : [0, 0, 0];
      const alpha = col && col.data.byteLength >= 4 ? col.data.getUint8(0) : 255;
      const pts2 = poly.map(([x, y]) => [x * sx + tx, y * sy + ty]);
      const pv = pts2.map(([a, b]) => add(add(fr.origin, mul(fr.u, a)), mul(fr.v, b)));
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
export function collect(node, out = []) {
  for (const k of node.children) {
    if (k.tag !== 'PRSM' && k.tag !== 'PGRP') continue;
    const W = posnMatrix(k.kid('POSN'));
    if (k.tag === 'PRSM') {
      const m = prismMesh(k);
      if (m) {
        const world = m.verts.map((p) => apply(W, p));
        out.push({ verts: world, faces: m.faces, color: colorOf(k), poly: m.poly, isFeature: false });
        if (options.drawSurf) {
          for (const f of surfaceFeatures(k, m)) {
            f.verts = f.verts.map((p) => apply(W, p));
            f.normal = apply([[W[0][0], W[0][1], W[0][2], 0], [W[1][0], W[1][1], W[1][2], 0], [W[2][0], W[2][1], W[2][2], 0]], f.normal);
            out.push(f);
          }
        }
      }
    }
    collect(k, out);
  }
  return out;
}

/** All meshes for a parsed file (a scene, or one gallery clip). */
export function sceneMeshes(root) {
  const roots = root.findAll('ROOT');
  const out = [];
  if (roots.length) for (const r of roots) collect(r, out);
  else collect(root, out);
  return out;
}
