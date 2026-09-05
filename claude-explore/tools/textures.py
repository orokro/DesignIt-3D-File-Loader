"""Decode the texture system: TXTB tables, and which face each texture lands on.

    TXTB                      the texture TABLE, embedded in the file
      TXTE                    one texture
        TXID  u32             id
        TXNM  64 B            name
        TXPD  [w:u16][h:u16][bpp:u16][pad][rowbytes:u32][size:u32]
                CMAP  256 x (pad, r, g, b)
                <pixels>      8-bit palette indices, rowbytes per row
        TXST  43 B            tiling: see tile_size()

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


def wrap_flags(body):
    """TXST -> (repeat_u, repeat_v) as booleans.

    Bytes 39 and 40 split the corpus's 56 distinct textures cleanly into 42 at
    `01 01` and 14 at `00 00`, and the names say what the split is: everything
    at 01 is a seamless MATERIAL (brick, marble, planks, tile, turf, checker,
    stripes) and everything at 00 is a picture meant to be shown ONCE --
    `CloudScape 1.0`, `Mountains 1.0`, `Trees 1.0`, `VR Logo`, `Single
    Contemporary Door`, and `School Bk Depos 2`, which is a photograph of the
    Texas School Book Depository stretched over the building in `DEALEY`.

    Without this the depository tiles a 32-inch photo across a hundred feet of
    wall, which is what it was doing.
    """
    if len(body) < 41:
        return (True, True)
    return (body[39] != 0, body[40] != 0)


def tile_size(body):
    """TXST -> (u, v) INCHES PER TILE.

    These two fields are 8.24 fixed point, NOT the 16.16 the rest of the format
    uses: `0x40000000` reads as 16384 under 16.16 and as 64 under 8.24, and the
    corpus values -- 32, 45, 55, 64, 88, 90, 128 -- are sane inches-per-tile for
    brick, stone and panelling. Bytes 20 and 24 are a pair of 1.0 scale factors
    in the same format.

    This was implemented in `web/src/textures.js` and never here, so the Python
    silently fell back to 64 on every texture in the corpus while the JS used
    the real value -- the two renderers disagreed about texture scale for weeks
    and no oracle noticed, because parity measures geometry and geometry is
    unaffected. Anything decoded in one implementation belongs in both the same
    day.
    """
    if len(body) < 36:
        return None
    u = struct.unpack('>I', body[28:32])[0] / (1 << 24)
    v = struct.unpack('>I', body[32:36])[0] / (1 << 24)
    return (u if u > 0.01 else 64.0, v if v > 0.01 else 64.0)


def table(root):
    """Every texture in a file -> {id: {'name', 'w', 'h', 'rgb', 'tile', 'wrap'}}"""
    out = {}
    def walk(n):
        for k in n.children:
            if k.tag == 'TXTB':
                for tag, body in subchunks(k.data):
                    if tag != 'TXTE':
                        continue
                    tid = name = img = None
                    tile = (64.0, 64.0)
                    wrap = (True, True)
                    for t2, b2 in subchunks(body):
                        if t2 == 'TXID' and len(b2) >= 4:
                            tid = struct.unpack('>I', b2[:4])[0]
                        elif t2 == 'TXNM':
                            name = b2.split(b'\0')[0].decode('latin1', 'replace')
                        elif t2 == 'TXPD':
                            img = decode_bitmap(b2)
                        elif t2 == 'TXST':
                            tile = tile_size(b2) or tile
                            wrap = wrap_flags(b2)
                    if tid is not None:
                        e = {'name': name, 'tile': tile, 'wrap': wrap}
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
