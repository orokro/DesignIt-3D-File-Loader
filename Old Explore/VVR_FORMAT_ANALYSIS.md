# Design-It! 3D — VVR/WLB Format Analysis
**Reverse-Engineering Notes, April 2026**

---

## Overview

The `.VVR` file is Design-It! 3D's native scene/model format. The `.WLB` file is its library format. Both are binary files built on a subset of the IFF (Interchange File Format) chunked-container standard, using big-endian byte order throughout. Every chunk follows the same pattern:

```
[4 ASCII chars] [4-byte big-endian uint32 = payload length] [N bytes of payload]
```

Chunks nest hierarchically. Some chunks are pure containers (their payload is more chunks); some are leaf nodes with typed data; a few serve as empty type-markers.

---

## Data Types

| Type | Size | Description |
|------|------|-------------|
| uint8 | 1 | Unsigned byte |
| int16 | 2 | Signed 16-bit big-endian integer |
| uint16 | 2 | Unsigned 16-bit big-endian integer |
| int32 | 4 | Signed 32-bit big-endian integer |
| uint32 | 4 | Unsigned 32-bit big-endian integer |
| fp16.16 | 4 | 16.16 fixed-point: `int32 / 65536.0` |
| double | 8 | IEEE 754 double-precision float, big-endian |
| pstring | var | Pascal string: uint8 length byte + that many ASCII chars. IFF word-aligned (padded with a null byte if the total length is odd) |

**Coordinate system:** 1 grid unit = 1 inch. Confirmed via the `UNIT` chunk which always stores `0.0254` (the number of meters in one inch). Coordinates in `POSN` are in inches as fp16.16.

---

## VVR File Structure

```
FORM (total_file_length_minus_8)
  VMDL                          ← empty marker: "this is a Visual MoDeL"
  VERS  (4)                     ← version number
  PREF  (514)                   ← FORM(VPRF) sub-IFF: all user preference settings
  CPRF  (52)                    ← colour profile / palette
  VPRF                          ← empty marker (end of preference block)
  LAYR  (16)                    ← layer definition
  ROOT  (variable)              ← scene root; contains all geometry
  TXTB  (0 or more)             ← texture bank (usually empty)
```

### ROOT chunk

The scene root is the top-level container for geometry. It always begins with three bookkeeping chunks and then contains any number of `PRSM` and `PGRP` objects:

```
ROOT
  UNIT  (8)       ← unit scale (IEEE 754 double = 0.0254)
  LGHT  (variable)← ambient/directional lighting
  COLR  (8)       ← scene background / ambient colour
  ELGT  (variable)← environment lighting
  [PRSM ...]      ← 3D prism objects
  [PGRP ...]      ← groups of prism objects
```

---

## The PRSM Chunk — 3D Prism Primitive

`PRSM` is the fundamental 3D geometry object. All visible shapes in Design-It! 3D are prisms — 2D polygons extruded along a depth axis. The full structure:

```
PRSM
  LOCK  (2)           ← lock state
  LNUM  (2)           ← layer number
  COLR  (8)           ← object colour (two ARGB values, see below)
  POLY  (variable)    ← 2D cross-section polygon
  POSN  (48)          ← position / rotation / scale
  [SLIC (variable)]   ← optional: slice definitions (angled/complex shapes)
  [ESLC (variable)]   ← optional: extended slice definitions
  [PLGR (2)]          ← optional: library item reference index
  [SURF (variable)]   ← optional: surface decorations (one per decorated face)
```

---

## Chunk Specifications

### LOCK — 2 bytes
```
byte[0]  lock mask (which attributes can be locked)
byte[1]  lock state (which attributes are currently locked)
```
Zero in both bytes = unlocked.

---

### LNUM — 2 bytes
```
byte[0]  = 0
byte[1]  = layer index (0-based)
```

---

### COLR — 8 bytes (3D object) or 4 bytes (2D feature)

3D form (8 bytes): two ARGB colours for the two sides of the double-sided surface.
```
byte[0]  alpha = 0x00 (outer face, or "unselected" state)
byte[1]  red
byte[2]  green
byte[3]  blue
byte[4]  alpha = 0xFF (inner face, or "selected" state)
byte[5]  red   (same RGB as outer)
byte[6]  green
byte[7]  blue
```
Both colours share the same RGB value. The alpha difference (0 vs 255) is likely a rendering flag distinguishing face orientation for the no-depth-buffer renderer.

2D form (4 bytes): a single ARGB value.

---

### POLY — Cross-Section Polygon

**3D POLY** (for `PRSM`): defines the 2D footprint of the prism.

