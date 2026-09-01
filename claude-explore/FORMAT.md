# Design-It! 3-D — VVR / WLB / TLB Format Specification

Reverse-engineered September 2026. Every claim below is either verified by an
exact-byte parse across the whole corpus (767 files) or by rendering the result
and comparing against the application's own gallery screenshots.

**Status legend:** ✅ confirmed · 🟡 strong hypothesis · ❓ open

---

## 1. Container: EA IFF-85

The format is standard **EA IFF-85** (the Amiga/Deluxe Paint interchange
format), big-endian throughout. It is not a bespoke format. ✅

```
[4-byte ASCII tag][uint32 big-endian payload length][payload]
```

Verified by parsing **766 of 767** files with zero leftover bytes in any
container. (The single failure, `MiscVVR/JUSTCUBE_forced_formatting.VVR`, is a
line-ending-mangled copy — a `\n` inserted inside the `VMDL` tag — not a format
variant.)

Notably, chunks are **not** padded to even boundaries as canonical IFF requires;
lengths are exact and always happen to be even.

### File types

| Extension | Top-level | Meaning |
|---|---|---|
| `.VVR` | `FORM<VMDL>` | A scene or model ("Visual MoDeL") |
| `.WLB` | `CAT <VCLP>` | A gallery library — many `FORM<VCLP>` clips |
| `.TLB` | `FORM<VMDL>` | Texture library (Key Design 3-D only) |

### Container rules

| Tag | Payload |
|---|---|
| `FORM`, `CAT `, `LIST` | 4-byte form type, then chunks |
| `FORM<VCLP>` | form type, then a **bare 4-byte subtype token** (`FEAT` or `PRSM`, no length field), then chunks ✅ |
| `ROOT`, `PRSM`, `PGRP`, `PREF`, `SUTX`, `VGER` | chunks only |
| `SURF` | 2 header bytes, then chunks ✅ |
| `FEAT` | 2 header bytes then chunks **when inside `SURF`**; chunks only when it is a top-level 2D library clip ✅ |
| any tag with length 0 | a type marker, not a container ✅ |

### Two real-world defects to tolerate ✅

1. The `CAT ` length in shipped `3GALLERY/ID*.WLB` files is **stale** — e.g.
   `IDCHAIR1.WLB` declares 124342 bytes in a 153180-byte file, and valid clips
   continue past the declared end. The app appended items without rewriting the
   header.
2. A few individual `FORM<VCLP>` clips in those same files **under-report their
   own length**, leaving ~20 stray bytes before the next clip.

The reader locates clips by scanning for the `FORM????VCLP` signature and bounds
each clip by the start of the next one, rather than trusting any length field.

---

## 2. Data types

| Type | Size | Notes |
|---|---|---|
| `fp16.16` | 4 | `int32 / 65536.0` — the universal numeric type |
| `f64` | 8 | IEEE-754 big-endian, only in `UNIT` |
| `pstring` | var | length byte + ASCII, null-padded to even total |

**Units and axes.** `UNIT` always holds the double `0.0254` — metres per unit —
so **1 unit = 1 inch**. **Z is up.** ✅ (Confirmed: every gallery primitive sits
at `z = 48` with a ±48 extrusion, i.e. resting on the floor and 96 in = 8 ft
tall.)

---

## 3. Scene structure (`.VVR`)

```
FORM<VMDL>
  VERS  (4)
  PREF  → FORM<VPRF>   application preferences (PRND PNAV PDEF PEDT PUNT
                        TRNS PMOD PWIN) — no geometry, safe to skip
  CPRF, VPRF, LAYR
  ROOT
    UNIT (8)     1 unit in metres (0.0254)
    LGHT         lighting  ❓
    COLR (8)     scene background
    ELGT         environment lighting  ❓
    PRSM / PGRP  … the actual geometry
  TXTB           texture bank (0 bytes unless textures are used)
```

---

## 4. `PRSM` — the one and only geometry primitive ✅

Everything visible in Design-It! 3-D is a **prism**: a 2D polygon swept along an
axis with a profile function. There is no mesh format, no vertex editing — which
is exactly why the editor only lets you place and stretch whole objects.

```
PRSM
  LOCK (2)      lock flags
  LNUM (2)      layer number
  COLR (8)      colour
  POLY (var)    the 2D cross-section + sweep parameters
  POSN (48)     transform
  [SLIC] [ESLC] optional per-slice profile data  ❓
  [PLGR (2)]    came-from-a-library flag
  [SURF …]      2D decorations applied to faces
  [PLTX (32)]   texture assignment (Key Design 3-D)  ❓
```

### 4.1 `POLY` — cross-section and sweep

