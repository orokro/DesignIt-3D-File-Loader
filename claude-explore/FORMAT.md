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
  [SLIC] [ESLC] optional cutting planes -- see 4.6         ✅
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
14   8     in-plane offset of the `za` cap (2 x fp16.16)  ✅
22   8     in-plane offset of the `zb` cap (2 x fp16.16)  ✅
30   2     uint16 vertex count N                          ✅
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

**Bytes 14–29 are FOUR fp16.16: an in-plane offset for EACH cap of the sweep** —
`(du, dv)` at `za`, then `(du, dv)` at `zb`. ✅ An offset slides that cap
sideways so the extrusion leans instead of running straight, and a ring between
them takes the linear blend. Neither offset has a component along the sweep, so
a lean can never change the prism's length. Non-zero on **341 prisms (5.1 %)**.

> **This was read as THREE values plus a mystery, and both halves of the mystery
> were the same field.** The old layout had a 3-vector at 14–25, "a small signed
> int16 of unknown meaning" at 26–27, and the vertex count as a uint32 at 28–31.
> The int16 was the *integer* half of the fourth fp16.16, and the uint32 count
> swallowed its *fractional* half.
>
> **Nine prisms prove the count is a uint16 at 30.** Their POLY length is
> impossible under the uint32 reading and exact under this one: `Curtis` declares
> 196612 vertices in a 64-byte chunk (eight times), `Bedroom with Porch`
> 2,696,019,971. All 4212 prisms satisfy `len == 32 + 8 * uint16[30]`; 4203 also
> satisfy the uint32 form, which is why it survived — a clamp hid the rest.
>
> The geometric symptom was worse than the parse one. Reading the fourth value
> as a third VECTOR component put it along the sweep, where an offset is a
> LENGTH CHANGE rather than a lean: the `Picnic Table`'s legs stretched 42 in —
> two down through the floor, two up through the table top — instead of crossing,
> and the `Lawnmower Man`'s handle stays slid off into the air instead of running
> down to the mower. `Curtis`'s diagonal-slat back came out as plain horizontal
> rungs, because its lean lived entirely in the discarded fourth value.
>
> Two prisms with the SAME axis, profile, class and vertex list encoded the same
> physical lean in different slots — which is what proves the triple was never a
> vector in a fixed frame. No permutation of three components can do that; two
> offsets, one per cap, can.

The user's own screenshot of `Bar Sink` in the application is what surfaced it —
its faucet is a spout that *leans* over the basin, and ours stood bolt upright.
That prism carries `(0, −7.87, 0)`. A `6' Work Table` leg carries `(0, −5, 0)`
and a `Conference Table` leg `(0, 5.5, 0)`: splayed legs, which is exactly what
those previews show.

Measured: detached prisms **51 → 25**, and mean silhouette IoU over the 24 clips
that contain a skewed prism **0.7583 → 0.7702**.

Which end moves is decided by `detach.py`: anchoring at `zb` and displacing `za`
gives 25 detached parts, the other way round gives 40. IoU cannot separate them
(0.7702 against 0.7726, on 24 clips — noise), so treat the direction as ✅ by the
sharper oracle but not independently confirmed. Anchoring at `za` is also what
the taper rule already does, which is at least consistent.

**Winding.** The stored polygon's signed area determines which way side quads
face; caps follow from the ring order; a final signed-volume check flips the
shell if it came out inside-out. A per-face "does the normal point away from
the mesh centroid" test is *not* good enough — it mis-orients faces on long or
concave prisms, such as the escalator side panels in `scenes/DEPARTME.VVR`.

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

### 4.4 `POSN` (24 or 48 bytes) — transform

Up to 12 × fp16.16:

| Index | Field | Status |
|---|---|---|
| 0–2 | translation (x, y, z) in inches | ✅ |
| 3–5 | **Euler angles** in radians, stored **(ry, rx, rz)** and applied in that order | ✅ |
| 6–8 | unknown; non-zero in only 2.3 % of parts, always small angle-like values | ❓ |
| 9–11 | scale (sx, sy, sz); **may be negative** (mirroring) | ✅ |