```
Offset  Size   Field
------  ----   -----
0       1      always 0x00
1       1      polygon class:
                 1 = user-modified (custom vertex positions)
                 2 = rectangle (always 4 vertices)
                 3 = regular N-gon (triangle, hex, circle approx, etc.)
2       1      prism subtype / gallery class:
                 1 = Room boundary (BASIC_R gallery preset)
                 2 = Floor tile (BASIC_F gallery preset, bounding values flipped)
                 3 = Standard 3D object (BASIC / ADVANCED gallery, extruded upward)
3       1      shape profile / variant:
                 1 = Standard (flat top and bottom, straight sides)
                 2 = Pointed (tapered to a point at top)
                 3 = Diamond
                 4 = Rounded (domed/curved top)
                 5 = Sphere (sphere-like approximation)
4       2      int16, typically 0x0001 (version/padding)
6       2      int16 = lower bound in local units (typically −48; FLIPPED to +48 for b[2]=2 Floor)
8       4      int32 = upper bound in local units (typically +48; FLIPPED to −48 for b[2]=2 Floor)
12      16     zeros (reserved/padding)
28      4      uint32 = vertex count N
32      N×8    vertices: each vertex is (x: fp16.16, y: fp16.16)
```

Total size: `32 + N×8`

**Size verification:** triangle(3)=56, quad(4)=64, pentagon(5)=72, hex(6)=80, oct(8)=96, 16-gon=160. All confirmed.

Standard polygons use unit radius = 48 (48 inches = 4 feet). The vertices for a regular N-gon at index `i` are:
```
x = round(48 * cos(2π * i / N))   (in fp16.16)
y = round(48 * sin(2π * i / N))   (in fp16.16)
```

The **shape profile** byte (b[3]) is what the engine uses to determine the 3D extrusion profile — flat, pointed, domed, diamond cross-section, or sphere approximation. Shapes with b[3] > 1 do NOT need SLIC/ESLC to render correctly; the profile is baked into this flag and the engine applies it procedurally. SLIC/ESLC are only present in user-created or scene-specific complex shapes.

**2D POLY** (inside `FEAT`, for surface decorations): completely different, compact 4-byte header.

```
Offset  Size   Field
------  ----   -----
0       1      always 0x00
1       1      polygon class:
                 1 = user-modified
                 2 = rectangle
                 3 = regular N-gon
2       1      always 0x00 (distinguishes 2D from 3D where b[2] is 1/2/3)
3       1      vertex count N  ← directly here, no separate count field
4       N×8    vertices: each vertex is (x: fp16.16, y: fp16.16)
```

Total size: `4 + N×8`

**Size verification for 2D:** triangle(3)=28, rectangle(4)=36, pentagon(5)=44, hexagon(6)=52, 8-gon=68, 9-gon(arch)=76, 12-gon=100. All confirmed.

The formula `(len - 4) / 8 = N` (or equivalently b[3] = N) applies to all 2D POLYs.

---

### POSN — 48 bytes (3D) or 24 bytes (2D)

**3D POSN** (48 bytes): all values are fp16.16 (`int32 / 65536`), units are inches (position) or radians (rotation).

```
Offset  Field    Notes
------  -----    -----
0       x        position X in inches
4       y        position Y in inches
8       z        position Z in inches
12      rx       rotation around X axis (radians)
16      ry       rotation around Y axis (radians)
20      rz       rotation around Z axis (radians)
24      d0       derived rotation component (≈0 for simple Z-only rotations)
28      d1       derived rotation component (≈0 for simple Z-only rotations)
32      d2       derived rotation component (≈0 for simple Z-only rotations)
36      sx       scale X (1.0 = no scaling)
40      sy       scale Y (1.0 = no scaling)
44      sz       scale Z (1.0 = no scaling)
```

The `d0/d1/d2` fields are non-zero only for complex 3-axis rotations. They appear to be derived trigonometric values (possibly elements of the rotation matrix that the engine pre-computes). For all scenes with only Z-axis rotation (the most common case in top-down floor planning), they are zero.

**2D POSN** (24 bytes, inside `FEAT`): 6 × fp16.16 — likely `(x, y, rotation, sx, sy, sz)` or a similar reduced transform for 2D placement.

---

### SURF — Surface Decoration Container

Attached to a specific face of a `PRSM`.

```
byte[0]  = 0
byte[1]  = face index (which face of the prism this decoration is on)
[FEAT children ...]
```

---

### FEAT — 2D Feature / Surface Shape

A 2D shape placed on a prism face. Also used as an empty type-marker in WLB items (when `len = 0`).

Populated form (no extra header bytes — children fill the entire payload):
```
COLR (4 bytes)     ← single ARGB colour of this 2D shape
POLY (variable)    ← 2D polygon (4-byte header + N×8 vertices)
POSN (24 bytes)    ← 2D position/transform on the face
```

Total payload: `12 + (4 + N×8) + 32 = 48 + N×8` (e.g., rectangle: 12+44+32=88 bytes)

**Transparency encoding** (from COLR alpha byte):

| Variant | COLR alpha | Notes |
|---------|-----------|-------|
| Opaque | 255 | Fully opaque |
| Translucent | 128 | 50% — engine uses dithering (checkerboard pattern) |
| Transparent | 0 | Invisible / glass — acts as a hole for doors/windows |

The RGB values are the same for Opaque and Translucent variants of the same shape. The Transparent variant uses white/neutral RGB since the shape is invisible.

---

### SLIC — Slice Definitions (14–130+ bytes)

