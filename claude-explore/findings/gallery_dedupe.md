# De-duplicating the 3-D galleries

First pass: **Gallery grid** only (`data/galleries3d`, 94 `.wlb` files, 1130 clips).

- `claude-explore/tools/dedupe.py` — the analysis, re-runnable per bucket
- `claude-explore/out/dedupe/` — fingerprint cache, vertex cache, the mark list
- `gallery_dedupe.json` (beside this file) — every cluster, machine-readable

## How a duplicate is decided

A clip is a bag of meshes; each mesh is vertices, triangles and an RGB colour.
Three tests, cheapest first.

**exact** — translate the clip so its bounding box starts at the origin, round to
0.01", hash `(verts, tris, colour)` per mesh, sort the mesh hashes and hash
again. Position- and order-independent, because several duplicates differ *only*
by a leftover world offset: `Chairs2::MR Ottoman` sits at (240, 1130) in one copy
and at the origin in the other, `Bentwood #18` likewise, and the two `Side Table
Lamp`s in `Lighting.wlb` differ in bytes but not in geometry.

**congruent** — for clips with equal triangle and mesh counts and equal surface
area, try all 48 signed axis permutations and measure a true Hausdorff distance
between the vertex sets, tolerance 0.30". Correspondence-free, so it survives
re-tessellation and re-ordering. The full axis permutation (not just rotation
about Z) is what catches the same solid stored in a different *working view* —
which is exactly what the BASIC/ADVANCED primitives are. Rotations and
reflections are scored separately, because a left-hand corner desk is not a
right-hand one however well they overlap.

**layout** — `web/src/pack.js` ported to Python, so a clip can be located by row
and column. Verified against the sweep: the port puts `Brutus::Little Bruti`,
`HOMELIFE::Little Bruti`, `ARCHSURV::Level Staff` as the first three items of row
18, which is where the sweep started. That let every questionable mark be checked
against what was actually standing next to it.

**Result: 1130 clips → 839 distinct objects. 291 redundant copies.** The exact
hash finds 247 of them; congruence finds the other 44.

(Hausdorff needs no correspondence and no equal point counts. Requiring equal
vertex counts -- which collapsing duplicate vertices makes unreliable -- silently
skipped most of the modular L/R families, i.e. exactly the pairs the reflection
test exists for. The triangle-count, mesh-count and surface-area gate is what
keeps the relaxed version honest.)

## The mark list

198 marks after the fridge correction.

| | |
|---|---|
| marks that hit a real duplicate | 187 |
| marks with no duplicate anywhere | 11 |
| clusters where every copy is marked | **0** |
| duplicates not marked | 91 — 44 in libraries the viewer hides, 42 in the BASIC/ADVANCED families, 5 real misses |

In every three-copy cluster exactly two are marked and the survivor is the
leftmost; the rule holds the whole way through.

### The 11 marks with no duplicate

| marked | verdict |
|---|---|
| `MODCRNR1::X1BL 24 42 4` ↔ `X1BR 24 42 2` | reflections of each other, 0.43" apart. Same solid, opposite hand. |
| `MODCRNR1::X1BI 32 48 2` | nearest relative 1.44" (reflected), rest of the family 6–7". Distinct. |
| `MODCRNR1::X1MI 32 60 3` | nearest 6.33". Distinct. |
| `MODCRNR2::X1NI 32 60 4` | nearest 6.13". Distinct. |
| `MODCRNR2::X1NL 30 60 1` | nearest 6.50". Distinct. |
| `MODCRNR2::X1MR 30 60 8` | nearest 11.84". Distinct. |
| `MODCONF3::X1CL 30 90 9` | nothing within tolerance. Distinct. |
| `crate::Crate Love Seat` | neighbour is `Crate Love Seat w/Arms`, 4.5" apart, 346 vs 450 triangles. The arms are real. **Un-mark.** |
| `HOMEMISC::Table Lamp` | `lights::Table Lamp` is immediately to its right: same silhouette, 2.72" apart, 182 vs 222 triangles. The same lamp at two detail levels — defensible either way. |
| `ARCHTEMP::Pediment` | a 52-foot temple pediment, last in its row, nothing like it in the corpus. Stray click. **Un-mark.** |