```
off  size  field
0    1     always 0x00
1    1     polygon class: 1 = user-edited, 2 = rectangle, 3 = regular N-gon
2    1     sweep axis: 3 = Z, 2 = Y, 1 = X          ✅
3    1     profile: 1 straight, 2 pointed, 3 diamond,
                    4 rounded, 5 sphere              ✅
4    2     uint16 nseg — curve subdivision           ✅
6    4     fp16.16  sweep bound A
10   4     fp16.16  sweep bound B
14   14    zeros (reserved)                          ❓
28   4     uint32 vertex count N
32   N×8   vertices, each (x: fp16.16, y: fp16.16)
```
Total size `32 + 8N`. Verified against file-size deltas across the Basic
gallery: triangle 998 → 16-gon 1102, exactly 8 bytes per extra vertex.

**`nseg` is 1 for every straight/pointed/diamond prism in the entire corpus, and
2, 3, 5 or 12 only for rounded and sphere.** It is the curve resolution, not a
segment count for flat shapes. ✅

**Sweep bounds.** The two fp16.16 values are the extents along the sweep axis;
their *order* flips between variants but `min`/`max` is what matters for
geometry. Default gallery primitives use ±48 (a 96-inch, 8-foot object). The
ordering flip is ❓ — possibly a normal-direction hint.

**Vertices** are a regular N-gon of circumradius 48, wound clockwise. For
even-sided polygons the centroid is at the origin; for the triangle the
*bounding box* is centred instead, so the centroid sits at y = −12. ✅

### 4.2 Profile functions ✅

Sweeping from `t = 0` at `zmin` to `t = 1` at `zmax`, with cross-section scale
`s`:

| Profile | Rings | Geometry |
|---|---|---|
| 1 straight | `(0,1) (1,1)` | prism / cylinder |
| 2 pointed | `(0,1) (1,0)` | cone / pyramid |
| 3 diamond | `(0,0) (½,1) (1,0)` | bipyramid |
| 4 rounded | `θ = kπ/2n`, `z ∝ sin θ`, `s = cos θ` | dome |
| 5 sphere | `θ = kπ/n`, `z ∝ (1−cos θ)/2`, `s = sin θ` | sphere |

Verified visually against the Basic and Advanced gallery screenshots.

### 4.3 Sweep axis is a cyclic permutation ✅

`POLY[2]` maps the local frame `(u, v, w)` — polygon x, polygon y, sweep — onto
object space:

| `POLY[2]` | Mapping | Gallery |
|---|---|---|
| 3 | `(X,Y,Z) = (u,v,w)` | upright — BASIC, ADVANCED |
| 2 | `(X,Y,Z) = (v,w,u)` | swept along Y — `_F` galleries |
| 1 | `(X,Y,Z) = (w,u,v)` | swept along X — `_R` galleries |

Derived from the Dining Chair and Coffee Table, where leg, stretcher and
armrest extents only reconcile under this mapping, then confirmed by rendering.
These are pure cyclic permutations (determinant +1), so winding is preserved.

### 4.4 `POSN` (48 bytes) — transform

12 × fp16.16:

| Index | Field | Status |
|---|---|---|
| 0–2 | translation (x, y, z) in inches | ✅ |
| 3–5 | rotation (rx, ry, rz) in radians | ✅ |
| 6–8 | unknown; non-zero in only 1.8 % / 0.6 % / 0.5 % of objects, always small angle-like values | ❓ |
| 9–11 | scale (sx, sy, sz); **may be negative** (mirroring) | ✅ |

Composed as `T · Rz · Ry · Rx · S`. Fields 6–8 are rare enough that ignoring
them is visually harmless; they may be shear, or a second rotation.

### 4.5 `COLR` (8 bytes)

Two 4-byte records, `00 RR GG BB` then `FF RR GG BB`, RGB identical in every
observed file. Rendering uses bytes 1–3. The leading `00`/`FF` is 🟡 a
front/back face flag for a renderer with no depth buffer. 2D `FEAT` colours are
a single 4-byte `A RR GG BB` where alpha encodes opaque / translucent /
transparent. ❓

---

## 5. Hierarchy: `PGRP` — and the trap ✅

`PGRP` groups prisms, and groups may nest. It carries its own `LOCK`, `LNUM`
and `POSN`.

> **Child transforms are absolute, not relative.** A `PGRP`'s `POSN` must **not**
> be composed onto its children. Every `PRSM` stores its final world transform
> directly; the group's `POSN` is a redundant record of the group's own pivot
> for editing.

Proof: in `MODELS/A10.VVR` a nested `PGRP` carries `rot = (π,0,0)` with negative
scales, and *its children carry the same flip again*. Composing double-flips
them and scatters the model; treating child transforms as absolute assembles a
correct A-10. The same test on `BULLDOG.VVR` (biplane) and `APOLLO.VVR`
(Saturn V) confirms it.

This is almost certainly why previous attempts at a loader produced exploded
models.

---

## 6. Galleries (`.WLB`)

