/**
 * Strict EA IFF-85 reader for Design-It! 3-D .VVR / .WLB / .TLB files.
 *
 * Correctness oracle: every container's payload must be consumed exactly by
 * its children. A wrong schema fails loudly instead of guessing.
 */

const FORMLIKE = new Set(['FORM', 'CAT ', 'LIST']);
const CONTAINERS = new Set(['ROOT', 'PRSM', 'PGRP', 'PREF', 'SUTX', 'VGER']);
const CONTAINERS_HDR = { SURF: 2 };
// A FEAT inside a SURF carries a 2-byte header (the side selector); a FEAT
// that IS a 2D library clip does not.
const CONTAINERS_HDR_CTX = { 'SURF/FEAT': 2 };

export class Chunk {
  constructor(tag, offset = 0) {
    this.tag = tag;
    this.formtype = null;
    this.subtype = null;
    this.data = null;      // DataView over the payload, for leaves
    this.hdr = null;       // DataView over header bytes, for SURF/FEAT
    this.children = [];
    this.offset = offset;
  }
  kid(tag) { return this.children.find((c) => c.tag === tag) || null; }
  kids(tag) { return this.children.filter((c) => c.tag === tag); }
  findAll(tag, out = []) {
    if (this.tag === tag) out.push(this);
    for (const c of this.children) c.findAll(tag, out);
    return out;
  }
}

export class IFFError extends Error {}

const dec = new TextDecoder('latin1');
const tagAt = (buf, o) => dec.decode(new Uint8Array(buf, o, 4));

function hdrLen(tag, parentTag) {
  const ctx = CONTAINERS_HDR_CTX[`${parentTag}/${tag}`];
  if (ctx !== undefined) return ctx;
  return CONTAINERS_HDR[tag];
}

function parseSeq(buf, view, start, end, parent, strict) {
  let off = start;
  while (off < end) {
    if (off + 8 > end) {
      if (strict) throw new IFFError(`truncated chunk header at ${off}`);
      return;
    }
    const tag = tagAt(buf, off);
    const len = view.getUint32(off + 4, false);
    const body = off + 8;
    let stop = body + len;
    if (stop > end) {
      // A few shipped ID*.WLB clips under-report their own length.
      if (!strict) { parent.trailing = end - off; return; }
      throw new IFFError(`${tag} at ${off} declares ${len} bytes, overruns ${end}`);
    }
    const c = new Chunk(tag, off);
    const hl = hdrLen(tag, parent.tag);
    if (len === 0) {
      // zero-length chunks are type markers, not containers
    } else if (FORMLIKE.has(tag)) {
      c.formtype = tagAt(buf, body);
      let p2 = body + 4;
      if (c.formtype === 'VCLP') { c.subtype = tagAt(buf, p2); p2 += 4; }
      parseSeq(buf, view, p2, stop, c, strict);
    } else if (hl !== undefined) {
      c.hdr = new DataView(buf, body, hl);
      parseSeq(buf, view, body + hl, stop, c, strict);
    } else if (CONTAINERS.has(tag) || tag === 'FEAT') {
      parseSeq(buf, view, body, stop, c, strict);
    } else {
      c.data = new DataView(buf, body, stop - body);
    }
    parent.children.push(c);
    off = stop;
    // IFF-85 pads an odd-length chunk to an even boundary, and this format does
    // too -- it simply never came up. Every chunk in the SoftKey corpus happens
    // to have an even length, so "exact lengths, no padding" held for 393 files
    // and got written into the spec as fact. The Virtus VRML content breaks it:
    // VRAN carries a URL, and `file:///kitchen.wrl` is 19 bytes followed by a
    // 00 before the next chunk. Without this, three tutorial files fail to parse.
    if (len % 2 && off < end && view.getUint8(off) === 0) off += 1;
  }
}

/** Parse a whole file. Returns a synthetic root chunk. */
export function parse(buf) {
  const view = new DataView(buf);
  const root = new Chunk('$ROOT');
  const n = buf.byteLength;
  let off = 0;
  while (off + 8 <= n) {
    const tag = tagAt(buf, off);
    const len = view.getUint32(off + 4, false);
    let stop = Math.min(off + 8 + len, n);
    const c = new Chunk(tag, off);
    if (FORMLIKE.has(tag)) {
      c.formtype = tagAt(buf, off + 8);
      if (tag === 'CAT ') {
        // CAT lengths are stale in the shipped gallery files. Find clips by
        // signature and bound each by the start of the next.
        stop = n;
        const starts = [];
        let i = off + 12;
        const bytes = new Uint8Array(buf);
        while (i < n - 12) {
          if (bytes[i] === 0x46 && bytes[i + 1] === 0x4f && bytes[i + 2] === 0x52 && bytes[i + 3] === 0x4d &&
              bytes[i + 8] === 0x56 && bytes[i + 9] === 0x43 && bytes[i + 10] === 0x4c && bytes[i + 11] === 0x50) {
            starts.push(i); i += 12;
          } else i += 1;
        }
        for (let si = 0; si < starts.length; si++) {
          const s0 = starts[si];
          const s1 = si + 1 < starts.length ? starts[si + 1] : n;
          const l2 = view.getUint32(s0 + 4, false);
          parseSeq(buf, view, s0, Math.min(s0 + 8 + l2, s1), c, false);
        }
      } else {
        parseSeq(buf, view, off + 12, stop, c, true);
      }
    } else if (CONTAINERS.has(tag)) {
      parseSeq(buf, view, off + 8, stop, c, true);
    } else {
      c.data = new DataView(buf, off + 8, stop - (off + 8));
    }
    root.children.push(c);
    off = stop;
    if (len % 2 && off < n && view.getUint8(off) === 0) off += 1;   // odd-length pad
  }
  return root;
}

// ---- typed readers ----
export const i32 = (d, o) => d.getInt32(o, false);
export const u32 = (d, o) => d.getUint32(o, false);
export const i16 = (d, o) => d.getInt16(o, false);
export const u16 = (d, o) => d.getUint16(o, false);
/** 16.16 fixed point -- the format's universal numeric type. */
export const fp = (d, o) => d.getInt32(o, false) / 65536;
export const f64 = (d, o) => d.getFloat64(o, false);

export function pstring(d, o = 0) {
  const n = d.getUint8(o);
  let s = '';
  for (let i = 0; i < n; i++) {
    const c = d.getUint8(o + 1 + i);
    if (c) s += String.fromCharCode(c);
  }
  return s;
}

/** Named clips inside a .WLB gallery. */
export function wlbItems(root) {
  const out = [];
  for (const cat of root.children) {
    for (const it of cat.children) {
      if (it.tag !== 'FORM' || it.formtype !== 'VCLP') continue;
      const nm = it.kid('NAME');
      // `root` rides along: the gallery's TXTB sits above the clips, so a
      // clip built on its own still needs a way back to the texture table.
      out.push({ name: nm ? pstring(nm.data) : '?', kind: it.subtype, chunk: it, root });
    }
  }
  return out;
}