Used for prisms with angled or stepped top faces (e.g., slanted roofs, dormers).

```
byte[0]  = 0
byte[1]  = slice count N
[N × 16-byte slice entries]
```

Each slice entry is 4 × fp16.16: the exact semantic of the four values is not yet fully decoded, but they appear to encode horizontal position, slope multiplier, Z-offset, and an accumulated-length value.

---

### ESLC — Extended Slice Definitions

Like `SLIC` but with 40 bytes per entry instead of 16. Carries more detailed profile information for complex shapes.

```
byte[0]  = 0
byte[1]  = slice count N
[N × 40-byte slice entries]
```

---

### PGRP — Prism Group

A locked group of primitives with a shared transform.

```
PGRP
  LOCK  (2)
  LNUM  (2)
  POSN  (48)       ← group's own world transform
  [PRSM ...]       ← member prisms
  [PGRP ...]       ← nested groups (allowed)
```

---

### UNIT — 8 bytes
IEEE 754 double = **0.0254**. Represents the number of metres per grid unit. Since 0.0254 m = 1 inch, every coordinate unit in the file is exactly 1 inch.

---

### PLGR — Library Source Flag (2 bytes)
```
byte[0]  = source type (always equals byte[1])
byte[1]  = source type:
             0 = this object was placed from the Basic/raw-primitive galleries
             1 = this object was placed from a named library gallery (furniture, equipment, etc.)
```

`PLGR` is a binary flag indicating the object's origin — it is NOT a gallery+item index. The full geometry is always embedded in the VVR file regardless. Only values `[0,0]` and `[1,1]` have ever been observed across all files. The actual gallery and item that the object came from are not recoverable from the VVR file alone.

---

### PREF — 514 bytes
A nested IFF: `FORM(VPRF)` containing all user-interface and project preference settings. Sub-chunks within:

| Chunk | Size | Purpose |
|-------|------|---------|
| VERS | 4 | Preference format version |
| PRND | 16 | Rendering settings (quality level, flags) |
| PNAV | 16 | Navigation/camera state |
| PDEF | 82 | Project definition: two Pascal strings (floor names, e.g. "Unnamed") |
| PEDT | 32 | Edit-mode UI colours |
| PUNT | 44 | Unit + project name (double=0.0254, two doubles=1.0, Pascal string = custom project name) |
| TRNS | 52 | Transparency mode and level settings |
| PMOD | 118 | 3D model display options |
| PWIN | 66 | Four-view window layout (positions and sizes of the four viewports) |

---

### SUTX — Surface Texture Container
A nested container for texture chunks attached to a surface:
```
SUTX
  TXID (4)   ← texture ID; 0xFFFFFFFE = no texture assigned
  TXOD (4)   ← texture operation data
  TATR (0)   ← texture attributes (empty if no texture)
```

---

### VRIF — Visual Riff / Thumbnail (variable, ~3856–4554 bytes)
Per-item thumbnail preview bitmap stored inside WLB library entries. The first few bytes encode image dimensions, followed by raw monochrome or colour pixel data.

---

### VGER / VGRS — Version Group
`VGER` is a small wrapper containing one `VGRS` chunk.
```
VGER
  VGRS (4)   ← two uint16: [major_version, minor_version], e.g. [1, 1]
```
Found only in complex scene files (rare chunk).

---

### LAYR — Layer Definition (16 bytes)
Encodes the state of one display layer (visibility, lock, colour). Exact field layout not yet decoded.

---

### LGHT — Lighting (variable)
Directional or ambient light source definition. Exact layout not decoded (lower priority for geometry export).

---

### ELGT — Environment Lighting (variable)
Global environment/ambient lighting parameters.

---

### TXTB — Texture Bank (0 bytes in all observed files)
Container for embedded texture data. Always empty in the files analysed, indicating textures are either not used in these scenes or stored externally.

---

### CONN — Connectivity (variable, WLB only)
Found inside 3D library items (e.g., `EQPMENT1.WLB`). Appears to encode snap/connection points — the points at which library objects can connect to walls or other objects. Structure: `byte[1]` = connection count, followed by pairs of uint16 values.

---

## WLB File Structure

WLB (Library) files are multi-item catalogs. They begin with a non-standard 8-byte header and then contain a sequence of IFF `FORM(VCLP)` blocks, one per library item.

```
"GAT " (4 bytes)    ← magic, note trailing space
uint32              ← total size of remaining data
[FORM(VCLP) ...]    ← one per library item
```

### FORM(VCLP) — Library Item

```
FORM (item_size)
  VCLP               ← sub-type marker: "Visual CLiP"
  FEAT  (0)          ← empty marker: flags this as a library entry
  VERS  (4)          ← item version
  NAME  (variable)   ← Pascal string: human-readable item name
  VRIF  (variable)   ← thumbnail image (preview bitmap)
  BMAP  (variable)   ← icon bitmap
  UNIT  (8)          ← 0.0254 (same as scene files)
  [geometry]         ← see below
  TXTB  (0)          ← empty texture bank
```

