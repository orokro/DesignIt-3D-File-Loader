# `data/` — the consolidated corpus

Every Design-It! 3-D and Key Design 3-D file from this repository, deduplicated
and organised by role. **Generated** by `claude-explore/tools/build_data.py`;
the original `D3D/` tree is the source of truth and is never modified. Re-run
the script to rebuild.

404 files, 19 MB (down from 41.7 MB — 201 files ship identically with both
applications and are stored once, with every origin recorded in the manifest).

| Folder | Files | What's in it |
|---|---:|---|
| `scenes/` | 88 | Complete `.VVR` scenes shipped with the apps — rooms, houses, dioramas |
| `models/` | 45 | Single-subject `.VVR` models — the A-10, Saturn V, biplane, 18-wheeler |
| `galleries3d/` | 45 | `.WLB` libraries of 3D objects (`PRSM` clips) |
| `galleries2d/` | 29 | `.WLB` libraries of 2D surface features (`FEAT` clips) — doors, windows, shapes |
| `textures/` | 36 | `.TLB` texture libraries, Key Design 3-D only |
| `exports/` | 134 | The single-object exports, one folder per gallery, each with the app screenshot |
| `misc/` | 27 | Loose test and probe files |

1,005 gallery clips are indexed across the `.WLB` libraries.

## `manifest.json`

One record per file. Every record carries `path`, `bucket`, `apps` (which
application(s) shipped it), `bytes`, and `sources` — the original paths it was
copied from, so a duplicate's full provenance is recoverable.

`.VVR` and `.TLB` records add geometry stats: `prisms`, `groups`, a `profiles`
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
