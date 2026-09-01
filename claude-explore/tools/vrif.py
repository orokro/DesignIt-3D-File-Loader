"""Decode the VRIF preview thumbnail embedded in every WLB gallery clip.

Layout (all big-endian):
    VRIF
      30 bytes  header (unknown; bytes 4-5 and 10-11 look like a 0x30 size)
      CGRP <len>
        uint32 count
        BMAP <len>            8-bit colour image
          uint16 width, height, depth
          uint16 x3 unknown, uint16 bytesPerRow, uint16 pad, uint32 dataSize
          CMAP <len>          palette, 4 bytes per entry: 00 RR GG BB
          DATA <len>          rows of `bytesPerRow`, `depth` bits per pixel
        BMAP <len>            1-bit mask, same geometry
"""
import struct
from PIL import Image


def _chunks(buf, off, end):
    while off + 8 <= end:
        tag = buf[off:off + 4]
        ln = struct.unpack('>I', buf[off + 4:off + 8])[0]
        yield tag, buf[off + 8:off + 8 + ln]
        off += 8 + ln


def _bmap(payload):
    w, h, depth = struct.unpack('>HHH', payload[0:6])
    stride = struct.unpack('>H', payload[10:12])[0]
    cmap, data = None, None
    for tag, body in _chunks(payload, 16, len(payload)):
        if tag == b'CMAP':
            cmap = [tuple(body[i + 1:i + 4]) for i in range(0, len(body), 4)]
        elif tag == b'DATA':
            data = body
    return w, h, depth, stride, cmap, data


def _unpack(w, h, depth, stride, data):
    out = []
    for y in range(h):
        row = data[y * stride:(y + 1) * stride]
        if depth == 8:
            out.append(list(row[:w]))
        else:
            px = []
            for x in range(w):
                b = row[x // 8]
                px.append((b >> (7 - (x % 8))) & 1)
            out.append(px)
    return out


def decode(vrif_bytes, transparent=(255, 255, 255)):
    """Return a PIL RGB image, using the 1-bit mask where present."""
    maps = []
    for tag, body in _chunks(vrif_bytes, 30, len(vrif_bytes)):
        if tag != b'CGRP':
            continue
        for t2, b2 in _chunks(body, 4, len(body)):
            if t2 == b'BMAP':
                maps.append(_bmap(b2))
    if not maps:
        return None
    w, h, depth, stride, cmap, data = maps[0]
    px = _unpack(w, h, depth, stride, data)
    mask = None
    if len(maps) > 1:
        mw, mh, md, ms, mc, mdata = maps[1]
        if mdata is not None and (mw, mh) == (w, h):
            mask = _unpack(mw, mh, md, ms, mdata)
    im = Image.new('RGB', (w, h), transparent)
    p = im.load()
    for y in range(h):
        for x in range(w):
            if mask is not None and mask[y][x] == 0:
                continue
            i = px[y][x]
            p[x, y] = cmap[i] if cmap and i < len(cmap) else (i, i, i)
    return im