**3D items** (from `3GALLERY`): geometry is a full `PRSM` or `PGRP` tree, identical to how objects appear in `.VVR` files.

**2D items** (from `2GALLERY`): geometry is a flat `COLR + POLY + POSN` triplet at the top level of the VCLP block (no `PRSM` wrapper).

---

## Primitive Type Reference Tables

### 3D Primitives (identified by POLY vertex count + b[3] profile)

These are the base shapes the user can place from the 3D gallery. Each can be scaled, rotated, and recoloured freely.

| Vertex Count | Base Shape | POLY b[1] |
|-------------|-----------|-----------|
| 3 | Triangle | 3 |
| 4 | Rectangle | 2 (`b[1]=2` is specific to rectangles) |
| 5 | Pentagon | 3 |
| 6 | Hexagon | 3 |
| 8 | Octagon | 3 |
| 16 | 16-Sided / Circle | 3 |

**Shape profile variants** — encoded entirely in `POLY b[3]`. No SLIC/ESLC needed for these; the engine applies the profile procedurally:

| POLY b[3] | Variant | Available sizes | Gallery |
|-----------|---------|-----------------|---------|
| 1 | Standard (flat prism) | 3, 4, 5, 6, 8, 16 | BASIC, BASIC_F, BASIC_R |
| 2 | Pointed (tapers to a point) | 3, 4, 5, 6, 8, 16 | BASIC, BASIC_F, BASIC_R |
| 3 | Diamond | 3, 4, 8, 16 | ADVANCED, ADVNCE_F, ADVNCE_R |
| 4 | Rounded (domed top) | 3, 4, 5, 6, 8, 16 | ADVANCED, ADVNCE_F, ADVNCE_R |
| 5 | Sphere | 8, 16 | ADVANCED, ADVNCE_F, ADVNCE_R |

**Gallery subtype variants** — encoded in `POLY b[2]`. Same geometry, different placement intent:

| POLY b[2] | Gallery suffix | Intended use |
|-----------|---------------|-------------|
| 3 | (none) = BASIC | Standard 3D objects, extruded upward |
| 2 | _F = BASIC_F | Floor tiles — bounding values flipped, lies flat |
| 1 | _R = BASIC_R | Room boundary shapes — walls/room outlines |

The `_F` (floor) variants have their POLY bounding values reversed: `b[6-7]=+48, b[8-11]=-48` vs. the standard `b[6-7]=-48, b[8-11]=+48`. This flips the extrusion direction.

### 2D Primitives (FEAT shapes on SURF / 2GALLERY items)

These are flat shapes placed on the face of a prism (windows, doors, art, etc.), or used as standalone 2D panels in `2GALLERY`. The vertex count is encoded directly in `POLY b[3]`.

**Basic shapes** (BASIC.WLB / BASIC2.WLB):

| Shape | Vertex count (POLY b[3]) | POLY size |
|-------|--------------------------|-----------|
| Triangle | 3 | 28 |
| Rectangle / Square | 4 | 36 |
| Pentagon | 5 | 44 |
| Hexagon | 6 | 52 |
| Octagon | 8 | 68 |
| Circle (16-sided) | 16 | 132 |
| Oval (ellipse approx) | 16 | 132 |

Each basic shape comes in three transparency variants encoded in the FEAT `COLR` alpha byte:
- **Opaque** (A=255) — solid colour
- **Translucent** (A=128) — dithered checkerboard in the renderer
- **Transparent** (A=0) — invisible / glass (used for open-air holes in doors/windows)

**Door shapes** (DOORS1–6, IDDOORS1–4, OFFDOOR1–4): named door styles (Panel A/B/C, French, Arched, Bifold, etc.). Arched door uses a 9-vertex polygon (b[3]=9, POLY len=76). Each in Opaque/Translucent/Transparent.

**Window shapes** (WINDOWS1–6, IDWINDO1–4, OFFWIND1–3): named window styles (Double Hung, Casement A/B/C, Gothic, Octagonal, etc.). Each in Opaque/Translucent/Transparent.

---

## 3D Gallery Library Catalogue

All available 3D library items, by WLB file:

| File | Items |
|------|-------|
| BASIC.WLB | Triangle, Rectangle, Pentagon, Hexagon, Octagon, 16-Sided (plain + Pointed variants) |
| ADVANCED.WLB | All 6 sizes in Rounded, Diamond, Sphere variants |
| HOME.WLB | Ceiling Fan, Coffee Table, Desk Lamp, Dining Chair, Dining Table, Fireplace, Floor Lamp, Love Seat, Platform Bed, Side Table, Sofa, Stereo with Stand, Study Desk, TV with Stand, Wooden Bookcase, Wing Back Chair |
| HMCHAIR1.WLB | Monolith, Overstuffed 1/2, Recliner, Rocker, Slip Covered, Swivel, W, Westside, Wooden |
| HMCHAIR2.WLB | Curtis, Eccles, Folding, Grable, Grid, High Back, K, Kid's Critter, Kid's House, Modern Steel |
| HOMTABLE.WLB | 20 table styles (Baleri, Brass, Glass, Kitchen, Meier, Pine, etc.) |
| HOMELIFE.WLB | 24 "Brutus" human figure variants (standing, sitting, dancing, etc.) |
| HOMEMISC.WLB | Frames, Books, Bracket Shelving, Brutus de Milo, Floor Lamp, Potted Plant, Telephone, Toilet, etc. |
| KITCHEN.WLB | Butcher Block, Dishwasher, Floor Cabinet, Cooktop Island, Kitchen Table, Microwave, Range, Refrigerator, Sink, Wall Cabinet |
| KITITEM1.WLB | Bar Sink, Bar Stool, Breakfast Table, Butcher Block, Cannisters, Electric Range, etc. |
| KITITEM2.WLB | Food Processor, Fridges, Islands, Microwave, Range Hood, Sink |
| KFLRCAB1–2.WLB | Modular floor cabinet components (labelled A–W) |
| KWALCAB1–2.WLB | Modular wall cabinet components (numbered 1–24) |
| OFFICE.WLB | Bookshelf, Conference Table, Copy Machine, Credenza, Computer Desk, Executive Chair/Desk, File Cabinet, Magazine Table, Office Sofa |
| OFFDESKS.WLB | Albini, Combo, Computer, Corner Work Center, Executive, Enterprise, Manhattan, Platner, Queen Anne, Roll-Top, Simple desks |
| FURNISH1–2.WLB | Office furnishings: desks, chairs, plants, boards, shelves |
| EQPMENT1–2.WLB | Office equipment: Macs (IIci, Classic, LC, Quadra, Powerbook), monitors, printers, scanners, projectors, PCs |
| PEOPLE.WLB | Human figures: Alexandra, Carnus the Dog, Cooking Man, Fellini the Cat, Lawnmower Man, Alexei, Nicholas, Baby, Jackie |
| IDCHAIR1–4.WLB | Interior design chairs: Adirondack, Mission, Shaker, Barcelona, Brno, Hoffmann, Bentwood, Windsor, Futon, etc. |
| IDTABLES.WLB | Interior design tables: Breuer, Trestle, Gate Leg, FLLW Sectional, Corb Pedestal, etc. |
| IDSTORAG.WLB | Antique/Mission/Shaker storage pieces |
| IDMISCEL.WLB | Interior design miscellany: mirrors, beds, lamps, chandeliers, writing tables |
| HOMCHAIR1–2.WLB | Home chairs (duplicate/extension of HMCHAIR series) |
| TAB_STOR.WLB | 5-High Bookcase, Barrister, Cherry Wall Unit, Credenza, etc. |
| ROOMS1–2.WLB | Complete pre-built room scenes (Bathroom, Bedroom, Kitchen, Living Room, Garage, etc.) |
| LANDSCAP.WLB | Outdoor items: Barbecue Grill, Basketball Goal, Potted Plant, Oak Tree, Pine Tree, Picnic Table, etc. |
| FARM.WLB | Barn, Farmer, Hay Bales, Jersey Cow, Silo, Pig, Tractor |
| MODCONF1–3.WLB | Modular conference workstation components (coded names: X1AI/X1AL/X1AR etc.) |
| MODCRNR1–2.WLB | Modular corner units |
| MODSTORG.WLB | Modular storage units |
| MODULARW.WLB | Modular wall units |

BASIC_F, BASIC_R, ADVNCE_F, ADVNCE_R are alternate versions of BASIC and ADVANCED (possibly different face orientations or flat/round floor variants).

---

## Complete Chunk Reference

| Chunk | Purpose | Typical Size |
|-------|---------|-------------|
| BMAP | Bitmap/icon image data | Variable |
| COLR | Colour: 8 bytes (3D), 4 bytes (2D) | 4 or 8 |
| CONN | Connectivity / snap points (WLB only) | Variable |
| CPRF | Colour profile / palette | 52 |
| DATA | Generic raw data block | Variable |
| ELGT | Environment / ambient lighting | Variable |
| ESLC | Extended slice definitions (N×40 bytes) | Variable |
| FEAT | 2D feature shape; or empty type-marker | 0 or variable |
| FORM | IFF container | Variable |
| LAYR | Layer definition (visibility, lock) | 16 |
| LGHT | Light source definition | Variable |
| LNUM | Layer number | 2 |
| LOCK | Lock state flags | 2 |
| NAME | Pascal string item name | Variable |
| PDEF | Project definition (floor names) | 82 |
| PEDT | Edit-mode UI colours | 32 |
| PGRP | Prism group (locked group + transform) | Variable |
| PLGR | Library reference index | 2 |
| PMOD | Project model display settings | 118 |
| PNAV | Camera / navigation state | 16 |
| POLY | Polygon cross-section (2D or 3D) | Variable |
| POSN | Position/rotation/scale transform | 48 (3D), 24 (2D) |
| PREF | Project preferences FORM(VPRF) | 514 |
| PRND | Rendering settings | 16 |
| PRSM | Prism 3D primitive | Variable |
| PUNT | Print unit + project name | 44 |
| PWIN | Viewport window layout | 66 |
| ROOT | Scene root container | Variable |
| SLIC | Slice definitions (N×16 bytes) | Variable |
| SURF | Surface decoration (face index + FEATs) | Variable |
| SUTX | Surface texture container (TXID+TXOD+TATR) | Variable |
| TATR | Texture attributes | 0 |
| TRNS | Transparency settings | 52 |
| TXID | Texture ID (0xFFFFFFFE = none) | 4 |
| TXOD | Texture operation data | 4 |
| TXTB | Texture bank (always empty in observed files) | 0 |
| UNIT | Unit scale (IEEE 754 double = 0.0254) | 8 |
| VERS | Format version number | 4 |
| VGER | Version group wrapper | Variable |
| VGRS | Version: uint16 major + uint16 minor | 4 |
| VMDL | Visual model type marker (empty) | 0 |
| VPRF | View preference type marker (empty) | 0 |
| VRIF | Visual riff / thumbnail bitmap | Variable |