### The 5 real misses

```
EQPMENT2::Machine Stand    = equip2::Machine Stand
FURNISH1::Decorative Plant = furnsh1::Decorative Plant
FURNISH2::Torchier         = lights::Torchier
HOME::Coffee Table         = idtable::Coffee Table
KITITEM1::Bar Stool        = kitems1::Bar Stool
```

All five sit inside libraries the plan below deletes wholesale.

### The fridges

Nine fridge clips, five standing in one row, four distinct objects:

```
Fridge, Hor. Almond   232 tris  KITCHEN::Refrigerator + KITITEM2 + kitems2   (3 copies)
Fridge, Vert. Almond  244 tris  KITITEM2 + kitems2                           (2 copies)
Fridge, Hor. White     64 tris  KITITEM2 + kitems2
Fridge, Vert. Black    76 tris  KITITEM2 + kitems2
```

Hor. Almond and Vert. Almond share a bounding box to the inch (30.5 × 30.75 ×
64.25) and differ only in the freezer door — which is why five near-identical
boxes stand in a row and why the first pass over-marked them. The corrected marks
keep one of each.

## The primitives

`BASIC` / `BASIC_F` / `BASIC_R` / `BASIC_R__virvrml` and `ADVANCED` / `ADVNCE_F` /
`ADVNCE_R` — 84 clips, 24 names, **46 distinct solids**. `_F` and `_R` are the
Front and Right working views: the same primitive swept along a different axis.
They cannot be compared by eye because `shelfPack` sorts by footprint, so the
three views of one primitive land in three different rows.

Per name, under pure rotation:

| pattern | names |
|---|---|
| all four BASIC copies identical | Rectangle, 16-Sided, 16-Sided Pointed |
| `_F` = `_R` = `virvrml`, plain BASIC different | Triangle, Pentagon, Octagon, Triangle Pointed, Pentagon Pointed, Octagon Pointed |
| BASIC = `_R` = `virvrml`, `_F` different | Hexagon, Hexagon Pointed |
| three different solids | Rectangle Pointed |
| ADVNCE_F = ADVNCE_R, ADVANCED different | 11 of the 12 Advanced names |
| ADVANCED = ADVNCE_F, ADVNCE_R different | Hexagon Rounded |

Consequences:

- **`BASIC_R__virvrml.WLB` is a byte-differing but geometrically identical copy of
  `BASIC_R.WLB`** — all 12 clips. Unambiguous delete.
- **`ADVNCE_F.WLB` is fully redundant**: every clip in it equals either its
  `ADVNCE_R` twin (11 names) or its `ADVANCED` twin (Hexagon Rounded). Delete.
- `BASIC_F` and `BASIC_R` each still hold solids the other does not (the hexagons
  and `Rectangle Pointed`, 17.2" and 6.0" apart), so neither can go wholesale.
  After the two deletions, 60 primitive clips remain holding 46 solids — the last
  14 need clip-level suppression, not a file deletion.

## The `X1CL 30 90 9` names

Modular systems furniture; the name is a catalogue code:

```
X 1 CL   30   90   9
│ │ │    │    │    └── check digit (varies freely, carries no geometry)
│ │ │    │    └─────── width, inches
│ │ │    └──────────── depth, inches
│ │ └───────────────── shape + handing:  I inline · L left · R right · E end
│ └─────────────────── family: 1 worksurface · 2 storage · 3 panel
└─────────────────────
```

`A` = straight run (`MODCONF1/2/3`), `B`/`M`/`N` = corner returns (`MODCRNR1/2`),
`C` = curved conference, `X2FC`/`X2BO`/`X2CL` = storage (`MODSTORG`),
`X3GN`/`X3VN` = panels (`MODULARW`).

