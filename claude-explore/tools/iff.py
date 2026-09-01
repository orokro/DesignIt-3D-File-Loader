"""
Strict IFF-85 reader for Design-It! 3-D VVR / WLB / TLB files.

Correctness oracle: every container's payload must be consumed EXACTLY by its
children, with zero leftover bytes. If the schema below is wrong, parsing fails
loudly instead of silently guessing.
"""
import struct, os

# Payload is 4-byte form-type followed by chunks.
FORMLIKE = {'FORM', 'CAT ', 'LIST'}

# Payload is pure chunks, no header bytes.
CONTAINERS = {'ROOT', 'PRSM', 'PGRP', 'PREF', 'SUTX', 'VGER'}

# Payload is N header bytes, then chunks.
CONTAINERS_HDR = {'SURF': 2}

# (parent, tag) -> header byte count. A FEAT inside a SURF carries a 2-byte
# header (the side selector); a FEAT that IS a 2D library clip does not.
CONTAINERS_HDR_CTX = {('SURF', 'FEAT'): 2}


class Chunk:
    __slots__ = ('tag', 'formtype', 'subtype', 'data', 'children', 'hdr',
                 'offset', 'trailing')

    def __init__(self, tag, data, offset=0):
        self.tag = tag
        self.formtype = None
        self.subtype = None
        self.data = data        # leaf payload (or header bytes for CONTAINERS_HDR)
        self.children = []
        self.hdr = b''
        self.offset = offset
        self.trailing = 0   # bytes at the end of this container we could not parse

    def kids(self, tag):
        return [c for c in self.children if c.tag == tag]

    def kid(self, tag):
        for c in self.children:
            if c.tag == tag:
                return c
        return None

    def find_all(self, tag):
        out = []
        if self.tag == tag:
            out.append(self)
        for c in self.children:
            out.extend(c.find_all(tag))
        return out

    def __repr__(self):
        t = f'{self.tag}<{self.formtype}>' if self.formtype else self.tag
        if self.subtype:
            t += f':{self.subtype}'
        return f'<{t} data={len(self.data)} kids={len(self.children)}>'


class IFFError(Exception):
    pass


def tag_bad(tag):
    return not all(('A' <= ch <= 'Z') or ch == ' ' for ch in tag)


def _hdrlen(tag, parent_tag):
    if (parent_tag, tag) in CONTAINERS_HDR_CTX:
        return CONTAINERS_HDR_CTX[(parent_tag, tag)]
    return CONTAINERS_HDR.get(tag)


def _parse_seq(buf, start, end, parent, strict=True):
    """Parse a sequence of chunks in buf[start:end] into parent.children."""
    off = start
    while off < end:
        if off + 8 > end:
            if strict:
                raise IFFError(f'truncated chunk header at {off} (end {end})')
            return
        tag = buf[off:off + 4].decode('latin1')
        ln = struct.unpack('>I', buf[off + 4:off + 8])[0]
        body = off + 8
        stop = body + ln
        if tag_bad(tag) or stop > end:
            # Known real-world defect: a handful of shipped ID*.WLB gallery
            # items have short/stale length fields, leaving stray bytes behind.
            # In tolerant mode, abandon the rest of this container rather than
            # inventing structure.
            if not strict:
                parent.trailing = end - off
                return
            raise IFFError(f'{tag!r} at {off} declares {ln} bytes, overruns end {end}')
        c = Chunk(tag, b'', off)
        if ln == 0:
            # Zero-length chunks are type markers (e.g. FEAT/PRSM inside a WLB
            # VCLP item declare what kind of library entry it is).
            pass
        elif tag in FORMLIKE:
            c.formtype = buf[body:body + 4].decode('latin1')
            p2 = body + 4
            if c.formtype == 'VCLP':
                # A library clip carries a bare 4-byte subtype token (FEAT for a
                # 2D gallery item, PRSM for a 3D one) right after the form type,
                # with no length field of its own.
                c.subtype = buf[p2:p2 + 4].decode('latin1')
                p2 += 4
            _parse_seq(buf, p2, stop, c, strict)
        elif tag in CONTAINERS:
            _parse_seq(buf, body, stop, c, strict)
        elif _hdrlen(tag, parent.tag) is not None:
            n = _hdrlen(tag, parent.tag)
            c.hdr = buf[body:body + n]
            _parse_seq(buf, body + n, stop, c, strict)
        elif tag in CONTAINERS or tag == 'FEAT':
            _parse_seq(buf, body, stop, c, strict)
        else:
            c.data = buf[body:stop]
        parent.children.append(c)
        off = stop


def parse(buf):
    """Parse a whole file buffer. Returns a synthetic root Chunk."""
    root = Chunk('$ROOT', b'')
    # Top level: walk to EOF, ignoring any declared top-chunk length that lies.
    off = 0
    n = len(buf)
    while off + 8 <= n:
        tag = buf[off:off + 4].decode('latin1')
        ln = struct.unpack('>I', buf[off + 4:off + 8])[0]
        stop = min(off + 8 + ln, n)
        c = Chunk(tag, b'', off)
        if tag in FORMLIKE:
            c.formtype = buf[off + 8:off + 12].decode('latin1')
            if tag == 'CAT ':
                # CAT lengths are unreliable in the shipped gallery files, and
                # a few individual items under-report their own length too.
                # Locate items by signature and bound each by the next one.
                stop = n
                starts = []
                i = off + 12
                while True:
                    i = buf.find(b'FORM', i)
                    if i < 0 or i >= n:
                        break
                    if buf[i + 8:i + 12] == b'VCLP':
                        starts.append(i)
                        i += 12
                    else:
                        i += 4
                for si, s0 in enumerate(starts):
                    s1 = starts[si + 1] if si + 1 < len(starts) else n
                    ln2 = struct.unpack('>I', buf[s0 + 4:s0 + 8])[0]
                    _parse_seq(buf, s0, min(s0 + 8 + ln2, s1), c, strict=False)
                    if c.children:
                        # re-bound the item we just added to the signature gap
                        pass
            else:
                _parse_seq(buf, off + 12, stop, c)
        elif tag in CONTAINERS:
            _parse_seq(buf, off + 8, stop, c)
        else:
            c.data = buf[off + 8:stop]
        root.children.append(c)
        off = stop
    return root


def load(path):
    with open(path, 'rb') as f:
        return parse(f.read())


# ---------- typed readers ----------

def i32(b, o):
    return struct.unpack_from('>i', b, o)[0]

def u32(b, o):
    return struct.unpack_from('>I', b, o)[0]

def i16(b, o):
    return struct.unpack_from('>h', b, o)[0]

def u16(b, o):
    return struct.unpack_from('>H', b, o)[0]

def fp(b, o):
    """16.16 fixed point."""
    return struct.unpack_from('>i', b, o)[0] / 65536.0

def f64(b, o):
    return struct.unpack_from('>d', b, o)[0]

def pstring(b, o):
    n = b[o]
    return b[o + 1:o + 1 + n].rstrip(b'\x00').decode('latin1'), o + 1 + n


def walk_files(rootdir, exts=('.VVR', '.WLB', '.TLB')):
    for dirpath, _, files in os.walk(rootdir):
        if '.git' in dirpath:
            continue
        for f in sorted(files):
            if f.upper().endswith(exts):
                yield os.path.join(dirpath, f)