---

## Hardcoded Gallery Order

The app's gallery selector lists galleries in a fixed order. The index from position 0 in these lists is what `PLGR b[1]` would encode IF it were a gallery index — however PLGR is now confirmed to be a binary flag (not an index), so this list is primarily useful for implementing a WLB loader that mirrors the app's UI.

### 3D Gallery Order (44 entries, 0-indexed)

| # | Gallery file | Notes |
|---|-------------|-------|
| 0 | Basic | Plain + Pointed variants of 6 polygon sizes |
| 1 | Advanced | Diamond/Rounded/Sphere variants |
| 2 | Advnce_f | Advanced Floor preset |
| 3 | Advnce_r | Advanced Room preset |
| 4 | Basic_f | Basic Floor preset |
| 5 | Basic_R | Basic Room preset |
| 6 | Eqpment1 | Office equipment A (Macs, monitors, etc.) |
| 7 | Eqpment2 | Office equipment B (scanners, projectors, etc.) |
| 8 | Farm | Barn, farm animals, tractor |
| 9 | Furnish1 | Office furnishings A |
| 10 | Furnish2 | Office furnishings B |
| 11 | Hmchair1 | Home chairs A |
| 12 | Hmchair2 | Home chairs B |
| 13 | Home | Home essentials (sofa, bed, fireplace, TV stand...) |
| 14 | Homelife | Brutus human figure variants (24 items) |
| 15 | Homemisc | Miscellaneous home items |
| 16 | Homtable | Home tables (20 styles) |
| 17 | Idchair1 | Interior design chairs A |
| 18 | Idchair2 | Interior design chairs B |
| 19 | Idchair3 | Interior design chairs C |
| 20 | Idchair4 | Interior design chairs D |
| 21 | Idmiscel | Interior design miscellany |
| 22 | Idstorag | Interior design storage |
| 23 | Idtables | Interior design tables |
| 24 | Kflrcab1 | Kitchen floor cabinets A–L |
| 25 | Kflrcab2 | Kitchen floor cabinets L–W |
| 26 | Kitchen | Kitchen essentials (10 items) |
| 27 | Kititem1 | Kitchen items A |
| 28 | Kititem2 | Kitchen items B |
| 29 | Kwalcab1 | Kitchen wall cabinets 1–12 |
| 30 | Kwalcab2 | Kitchen wall cabinets 13–24 |
| 31 | Landscap | Outdoor / landscape items |
| 32 | Modconf1 | Modular conference workstations A |
| 33 | Modconf2 | Modular conference workstations B |
| 34 | Modconf3 | Modular conference workstations C |
| 35 | Modcrnr1 | Modular corner units A |
| 36 | Modcrnr2 | Modular corner units B |
| 37 | Modstorg | Modular storage |
| 38 | Offdesks | Office desks (12 named styles) |
| 39 | Office | Office essentials (10 items) |
| 40 | People | Human/animal figures |
| 41 | Rooms1 | Complete pre-built rooms A |
| 42 | Rooms2 | Complete pre-built rooms B |
| 43 | Tab_stor | Tables and storage |

**Note:** `MODULARW.WLB` exists on disk (11 modular wall items) but does NOT appear in the UI gallery list. It may be a hidden or disabled gallery, or used internally.

### 2D Gallery Order (28 entries, 0-indexed)

