# SLIC / ESLC — investigation notes

## Established facts ✅

- `SLIC` = 2-byte header + N × 16 bytes. `ESLC` = 2-byte header + N × 40 bytes.
  **N is always identical between the two** across all 3,168 slice records in the
  corpus — they are parallel arrays over the same N slices. N is unrelated to the
  `POLY` `nseg` field.

- A `SLIC` record is 4 × fp16.16 = **a plane**: `(a, b, c, d)` with `a·x + b·y +
  c·z + d = 0`.

- An `ESLC` record is 10 × fp16.16:
  - `[0..2]` — **exactly zero in every one of the 3,168 records.** Reserved.
  - `[3..5]` — three angles in `[0, 2π]`. Non-zero in 39.6 % / 6.9 % / 22.3 % of
    records, the same lopsided pattern as the `POSN` rotation triple. Common
    values are exact multiples of π/4 (0, π/2, π, 3π/2 account for ~85 %).
  - `[6..9]` — **two 2D points that lie exactly on the SLIC plane.** Verified
    directly: e.g. `PC, Compaq` has plane `1.5y − 8.5z = 402` and points
    `(−4, −48)` and `(4.5, −46.5)`, both of which satisfy it to the last bit.
    Which two axes the pair spans depends on which component of the normal is
    zero.

- Planes genuinely intersect their prism. The `Decorative Cactus` body has a
  slice with normal `(0, 0, 24)`, `d = −336` → the plane `z = 14`, cutting a
  prism whose z range is −30…30 — and both ESLC points have their second
  coordinate equal to 14.

## Rejected hypotheses ❌

Measured with the silhouette-IoU oracle (see `findings/oracle.md`) over the 157
gallery items that contain a sliced prism, best-of-36-views:

| Model | mean IoU | median |
|---|---|---|
| ignore SLIC entirely | **0.749** | 0.747 |
| hinge: rotate geometry past the plane by ESLC[3..5] | 0.703 | 0.692 |
| clip: discard the half-space `n·p + d > 0` | worse still | |
| clip: discard the half-space `n·p + d < 0` | worse still | |

Both subtractive models make reconstruction *worse*, and the hinge model helps
24 items while hurting 66. The clipper itself is not at fault — it is verified
watertight (two complementary half-cuts of a cube sum back to the exact
original volume for every plane tested).

So the plane is real and precisely encoded, but **its role is not to remove or
bend the prism's bulk.**

## Live hypotheses for next time

1. **Slices are additive, not subtractive** — each record may describe an extra
   cross-section inserted along the sweep (giving stepped or tapered profiles)
   rather than a cut through the existing solid.
2. **The two ESLC points bound a segment, not an infinite plane** — the cut may
   apply only between them, making it a local notch rather than a global
   half-space.
3. **The records may be derived/cached data** the editor keeps for hit-testing
   or for drawing the 2D floor-plan projection, and contribute no geometry at
   all. The fact that ignoring them scores best is weak evidence for this.
4. `ESLC[3..5]` being a rotation triple in the same lopsided proportions as
   `POSN[3..5]` suggests slices carry an orientation; worth checking whether
   they reproduce the parent's rotation rather than adding one.

Highest-value next experiment: find two gallery items that are identical except
that one carries slices, and diff them. `Bathroom/Platform Tub` and
`Bathroom/Tiled` share a POLY signature and differ in slice count.
