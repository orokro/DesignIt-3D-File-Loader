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
import { sceneMeshes, collect, options, setTextures } from './geometry.js';
import { textureTable } from './textures.js';

export { options, parse, wlbItems };

const key = (rgb) => (rgb[0] << 16) | (rgb[1] << 8) | rgb[2];

export function buildGroup(meshes, { flatShading = true } = {}) {
  const g = new THREE.Group();
  const solids = new Map();   // colour -> {pos: [], }
  const feats = new Map();
  let tris = 0, maskSeq = 0;

  for (const m of meshes) {
    const bucket = m.isFeature ? feats : solids;
    // features are keyed by colour AND stack layer so each layer keeps its own
    // depth bias; solids merge by colour alone
    // alpha is part of the key: a translucent decal must not be merged into
    // the same draw call as an opaque one of the same colour and layer.
    // Alpha is part of the SOLID key too now: a prism face set Translucent in
    // the application carries opacity 128 on its own SURF record, and merging it
    // with the opaque faces of the same colour would make the whole prism
    // see-through. A face at opacity 0 is simply not drawn -- the application
    // calls that state Transparent, and the Virtus VRML exporter agrees, writing
    // `transparency 1.0000` for exactly those faces.
    if (!m.isFeature && (m.alpha ?? 255) === 0) continue;
    // A textured mesh keeps its own bucket: the UV attribute only makes sense
    // alongside the bitmap it was measured against.
    const t = m.tex && m.uv ? `#${m.tex.id}` : '';
    // A stencilled face never merges with anything: its mask is in that one
    // face's own frame. `maskSeq` keys it uniquely without needing a face id.
    const ms = m.mask ? `@${maskSeq++}` : '';
    // The texture belongs in the FEATURE key too: a decoration can carry its
    // own bitmap through SFTX, and two decorations of the same colour and layer
    // may well wear different ones.
    const k = m.isFeature ? `${key(m.color)}/${m.layer ?? 0}/${m.alpha ?? 255}${t}`
                          : `${key(m.color)}/${m.alpha ?? 255}${t}${ms}`;
    if (!bucket.has(k)) bucket.set(k, { pos: [], uv: [], muv: [], rgb: m.color,
                                        alpha: m.alpha ?? 255, layer: m.layer ?? 0,
                                        tex: t ? m.tex : null, mask: m.mask || null });
    const b = bucket.get(k);
    m.faces.forEach(([a, c, d], fi) => {
      const A = m.verts[a], B = m.verts[c], C = m.verts[d];
      b.pos.push(A[0], A[1], A[2], B[0], B[1], B[2], C[0], C[1], C[2]);
      if (b.mask) {
        const q = m.mask.uv[fi];
        if (q) b.muv.push(q[0][0], q[0][1], q[1][0], q[1][1], q[2][0], q[2][1]);
        else b.muv.push(0, 0, 0, 0, 0, 0);
      }
      if (b.tex) {
        const q = m.uv && m.uv[fi];
        // A face inside a textured prism can still be untextured (per-face
        // SUTX); park it at the origin of the tile rather than dropping it.
        if (q) b.uv.push(q[0][0], q[0][1], q[1][0], q[1][1], q[2][0], q[2][1]);
        else b.uv.push(0, 0, 0, 0, 0, 0);
      }
      tris++;
    });
  }

  const texCache = new Map();
  const makeTex = (t) => {
    if (texCache.has(t.id)) return texCache.get(t.id);
    const tx = new THREE.DataTexture(t.rgba, t.w, t.h, THREE.RGBAFormat);
    // Backdrops and photo-textures are fitted once to the face and must CLAMP:
    // a UV a hair outside 0..1 at the seam would otherwise wrap the far edge of
    // the sky round to the near one. See textures.js wrapFlags.
    const [wu, wv] = t.wrap || [true, true];
    tx.wrapS = wu ? THREE.RepeatWrapping : THREE.ClampToEdgeWrapping;
    tx.wrapT = wv ? THREE.RepeatWrapping : THREE.ClampToEdgeWrapping;
    tx.magFilter = THREE.LinearFilter;
    tx.minFilter = THREE.LinearMipmapLinearFilter;
    tx.generateMipmaps = true;
    tx.colorSpace = THREE.SRGBColorSpace;
    tx.flipY = false;              // UVs are measured downward from the face's corner
    tx.needsUpdate = true;
    texCache.set(t.id, tx);
    return tx;
  };

  // The OPENING stencil. The face keeps every one of its triangles and the
  // pixels inside a hole are simply never drawn -- alphaTest, no blending, so
  // depth still writes correctly and the wall behind stays solid geometry.
  // It rides on the SECOND uv channel so a face can be textured and stencilled
  // at once: the texture's UVs are inches/tile, the mask's are face-relative.
  const maskCache = new Map();
  const makeMask = (mk_) => {
    if (maskCache.has(mk_)) return maskCache.get(mk_);
    const n = mk_.w * mk_.h, rgba = new Uint8Array(n * 4);
    for (let i = 0; i < n; i++) {
      const a = mk_.a[i];
      rgba[i * 4] = a; rgba[i * 4 + 1] = a; rgba[i * 4 + 2] = a; rgba[i * 4 + 3] = 255;
    }
    const tx = new THREE.DataTexture(rgba, mk_.w, mk_.h, THREE.RGBAFormat);
    tx.wrapS = tx.wrapT = THREE.ClampToEdgeWrapping;
    tx.magFilter = THREE.LinearFilter;
    tx.minFilter = THREE.LinearMipmapLinearFilter;
    tx.generateMipmaps = true;
    tx.flipY = false;
    tx.channel = 1;                    // read the uv1 attribute, not uv
    tx.needsUpdate = true;
    maskCache.set(mk_, tx);
    return tx;
  };

  const mk = (entry, isFeature) => {
    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.Float32BufferAttribute(entry.pos, 3));
    if (entry.tex && entry.uv.length) {
      geo.setAttribute('uv', new THREE.Float32BufferAttribute(entry.uv, 2));
    }
    if (entry.mask && entry.muv.length) {
      geo.setAttribute('uv1', new THREE.Float32BufferAttribute(entry.muv, 2));
    }
    geo.computeVertexNormals();
    const mat = new THREE.MeshLambertMaterial({
      // A textured face keeps its base colour as a WHITE multiplier: the app
      // paints the bitmap over the surface, it does not tint it.
      color: entry.tex ? new THREE.Color(1, 1, 1)
        : new THREE.Color(entry.rgb[0] / 255, entry.rgb[1] / 255, entry.rgb[2] / 255),
      map: entry.tex ? makeTex(entry.tex) : null,
      alphaMap: entry.mask && entry.muv.length ? makeMask(entry.mask) : null,
      alphaTest: entry.mask && entry.muv.length ? 0.5 : 0,
      side: THREE.DoubleSide,
      flatShading,
    });
    // COPLANAR SOLIDS: strictly-less depth, so the FIRST surface drawn at a
    // given depth keeps the pixel. `GLASHOUS` puts an orange carpet face on the
    // house body and a maroon foundation slab at exactly the same z; the file
    // orders the body first, and the original application -- like the Python
    // reference -- draws with a strict `<` and shows orange. Three.js defaults
    // to LessEqualDepth, which let the later maroon slab overwrite it.
    if (!isFeature) mat.depthFunc = THREE.LessDepth;
    if (isFeature) {
      // depth bias: keeps decals coplanar yet in front, without moving them
      mat.polygonOffset = true;
      mat.polygonOffsetFactor = -1 - entry.layer;
      mat.polygonOffsetUnits = -4 * (entry.layer + 1);
      mat.depthWrite = false;
    }
    // Translucent. The original dithered on a checkerboard because it had an
    // 8-bit palette and no blending; a real alpha blend is the same intent. The
    // pane must not write depth, or the geometry behind it is culled before it
    // is ever drawn.
    if (entry.alpha < 250) {
      mat.transparent = true;
      mat.opacity = entry.alpha / 255;
      mat.depthWrite = false;
    }
    const mesh = new THREE.Mesh(geo, mat);
    mesh.userData.isFeature = isFeature;
    // Keep both looks on the mesh so a Textures toggle is a material swap
    // rather than a rebuild: the UV attribute is always there.
    mesh.userData.tex = mat.map || null;
    mesh.userData.rgb = entry.rgb;
    mesh.userData.hasMask = !!mat.alphaMap;
    if (isFeature) mesh.renderOrder = 1 + entry.layer;
    // translucent solids after every opaque one, before the decals
    if (!isFeature && entry.alpha < 250) mesh.renderOrder = 0.5;
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
  // A gallery keeps ONE TXTB for the whole .WLB, above the clips, so a clip
  // built on its own has to be handed the table explicitly.
  setTextures(options.drawTextures && clip.root ? textureTable(clip.root) : null);
  return buildGroup(collect(clip.chunk, []), opts);
}
