"""Decode the texture system: TXTB tables, and which face each texture lands on.

    TXTB                      the texture TABLE, embedded in the file
      TXTE                    one texture
        TXID  u32             id
        TXNM  64 B            name
        TXPD  [w:u16][h:u16][bpp:u16][pad][rowbytes:u32][size:u32]
                CMAP  256 x (pad, r, g, b)
                <pixels>      8-bit palette indices, rowbytes per row
        TXST  43 B            unknown -- tiling/scale flags?

    SUTX (in SURF) = TXID + TXOD + TATR    assign a texture to one FACE
    PLTX (in PRSM) = TXID + TXOD + TATR    assign to a whole prism
    SFTX (in FEAT) = TXID + TATR           assign to a decoration
    TXID 0xFFFFFFFE (-2) is the "no texture" sentinel.

All 371 texture entries in the corpus decode; 351 are unique. Only 22 files
assign one to anything, and the SoftKey applications never DRAW them -- see
vvr_provenance. We can.
"""
import os, sys, struct
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import iff

NO_TEXTURE = 0xFFFFFFFE


def subchunks(buf, start=0):
    """Walk chunks inside a chunk payload (TXTB and friends nest this way)."""
    i, out = start, []
    while i + 8 <= len(buf):
        tag = buf[i:i + 4]
        if not all(32 <= c < 127 for c in tag):
            break
        n = struct.unpack('>I', buf[i + 4:i + 8])[0]
        if i + 8 + n > len(buf):
            break
        out.append((tag.decode('latin1'), buf[i + 8:i + 8 + n]))
        i += 8 + n + (1 if n % 2 else 0)      # odd-length chunks are padded
    return out


def decode_bitmap(body):
    """TXPD / BMAP -> (width, height, RGB bytes) or None."""
    if len(body) < 16:
        return None
    w, h, bpp, _ = struct.unpack('>4H', body[:8])
    rowbytes, size = struct.unpack('>2I', body[8:16])
    pal = pix = None
    for tag, b in subchunks(body, 16):
        if tag == 'CMAP':
            pal = [(b[i + 1], b[i + 2], b[i + 3]) for i in range(0, len(b), 4)]
        elif len(b) >= size:
            pix = b[:size]
    if pix is None or not pal or bpp != 8 or w == 0 or h == 0:
        return None
    rgb = bytearray(w * h * 3)
    for y in range(h):
        row = y * rowbytes
        for x in range(w):
            c = pal[pix[row + x]] if row + x < len(pix) else (0, 0, 0)
            o = (y * w + x) * 3
            rgb[o], rgb[o + 1], rgb[o + 2] = c
    return w, h, bytes(rgb)


def table(root):
    """Every texture in a file -> {id: {'name', 'w', 'h', 'rgb'}}"""
    out = {}
    def walk(n):
        for k in n.children:
            if k.tag == 'TXTB':
                for tag, body in subchunks(k.data):
                    if tag != 'TXTE':
                        continue
                    tid = name = img = None
                    for t2, b2 in subchunks(body):
                        if t2 == 'TXID' and len(b2) >= 4:
                            tid = struct.unpack('>I', b2[:4])[0]
                        elif t2 == 'TXNM':
                            name = b2.split(b'\0')[0].decode('latin1', 'replace')
                        elif t2 == 'TXPD':
                            img = decode_bitmap(b2)
                    if tid is not None:
                        e = {'name': name}
                        if img:
                            e.update(w=img[0], h=img[1], rgb=img[2])
                        out[tid] = e
            walk(k)
    walk(root)
    return out


def _tex_id(chunk):
    for t, b in subchunks(chunk.data) if chunk.data else []:
        if t == 'TXID' and len(b) >= 4:
            v = struct.unpack('>I', b[:4])[0]
            return None if v == NO_TEXTURE else v
    # SUTX is parsed as a container, so TXID is a child chunk
    k = chunk.kid('TXID') if hasattr(chunk, 'kid') else None
    if k is not None and len(k.data) >= 4:
        v = struct.unpack('>I', k.data[:4])[0]
        return None if v == NO_TEXTURE else v
    return None


def assignments(prsm):
    """-> (prism texture id or None, {face id: texture id})"""
    whole = None
    pl = prsm.kid('PLTX')
    if pl is not None:
        whole = _tex_id(pl)
    faces = {}
    for surf in prsm.kids('SURF'):
        su = surf.kid('SUTX')
        if su is None:
            continue
        t = _tex_id(su)
        if t is not None:
            faces[iff.u16(surf.hdr, 0)] = t
    return whole, faces
