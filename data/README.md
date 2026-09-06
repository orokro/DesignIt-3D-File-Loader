# `data/` — the consolidated corpus

Every file from all **four** Virtus-engine products in this repository —
Design-It! 3-D, Key Design Center 3-D, Virtus VRML and 3D Website Builder —
deduplicated and organised by role. **Generated** by
`claude-explore/tools/build_data.py`; the original `D3D/` tree is the source of
truth and is never modified. Re-run the script to rebuild.

695 files, 70 MB (down from 104 MB — 282 files ship identically with more than
one product and are stored once, with every origin recorded in the manifest).

| Folder | Files | What's in it |
|---|---:|---|
| `scenes/` | 179 | Complete `.VVR` / `.WSB` scenes — rooms, houses, dioramas, sites |
| `models/` | 127 | Single-subject models — the A-10, Saturn V, Himeji Castle, an articulated figure |
| `galleries3d/` | 94 | `.WLB` libraries of 3D objects (`PRSM` clips) |
| `galleries2d/` | 33 | `.WLB` libraries of 2D surface features (`FEAT` clips) — doors, windows, shapes |
| `textures/` | 97 | `.TLB` texture libraries |
| `exports/` | 134 | The single-object exports, one folder per gallery, each with the app screenshot |
| `misc/` | 31 | Loose test and probe files |

1,595 gallery clips are indexed across the `.WLB` libraries, and the scenes and
models together come to 726,876 triangles.

**`.WSB` is 3D Website Builder's scene extension and the container is
byte-identical `FORM<VMDL>`** — across its 408 files there is not one chunk tag
the other three products do not use. The extension is the only difference.

## `manifest.json`

One record per file. Every record carries `path`, `bucket`, `apps` (which
application(s) shipped it), `bytes`, and `sources` — the original paths it was
copied from, so a duplicate's full provenance is recoverable.

`.VVR`, `.WSB` and `.TLB` records add geometry stats: `prisms`, `groups`, a `profiles`
histogram, `slicedPrisms`, `decoratedFaces`, `features`, and for scenes a
`bounds` block with world min/max, mesh count and triangle count.

`.WLB` records instead carry `clipCount` and a `clips` array with the same
stats per named clip.

Coordinates are inches with **Z up**, matching the format.

## Deliberate inclusion

`misc/JUSTCUBE_forced_formatting.VVR` does **not** parse — it is a
line-ending-mangled copy with a stray byte inside the `VMDL` tag. It is kept on
purpose as a negative test: a loader should reject it cleanly rather than
produce garbage. It is the only file in the corpus that fails to parse, and the
manifest records its `parseError`.

## Deliberate EXCLUSION

`3DWebBld/Samples/booth/booth_e.wsb` is the one source file left out. It has the
same damage the negative test above imitates, but for real: **zero `0x0A` bytes
in 334 KB, and 93 `0x0D`**. Every line feed in it was rewritten as a carriage
return by a text-mode transfer, which turns a chunk length of 10 into 13 and
derails the parse.

It is not repairable. The parse constrains only the length bytes; the same
substitution also hit bytes inside colour and coordinate payloads, where nothing
constrains them — so a "fixed" file would parse cleanly while carrying silently
wrong geometry, which is worse than not having it. **Re-extracting that one file
from the ISO in binary mode would recover it properly.** The same zero-`0x0A`
test over all 775 binaries in the project finds no other affected file.

## Duplicates: `dedupe.json`

The corpus ships the same object many times over. 3DWebBld reissued whole
Design-It! libraries under new lowercase names (`equip1.wlb` is `EQPMENT1.WLB`),
a few galleries repeat a clip inside one file (`Chairs1.wlb` holds five
identical `Adirondack Chair`s), and thirteen scenes exist twice under different
filenames. Across `galleries3d`, `models` and `scenes` that is **279 redundant
copies of 1157 distinct objects**.

**Nothing here is deleted.** `dedupe.json` simply lists the copies the explorer
skips, so the grid shows each object once; its `Show all` toggle ignores the
list and the files themselves are untouched. Editing a 1993 vendor file to
remove a clip would make this tree useless as evidence for any future format
question, which is the whole reason it exists.

Two things are deliberately NOT duplicates. Rotations: `BASIC_F` / `BASIC_R` are
the Front and Right working views of one primitive, offered by the app as
separate library entries. And textures: Design-It! and Kesign3D ship
geometrically identical models where only the Kesign3D copy is textured
(`APOLLO.VVR` vs `APOLLO__kesign3d.VVR`), so a texture's name and pixels are
part of the fingerprint.

Regenerate after any change to the corpus, since `build_data.py` adds files but
never prunes this list:

    python claude-explore/tools/dedupe.py suppress galleries3d models scenes