**A POSN is 24 bytes when the scale is identity.** The writer simply stops after
the rotation. 1003 records across the corpus are this short form (789 `PRSM`,
214 `PGRP`), and 131 of them carry a real rotation as well as a real position.
This is easy to get catastrophically wrong, because a 2D `FEAT` `POSN` is *also*
24 bytes — guarding with `len < 48` throws away every short 3D record and drops
those parts at the model origin. Distinguish by context, not by length: only
`PRSM`/`PGRP` reach this code path. Fixing it took the detached-part count from
165 to 49 and is what put Brutus's arms back on his shoulders.

**Fields 3–5 are three Euler angles, not an axis-angle rotation vector.** The
first two are swapped relative to the obvious order, and the composition order
matches the storage order: `R = Ry(v[3]) · Rx(v[4]) · Rz(v[5])`.

This is genuinely hard to pin down, and a first pass got it wrong. A single-axis
rotation reads identically under either model, and a mirrored pair negates the
same two components under both — `Make My Day Brutus`'s two arms carry
`(1.397, -1.0405, 1.7211)` and `(-1.3652, -1.126, -1.7567)`, `v[3]` and `v[5]`
negated while `v[4]` is not, which looks like pseudovector behaviour but is
equally what Euler angles do when the middle field is the rotation about the
mirror axis. Neither the common case nor the obvious mirror test discriminates.

What discriminates is the **distribution of compound values**. 159 parts carry
exactly `(180°, 0, 180°)`, and a whole family carries `(180°, 0, θ)` for θ in
{−175, −135, −90, −65, −45, 45, 56, 90, 135, 170, …}; `(−90°, 0, 180°)` and
`(−90°, 0, −90°)` appear too. 58 % of compound parts have *every* non-zero
component within half a degree of a 45° multiple — the same rate as single-axis
parts. A rotation vector composed from two round turns does not land on round
components, and certainly does not pin one field at exactly 180° across a
family; "flip it over, then turn it" does, and that is what a modelling UI
offers. Under this reading `(180, 0, 180)` with scale `(−1, −1, −1)` is exactly
a mirror in X, which is what those `ID*` furniture variants are.

Two independent measurements agree:

| model | detached parts (of 4083) | mean IoU, compound items |
|---|---|---|
| Euler `yxz`, order `Ry·Rx·Rz` | **26** | **0.7882** |
| Euler `yxz`, order `Rx·Ry·Rz` | 26 | 0.7837 |
| Euler `yxz`, order `Ry·Rz·Rx` | 30 | 0.7858 |
| axis-angle rotation vector | 40 | — |
| every other field→axis map | 62–167 | — |

Sign flips on individual angles, and applying scale after the rotation instead
of before, both make it worse; `R · diag(scale)` with the angles as stored is
the floor.

Fields 6–8 remain unexplained. They are rare enough that ignoring them is
visually harmless everywhere except `Printer w/stand`, whose paper path is the
one object they might explain.

### 4.6 `SLIC` / `ESLC` — cutting planes ✅

`SLIC` holds N planes `(a, b, c, d)` as fp16.16; `ESLC` holds N matching records
of two points lying on each plane plus three angles. The prism keeps the
half-space `n·p + d ≥ 0`; cuts apply in order. Planes are in **object space**,
after the axis permutation.

This is how the program makes wedges (a slab cut corner to corner — the
`PC, Compaq` keyboard) and, far more often, **frusta**: a pointed prism with its
taper truncated. Hence 61 % of pointed prisms carry a `SLIC` against 6 % of
straight ones. Full derivation in `findings/slic.md`.

> **Compact the vertex array after clipping.** The clipper appends the vertices
> it creates and simply stops referencing the ones it removed. Nothing indexes
> them, so drawing is unaffected — but a clipped prism's vertex array still holds
> the geometry that was cut away, so its bounding box is the box of the *uncut*
> prism. That quietly inflated the manifest bounds, the detached-part oracle, and
> the explorer's ground placement, which is why cut objects hovered above the
> floor instead of resting on it.

### 4.7 `SURF` / `FEAT` — per-face overrides ✅

`SURF` carries a 2-byte face index and then a `COLR` (recolour that face), any
number of `FEAT` records (2D shapes on it), or both.

**A `SURF`'s `COLR` is not laid out like a `PRSM`'s.** ✅ There is a 2-byte prefix
first, and the length follows it:

```
 6 B    prefix 1 or 3, then ONE  (a, r, g, b)      96 records
10 B    prefix 2,      then TWO  (a, r, g, b)     452 records
```

