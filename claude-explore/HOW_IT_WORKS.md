# Design-It! 3-D — how the format works, as best I understand it

A rubber-duck pass over the whole format. The point of writing it out is to find
the corners I've been walking past. Everything here is either **✅ measured**,
**🟡 believed but weakly evidenced**, or **❓ unknown** — and I've tried to be
honest about which, because three times now something I marked ✅ turned out to
be a coincidence that fit the common case.

Companion documents: `FORMAT.md` is the terse spec, `findings/` holds the
per-chunk investigations, and this file is the narrative.

---

## 1. The one-paragraph version

A `.VVR` or `.WLB` file is an **EA IFF-85 chunk tree**. Inside it, every visible
thing in the world is a **`PRSM`** — a 2-D polygon swept along an axis with a
profile function. There is no mesh format anywhere: no vertex buffers, no
triangles, no faces. A chair is a dozen swept polygons. Cuts are half-space
planes (`SLIC`). Surface detail is 2-D vector shapes painted onto named faces
(`SURF`/`FEAT`). Every number is fixed-point `int32 / 65536`. The result is a
procedural CAD format, not a 3-D file format, and almost every bug I've hit came
from assuming otherwise.

---

## 2. The layers, and where the bugs live

```mermaid
flowchart TD
    A["<b>Container</b><br/>EA IFF-85 chunk tree<br/>tag + length + payload"] --> B
    B["<b>Document</b><br/>ROOT / VCLP, units, layers,<br/>preferences, the app's own preview"] --> C
    C["<b>Assembly</b><br/>PGRP groups, PRSM parts,<br/>one POSN transform each"] --> D
    D["<b>Primitive</b><br/>POLY: a polygon swept along an axis<br/>with a profile and a lean"] --> E
    E["<b>Modifiers</b><br/>SLIC half-space cuts"] --> F
    F["<b>Decoration</b><br/>SURF names a face,<br/>FEAT paints a 2-D shape on it"]

    style A fill:#e8f0fe,stroke:#5b7fbd
    style B fill:#e8f0fe,stroke:#5b7fbd
    style C fill:#fff4e5,stroke:#c79a4a
    style D fill:#fff4e5,stroke:#c79a4a
    style E fill:#fde8e8,stroke:#c25b5b
    style F fill:#fde8e8,stroke:#c25b5b
```

Layers 1–2 are **solved and boring**. Layer 3 took two wrong answers to get
right. Layers 4–6 are where every open bug lives, and the pattern is consistent:
*the geometry generators are fine; it's the coordinate frames around them that
keep biting.*

---

## 3. The container ✅

```
┌────────┬──────────────┬────────────────────────────┐
│ tag    │ length       │ payload                    │
│ 4 char │ uint32 BE    │ `length` bytes, no padding │
└────────┴──────────────┴────────────────────────────┘
```

