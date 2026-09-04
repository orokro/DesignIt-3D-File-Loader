// Emit an order-independent geometry digest per file, for comparison with the
// Python implementation in claude-explore/tools/.
import fs from 'fs';
import path from 'path';
import { parse, wlbItems } from './src/iff.js';
import { sceneMeshes, collect, options } from './src/geometry.js';

options.applySlic = true; options.slicKeepNeg = false; options.drawSurf = process.env.SURF === "1";

function digest(meshes) {
  let tris = 0, area = 0, vol = 0;
  const lo = [Infinity, Infinity, Infinity], hi = [-Infinity, -Infinity, -Infinity];
  for (const m of meshes) {
    for (const [a, b, c] of m.faces) {
      const A = m.verts[a], B = m.verts[b], C = m.verts[c];
      const u = [B[0] - A[0], B[1] - A[1], B[2] - A[2]];
      const v = [C[0] - A[0], C[1] - A[1], C[2] - A[2]];
      const n = [u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0]];
      area += Math.hypot(n[0], n[1], n[2]) / 2;
      // signed volume is independent of how a surface happens to be tessellated
      vol += (A[0] * (B[1] * C[2] - B[2] * C[1]) + A[1] * (B[2] * C[0] - B[0] * C[2]) + A[2] * (B[0] * C[1] - B[1] * C[0])) / 6;
      tris++;
    }
    for (const p of m.verts) for (let i = 0; i < 3; i++) { if (p[i] < lo[i]) lo[i] = p[i]; if (p[i] > hi[i]) hi[i] = p[i]; }
  }
  const r = (x) => Math.round(x * 1000) / 1000;
  return { meshes: meshes.length, tris, area: r(area), volume: r(vol), lo: lo.map(r), hi: hi.map(r) };
}

const out = {};
for (const rel of process.argv.slice(2)) {
  const b = fs.readFileSync(rel);
  const ab = b.buffer.slice(b.byteOffset, b.byteOffset + b.byteLength);
  try {
    const root = parse(ab);
    if (rel.toUpperCase().endsWith('.WLB')) {
      for (const { name, chunk } of wlbItems(root)) {
        out[`${path.basename(rel)}::${name}`] = digest(collect(chunk, []));
      }
    } else {
      out[path.basename(rel)] = digest(sceneMeshes(root));
    }
  } catch (e) { out[path.basename(rel)] = { error: `${e.constructor.name}: ${e.message}` }; }
}
console.log(JSON.stringify(out));