A `PRSM`'s own 8-byte `COLR` is the same two-record body with no prefix, and its
two records carry identical RGB in 6643 of 6647 cases — which fits the
application's two-sided-surface model, where a face can be coloured differently
inside and out. The prefix looks like the same outside/inside/both selector
`FEAT` uses, one-based: 1 and 3 take a single colour, 2 takes a pair.

Reading a `SURF` `COLR` at the `PRSM` offsets picks the prefix up as part of the
colour: `00 02 00 ff ff ff 00 ff ff ff` is white, but bytes 1–3 read it as
`(0x02, 0x00, 0xff)`, a dark blue. All 548 per-face recolours were previously
ignored outright. Face numbering is
`side quads (band-major)`, then the two caps, then one face per `SLIC` cut —
99.84 % of indices in the corpus fall in that range.

Rings run from the **high** end of the sweep to the low end, which is why
`POLY`'s two sweep bounds are stored in an order that flips between objects.
Face 0 is the cap at that high end, faces `1 .. bands*n` are the sides, face
`bands*n + 1` is the low cap, and cut faces follow.

**A side face is named after the vertex its edge ARRIVES at, plus one.** The
edge `v_j -> v_j+1` is face `(j+1) + 1`, so face 1 is the edge that closes the
polygon back onto vertex 0:

```
    side_id(band, edge i) = 1 + band*n + ((i + 1) % n)
```

This corrects a long-standing error: the sides were being numbered by walking
the edges BACKWARDS. On a rectangular prism the two rules differ only by
swapping OPPOSITE faces, so every oracle that measures bounding boxes scored
them identically and the renders merely looked odd rather than broken -- the
`Lectern`'s pages painted on its underside, the `Microwave, undercabinet`'s
control panel on its back. On a profile with an odd or irregular vertex count
the rules diverge properly and the decoration lands in mid-air, which is what
the `Bar Sink`'s floating basin was. Measured with `tools/facefit.py`, which
asks which individual FACE an outline fits on rather than which bounding box:

| side numbering | decorations that do not fit their stored face |
|---|---|
| edges backwards (old) | 126 / 2532 (4.98 %) |
| **arriving vertex (current)** | **22 / 2532 (0.87 %)** |

`decalfit.py` fell from 94/2932 to 15/2932 on the same change.

> **Lift a decoration off its face by `SURF_OFFSET` INCHES, not by that many
> local units.** A prism's `W` carries the object's `UNIT` scale and its own
> `POSN` scale, so a fixed local offset shrinks by whatever those come to — 4× on
> a quarter-inch-unit object, 16× on a sixteenth. Divide by
> `|W[:3,:3] · normal|`.

`FEAT`'s 2-byte header is the Outside / Inside / Both selector (values 0, 1, 2).
Full details in `findings/surf.md`.

**A `FEAT`'s own `POSN` comes in two lengths, and the short one is a trap.**

```
24 B   (x, y, rotation, ~0, sx, sy)      2194 records
12 B   (x, y, rotation)                   338 records, scale implied (1, 1)
```

Exactly the same omit-the-default trick the 3D `POSN` plays (§4.4), and it bites
the same way: requiring 24 bytes returns `(0, 0)` for every short record, so 338
decorations lose their placement and pile up at their face's origin corner.

That is what put `Mac LC`'s and `Mac IIci`'s screens off the side of the
monitor while `Mac Quadra`, the two `Computer Desk` Macs and the
`Corner Work Center` Mac — same class of object, full-length records — were
pixel-perfect. **Same object class, some right and some wrong, is the signature
of a short-record bug**, and I misread it twice: first as evidence for two
different coordinate conventions keyed on a zero translation, then as a
"sentinel" meaning *centre me*. Both were elaborate wrong rules built on a
parsing failure. The real lesson: when a rule needs an exception for a specific
subset, check whether that subset is defined by a parsing failure before
inventing semantics for it.

There is **one** placement convention: the outline is measured from the face's
minimum corner, offset by `(tx, ty)`.

Field 2 is a **rotation** in radians about the decoration's own origin —
non-zero on 4.3 % of decals, with unmistakable values (π, π/2, −π/2, π/4, 5.359,
−0.2618). Field 3 is zero on 99.7 % of the long records. Fields 4 and 5 are
scale, exactly 1.0 on 94 % of them.