Big-endian, exact lengths, **no even-byte padding** (real IFF pads; this doesn't).
766 of 767 corpus files parse with zero leftover bytes, which is the hard oracle
that makes everything else checkable — a wrong schema fails loudly instead of
drifting.

Three real-world defects to tolerate:

| Defect | Where | Fix |
|---|---|---|
| `FORM<VCLP>` carries a bare 4-byte subtype token (`FEAT`/`PRSM`) with **no length field** | every gallery clip | read 4 bytes when formtype is `VCLP` |
| `FEAT` has a 2-byte header inside `SURF` but not as a top-level 2-D clip | 106 files | context-sensitive header table |
| Shipped `3GALLERY/ID*.WLB` have **stale `CAT` lengths** | 19 files | locate clips by scanning for the `FORM????VCLP` signature |

> **Corner I keep meaning to revisit.** That third one is still unvalidated.
> `Breuer Coffee Table` recovers as 50 parts spread over 61 feet, which is
> obviously wrong, and those six files are excluded from every score I quote.
> They're 6 of 45 galleries — not nothing.

---

## 4. Numbers ✅

Everything is **fp16.16**: a big-endian `int32` divided by 65536. Not floats,
not fixed-precision decimals. One consequence worth remembering: a value that
looks like `3.1416` is *exactly* `205887/65536`, so exact-equality tests against
π work to 4 decimal places and the "is this a round angle?" histograms that
solved the rotation question are reliable.

The exception is **`UNIT`**, which is an IEEE-754 **double**. That was hiding a
bug for the entire project — see §6.

---

## 5. The document layer

```mermaid
flowchart LR
    subgraph VVR[".VVR — a scene"]
        F1["FORM"] --> R1["ROOT"] --> P1["PGRP / PRSM …"]
        F1 --> PREF["PREF: PWIN PMOD PDEF<br/>PEDT PUNT PNAV PRND<br/>CPRF VPRF TRNS LAYR"]
    end
    subgraph WLB[".WLB — a gallery"]
        C1["CAT "] --> V1["FORM&lt;VCLP&gt;"] --> N1["NAME · VRIF · UNIT<br/>PGRP / PRSM"]
        C1 --> V2["FORM&lt;VCLP&gt;"]
        C1 --> V3["…"]
    end
```

`VRIF` is the most useful thing in here: a **50×50 preview bitmap the
application drew itself**, 3,008 of them across the corpus. It's line art, so
flood-filling from the border and inverting gives a silhouette to score against.
It is the closest thing to ground truth we have without running the program.

> **Corner.** The whole `PREF` subtree — 169 of each of `PWIN`, `PMOD`, `PDEF`,
> `PEDT`, `PUNT`, `PNAV`, `PRND`, `CPRF`, `VPRF`, `TRNS`, `LAYR` — is completely
> undecoded. Most of it is window positions and editor preferences and genuinely
> doesn't matter. But `LAYR` contains **named layers** (one literally reads
> `"Stone"`), and `TRNS` looks like it could be transparency. Neither is wired up.

---

## 6. `UNIT` — the bug I found while writing this section ✅

`UNIT` is 8 bytes, and I'd been treating it as opaque. It's an IEEE-754 double
giving **metres per stored unit**:

| value | means | clips |
|---|---|---|
| `0.0254` | 1 inch | 497 |
| `0.00635` | ¼ inch | 30 |
| `0.0025400` | ⅒ inch | 5 |
| `0.0015875` | 1/16 inch | 17 |
| `0.003175` | ⅛ inch | 2 |
| `0.01` | 1 cm | 1 |

So **"1 unit = 1 inch" was only true for most objects**, and everything else was
rendering 4×, 8×, 10× or 16× too large. The proof is that the sizes snap into
place the moment you divide:

| object | raw | ÷ UNIT | verdict |
|---|---|---|---|
| `Bar Stool` | 48 × 48 × 104 | **12 × 12 × 26 in** | a bar stool |
| `Microwave Oven` | 96 × 78 × 62 | **24 × 19.5 × 15.5 in** | a microwave |
| `Fridge, Vert. Black` | 131 × 133 × 262 | **33 × 33 × 65 in** | a fridge |
| `Dishwasher, Brown` | 300 × 318 × 320 | **30 × 32 × 32 in** | a dishwasher |
| `Queen Anne Desk` | 260 × 168 × 280 | **32.5 × 21 × 35 in** | a desk |
| `Pig` | 241 × 96 × 142 | **60 × 24 × 35 in** | a pig |

`UNIT` appears on `ROOT`, `VCLP`, `PGRP` and even `PRSM`, but across 537 nested
occurrences a child **never** disagrees with its ancestor, so one lookup is
enough. Now applied in both implementations.

This is a good illustration of why this document was worth writing: the chunk
was in the census the whole time, marked "8 bytes, unknown", and I never opened
it because nothing looked visibly broken. Nineteen gallery objects were silently
ten times too big.

---

## 7. The assembly layer — `PGRP`, `PRSM`, `POSN`

### 7.1 Child transforms are ABSOLUTE ✅

The single most counter-intuitive fact in the format. A `PGRP`'s `POSN` is **not**
composed onto its children; each part already carries its final placement.

```
       WRONG                            RIGHT
   world = M_group · M_part         world = M_part
```

A nested `PGRP` in `MODELS/A10.VVR` carries a π rotation with negative scales and
its children carry the same flip *again*. Composing applies it twice and explodes
the model. This is almost certainly why earlier loader attempts produced
scattered geometry.