**The depth digit does change the mesh.** `X1BI 24 48 7`, `30 48 0`, `23 48 6` and
`32 48 2` all have 132 triangles and a 48×48 footprint to within 0.1", yet they
are 6–7" apart in Hausdorff distance. They look identical in the gallery and are
not.

**`L` and `R` are reflections, but only sometimes.** All ten `X1AL`/`X1AR`
straight worksurfaces are exact mirror pairs (0.01–0.15" under reflection, 9–13"
apart under any rotation). Four of the five `X1BL`/`X1BR` corner returns are too
(0.43–0.49"), and one `X1NL`/`X1NR` pair at 0.59". The rest of the `M`/`N`
families are 12–18" apart — genuinely different parts that merely look alike.
So the handing question is worth about 15 clips, not the whole 25, and a blanket
"delete every `L`" would destroy real content.

Can the app mirror? Scanning all 45,122 `POSN` chunks in the galleries, scenes
and models: 1,660 carry a negative scale, and **every one of them is negative on
all three axes** — never one axis, never two. `(-1,-1,-1)` has determinant -1, so
a mirrored placement is representable and the shipped content uses it 1,660
times; but the app never emits a single-axis flip, and the library ships both
hands as separately named catalogue parts.

Recommendation: keep both hands, and drop all 7 `MODCRNR`/`MODCONF` marks. The
upside is ~15 clips out of 1130, against the risk of deleting parts a user picks
by name.

## The real structure: 3DWebBld re-released the libraries

Every cross-library duplicate traces to one fact, and the manifest's `apps` field
makes it plain:

```
EQPMENT1.WLB   designit + kesign3d      12 clips
equip1.wlb     3dwebbld                 12 clips     ← same 12 objects, renamed
```

3DWebBld shipped 32 genuinely new galleries (Brutus, Capitals, LowerCas, Numbers,
Municipa, Spacship, beds, crate, wodchair, modacces, spacvehc, Chairs1–3,
idtable, lights, modlight, tables …) **and** re-cut a handful of the old ones
under friendly lowercase names. The re-cuts are what the sweep kept finding.

So this is not 198 individual decisions. It is one question asked sixteen times:
*when two products ship the same objects, which file survives?*

## The plan, as built

**Nothing is deleted.** `data/dedupe.json` lists the copies the viewer skips;
every file stays on disk and `Show all` (button, or <kbd>U</kbd>) ignores the
list entirely. The list is regenerated by `python dedupe.py suppress galleries3d
models scenes`, so it never drifts from the analysis.

```
galleries3d   266 hidden   (16 whole libraries + 65 individual clips)
models          0 hidden
scenes         13 hidden   (13 whole files)
```

Verified: after hiding, every one of the 1157 distinct objects has **exactly
one** visible copy — none lost, none doubled, and no stale entry in the list.

Which copy survives, in order: the product this project is about
(Design-It!/Kesign3D) over 3DWebBld's re-release; then the file that is not a
`build_data.py` collision rename (`__virvrml`, `__3dwebbld`); then the more
legible name — a real word beats `KWALCAB1::2`; then the shortest path. A
library that is redundant end to end disappears as a library rather than as
twenty-one separate clips, so the galleries keep coherent sets.

The `ID*` filter is gone. It was hiding 7 files and 91 clips, 25 of which
(`IDSTORAG`, `IDCHAIR4`) exist nowhere else in the corpus and had never been
visible in the explorer at all.

## Scenes and models, pre-pass

`models`: **127 files, 127 distinct objects, nothing to hide.**

`scenes`: 179 files, 166 distinct. The 13 duplicates are all whole-file:

```
berlin.wsb      = BERLINHS.VVR      confer.wsb   = RECPTION.VVR
Colonial.wsb    = COLONIAL.VVR      genoff.wsb   = GNRLPURP.VVR
homoff.wsb      = HMOFFICE.VVR      offices.wsb  = OFFICEA.VVR
teleconf.wsb    = TELECONF.VVR      neptune.wsb  = TEMPLENP.VVR
THRLOBBY.VVR    = THTRLOBY.VVR      PEAKED__kesign3d.VVR   = PEAKED.VVR
BATHRMA__virvrml.VVR = BATHA.VVR    BATHRMB__virvrml.VVR   = BATHB.VVR
HOUSESQD__virvrml.VVR = HOUSESQD.VVR
```

### The textured/untextured pairs — kept, both of them

Design-It! and Kesign3D ship geometrically identical models where only the
Kesign3D copy carries bitmaps. The fingerprint includes each texture by name
plus a hash of its pixels, so those never merge:

```
models   APOLLO.VVR [0 tex]  vs  APOLLO__kesign3d.VVR [3 tex]
         HUBBLE, LUNARMOD, SPLASHDN, SPUTNIK, VOYAGER — same story
         SPACSTAT.VVR [0]    vs  SPACESTA.VVR [1]      (different names, same model)
scenes   BEDROOMA.VVR [0]    vs  BEDRMTIL.VVR [6]
         WHTHOUSE.VVR [0]    vs  WHTHOUS.VVR [4] and WHTHOUSE__kesign3d.VVR [4]
         BATHA.VVR [0]       vs  BATHRMA.VVR [3]
         BEDROOMA__virvrml [0] vs BEDROOMA__kesign3d [6]
```

`OCEANFLR__kesign3d.VVR` and `OCEANFLR__virvrml.VVR` are the sharpest case:
identical geometry, identical colours, 7 textures each — and they differ by one
bitmap (`Water-Pool 1.0` where the other has a second `Water-Pool 1.0¥8+¥
128x64`). Both kept.

That check matters beyond these files: the tolerance path merges on geometry, so
without the texture test it would have re-merged exactly the pairs the exact
hash had correctly separated.

## Still open

- Whether the `HOMEMISC::Table Lamp` / `lights::Table Lamp` pair (same lamp,
  182 vs 222 triangles, 2.72" apart) counts as one object. Currently both are
  shown.
- Rotations and reflections are detected and reported but never hidden, by
  decision: the app offers `_F`/`_R` views and `L`/`R` handed parts as separate
  library entries, so the explorer does too. 42 rotated and 9 reflected pairs
  are listed by `dedupe.py pairs`.

## Second pass: the scenes/models marks

Fourteen marks, checked one by one. Three classes.

**Textured vs untextured — SUPERSEDED, see "Levels of finish" below.** These
were kept at first on the grounds that a texture makes a different object. In
the explorer that just puts two identical-looking models side by side, so the
plain copy is now hidden and the painted one shown. Nothing is deleted; `Show
all` brings the plain copy back. The marks named the textured copy in five of
six cases, which is the opposite of what a browser wants:

```
LUNARMOD__kesign3d [2 tex]   vs  LUNARMOD.VVR  [0]
VOYAGER__kesign3d  [1]       vs  VOYAGER.VVR   [0]
SPLASHDN__kesign3d [1]       vs  SPLASHDN.VVR  [0]
HUBBLE__kesign3d   [1]       vs  HUBBLE.VVR    [0]
SCLPTHAL__kesign3d [6]       vs  SCLPTHAL.VVR  [0]
SPACSTAT.VVR       [0]       vs  SPACESTA.VVR  [1]   <- this one marks the UNtextured copy
```

**Revisions, not copies.** Same name, genuinely different geometry:

```
BATHC.VVR   632 tris / 78 meshes   vs  BATHC__virvrml   632 / 77
ATTIC.VVR    99 tris               vs  ATTIC__virvrml    94
CNCLUB.VVR  3057 tris, 14286x16296 vs  CNCLUB__virvrml  3105 tris, 6600x6600 (a different site)
ADRNDACK.VVR 3832 tris / 15 tex    vs  adiron.wsb       5042 / 0
SHUTTLE.VVR 2530 / 0               vs  SHUTTLE__kesign3d 2458 / 3   vs  launch__3dwebbld 2458 / 3 at a different extent
```

BATHC and ATTIC differ by a handful of meshes with different triangle counts and
colours — small edits, not noise.

**The ocean floors — nearly right.** `OCEANFLR__kesign3d` and
`OCEANFLR__virvrml` have identical geometry, identical colours and seven
textures each. They differ by one bitmap: Kesign3D carries two `Water-Pool 1.0`
variants and uses both, VirVRML dropped one and uses the other twice, on a
different tile size (60" vs 32"). One face is watered differently. Both kept.

Chasing that turned up something worth knowing: **the two products store the
same texture with different palettes.** `Tile 3.0` is quantised to six channel
levels in the Kesign3D copy (0, 64, 128, 192, 224, 255) and sixteen in the
VirVRML one (multiples of 17) — the same picture, correlation 0.976, not one
byte alike. VirVRML also renames as it stores: `Water-Pool 1.0` becomes
`Water-Pool 1.0¥8+¥ 128x64`. A pixel-exact texture key would have called
every re-encoded pair distinct. The key is now the stripped name, the pixel
dimensions, and a mean colour rounded to 32 levels.

### The bedrooms

Five files, and the difference really is one side table:

```
BEDROOMA.VVR           680 tris  0 tex     table, untextured
BEDRMTIL.VVR           680 tris  6 tex     same geometry, textured table
BEDROOMA__kesign3d     920 tris  6 tex
BEDROOMA__virvrml      920 tris  0 tex     same geometry as above, untextured
BEDRMTIL__virvrml      552 tris  0 tex     NO table
```

Not marking them was right. All five are distinct.

## Invisible geometry and the parachute

Design-It! drew an edge on every polygon whether or not the polygon was painted,
and some models depend on it: `SPLASHDN`'s parachute shrouds are the facet edges
of a fully transparent 14-triangle cone, 441 x 441 x 444 inches. The loader was
dropping opacity-0 solids outright (`continue`), so the cone never existed and
the strings went with it.

Now the mesh is built and its **material** is made invisible rather than the
object -- `object.visible = false` would hide the subtree, including the edge
overlay that is the only reason the mesh is still there. The edge toggle then
outlines it like anything else.

Two guards came with it. Invisible geometry is excluded from the crosshair pick
and from the walker's floor raycast, so a construction box you cannot see is
never what you are standing on or naming. And the group's bounding box counts
only painted meshes: 1,880 opacity-0 solids exist across 175 scenes -- 165 in
`STUDIOHS.VVR` alone -- and they are routinely an order of magnitude larger than
the model, so letting them into the box would resize objects in the packed grid.

They are drawn only when Edges is on, which is what you were expecting. Making
them always-on would be more faithful to the original, but `STUDIOHS` would then
show 165 wireframe boxes indoors.


## Levels of finish

Design-It! and Kesign3D ship the same model where only the Kesign3D copy carries
bitmaps, and VirVRML does it again. Both copies were kept at first -- a texture
is a real difference -- but in the explorer that means two identical-looking
parachutes standing next to each other, which is the thing this pass exists to
stop. They are now treated as one object at two levels of finish: the painted
copy is shown, the plain one hidden.

The fingerprint for that is `body` -- geometry and opacity, no colour and no
texture. Colour has to come out too, because **painting a face changes the
colour underneath it**: APOLLO's sky face is `(99, 99, 255)` plain and
`(255, 255, 255)` once `CloudScape 1.0` goes on, and SPLASHDN's sea goes blue to
grey under `Water-Pool 1.0`. Checked mesh by mesh on both: the ONLY meshes that
differ between the two copies are the ones that gained a bitmap -- 1 of 39 in
SPLASHDN, 3 of 88 in APOLLO. Colour is an effect of the finish, not a
distinction from it.

The rule fires only when one copy's texture set is a strict SUBSET of the
other's, so a copy that is textured *differently* is never touched --
`OCEANFLR__kesign3d` and `OCEANFLR__virvrml` both carry seven bitmaps and differ
by which water goes on one face, and both still show.

```
models   APOLLO.VVR   -> APOLLO__kesign3d.VVR [3 tex]    SPLASHDN -> SPLASHDN__kesign3d [1]
         HUBBLE.VVR   -> HUBBLE__kesign3d [1]            SPUTNIK  -> SPUTNIK__kesign3d [1]
         LUNARMOD.VVR -> LUNARMOD__kesign3d [2]          VOYAGER  -> VOYAGER__kesign3d [1]
         SPACSTAT.VVR -> SPACESTA.VVR [1]
scenes   BATHA.VVR    -> BATHRMA.VVR [3]                 BATHRMA__virvrml -> BATHRMA.VVR
         BEDROOMA.VVR -> BEDRMTIL.VVR [6]                BEDROOMA__virvrml -> BEDROOMA__kesign3d [6]
         WHTHOUSE.VVR -> WHTHOUS.VVR [4]
```

Twelve copies, and the corpus is untouched.

## Why the models grid hides things

`shelfPack` sets its row width from the TOTAL area of everything in the bucket,
so a handful of giants stretches every row to fit them. In `models`:

```
126 models, 7 rows, field 51,698 x 71,797 in (0.82 x 1.13 miles)
  rows 0-2:   8 models   (Katzport 24,000 in, Picabia 22,800, mirror 20,400, Tzara 18,000)
  row  5:    63 models   -- half the bucket, strung along the full 0.82-mile width
```

You spawn beside the median item, which is also in row 5. `sonic.wsb` is in that
same row, 25,055 inches away -- 0.4 miles -- and is 147 inches wide, so it
subtends 0.34 degrees: about **7 pixels** on a 1080-tall viewport. Fully lit,
inside the fog, never culled, never hidden, and effectively invisible.

Worth fixing by taking the row width from the median footprint rather than the
total area, so the giants get their own overflow rows and the small models pack
into a block you can actually read. The same applies to `scenes`.


## Fingerprint the geometry the VIEWER shows, not the file

Three near-identical red rockets stayed on screen after every rule above, and
the reason was that `dedupe.py` was measuring a different model from the one
`explore.html` draws. The explorer culls backdrop slabs -- a median-anchored
largest-gap rule on mesh footprints -- and the fingerprint was not.

```
                            file as stored          after the pad cull
SHUTTLE.VVR            134 meshes  29280 in       131 meshes  1104 x 1236 x 2472
SHUTTLE__kesign3d.VVR  132 meshes  29280 in  3tex 128 meshes  same, 0 tex
launch__3dwebbld.wsb   132 meshes  17160 in  3tex 128 meshes  same, 0 tex   <- identical
```

With the slabs on, `SHUTTLE__kesign3d` and `launch__3dwebbld` look 2.4x apart in
extent and carry three textures each. With the slabs off they are the same 128
meshes and 2,428 triangles, byte for byte -- and **all three of those textures
were painted on the slabs**, so the model itself is untextured and the "levels
of finish" rule had been reasoning about a backdrop.

`cull_pads()` is now part of `dedupe.py` and runs for `scenes` and `models`
before fingerprinting (galleries are not culled, matching the viewer). Seven of
the space pairs that the finish rule had been catching turn out to be plain
duplicates once their painted backdrops come off, so they are merged rather than
ranked.

`SHUTTLE.VVR` remains distinct from `SHUTTLE__kesign3d.VVR`: it carries three
meshes the Kesign3D copy does not -- a second 288 x 84 grey/white panel where
the other has only the 288 x 72, plus a 60-triangle black element 144 inches
across -- 72 triangles in all. A revision, not a copy, so both still show.

## Cache

`data/dedupe.json` is regenerated far more often than the page is deployed, so
`explore.html` re-reads it on every mode switch with `cache: 'no-store'` and a
timestamp. A cached copy silently shows duplicates that were supposed to be
gone, which is exactly what happened. The HUD now prints `N duplicates hidden of
M listed` so a stale list is visible at a glance.