```
CAT <VCLP>
  FORM<VCLP> PRSM|FEAT        ← bare subtype token, no length
    VERS (4)
    NAME (pstring)            "Adirondack Chair"
    VRIF (4554)               fixed-size preview thumbnail  ❓
    PRSM | PGRP | COLR+POLY+POSN   ← the clip's geometry
    TXTB (0)
```

`3GALLERY/*.WLB` hold 3D clips (`PRSM` subtype); `2GALLERY/*.WLB` hold 2D
surface features (`FEAT` subtype) — doors, windows, shapes. A gallery is itself
laid out as a scene: each clip's `POSN` holds its position on the gallery's
sheet, which is why clip coordinates are large and arbitrary.

Dragging a clip into a scene copies its `PRSM` tree verbatim and rewrites only
the top-level `POSN` translation. ✅ (The user's 130 single-object exports match
the gallery definitions byte-for-byte in `POLY` and `COLR`.)

---

## 7. Complete chunk census

Counts across all 767 files.

| Tag | Count | Parent(s) | Payload | Meaning |
|---|---|---|---|---|
| `COLR` | 138282 | FEAT, PRSM, SURF | 4/6/8/10 | colour ✅ |
| `POSN` | 132411 | FEAT, PRSM, PGRP | 12/24/48 | transform ✅ |
| `POLY` | 126738 | FEAT, PRSM | 32+8N | polygon ✅ |
| `FEAT` | 71795 | SURF, FORM | container | 2D feature ✅ |
| `LNUM` | 60616 | PRSM, PGRP | 2 | layer number |
| `LOCK` | 57607 | PRSM, PGRP | 2 | lock flags |
| `PRSM` | 54943 | PGRP, PRSM, ROOT | container | prism ✅ |
| `SURF` | 18060 | PRSM | container | face decoration set ✅ |
| `PLGR` | 13027 | PRSM | 2 | from-library flag |
| `PGRP` | 5673 | PGRP, FORM, PRSM | container | group ✅ |
| `SLIC` | 5063 | PRSM | 2 + 16N | per-slice data ❓ |
| `ESLC` | 5063 | PRSM | 2 + 40N | per-slice data, same N ❓ |
| `UNIT` | 3439 | FORM, PGRP, ROOT | 8 | metres per unit ✅ |
| `NAME` | 3035 | FORM | pstring | clip name ✅ |
| `VRIF` | 3008 | FORM | 4554 | preview thumbnail ✅ *(decoded — see `findings/oracle.md`)* |
| `TXTB` | 2520 | FORM | 0 … 123144 | texture bank ❓ |
| `CONN` | 1807 | PGRP, PRSM, ROOT | var | snap/connection points ❓ |
| `LGHT` / `ELGT` | 616 each | ROOT, PRSM | var | lighting ❓ |
| `PLTX` | 474 | PRSM | 32 | **texture assignment** ❓ *(undocumented before)* |
| `SUTX` `TXID` `TXOD` `TATR` | 115 each | SURF / SUTX | 0–4 | surface texture ❓ |
| `SFTX` | 87 | FEAT | 20 | **2D feature texture** ❓ *(undocumented before)* |
| `VGER` / `VGRS` | 4 each | FORM / VGER | 4 | version group |
| preference chunks | 542 each | FORM | var | `PRND PNAV PDEF PEDT PUNT TRNS PMOD PWIN CPRF VPRF LAYR` — no geometry |

`BMAP` and `DATA` do **not** occur anywhere in the corpus.

`SLIC` and `ESLC` always appear together with the **same record count** — they
are parallel arrays over the same N slices, 16 and 40 bytes per record. N is
unrelated to `nseg`.

---

## 8. Open questions, by priority

| # | Question | Priority |
|---|---|---|
| 1 | `SLIC` / `ESLC` record semantics — plane + two points on it are decoded, but their geometric role is not (see `findings/slic.md`) | High |
| 2 | `SURF` / `FEAT` placement: which face, and the 2D-on-3D projection | High |
| 3 | `POSN` fields 6–8 | Medium |
| 4 | Sweep-bound ordering flip | Medium |
| 5 | `PLTX` / `SFTX` / `TXTB` — the Key Design 3-D texture system | Medium |
| 6 | `COLR` two-record meaning; `FEAT` alpha semantics | Medium |
| 8 | `CONN` snap points | Low |
| 9 | `LGHT` / `ELGT` | Low |

---

## 9. Validation

`tools/score.py` measures reconstruction fidelity objectively against the
application's own `VRIF` previews — 3,008 ground-truth images. See
`findings/oracle.md` for how the metric works and why a fixed camera gives
misleading numbers.

Current baseline: **mean best-view silhouette IoU 0.766** over the 157 gallery
items containing sliced prisms. Treat that as the regression bar.

`tools/clip.py` (plane clipping) is verified watertight: the two complementary
half-cuts of a cube sum back to the exact original volume for every plane
tested, including oblique ones.