> **`FEAT`'s side selector: 1 is OUTSIDE, not inside.** ✅ It accounts for 2048 of
> the 2520 gallery decorations; 2 is both (412) and 0 is rare (60). Reading 1 as
> "inside" pushes four decorations in five 0.05 in *into* their own prism, where
> the depth buffer hides them. This stayed invisible for as long as the
> short-record bug kept decals hanging off their faces in open air — they were
> only visible *because* they were misplaced — and surfaced the instant placement
> was fixed and they landed flush. Fixing both together is what finally put the
> `Mac LC` screen on its monitor, the `Bar Sink`'s doors on its cabinet and the
> `Mac Classic`'s disk slot on its case.

Applying both took decals-outside-their-prism from **11.8 % to 3.2 %**
(`tools/decalfit.py`) — though note that metric barely moved on the short-record
fix itself, which is a fair warning about how little it sees (see section 9).

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
| `SLIC` | 5063 | PRSM | 2 + 16N | cutting plane ✅ |
| `ESLC` | 5063 | PRSM | 2 + 40N | two points on that plane + angles, same N ✅ |
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
| 1 | `ESLC[3..5]` angles — not needed for geometry (see `findings/slic.md`) | Low |
| 3 | `POSN` fields 6–8, and `POLY[26:28]` (a small signed int16, non-zero on 72 of the 341 skewed prisms) | Medium |
| 4 | A few clipped prisms are not perfectly watertight (`scenes/REEVES.VVR`), so their volume depends on cap tessellation | Low |
| 2 | **3.2 % of `FEAT` decals still land outside the prism they decorate** (94 of 2932). Worst: `Tiled Bedroom` 72 in, `Red Bedroom` 60 in, `Springs Kitchen` 49 in, `Jersey Cow` 34 in, `Bar Sink` 20 in. Both remaining shapes look like a face-index problem on prisms with many `SLIC` cuts: `Bar Sink`'s stray panel is 13.6 × 15.6 in but is assigned to a face that is 19.7 × 0.5 in. Sweeping six face-numbering variants did not beat the current one, so the answer is probably not a global renumbering | **High** |
| 5 | `Printer w/stand`'s paper path: four identical sheets whose `POSN` differs only in `v[3]` and position, all carrying scale `(-0.112, -1.0, -0.585)` and fields 6–8 `(0, -0.174, 0)`. The `VRIF` preview draws them as one continuous curled ribbon, so they are probably chained rather than independent — note the `CONN` chunk on that clip | Medium |
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

`tools/detach.py` is a second, sharper oracle: it counts prisms whose world AABB
touches no other prism's. Silhouette IoU forgives a part rotated into the wrong
place — a 50×50 preview simply cannot see it — but real assemblies are connected,
so "floating detached piece" is directly measurable. It is what settled Euler vs
axis-angle when IoU could not, and what showed the short-`POSN` bug at a glance.
Current baseline: **25 isolated of 6487** gallery parts (0.39 %), and a good
share of those are legitimately separate objects (`Cannisters`, `Patio
Ensemble`). Treat it as the regression bar alongside IoU.

`tools/decalfit.py` is the third oracle: every `FEAT` decal's world box must sit
inside the box of the prism it decorates. Neither of the others can see a decal
at all — IoU because 50×50 hides it, detach.py because it only looks at prisms.
Current baseline: **94 of 2932 (3.2 %)**, down from 346 (11.8 %). Measured at
the level of the 2D face frame rather than the world box it is 147 of 2520
(5.8 %); six alternative face numberings were swept against that figure after
the coordinate-convention and oblique-sweep fixes and none beat the current one,
so whatever remains is not a global renumbering.

Note that decal geometry is deliberately **not** identical between the two
implementations: Python lifts each decoration off its face by `SURF_OFFSET` and
emits two copies for a Both-sided `FEAT`, while the JS leaves them coplanar and
lets the renderer's polygon offset and `layer` separate them. So `parity.py` /
`parity.mjs` exclude decorations by default (set `SURF=1` to include them, and
expect area and volume to differ). To check decal *placement* across the two,
compare per-decal world bounding boxes instead — they agree to 0.01 in.

`tools/clip.py` (plane clipping) is verified watertight: the two complementary
half-cuts of a cube sum back to the exact original volume for every plane
tested, including oblique ones.
