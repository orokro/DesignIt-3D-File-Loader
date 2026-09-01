# SLIC / ESLC — SOLVED

**`SLIC` is a cutting plane. The prism keeps the half-space where `n·p + d ≥ 0`
and the rest is discarded.** Established September 2026, decisively, by
comparing against `PC, Compaq` as the original application renders it.

## Encoding

| Chunk | Layout |
|---|---|
| `SLIC` | 2-byte header + N × 16 bytes. Each record = 4 × fp16.16 = a plane `(a, b, c, d)` satisfying `a·x + b·y + c·z + d = 0`. |
| `ESLC` | 2-byte header + N × 40 bytes. Each record = 10 × fp16.16: `[0..2]` always exactly zero; `[3..5]` three angles; `[6..9]` two 2D points that lie exactly on the corresponding SLIC plane. |

N is always identical between the two — parallel arrays over the same N cuts.
N is unrelated to `POLY`'s `nseg`.

The plane is expressed in **object space** — after the `POLY[2]` axis
permutation, not in the polygon's local frame. The plane intersects its own
prism in 96.7 % of records in object space versus only 76.2 % locally.

Cuts are applied in order, each to the result of the last.

## The proof

`PC, Compaq` (EQPMENT2.WLB) is six prisms, three of them sliced. Two settle it:

**The keyboard** — prism 0, a plain 18 × 8.5 × 1.5 in rectangular slab. Its
plane is `1.5y − 8.5z = 402`, and the signed distances to its eight corners come
out as exactly `{−1.477, 0, +1.477}`: the plane passes precisely through two
opposite corners and splits the slab corner to corner. Cutting it produces a
**wedge** — which is exactly how the keyboard appears in the application, and it
is *not* a triangle extruded sideways. It is a box, mitred.

**The monitor housing** — prism 2, a *pointed* prism (`POLY[3] = 2`) swept 52 in.
Its plane truncates the taper 7 in from the wide end, turning a cone into a
**frustum**. Without the cut, the model grows a long spike out the back of the
monitor; with it, you get the CRT housing.

That second case explains the corpus-wide statistic that had been sitting there
unexplained all along: **61 % of pointed prisms carry a `SLIC`, against 6 % of
straight ones.** "Pointed primitive + truncating cut" is simply how this program
expresses every tapered box — monitor housings, lampshades, table legs. It is
the single most common use of the chunk.

Rendering `PC, Compaq` with the cut applied reproduces the application's own
render: wedge keyboard, truncated monitor, no spike.

## Shape of the data

Across 1,129 slice planes (ID*.WLB excluded):

- Keeping `n·p + d ≥ 0` retains a median **89.7 %** of the prism's span — most
  cuts shave roughly a tenth off one end. The keyboard's 50/50 diagonal is
  unusual.
- Only 5.3 % of planes pass exactly through two of the prism's own vertices, so
  corner-to-corner mitres like the keyboard are the exception, not the rule.
- Exactly one plane in 1,129 is tangent to its solid — these are real cuts, not
  cached face planes.
- The opposite sign convention scores 0.671 against 0.761 on the silhouette
  metric and is worse on 89 of 124 items. Not ambiguous.

## Why the silhouette oracle missed this

Reported for the record, because it cost two long passes.

`tools/score.py` compares filled silhouettes. A cut that removes a tenth of one
prism inside a fifteen-part model barely moves the outline, so the metric scored
"clip" and "no clip" within noise of each other (0.7615 vs 0.7610) and I read
that as evidence against the model. It was evidence of an insensitive
instrument.

Worse, the metric actively misleads on individual items: with the cut applied
`Decorative Cactus` *looks* far closer to its preview — proper trunk, fuller
body — while its IoU drops from 0.698 to 0.644. Bounding-box normalisation is
part of the problem: removing a spike shrinks the box and rescales everything
inside it.

**Lesson: for changes below silhouette resolution, trust a direct visual
comparison against a known-good render over the aggregate score.** The oracle is
still valuable as a regression check on gross geometry (axis permutation,
transform composition, profile generation); it is not a microscope.

## Still open

- `ESLC[3..5]`, the three angles. Non-zero in 39.6 % / 6.9 % / 22.3 % of
  records — the same lopsided distribution as the `POSN` rotation triple. Not
  needed to place the cut, since the plane in `SLIC` fully determines it. Most
  likely the orientation of the cut's own coordinate frame, kept so the editor
  can draw and drag the cut handle.
- Whether the two `ESLC` points **bound** the cut to a segment. Every case
  examined so far behaves as a full half-space, but a bounded notch would be
  indistinguishable in those cases.