### 7.2 `POSN` layout ✅

```
off  size  field
──────────────────────────────────────────────────────────────
 0    12   translation (x, y, z)            fp16.16
12    12   EULER ANGLES, stored (ry, rx, rz)  ← first two SWAPPED
24    12   ???  non-zero on 2.3 % of parts, small angle-like values
36    12   scale (sx, sy, sz), may be negative
──────────────────────────────────────────────────────────────
      48   full record
      24   SHORT record — stops after the rotation, scale implied (1,1,1)
```

Two traps here, and I fell into both.

**Trap 1 — the short record.** 1003 `POSN`s are 24 bytes because the scale is
identity and the writer just stopped. A 2-D `FEAT` `POSN` is *also* 24 bytes, so
the `len < 48` guard that was meant to exclude `FEAT` silently threw away every
short 3-D record and dumped those parts at the model origin. That was Brutus's
arms fanning out of his chest. **Detached parts: 165 → 49.** Distinguish by
*context* — only `PRSM`/`PGRP` reach the 3-D path — never by length.

**Trap 2 — Euler vs axis-angle.** I published the wrong answer here once, so it
deserves the space.

Fields 3–5 are three Euler angles applied in storage order, `R = Ry · Rx · Rz`.
They are *not* an axis-angle rotation vector, but the corpus fights hard to look
like one:

- a single-axis rotation reads **identically** under both models, and most parts
  use one axis, so most of the corpus renders fine either way;
- a mirrored pair negates the **same two components** under both models, so the
  obvious mirror test — Brutus's two arms — doesn't discriminate either;
- the silhouette oracle scored all six Euler orders *and* axis-angle within
  0.66–0.69, so it couldn't tell them apart.

What settled it was the **distribution of compound values**, not any render:

```
  159 parts carry exactly (180°, 0, 180°)
   and a whole family carries (180°, 0, θ) for
   θ ∈ {−175, −135, −90, −65, −45, 45, 56, 90, 135, 170, …}

  58 % of compound parts have EVERY non-zero component
  within 0.5° of a 45° multiple — the same rate as single-axis parts
```

A rotation vector composed from two round turns does not land on round
components, and certainly doesn't pin one field at exactly 180° across a whole
family. "Flip it over, then turn it" does — and that's what a modelling UI
offers. Under Euler, `(180, 0, 180)` with scale `(−1,−1,−1)` is exactly a mirror
in X, which is what those `ID*` furniture variants are.

| model | detached (of 4083) | mean IoU, compound items |
|---|---|---|
| **Euler yxz, `Ry·Rx·Rz`** | **26** | **0.7882** |
| Euler yxz, `Rx·Ry·Rz` | 26 | 0.7837 |
| axis-angle rotation vector | 40 | — |
| every other field→axis map | 62–167 | — |

> **Corner.** `POSN` fields 6–8 are still unexplained. Non-zero on 2.3 % of
> parts, always small and angle-like. Tested as a second rotation in five
> different compositions; none helped. Given that `POLY`'s "reserved" bytes
> turned out to be a real feature (§8.3), I no longer believe these are padding.

---

## 8. The primitive — `POLY`

### 8.1 Layout

```
off  size  field                                     status
──────────────────────────────────────────────────────────────
 0    1    zero                                        ❓
 1    1    class: 1 custom · 2 rectangle · 3 n-gon      ✅
 2    1    sweep axis (cyclic permutation)              ✅
 3    1    profile function                             ✅
 4    2    nseg — curve subdivision (uint16)            ✅
 6    4    sweep bound za                               ✅
10    4    sweep bound zb                               ✅
14   12    OBLIQUE-SWEEP OFFSET (3 × fp16.16)           ✅ ← was "reserved"
26    2    small signed int16                           ❓
28    4    vertex count N (uint32)                      ✅
32   8N    vertices (x, y) as fp16.16                   ✅
```

### 8.2 The sweep

```
        polygon (2-D)              profile              result
                                   
         ┌───────┐                 1 straight           ┌───────┐
         │       │       swept     2 pointed            │       │
         │   ·   │   ──────────>   3 diamond            │       │
         │       │    along an     4 rounded            │       │
         └───────┘    axis with    5 sphere             └───────┘
                      a profile
```

