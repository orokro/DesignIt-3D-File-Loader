# `web/` — Design-It! 3-D viewer

A self-contained Three.js viewer for `.VVR` scenes and `.WLB` galleries. No
build step, no bundler, no network: Three.js is vendored in `vendor/`.

```sh
./serve.sh          # then open http://localhost:8080/web/
```

A server is required — the viewer `fetch()`es binaries, which `file://` blocks.

## Layout

| File | Role |
|---|---|
| `src/iff.js` | Strict IFF-85 reader. No Three.js dependency. |
| `src/clip.js` | Plane clipping for `SLIC` cuts. No Three.js dependency. |
| `src/geometry.js` | `PRSM` sweeping, profiles, transforms, `SURF`/`FEAT`. No Three.js dependency. |
| `src/three-loader.js` | The only file that imports Three.js. |
| `index.html` | The viewer UI. |
| `parity.mjs` | Geometry digest for cross-checking against the Python reference. |

The three `src/` modules below `three-loader.js` are deliberately free of
Three.js so they can run under Node and be diffed against the Python
implementation in `claude-explore/tools/`.

## Verification

`parity.mjs` and `claude-explore/tools/parity.py` emit the same digest — mesh
count, triangle count, surface area, **signed volume** and bounding box — for
any set of files. Area, volume and bounds are independent of how a surface
happens to be tessellated, so they compare geometry rather than triangle
bookkeeping.

```sh
node parity.mjs ../data/models/*.VVR > /tmp/js.json
python3 ../claude-explore/tools/parity.py ../data/models/*.VVR > /tmp/py.json
```

Current result across all 160 models, scenes and misc files: **159 identical**,
36 of which differ only in tessellation. The one exception is
`misc/JUSTCUBE_forced_formatting.VVR`, which both implementations correctly
refuse to parse.

## Decals

Surface decorations are coplanar with the face they sit on. Rather than nudging
them along the normal — which leaves them mathematically floating and still
fights at distance — they use `polygonOffset`, which biases depth *during the
depth test only*. The vertices stay exactly on the surface.

Decorations also **stack**: an RAF roundel is three concentric `FEAT` records on
a single face, mutually coplanar. Each gets its own bias and `renderOrder` from
its paint order within the `SURF`, so layers separate cleanly instead of
fighting each other.
