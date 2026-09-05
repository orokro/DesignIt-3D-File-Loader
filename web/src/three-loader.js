/**
 * Turn parsed Design-It! 3-D geometry into Three.js objects.
 *
 * Solid prisms are merged per colour so a 400-part scene is a handful of draw
 * calls. Surface decorations get their own material with a depth bias
 * (glPolygonOffset) rather than being nudged along the normal -- the vertices
 * stay mathematically on the surface, and the slope-scaled term keeps them
 * stable at distance and at grazing angles.
 */
import * as THREE from 'three';
import { parse, wlbItems } from './iff.js';
import { sceneMeshes, collect, options } from './geometry.js';

export { options, parse, wlbItems };

const key = (rgb) => (rgb[0] << 16) | (rgb[1] << 8) | rgb[2];

function buildGroup(meshes, { flatShading = true } = {}) {
  const g = new THREE.Group();
  const solids = new Map();   // colour -> {pos: [], }
  const feats = new Map();
  let tris = 0;

  for (const m of meshes) {
    const bucket = m.isFeature ? feats : solids;
    // features are keyed by colour AND stack layer so each layer keeps its own
    // depth bias; solids merge by colour alone
    // alpha is part of the key: a translucent decal must not be merged into
    // the same draw call as an opaque one of the same colour and layer.
    const k = m.isFeature ? `${key(m.color)}/${m.layer ?? 0}/${m.alpha ?? 255}` : key(m.color);
    if (!bucket.has(k)) bucket.set(k, { pos: [], rgb: m.color, alpha: m.alpha ?? 255, layer: m.layer ?? 0 });
    const b = bucket.get(k);
    for (const [a, c, d] of m.faces) {
      const A = m.verts[a], B = m.verts[c], C = m.verts[d];
      b.pos.push(A[0], A[1], A[2], B[0], B[1], B[2], C[0], C[1], C[2]);
      tris++;
    }
  }

  const mk = (entry, isFeature) => {
    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.Float32BufferAttribute(entry.pos, 3));
    geo.computeVertexNormals();
    const mat = new THREE.MeshLambertMaterial({
      color: new THREE.Color(entry.rgb[0] / 255, entry.rgb[1] / 255, entry.rgb[2] / 255),
      side: THREE.DoubleSide,
      flatShading,
    });
    if (isFeature) {
      // depth bias: keeps decals coplanar yet in front, without moving them
      mat.polygonOffset = true;
      mat.polygonOffsetFactor = -1 - entry.layer;
      mat.polygonOffsetUnits = -4 * (entry.layer + 1);
      mat.depthWrite = false;
      if (entry.alpha < 250) { mat.transparent = true; mat.opacity = entry.alpha / 255; }
    }
    const mesh = new THREE.Mesh(geo, mat);
    mesh.userData.isFeature = isFeature;
    if (isFeature) mesh.renderOrder = 1 + entry.layer;
    g.add(mesh);
  };
  for (const e of solids.values()) mk(e, false);
  for (const e of feats.values()) mk(e, true);

  const box = new THREE.Box3().setFromObject(g);
  return { group: g, box, triangles: tris, meshCount: meshes.length };
}

/** Load a .VVR scene or model from an ArrayBuffer. */
export function loadScene(buf, opts) {
  const root = parse(buf);
  return buildGroup(sceneMeshes(root), opts);
}

/** List the clips in a .WLB gallery without building geometry. */
export function listClips(buf) {
  return wlbItems(parse(buf));
}

/** Build one named clip from an already-parsed gallery. */
export function loadClip(clip, opts) {
  return buildGroup(collect(clip.chunk, []), opts);
}