| # | Gallery file | Contents |
|---|-------------|---------|
| 0 | Basic | Rectangle, Square, Triangle, Pentagon (Opaque/Translucent/Transparent) |
| 1 | Basic2 | Circle, Hexagon, Octagon, Oval |
| 2 | Doors1 | Arched, Divided Arch, Divided A/B, French doors |
| 3 | Doors2 | Panel A/B/C, Surround A/B doors |
| 4 | Doors3 | Beebe, Bell, Forster, Honeychurch, Wharton doors |
| 5 | Doors4 | Emerson, Macintosh, Morris, Ruskin, Whitman doors |
| 6 | Doors5 | Booth, Dreyfus, Moore, Schindler, Weaver doors |
| 7 | Doors6 | Felix, Krull, Sorrows, Young, Werther doors |
| 8 | Iddoors1 | Interior design doors A |
| 9 | Iddoors2 | Interior design doors B |
| 10 | Iddoors3 | Interior design doors C |
| 11 | Iddoors4 | Interior design doors D |
| 12 | Idwindo1 | Interior design windows A |
| 13 | Idwindo2 | Interior design windows B |
| 14 | Idwindo3 | Interior design windows C |
| 15 | Idwindo4 | Interior design windows D |
| 16 | Offdoor1 | Office doors A |
| 17 | Offdoor2 | Office doors B |
| 18 | Offdoor3 | Office doors C |
| 19 | Offdoor4 | Office doors D |
| 20 | Offwind1 | Office windows A |
| 21 | Offwind2 | Office windows B |
| 22 | Offwind3 | Office windows C |
| 23 | Windows1 | Residential windows A |
| 24 | Windows2 | Residential windows B |
| 25 | Windows3 | Residential windows C |
| 26 | Windows4 | Residential windows D |
| 27 | Windows5 | Residential windows E |

**Note:** `WINDOWS6.WLB` exists on disk (15 items: Bradley, Doolittle, Ike, Marshall, Ridgeway) but does NOT appear in the UI list.

---

## Complex Prefab Geometry

All library items are built entirely from `PRSM` + `PGRP` primitives — no custom geometry format. Complex-looking objects use:

- **Many small rectangular PRSMs** positioned and scaled to simulate shelves, frames, legs, etc. (e.g. the 3-Tiered Table: 14 PRSMs using 4-vertex, 6-vertex, 8-vertex polygons)
- **SLIC/ESLC slices** for objects that need bent, tapered, or angled profiles. The Decorative Cactus, for instance, uses a 6-sided prism with 6 slices (`SLIC 6 slices`) bent at `rx = -0.537 radians` to create the curved cactus arm.
- **Multiple PGRP nesting** for complex grouped objects

The flame effect in the Fireplace is entirely PRSMs — orange/yellow pointed (b[3]=2) triangular prisms arranged and scaled to look like flames when rendered without depth buffering.

The 16-Sided Sphere in ADVANCED.WLB is a single 16-sided PRSM with `b[3]=5` — the spherical profile is applied procedurally by the engine, not via SLIC/ESLC. The same 276-byte PRSM structure is used for both flat 16-sided prisms and spheres; only b[3] differs.

---

## Files Tested

| File | Contents | Key findings |
|------|----------|-------------|
| D3D/DESIGNIT/G/EMPTY.VVR | Empty scene | Baseline structure; ROOT with no geometry |
| D3D/JUSTCUBE.VVR | Single cube | PRSM with POLY(4 verts), confirmed POSN layout |
| D3D/MiscVVR/JUSTHEX.VVR | Single hexagonal prism | POLY(6 verts) |
| D3D/MiscVVR/TRI_1.VVR | Red triangular prism | POLY(3 verts), COLR=red confirmed |
| D3D/MiscVVR/JUST8.VVR | Octagonal prism | POLY(8 verts) |
| D3D/MiscVVR/JUST16.VVR | 16-sided prism | POLY(16 verts), vertices on radius-48 circle confirmed |
| D3D/MiscVVR/GROUP.VVR | Group of 3 prisms | PGRP structure confirmed |
| D3D/MiscVVR/ROT_1/2/3.VVR | Rotated shapes | POSN rotation (rz in radians) confirmed |
| D3D/MiscVVR/MOD_1/2.VVR | Unmodified vs. user-edited polygon | POLY b[1]: 3=regular, 1=custom |
| D3D/LOTSJUNK.VVR | Complex scene | SURF/FEAT/SUTX/2D POLY/2D POSN structure |
| D3D/MiscVVR/BEACHCBN.VVR | Complex beach scene | SLIC, ESLC, PLGR chunks; 3-axis rotations |
| D3D/OFFICE.WLB | Office furniture library | WLB structure; NAME, VRIF, BMAP, CONN |
| D3D/DESIGNIT/2GALLERY/BASIC.WLB | 2D basic shapes | 2D item structure (no PRSM wrapper) |
| D3D/DESIGNIT/3GALLERY/HOME.WLB | Home furniture | 3D item names, SLIC/ESLC in complex items |
| D3D/DESIGNIT/3GALLERY/BASIC.WLB | 3D basic prisms | All 6 sizes × 2 variants (plain + Pointed) |
| D3D/DESIGNIT/3GALLERY/ADVANCED.WLB | Advanced prism variants | Rounded, Diamond, Sphere variants |
| D3D/DESIGNIT/ASDASD.VVR | Test scene | PUNT, PDEF, VGER/VGRS decoded |
| All 50+ WLB files | Full library | Complete item name catalogue extracted |

---

## Implementation Guide: VVR → OBJ Converter

### Priority 1 — Minimum viable scene (most scenes will render)