Two things are encoded in the *order* of `za` and `zb`, which is why they're
sometimes stored high-first and sometimes low-first:

1. **Taper direction.** A profile's SMALL end sits at `za` — the *first* bound —
   not at whichever end is higher. 124 of 213 pointed prisms have `za < zb`, and
   assuming the apex is always uppermost turns those upside down. That was the
   inverted cones on the Basketball Goal, the Toilet and the BBQ (which also read
   as "missing geometry", because the flipped lid swallowed everything else).
2. **Ring order**, which fixes the face numbering `SURF` indexes into.

The axis byte is a **cyclic permutation**, not a rotation matrix:

```
   3 → (X,Y,Z) = (u, v, w)    upright
   2 → (X,Y,Z) = (v, w, u)    along Y
   1 → (X,Y,Z) = (w, u, v)    along X
        where (u,v,w) = (polygon x, polygon y, sweep)
```

### 8.3 The oblique sweep — the other thing I found this week ✅

Bytes 14–25 are **not padding**. They're three fp16.16 that displace the `za` end
of the sweep, so the extrusion *leans*:

```
    straight sweep              oblique sweep (skew = (0, −7.9, 0))
                                
        ┌───┐                              ┌───┐
        │   │                             /   /
        │   │                            /   /
        │   │                           /   /
        └───┘                          └───┘
```

Non-zero on **341 prisms (5.1 %)**. This surfaced because Greg screenshotted the
`Bar Sink` in the real application and noticed its **faucet leans** while ours
stood bolt upright. That prism carries `(0, −7.87, 0)`. A `6' Work Table` leg
carries `(0, −5, 0)` and a `Conference Table` leg `(0, 5.5, 0)` — splayed legs,
exactly what those previews show.

Measured: detached prisms **51 → 25**, mean IoU over the 24 affected clips
**0.7583 → 0.7702**.

> **Corner.** Which end moves is decided only by the detach oracle (25 vs 40 the
> other way). IoU can't separate the two directions at all — 0.7702 vs 0.7726 on
> 24 clips, pure noise. And `POLY[26:28]`, a small signed int16 sitting right
> next to the skew vector, is non-zero on 72 of those 341 prisms and completely
> unexplained. If the skew is a *lean*, that int16 might be what makes it a
> *bend*.

---

## 9. `SLIC` — cuts ✅

N planes `(a, b, c, d)` as fp16.16, in **object space** (after the axis
permutation), applied in order. Keep the half-space `n·p + d ≥ 0`.

```
     pointed prism            + SLIC plane            = frustum
        /\                        /\
       /  \                      /--\  ← cut            ┌────┐
      /    \                    /    \                  │    │
     /______\                  /______\                 └────┘
```

This is how the program expresses **every tapered box**: 61 % of pointed prisms
carry a `SLIC` versus 6 % of straight ones. `PC, Compaq`'s keyboard is a plain
slab cut corner-to-corner into a wedge; its monitor is a cone truncated 7 in from
the wide end. Brutus's odd wedge-shaped head is the same trick, and is correct.

Two implementation notes that cost real time:

- **Cap from on-plane vertices, not from new edges.** A slab mitred exactly
  corner-to-corner creates *no new vertices* at two of its four cut corners, so
  edge-stitching yields a degenerate sliver. Collect the vertices lying on the
  plane and sort them by angle about their centroid.
- **Compact the vertex array afterwards.** The clipper appends new vertices and
  stops referencing the removed ones. Harmless for drawing, poisonous for
  measuring: a clipped prism's array still holds the geometry that was cut away,
  so its bounding box is the box of the *uncut* prism. That inflated the manifest
  bounds and made cut objects hover above the floor in the explorer.

`ESLC` runs parallel to `SLIC`: `[3 zeros][3 angles][two points on the plane]`.
The angles aren't needed for geometry and are ❓.

---

## 10. Surface decoration — `SURF` / `FEAT`, and the swamp

This is where all the remaining bugs are. **113 of 2,932 decals (3.9 %) still
land outside the prism they decorate.**

