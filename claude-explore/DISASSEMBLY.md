# Reading the original binary

`D3D/DESIGNIT/DESIGNIT.EXE` is a **16-bit NE (Windows 3.x) executable**, 1.65 MB,
122 segments (121 code + 1 data), ~1.2 MB of code. It is compiled for 386 — the
code is 16-bit segmented but uses 32-bit operand prefixes (`0x66`), which is why
the four-character IFF tags appear as single **dword** compares.

This is the source of truth. Three long-running questions were settled from it in
an afternoon, two of them confirming answers we had only inferred statistically.

## Method

No Ghidra needed so far — `pip install capstone` and 40 lines of Python.

```python
b   = open('DESIGNIT.EXE','rb').read()
off = struct.unpack_from('<I', b, 0x3c)[0]      # e_lfanew -> 'NE'
ne  = b[off:]
shift  = struct.unpack_from('<H', ne, 0x32)[0]  # sector alignment shift (9 = 512)
segtab = struct.unpack_from('<H', ne, 0x22)[0]
cseg   = struct.unpack_from('<H', ne, 0x1c)[0]
# each entry: sector, length, flags, minalloc  (file offset = sector << shift)
md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_16)
```

**How to find things.** The chunk tags are not stored as strings — searching for
`POLY` as ASCII finds only a UI string. They are dword immediates, so search for
each tag's bytes **reversed** (`YLOP`). Segment 28 holds 36 of them: it is the
IFF reader. `java` is present in the cloud container if Ghidra is ever wanted,
but targeted disassembly has been enough.

## The chunk dispatcher — segment 28 (file offset 0x4c600)

An MSVC `switch`: 14 dword case values in ascending order at seg28 + 0x7951,
then a table of 16-bit jump targets. **The case list includes `MESH` and `LGHT`,
neither of which occurs anywhere in our corpus** — the app supports chunk types
the shipped content never uses.

| chunk | stub | parser |
|---|---|---|
| COLR | 0x74d4 | 0x84f2 |
| CONN | 0x759c | 0x7edf |
| DATA | 0x7495 | 0x82dd |
| LGHT | 0x74bf | 0x843b |
| MESH | 0x7513 | 0x8878 |
| NAME | 0x7480 | 0x821f |
| PGRP | 0x7566 | 0x7d14 (arg 1) |
| PLTX | 0x74e9 | far call, other segment |
| POLY | 0x74fe | **0x85d6** |
| POSN | 0x7552 | 0x8f94 |
| PRSM | 0x7581 | 0x7d14 (arg 0) |
| SLIC | 0x7528 | 0x8c7e |
| SURF | 0x753d | **0x8e99** |
| UNIT | 0x74aa | 0x839b |

PRSM and PGRP share one parser, distinguished by a 0/1 flag.

## CONFIRMED: the POLY layout

The parser at **0x85d6** reads fields into the prism struct in this order. The
first pushed argument is a type code; the struct offset is the destination.

| struct | type | bytes | field |
|---|---|---|---|
| +0x26 | 2 | 2 | the leading word (b[0:2]) — a real field, not padding |
| +0x28 | 1 | 1 | sweep axis |
| +0x29 | 1 | 1 | profile |
| +0x2a | 2 | 2 | nseg |
| +0x2c | 0x65 | 4 | sweep bound za |
| +0x30 | 0x65 | 4 | sweep bound zb |
| +0x34 | **0x6a** | **8** | **cap offset A (du, dv)** |
| +0x3c | **0x6a** | **8** | **cap offset B (du, dv)** |
| — | 2 | 2 | **vertex count, as a WORD** |
| loop | 0x6a | 8 each | vertices, pointer stepped by 8 |

Type 0x65 is 4 bytes and type **0x6a is 8** — proved by the vertex loop, which
reads one 0x6a per vertex and advances the pointer by exactly 8.

So there are **two 8-byte cap offsets, not a 12-byte vector plus a mystery**, and
the count is a **u16, not a u32**. This is precisely the layout deduced from the
nine prisms whose chunk length was impossible under the old reading — now
confirmed by the application itself.

## CONFIRMED: bands per profile, and the sphere

`0x58b2` returns the band count, switching on the profile byte at +0x29:

| profile | bands |
|---|---|
| 1 straight | 1 |
| 2 pointed | 1 |
| 3 diamond | 2 |
| 4 rounded | `nseg` |
| **5 sphere** | **`nseg` shifted left by 1 — 2 × nseg** |

`d1e0` (`shl ax, 1`) is the whole answer. `nseg` counts bands per QUARTER turn,
so a half-turn sphere takes twice as many. Confirms the change made from the
SURF face-id overflows and the never-reaches-full-radius argument.

`0x57fb` returns the CAP count, also by profile: straight → **2**, pointed and
rounded → **1**, diamond and sphere → **0**.

## CONFIRMED: the face numbering

`0x56f4` (called by the SURF parser to validate a face index) is
`0x573b + 0x57b2` — base faces plus cut faces. For a POLY prism (type word
`0x100`, which the POLY parser writes at +6), base faces are
`0x57fb + 0x5861` = **caps + sides**, and `0x5861` computes
**sides = vertexCount × bands**.

`0x5929` maps a cap to its index: the high cap is **0**, the low cap is
`total − 1`. Cut faces follow. That is exactly the caps-bracket-the-sides
numbering, independently confirmed.

For a one-cap profile the code compares `za` and `zb` to decide which end carries
it — so a pointed prism has a face 0 only when `za <= zb`.

## The five profiles are really THREE

`0x189e` is `setProfile`, and `0x1cb3` is `setNseg`. Between them they show that
the profile codes are not five independent shapes:

```
    nseg becomes 1  ->  ROUNDED (4) becomes POINTED (2)
                        SPHERE  (5) becomes DIAMOND (3)
    nseg leaves 1   ->  POINTED (2) becomes ROUNDED (4)
                        DIAMOND (3) becomes SPHERE  (5)
```

So **pointed IS rounded with one band, and diamond IS sphere with one band** —
the app rewrites the profile byte as `nseg` crosses 1. That is exactly consistent
with the band counts (rounded `nseg` -> pointed 1; sphere `2*nseg` -> diamond 2)
and the cap counts (rounded 1 = pointed 1; sphere 0 = diamond 0), which is a
useful cross-check that those readings are right.

`setProfile` converts a prism between families one step at a time via `0x19c7`
(straight <-> curved) and `0x1aca` (quarter turn <-> half turn), resizing the
SURF collection as it goes so decoration face indices survive the change.

## SURF carries no orientation

The parser at **0x8e99** reads a single `u16` face index, bounds-checks it
against the face count, fetches that face, and then reads nested chunks. **There
is no orientation or frame field.** Whatever decides the 2D frame of a face is
computed in the renderer, not stored — so the space-station frame question will
not be answered by finding a flag we missed.

## Where to look next

The open question is the **face 2D frame** (see [[vvr-decal-sides]]). It is not in
the reader. The route is `0x5e7d`, called by the SURF parser right after the
bounds check to fetch face *n* of a prism — following that into the renderer
should reach the code that builds a face's axes.

Also unexamined: the `MESH` parser at 0x8878 and `LGHT` at 0x843b, for chunk
types the corpus never uses.