1. **Parse the IFF frame** — read chunks recursively using the 4-char tag + uint32 length pattern.
2. **Find ROOT** → iterate children for `PRSM` and `PGRP`.
3. **For each PRSM:**
   - Read `POLY` → extract vertices (skip 32-byte header, read uint32 count, then N × 8-byte fp16.16 pairs). This gives you the 2D footprint.
   - Read `POSN` bytes 0–47. Position: fp[0–2]. Rotation (rz): fp[5]. Scale: fp[9–11].
   - Read `COLR` bytes 1–3 for RGB.
   - Extrude the POLY vertices in 3D to create a prism mesh. A sensible default extrusion depth is 96 units (96 inches = 8 feet) unless you later decode a height value.
   - Apply the POSN transform: translate by (x,y,z), rotate by (rx,ry,rz), scale by (sx,sy,sz).
4. **For each PGRP:**
   - Read the group's `POSN` for its own transform.
   - Recurse into children, applying the group transform on top of each child's own POSN.
5. **Output OBJ** with MTL for colours.

This handles every scene that contains only plain prisms — which is the majority of them.

### Priority 2 — Library items

6. **Detect `PLGR`** inside a PRSM/PGRP → this object was placed from the library. The index refers to a WLB file. To resolve it fully you'd need to know which WLB was loaded; for a first pass you can treat it as a regular PRSM using the geometry that IS present in the VVR.

### Priority 3 — Surface decorations

7. **Parse `SURF`** children of PRSM → `FEAT` children → 2D POLY + 2D POSN. Project these onto the designated face of the parent PRSM using the face index.

### Priority 4 — Complex shapes

8. **Parse `SLIC` / `ESLC`** to handle angled roofs and slanted faces. The full decoding of these fields is still incomplete (see unknowns below).

### Priority 5 — WLB loader

9. Parse the WLB `GAT ` header, iterate `FORM(VCLP)` blocks, extract `NAME` (for display) and embedded geometry.

---

## Unknowns and Open Questions

| Unknown | Where | Priority |
|---------|-------|---------|
| Prism extrusion height / depth | PRSM | **High** — how deep is the prism extruded? The POSN sz scale changes the overall size but the base depth isn't obvious. Likely stored as a separate parameter or baked into POSN sz against a default. |
| SLIC/ESLC full decode | SLIC, ESLC | **High** for complex shapes (roofs, dormers, bent cactus arms). Currently confirmed structure (count × 16 or 40 bytes), semantics of the 4/10 fp16.16 values not yet decoded. |
| POLY b[3] profile rendering | PRSM | **High** — the engine clearly uses b[3] to render Pointed/Rounded/Diamond/Sphere profiles. Understanding the exact algorithm is needed for the OBJ exporter to match the original look. |
| POSN `d0/d1/d2` fields (bytes 24–35) | POSN | Medium — derived rotation components, zero for Z-only rotations. Only relevant for full 3-axis rotation support. |
| COLR double-value semantics | COLR | Medium — the two ARGB values in 3D COLR (A=0 and A=255, same RGB) likely flag outer/inner face orientation for the no-depth-buffer renderer. |
| TRNS transparency encoding | TRNS | Medium — PRSM-level transparency (distinct from the 2D FEAT alpha). The 52-byte TRNS block controls overall prism translucency. |
| CPRF colour profile format | CPRF | Low — UI colours, not geometry |
| VRIF thumbnail format | VRIF | Low — previews only |
| CONN snap-point format | CONN | Low — library item connection points only |
| TXID/TXOD texture mapping | SUTX children | Low — textures appear empty in all observed files |
| LAYR full structure | LAYR | Low — layer management only |

---

## Quick-Reference: Decoding a PRSM in JavaScript

```javascript
function decodePRSM(prsm) {
  // prsm.children has been populated by the objectParse() recursive parser

  const poly = prsm.children.find(c => c.header === 'POLY');
  const posn = prsm.children.find(c => c.header === 'POSN');
  const colr = prsm.children.find(c => c.header === 'COLR');

  // --- Decode POLY ---
  const polyBuf = Buffer.from(poly.data);
  const vertexCount = polyBuf.readUInt32BE(28);
  const vertices = [];
  for (let i = 0; i < vertexCount; i++) {
    const x = polyBuf.readInt32BE(32 + i * 8) / 65536;
    const y = polyBuf.readInt32BE(32 + i * 8 + 4) / 65536;
    vertices.push([x, y]);
  }

  // --- Decode POSN ---
  const posnBuf = Buffer.from(posn.data);
  const fp = (off) => posnBuf.readInt32BE(off) / 65536;
  const position = [fp(0), fp(4), fp(8)];    // inches
  const rotation = [fp(12), fp(16), fp(20)]; // radians (rx, ry, rz)
  const scale    = [fp(36), fp(40), fp(44)]; // multipliers

  // --- Decode COLR ---
  const colrBuf = Buffer.from(colr.data);
  const rgb = [colrBuf[5], colrBuf[6], colrBuf[7]]; // R, G, B of inner face

  return { vertices, position, rotation, scale, rgb };
}
```

---

*Analysis performed April 2026 using custom Node.js parser against DESIGNIT installation files and personal project backups.*
