/**
 * The texture system: TXTB tables, per-prism and per-face assignments.
 *
 *   TXTB                      the texture TABLE, embedded in the file
 *     TXTE                    one texture
 *       TXID  u32             id
 *       TXNM  64 B            name
 *       TXPD  [w:u16][h:u16][bpp:u16][pad][rowbytes:u32][size:u32]
 *               CMAP  256 x (pad, r, g, b)
 *               <pixels>      8-bit palette indices, rowbytes per row
 *       TXST  43 B            tiling: see TILE below
 *
 *   SUTX (in SURF) = TXID + TXOD + TATR    assign a texture to one FACE
 *   PLTX (in PRSM) = TXID + TXOD + TATR    assign to a whole prism
 *   TXID 0xFFFFFFFE (-2) is the "no texture" sentinel.
 *
 * 39 files carry assignments: 180 whole-prism and 96 per-face. The SoftKey
 * applications store all of this and never draw it -- only Virtus VRML does.
 */
const NO_TEXTURE = 0xfffffffe;

/** Chunks nested inside a chunk payload. Odd lengths are padded. */
export function subchunks(dv, start = 0, end = dv.byteLength) {
  const out = [];
  let i = start;
  while (i + 8 <= end) {
    let tag = '';
    for (let k = 0; k < 4; k++) {
      const c = dv.getUint8(i + k);
      if (c < 32 || c > 126) return out;
      tag += String.fromCharCode(c);
    }
    const n = dv.getUint32(i + 4, false);
    if (i + 8 + n > end) return out;
    out.push({ tag, off: i + 8, len: n });
    i += 8 + n + (n % 2 ? 1 : 0);
  }
  return out;
}

/** TXPD -> { w, h, rgba } (Uint8Array), or null. */
export function decodeBitmap(dv, off, len) {
  if (len < 16) return null;
  const w = dv.getUint16(off, false), h = dv.getUint16(off + 2, false);
  const bpp = dv.getUint16(off + 4, false);
  const rowbytes = dv.getUint32(off + 8, false), size = dv.getUint32(off + 12, false);
  if (bpp !== 8 || !w || !h) return null;
  let pal = null, pix = null;
  for (const c of subchunks(dv, off + 16, off + len)) {
    if (c.tag === 'CMAP') {
      pal = new Uint8Array(256 * 3);
      for (let i = 0; i * 4 + 3 < c.len && i < 256; i++) {
        pal[i * 3] = dv.getUint8(c.off + i * 4 + 1);
        pal[i * 3 + 1] = dv.getUint8(c.off + i * 4 + 2);
        pal[i * 3 + 2] = dv.getUint8(c.off + i * 4 + 3);
      }
    } else if (c.len >= size) {
      pix = { off: c.off, len: c.len };
    }
  }
  if (!pal || !pix) return null;
  const rgba = new Uint8Array(w * h * 4);
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      const src = pix.off + y * rowbytes + x;
      const c = src < pix.off + pix.len ? dv.getUint8(src) : 0;
      const o = (y * w + x) * 4;
      rgba[o] = pal[c * 3]; rgba[o + 1] = pal[c * 3 + 1];
      rgba[o + 2] = pal[c * 3 + 2]; rgba[o + 3] = 255;
    }
  }
  return { w, h, rgba };
}

/**
 * TXST's tile size. Those fields are 8.24 fixed point, NOT the 16.16 the rest
 * of the format uses: 0x40000000 reads as 16384 under 16.16 and as 64 under
 * 8.24, and 64 / 88 / 80 / 32 are sane inches-per-tile for brick and panelling.
 */
function tileSize(dv, off, len) {
  if (len < 40) return [64, 64];
  const u = dv.getUint32(off + 28, false) / (1 << 24);
  const v = dv.getUint32(off + 32, false) / (1 << 24);
  return [u > 0.01 ? u : 64, v > 0.01 ? v : 64];
}

/** Every texture in a parsed file -> Map(id -> {name, w, h, rgba, tile}). */
export function textureTable(root) {
  const out = new Map();
  const walk = (n) => {
    for (const k of n.children) {
      if (k.tag === 'TXTB' && k.data) {
        for (const e of subchunks(k.data)) {
          if (e.tag !== 'TXTE') continue;
          let id = null, name = null, img = null, tile = [64, 64];
          for (const f of subchunks(k.data, e.off, e.off + e.len)) {
            if (f.tag === 'TXID' && f.len >= 4) id = k.data.getUint32(f.off, false);
            else if (f.tag === 'TXNM') {
              let s = '';
              for (let i = 0; i < f.len; i++) {
                const c = k.data.getUint8(f.off + i);
                if (!c) break;
                s += String.fromCharCode(c);
              }
              name = s;
            } else if (f.tag === 'TXPD') img = decodeBitmap(k.data, f.off, f.len);
            else if (f.tag === 'TXST') tile = tileSize(k.data, f.off, f.len);
          }
          if (id !== null && img) out.set(id, { name, ...img, tile });
        }
      }
      walk(k);
    }
  };
  walk(root);
  return out;
}

function texId(chunk) {
  if (!chunk) return null;
  const k = chunk.kid ? chunk.kid('TXID') : null;
  if (k && k.data && k.data.byteLength >= 4) {
    const v = k.data.getUint32(0, false);
    return v === NO_TEXTURE ? null : v;
  }
  if (chunk.data) {
    for (const c of subchunks(chunk.data)) {
      if (c.tag === 'TXID' && c.len >= 4) {
        const v = chunk.data.getUint32(c.off, false);
        return v === NO_TEXTURE ? null : v;
      }
    }
  }
  return null;
}

/** -> { whole: id|null, faces: Map(faceId -> id) } */
export function assignments(prsm, u16) {
  const faces = new Map();
  for (const surf of prsm.kids('SURF')) {
    const t = texId(surf.kid('SUTX'));
    if (t !== null) faces.set(u16(surf.hdr, 0), t);
  }
  return { whole: texId(prsm.kid('PLTX')), faces };
}