### 10.1 Face numbering ✅ (corrected — the old rule was wrong)

```
   face 0            cap at the HIGH end of the sweep
   1 .. bands·n      side faces, band-major; the edge v_j -> v_j+1
                     is face ((j+1) mod n) + 1, i.e. a side face is
                     named after the vertex its edge ARRIVES at
   bands·n + 1       cap at the LOW end
   bands·n + 2 + k   the face created by SLIC cut k
```

**This section previously claimed the sides were the polygon's edges traversed
BACKWARDS, "twice re-verified".** It was wrong, and the way it was wrong is the
most useful lesson in this document.

The verification swept six alternative numberings against the containment
oracle. But that oracle asks only whether a decal escapes its prism's bounding
BOX — and on a rectangular prism the backwards rule and the correct rule differ
*only by swapping opposite faces*. Opposite faces of a box have identical
extents and sit inside the same bounding box, so the oracle scored the right
answer and the wrong answer exactly the same, and reported a tie as a win. Six
alternatives, twice, all measured with an instrument that was blind to the
distinction being tested.

What broke the tie was a sharper oracle (`tools/facefit.py`): ask which
individual FACE the outline fits on, not which box it stays inside.

| side numbering | decorations that do not fit their stored face |
|---|---|
| edges backwards (old) | 126 / 2532 (4.98 %) |
| **arriving vertex (current)** | **22 / 2532 (0.87 %)** |

The symptom in the corpus was subtle by construction: a decal on the far side of
an object still looks like a plausible object, so it survives a flythrough. It
took `Lectern` (pages on the underside), `Microwave, undercabinet` (control
panel on the back) and `Bar Sink` (basin adrift in mid-air, because a 7-vertex
profile makes the two rules diverge properly) to expose it.

**Rule of thumb this earns:** before trusting a sweep, check that the oracle can
actually distinguish the options being swept. A metric that ties on the
discriminating cases will confirm whatever you started with.

### 10.2 The 2-D frame 🟡

Drop the axis the face normal is most aligned with; keep the other two in
ascending axis order. **Break an exact tie towards the lowest axis index**, and
take the normal from the area-weighted sum over the face rather than from its
largest triangle. A face at exactly 45 degrees ties two axes, and a single
triangle's cross product carries enough float noise to decide the tie by luck:
the `Jersey Cow`'s two flanks are mirror images, and they were getting
TRANSPOSED frames, one keeping (Y, Z) and the other (X, Y). The spot painted on
the second flank was then laid out along a 7-inch axis using a 59-inch
coordinate, and flew off into space. Rejected alternatives, with their failure
rates:

| frame | decals outside their face |
|---|---|
| **current (world axes, ascending)** | **14 %** |
| u/v swapped | 55 % |
| intrinsic (polygon edge × sweep) | 22 % |
| polygon space instead of object space | 22 % |

### 10.3 Two coordinate conventions ✅

The `FEAT`'s own `POSN` is 24 bytes: `(x, y, ROTATION, ~0, sx, sy)`.

Field 2 being a **rotation** was itself a find — non-zero on 4.3 % of decals with
unmistakable values (π, π/2, −π/2, π/4, 5.359, −0.2618). We'd been drawing those
unrotated, which leaves a decal the right size in the right place but facing the
wrong way, so it hid behind the louder placement bugs.

And the translation turns out to select the coordinate frame:

```
  (tx, ty) ≠ (0, 0)  →  outline measured from the face's MINIMUM CORNER
  (tx, ty) = (0, 0)  →  outline measured from the face's CENTRE
```

The evidence is a clean cross-tab. Of 2,182 decals *with* a translation, 2,064
fit the corner frame and **none** fit only the other; of 338 *without* one, 309
fit the centre frame and **none** fit only the corner frame. Measured on the
no-translation group alone: centre-origin leaves 19 outside, the prism's bare
local origin 29, the face corner 62.

Applying the split took decals-outside-their-prism from **11.8 % → 3.9 %**.

### 10.4 What's still wrong 🟥

