/**
 * Clip a closed triangle mesh by a plane and re-cap the cut.
 *
 * Sutherland-Hodgman per triangle, then the cut face is rebuilt from the
 * vertices that end up ON the plane -- not by stitching the edges we happened
 * to create. That distinction matters: a slab mitred exactly corner to corner
 * (the PC Compaq keyboard) creates no new vertices at two of its four cut
 * corners, and edge-stitching degenerates there.
 *
 * The cut face is assumed convex, which holds for a plane through a convex
 * prism.
 */
const ON = 1e-6;

const sub = (a, b) => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
const len = (a) => Math.hypot(a[0], a[1], a[2]);

function area(V, a, b, c) {
  return len(cross(sub(V[b], V[a]), sub(V[c], V[a]))) / 2;
}

/**
 * @param {number[][]} verts
 * @param {number[][]} faces  index triples
 * @param {number[]} n plane normal
 * @param {number} d plane offset: keeps n.p + d >= 0 when keepNegative is false
 * @param {object} opts {keepNegative, ids, newId}
 */
export function clipMesh(verts, faces, n, d, { keepNegative = true, ids = null, newId = null } = {}) {
  const sgn = keepNegative ? 1 : -1;
  const V = verts.map((v) => v.slice());
  const dist = V.map((v) => sgn * (dot(n, v) + d));
  const nl = len(n) || 1;
  let maxAbs = 1;
  for (const x of dist) maxAbs = Math.max(maxAbs, Math.abs(x));
  const tol = ON * nl * maxAbs;

  let lo = Infinity, hi = -Infinity;
  for (const x of dist) { if (x < lo) lo = x; if (x > hi) hi = x; }
  if (hi <= tol) return { verts: V, faces: faces.map((f) => f.slice()), ids: ids ? ids.slice() : null };
  if (lo > tol) return { verts: V, faces: [], ids: ids ? [] : null };

  const cache = new Map();
  const cut = (i, j) => {
    const key = i < j ? `${i},${j}` : `${j},${i}`;
    if (!cache.has(key)) {
      const a = dist[i], b = dist[j];
      const t = a / (a - b);
      V.push([V[i][0] + t * (V[j][0] - V[i][0]), V[i][1] + t * (V[j][1] - V[i][1]), V[i][2] + t * (V[j][2] - V[i][2])]);
      dist.push(0);
      cache.set(key, V.length - 1);
    }
    return cache.get(key);
  };

  const out = [], outIds = [], onPlane = new Set();
  faces.forEach((tri, ti) => {
    const fid = ids ? ids[ti] : null;
    const ds = tri.map((k) => dist[k]);
    if (ds.every((x) => x > tol)) return;
    let poly;
    if (ds.every((x) => x <= tol)) poly = tri.slice();
    else {
      poly = [];
      for (let i = 0; i < 3; i++) {
        const a = tri[i], b = tri[(i + 1) % 3];
        const da = dist[a], db = dist[b];
        if (da <= tol) poly.push(a);
        if ((da <= tol) !== (db <= tol)) poly.push(cut(a, b));
      }
    }
    for (const k of poly) if (Math.abs(dist[k]) <= tol) onPlane.add(k);
    if (poly.length < 3) return;
    for (let k = 1; k < poly.length - 1; k++) {
      if (area(V, poly[0], poly[k], poly[k + 1]) > 1e-12) {
        out.push([poly[0], poly[k], poly[k + 1]]);
        outIds.push(fid);
      }
    }
  });

  const nhat = [n[0] * sgn / nl, n[1] * sgn / nl, n[2] * sgn / nl];
  const cap = capFace(V, onPlane, nhat);
  for (const f of cap) { out.push(f); outIds.push(newId); }
  return { verts: V, faces: out, ids: ids ? outIds : null };
}

function capFace(V, onPlane, nhat) {
  const idx = [...onPlane].sort((a, b) => a - b);
  if (idx.length < 3) return [];
  const keep = [], seen = [];
  for (const k of idx) {
    const p = V[k];
    if (!seen.some((q) => Math.abs(q[0] - p[0]) < 1e-7 && Math.abs(q[1] - p[1]) < 1e-7 && Math.abs(q[2] - p[2]) < 1e-7)) {
      keep.push(k); seen.push(p);
    }
  }
  if (keep.length < 3) return [];
  const ctr = [0, 0, 0];
  for (const p of seen) { ctr[0] += p[0] / seen.length; ctr[1] += p[1] / seen.length; ctr[2] += p[2] / seen.length; }
  let u = cross(nhat, [0, 0, 1]);
  if (len(u) < 1e-6) u = cross(nhat, [0, 1, 0]);
  const ul = len(u); u = [u[0] / ul, u[1] / ul, u[2] / ul];
  const w = cross(nhat, u);
  const ang = keep.map((k, i) => [Math.atan2(dot(sub(seen[i], ctr), w), dot(sub(seen[i], ctr), u)), k]);
  ang.sort((a, b) => a[0] - b[0]);
  const order = ang.map((a) => a[1]);
  const faces = [];
  for (let k = 1; k < order.length - 1; k++) {
    if (area(V, order[0], order[k], order[k + 1]) > 1e-12) faces.push([order[0], order[k], order[k + 1]]);
  }
  return faces;
}
