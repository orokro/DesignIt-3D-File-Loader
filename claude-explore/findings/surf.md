# SURF / FEAT — surface decorations. SOLVED

`SURF` is a **per-face override** on a prism. It carries a 2-byte face index and
then any mix of:

- a `COLR` — recolour that one face (2,981 occurrences, the most common use)
- one or more `FEAT` — 2D vector shapes laid on that face (2,218; both together 443)
- rarely a `SUTX` — texture assignment (5)

## Face numbering ✅

The 2-byte `SURF` header is an index into the prism's faces. The caps are not
both at the end -- one brackets each side of the run:

```
0                     cap at the HIGH end of the sweep
1 .. bands*n          side faces, band-major; within a band the polygon edges
                      run BACKWARDS, so index 1+r*n+k is edge (n-1-k)
bands*n + 1           cap at the LOW end of the sweep
bands*n + 2 + j       the face created by SLIC cut j
```

Four objects pin this down, each with an unambiguous correct answer:

| Object | Index | Must be | Why it is forced |
|---|---|---|---|
| Paper Shredder, top box | 0 | top cap | its decals span 25 x 7 in; the sides are only 6 in tall, the cap is 27 x 10 |
| Fax Machine, control panel | 0 | top cap | decals span 9.8 x 5.4 on a 1.5 in thick slab -- only the 11 x 6 cap fits |
| PC Compaq, desktop base | 3, 4, 5 | front + its two chamfers | the three-decal group spans **exactly 16.0 in**, the front face is exactly 16.0 wide; the two single decals are 1.41 wide and the chamfers are exactly 1.41 |
| PC Compaq, monitor bezel | 5 | front cap | the screen needs 11.6 x 8.5; only the 14 x 11 cap fits |

The shredder and fax force the caps apart from the sides; the Compaq base then
forces the backwards edge order (with forward edges the 16-inch group lands on a
15-inch side face and overflows).

where `n` is the polygon's vertex count and `bands` is the number of rings
minus one (so `nseg` for curved profiles, 1 for flat ones). **99.84 %** of the
5,647 `SURF` indices in the corpus fall inside that range; the handful that
don't are sphere profiles where the apex ring collapses.

### Ring order matters — and this resolves an earlier open question

Rings run **from the high end of the sweep to the low end**, which fixes which
cap is index `bands*n` and which is `bands*n + 1`.

This was determined against cases where the correct face is unambiguous: the
`PC, Compaq` monitor screen, the `Safe`'s front panel, and the `Tractor`'s
hubcap. All three land correctly under high→low and on the wrong face under the
reverse. That also explains why `POLY`'s two sweep bounds are stored in an order
that flips between objects — the order is meaningful, not noise.

## FEAT ✅

```
FEAT  (2-byte header = side selector)
  COLR (4)    A R G B -- alpha encodes opaque / translucent / transparent
  POLY (var)  4-byte header (0, class, 0, vertexCount) then N x (x, y) fp16.16
  POSN (24)   6 x fp16.16 = (x, y, ?, ?, sx, sy)
  [SFTX (20)] texture, Key Design 3-D only
```

The 2-byte header takes exactly three values across the whole corpus —
**0 (16,056), 1 (1,356), 2 (327)** — matching the editor's *Outside / Inside /
Both* choice for which side of the surface to decorate.

The 2D `POLY` uses a different, more compact header than the 3D one: the vertex
count sits directly in byte 3, so the size is `4 + 8N`. Class byte values 1, 2
and 3 mirror the 3D meaning (custom / rectangle / regular n-gon).

## Placing a feature on its face ✅

Feature coordinates are in a **2D frame local to the face**, not in the prism's
polygon space. The frame:

- drop the axis the face normal is most aligned with, keep the other two in
  ascending axis order (normal along z → `(x, y)`; along y → `(x, z)`; along
  x → `(y, z)`)
- the origin is the minimum corner of the face in that projection

Checked against `PC, Compaq`: the keyboard's two panels are stored at
`(6.75, 4.0)` half-extent `5.75 x 3.0`, and `(15.5, 4.0)` half-extent
`1.5 x 3.0`, on an 18 x 8.5 in face. Those map to `1.0..12.5` and `14.0..17.0`
along the face — the main key block and the numeric keypad, exactly as the
application draws them.

Decorations are coplanar with their face, so a renderer must offset them along
the face normal (`d3d.SURF_OFFSET`, 0.05 in) to avoid z-fighting.

## Bug this uncovered in the clipper

Capping a cut by stitching together *newly created* edges fails when the plane
passes through vertices that already exist — the `PC, Compaq` keyboard is
mitred exactly corner to corner, so two of its four cut-face corners are
original vertices and the cap came out as a degenerate sliver.

`tools/clip.py` now rebuilds the cut face from the set of vertices that end up
on the plane, sorted by angle about their centroid. It is verified watertight
for oblique, tangent and entirely-outside planes, and the keyboard mitre now
splits a 229.5 in³ slab into 114.787 + 114.713.