`Bar Sink` is the readable exemplar. Its 13.7 × 15.7 in basin outline is assigned
by `SURF` to **face 6**, which is a 19.7 × **0.5** in sliver on the counter's
rounded end. Face 3 — the counter top, 19.7 × 38.0 — fits it perfectly with room
to spare.

```
   PRSM 0, the counter slab (7-vertex profile, swept 19.7 in)

   face 0  39.7 × 2.0    cap
   face 1  19.7 × 38.8   underside
   face 2  19.7 × 2.0    end
   face 3  19.7 × 38.0   TOP  ← the basin belongs here
   face 4  19.7 × 1.0    chamfer
   face 5  19.7 × 0.9    chamfer
   face 6  19.7 × 0.5    chamfer ← SURF says this one
   face 7  19.7 × 1.1    chamfer
   face 8  39.7 × 2.0    cap
```

So it's the face **index** that's wrong for these, not the frame. But the
stated→fitting delta histogram is scattered — `1:90, 4:61, 2:57, 5:46, 3:37` —
so it isn't an off-by-N either. And 32 of the 159 failures have *no* face on
their prism that fits at all, which means for those the problem is upstream of
face selection entirely.

Same shape of bug: `Jersey Cow`'s one floating spot, `Mac LC`'s screen (which
lands off the monitor's edge under *every* convention I've tried, including the
one that's right for 2,064 other decals), `Tiled Bedroom` at 72 in out.

---

## 11. `Printer w/stand` — a bug I can now describe precisely and still not fix 🟥

Four identical paper sheets. Their `POSN`s differ only in `v[3]` and position;
all four carry scale `(−0.112, −1.0, −0.585)` and the mystery fields 6–8 as
`(0, −0.174, 0)`. The `VRIF` preview draws them as **one continuous curled
ribbon** coming out of the printer's left side. Greg confirms the orientations
look right and only the translation is off.

Our sheets sit along roughly that curve with gaps of **6.1 / 3.7 / 3.1 in** on
9.36 in sheets.

The useful negative result: a grid search over *every possible pair* of sweep
endpoints cannot get the total gap below 10.45 in (the current model gives
12.89). So no reinterpretation of the sheet's own extent closes the chain — the
**positions themselves** must be transformed differently.

Ruled out so far: sibling chaining (much worse), pivot at the geometry centre
(467 detached parts vs 26), pivot at either sweep end, sweep-axis scale anchored
at `za` or `zb`, scale before vs after rotation, `|scale|`, `sz = −1`, fields 6–8
as a second rotation in five compositions, and `CONN` (decoded — it's
`[count][count × 4 × uint16]` snap metadata, and this clip has only one record).

---

## 12. Chunk census — the honest ledger

Everything in the corpus, and whether we do anything with it.

| chunk | count | size | in | status |
|---|---|---|---|---|
| `COLR` | 52,293 | 4 / 8 / 10 | FEAT, PRSM, SURF | ✅ RGB read; **the 10-byte variant has 2 trailing bytes we ignore** ❓ |
| `POSN` | 49,230 | 24 / 48 / 12 | FEAT, PRSM, PGRP | ✅ except fields 6–8 ❓ |
| `POLY` | 47,255 | 36 / 64 / 96 | FEAT, PRSM | ✅ except byte 0 and `[26:28]` ❓ |
| `FEAT` | 26,391 | container | SURF, VCLP | ✅ |
| `LNUM` | 22,839 | 2 | PRSM, PGRP | ❓ **ignored** — layer number, 14 distinct values, pairs with `LAYR` |
| `LOCK` | 21,836 | 2 | PRSM, PGRP | 🟡 ignored — 0 except 5 cases; a UI lock flag |
| `PRSM` | 20,864 | container | PGRP, PRSM, ROOT | ✅ |
| `SURF` | 7,472 | container | PRSM | ✅ |
| `PLGR` | 5,794 | 2 | PRSM | ❓ **ignored** — always 0 in the sample I checked |
| `PGRP` | 1,975 | container | PGRP, PRSM, VCLP | ✅ |
| `SLIC` / `ESLC` | 1,928 ea. | 18 / 34 / 2 | PRSM | ✅ / 🟡 angles unused |
| `VERS` | 1,343 | 4 | VCLP, FORM | 🟡 ignored |
| `UNIT` | 1,128 | 8 | VCLP, PGRP, ROOT | ✅ **as of today** |
| `NAME` | 1,005 | var | VCLP | ✅ |
| `VRIF` | 996 | 4554 | VCLP | ✅ the oracle |
| `TXTB` | 821 | 0 / 17592 / 123144 | VCLP, FORM | ❓ **ignored** — texture blobs |
| `CONN` | 681 | 10–66 | PGRP, PRSM, ROOT | 🟡 decoded, unused |
| `PLTX` | 474 | 32 | PRSM | ❓ **ignored** — payload begins with ASCII `TXID` |
| `LGHT` / `ELGT` | 196 ea. | 68–112 / 8–12 | ROOT, PRSM | ❓ **ignored** — lights |
| `SUTX` `TXID` `TXOD` `TATR` | 110 ea. | 0 / 4 / 4 / 0 | SURF | ❓ **ignored** — per-face texture |
| `SFTX` | 87 | 20 | FEAT | ❓ **ignored** — also begins `TXID` |
| `PREF` subtree | 169 ea. | var | FORM | ❓ ignored; `LAYR` carries **named layers** |
| `VGER` / `VGRS` | 2 | — | FORM | ❓ |

**Reading that table back is uncomfortable.** `PLGR` appears 5,794 times and I
have never looked at it. `LNUM` appears 22,839 times and I've never wired it to
`LAYR`. The texture system (`PLTX`, `SFTX`, `SUTX`/`TXID`/`TXOD`/`TATR`, `TXTB`)
is five chunk types that clearly form one coherent feature — and `PLTX` and
`SFTX` both literally start with the ASCII bytes `TXID`, which means they're the
same record type embedded in two places. That's a thread I've never pulled.

---

## 13. The three oracles, and the lesson

The single most repeated mistake on this project is **trusting silhouette IoU
past its resolution.**

| oracle | what it sees | current baseline |
|---|---|---|
| `score.py` — best-view silhouette IoU vs `VRIF` | gross geometry | — |
| `detach.py` — prisms whose AABB touches no other prism | "floating detached piece" | **25 / 6,487** |
| `decalfit.py` — decal box inside its prism's box | misplaced decoration | **113 / 2,932** |

IoU scored the SLIC clip-vs-no-clip question at 0.7615 against 0.7610 and cost
two long passes on a false tie. It could not separate the six Euler orders from
axis-angle. It cannot tell which end an oblique sweep leans from. It is genuinely
good at gross geometry and genuinely blind below the silhouette.

**The rule I should have written down earlier:** when candidate models score
within a few points of each other, stop scoring and go read the data
distribution instead. Both of the big analytic wins came from histograms rather
than renders — the Euler answer from the distribution of compound angle values,
the decal answer from cross-tabulating "is the translation zero?" against "which
frame contains it?".

And the other rule, which is really about Greg rather than the format: **the most
valuable evidence has consistently been an offhand remark about a shape.** "The
faucet has a slant to it" found an entire `POLY` field that had been written off
as reserved. "You picked the wrong Copy Machine" found the two coordinate
conventions.

---

## 14. Where I'd look next, in order

1. **The texture system.** Five chunk types, one coherent feature, never opened.
   `PLTX` and `SFTX` share a `TXID` record; `SUTX` wraps `TXID`/`TXOD`/`TATR`;
   `TXTB` holds blobs of 17 KB and 123 KB. This is the Key Design 3-D feature set
   and it is completely dark.
2. **`PLGR` (5,794 occurrences) and `LNUM` → `LAYR`.** Cheap to census, and
   `LNUM` at least has a plausible mechanism.
3. **`POLY[26:28]`** — the int16 sitting next to the skew vector, non-zero on 72
   of the 341 skewed prisms. If the skew is a lean, this may be the bend.
4. **`POSN` fields 6–8** — no longer plausibly padding, given §8.3.
5. **The remaining decal face-index problem** — with the caveat that it is *not*
   a global renumbering, and that 32 cases fail on every face, so part of it is
   upstream.
6. **`ID*.WLB` clip recovery** — six galleries currently excluded from all
   scoring.
