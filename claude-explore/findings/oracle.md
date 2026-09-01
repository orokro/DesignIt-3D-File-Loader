# The fidelity oracle

Every WLB gallery clip carries a `VRIF` chunk: a fixed 4,554-byte preview the
application itself drew. It decodes (see `tools/vrif.py`) to a nested structure:

```
VRIF
  30 bytes header
  CGRP <len>
    uint32 count
    BMAP <len>     50x50, 8-bit  -> CMAP (256 x 4-byte 00RRGGBB) + DATA (rows of `stride`)
    BMAP <len>     50x50, 1-bit  -> CMAP (2 entries) + DATA        <- ink mask
```

That gives **3,008 ground-truth images** of what the objects are supposed to
look like.

Two things had to be right before it became useful as a metric:

1. **The previews are line art, not filled shapes.** The 1-bit map marks drawn
   strokes only (5–13 % coverage). Flood-filling the background in from the
   border and inverting recovers the true silhouette. Comparing against the raw
   ink mask scores ~0.17 IoU even for perfect geometry.

2. **Each preview is posed individually — there is no single camera.** Scoring
   against a fixed front elevation put `Hanging Shelf` at 0.066 and `5-High
   Bookcase` at 0.160; sweeping views puts them at 0.960 and 0.929. The
   geometry was right all along. Any global scoring must take the best match
   over a view grid.

`tools/score.py` implements this: crop both silhouettes to their bounding box,
normalise to a common size (making the score scale- and position-invariant),
and take the best IoU over a grid of azimuth/elevation.

## Current baseline

| Population | Metric | Score |
|---|---|---|
| 157 items containing sliced prisms | best of 36 views | mean **0.766**, median 0.772 |
| all 574 3GALLERY items | single front view | mean 0.677 |

Use the first number as the regression baseline; the second is depressed by the
fixed-camera problem above.

**Caveat:** items recovered from the six damaged `ID*.WLB` files should be
excluded from scoring until the clip-boundary recovery is validated — e.g.
`Breuer Coffee Table` reconstructs as 50 parts spread over 61 feet, which looks
like neighbouring clips being merged rather than a geometry bug.
