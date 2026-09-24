# Garment Capture Pipeline Tooling

Standalone scripts supporting the 3D garment capture pipeline (photogrammetry
scan → retopology → feature extraction). Full project context, decisions, and
history live in the project vault, not here — this repo holds only the
runnable tooling.

## Setup

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

`bake_texture.py` additionally requires **Blender** (tested against 5.2.0
LTS) as a system install — it's a Blender script run via `blender
--background --python`, not a regular Python dependency, so it isn't in
`requirements.txt`.

## Pipeline order

```
RealityScan export (OBJ)
   ↓
weld_source.py             <- this repo, run every scan
   ↓
AutoRemesher retopology
   ↓
bake_texture.py             <- this repo, via Blender, run every scan needing color
   ↓
assemble_textured_glb.py    <- this repo, run every scan needing color
   ↓
Blender preprocessing (crop/align)
   ↓
decimate_mesh.py            <- this repo, normalizes mesh density before extraction
   ↓
extract_features.py         <- this repo, upserts one row per garment into features.csv
   ↓
pca_sanity_check.py         <- this repo, PCA smoke test once a few rows exist
```

## Scripts

### `weld_source.py`

Run immediately after exporting the raw OBJ from RealityScan, before opening
it in AutoRemesher:

```bash
python weld_source.py raw_scan.obj raw_scan_welded.obj
```

**Why this step exists:** RealityScan can reconstruct a tight fabric fold
(a crease, a strap, a rolled edge) as two separate surface patches sitting at
coincident 3D positions instead of one connected surface, because the two
sides sit closer together than the capture rig's stereo baseline can
resolve. This looks completely normal in Blender or in AutoRemesher's own
source-mesh viewer, but AutoRemesher's retopology algorithm can't resolve the
ambiguity and leaves a real, unfillable gap exactly at the seam. The fix is
to weld the coincident duplicate vertices back into one connected surface —
this must happen on the raw scan, before retopology, since the duplicate-
vertex signature the script relies on does not survive AutoRemesher's
resampling.

Diagnosed and fixed 2026-09-06 on a test dress scan: 571,386 boundary edges
(2,482 separate hole regions) went to zero after welding, with zero
non-manifold edges and zero degenerate faces introduced. Full diagnostic
writeup — including the dead ends tried first (Target Quads tuning, a
Blender Fill Holes crash on the dense raw mesh, two failed post-retopology
capping attempts) — is in the project vault under
`concepts/realityscan-wine-workflow.md`.

**Pass/fail check, every run:** the script prints boundary-edge counts
before and after welding. After welding, this should land at or near zero.
If a future scan still shows a large residual count, that scan likely has a
*different* defect — a genuine occlusion hole with no nearby duplicate
vertex, not this fold-collapse pattern — and needs manual inspection rather
than trusting this script's output as fully closed. The script prints an
explicit warning when this happens.

**Known open question:** on the test scan, welding closed *every* boundary
edge in the mesh, including what may be the garment's neckline/hem — this
might be the same fold-collapse artifact happening at a rolled fabric edge
(desirable to weld), or it might be a real intentional opening that
shouldn't be sealed. Not yet resolved generally; check on a per-garment
basis until this is settled.

### `bake_texture.py` + `assemble_textured_glb.py`

Run after AutoRemesher retopology, if the garment needs real color/texture
(not just clean geometry) for display:

```bash
blender --background --python bake_texture.py -- \
  --source-obj raw_scan.obj \
  --diffuse-png raw_scan_textures/diffuse.png \
  --target-obj retopologized.obj \
  --out-obj retopologized_uv.obj \
  --out-texture baked_diffuse.png \
  --angle-limit 66.0 \
  --island-margin 0.02

python assemble_textured_glb.py \
  --mesh-obj retopologized_uv.obj \
  --texture-png baked_diffuse.png \
  --out-glb final.glb
```

`--angle-limit`/`--island-margin` control Blender's Smart UV Project call
directly (defaults shown above, Blender's own defaults) — see the
texture-stretch gotcha below before reaching for these on a future scan
that looks stretched; they're less likely to help than they sound.

**Why two steps, and why this exists at all:** AutoRemesher's retopology
produces entirely new geometry with no UV coordinates, so there's no way to
carry the original scan's photo texture over directly — without this step,
the only option is a coarse per-vertex-color approximation (one color
sample per vertex, blended across each triangle), which looks visibly
low-resolution regardless of how good the source photo is. `bake_texture.py`
UV-unwraps the clean mesh and bakes real per-pixel detail from the dense
source mesh's actual texture onto that new layout (Blender/Cycles,
selected-to-active baking — the standard game-dev "high-poly to low-poly"
technique). `assemble_textured_glb.py` then builds the actual GLB, kept
separate from the Blender step because Blender's own glTF exporter failed
to embed the baked image in testing (an OCIO colorspace-version mismatch),
silently falling back to a flat gray material — `trimesh` doesn't have that
failure mode for this use case.

**Real gotchas hit building this, worth knowing before debugging a future
scan that "looks wrong":**
- The scan's own diffuse texture file may not be the one referenced by any
  GLB's embedded material — one export in this project had a bogus
  UV-checker/UDIM debug grid embedded instead of the real photo. Confirm
  visually (or by checking image dimensions/content) which file is
  actually the captured texture before assuming a GLB's embedded one is it.
- `bake_texture.py` exports OBJ, not GLB, specifically to avoid GLB's
  scene-graph node transforms — reading a GLB's raw geometry via a generic
  loader's `scene.geometry` can return *untransformed local-space*
  vertices instead of the actual world-space mesh (use `scene.to_geometry()`
  in trimesh if you ever do need to read a GLB's geometry directly).
- A GLB primitive with no material at all should fall back to a white
  default per the GLTF spec, but rendered solid black in this project's
  actual viewer — always set an explicit `baseColorFactor`.
- **Smeared texture + black blocks on `testdress4` (2026-09-23): the
  retopologize-and-rebake route itself was the problem, not any tunable.**
  The dense RealityScan mesh + its own texture rendered clean in Blender;
  the baked result did not, with streaks and solid black squares
  concentrated along the center-front placket (thin overlapping fabric
  layers, ribbon ties and ruffles that the smooth ~23k-vertex AutoRemesher
  shell doesn't represent, so bake rays land on the wrong layer or miss).
  Verified by rendering both in headless Blender and comparing. All of
  these produced *pixel-identical artifacts in the same places*, so none of
  them is the lever: Smart UV Project `angle_limit` 30/66/89, bake
  `cage_extrusion`/`max_ray_distance` up to 1.0/4.0 (all now CLI flags), and
  a switch to LSCM unwrap with auto-seams (far worse, near-zero UV area on
  99.9% of faces). The baked atlas was also visibly paler than the source
  texture, so a colorspace shift (the OCIO fallback) sits on top of this.
  **Fix, now applied to all five test dresses (2026-09-23):** skip
  retopology/baking for the *display* asset and decimate the dense textured
  mesh directly, keeping RealityScan's own UVs and texture. Each GLB is
  3.9-5.3MB (4K JPEG texture, 100k faces), verified by front/back renders
  with no smearing or black blocks and the correct color. Retopology is
  still what feeds `decimate_mesh.py` / `extract_features.py`; only the
  display GLB changed. See `dense_to_glb.py` below.

### `dense_to_glb.py` + `decimate_dense_textured.py`

The current way to build a display GLB (replaces `bake_texture.py` +
`assemble_textured_glb.py` for this purpose):

```bash
python dense_to_glb.py \
  --obj raw_scan.obj \
  --texture raw_scan_u1_v1_diffuse.png \
  --out-glb final.glb \
  --rotate-x -90          # 0 for a Y-up export, -90 for a Z-up one
```

Wraps the Blender Collapse decimate (5.0M -> 100k faces, ~75s) and the
trimesh GLB assembly. Instead of `--rotate-x` you can pass
`--reference-glb existing.glb` to auto-pick the axis-aligned rotation that
best matches an existing GLB's bounds, and it prints the residual. Handy
when re-doing a garment so a tuned `model3d_rotationY` stays valid. Two
things worth knowing from doing that for testdress0-3:
- `testdress1`'s old GLB also had a +7.81 vertical offset (recovered
  exactly by Procrustes-aligning its old UV mesh against the live GLB), so
  the reference check reported a large residual there even though the
  rotation was right. A large residual means "look for an offset", not
  "wrong rotation".
- `testdress0`'s dense OBJ has no texture in its `.mtl`; its only texture is
  the `..._LowPoly_u0_v0_diffuse.png` from RealityScan's low-poly export,
  and that pairs correctly with the dense mesh's UVs (verified by render),
  so don't assume a missing `map_Kd` means the UVs are unusable.

The old retopologized-and-baked GLBs are kept as
`textured/testdressN_baked_old.glb` (gitignored) and in the frontend's git
history.

### `decimate_mesh.py`

Run after retopology (and before feature extraction) on a copy of the mesh
dedicated to extraction -- keep it separate from whatever copy feeds
`bake_texture.py`/the frontend, since decimating after UV-unwrap + baking
would invalidate the baked texture's UV layout:

```bash
blender --background --python decimate_mesh.py -- \
  --input-obj retopologized.obj \
  --output-obj retopologized_decimated.obj \
  --target-vertices 15000
```

**Why this exists:** `extract_features.py`'s `surface_area` and curvature
columns are density-sensitive -- a denser mesh reads as having more
surface detail purely from having more, smaller triangles, independent of
actual garment shape. AutoRemesher's output vertex count isn't currently
controlled and varied 21,872–30,303 across the three test garments before
this script existed. Uses Blender's Decimate modifier (Collapse type),
computing a ratio from the mesh's current vertex count to hit the target
(Blender's decimate takes a ratio, not a target count directly, so this
doesn't land on the target exactly -- it prints a warning if the result is
off by more than 15%). Default target (15,000) is below every garment's
vertex count seen so far, since a mesh can only be decimated down, not up.

**Real gotcha hit building this:** the first version exported OBJ with
default settings and the *reloaded* vertex count came back wildly
inflated (~70,000, not the ~15,000 Blender's own mesh data actually had)
-- Blender's OBJ exporter writes a separate vertex line per unique
(position, normal) combination referenced by a face, and the Decimate
modifier leaves flat/hard-shaded normals at collapsed edges, so nearly
every face corner ended up with its own duplicate-position vertex on
export. Fixed with `export_normals=False` -- normals aren't meaningful
for geometric feature extraction anyway, and this makes the exported
vertex count match Blender's internal count exactly.

### `extract_features.py`

Run after preprocessing, once a clean, density-normalized mesh (`decimate_mesh.py`'s
output, OBJ or GLB) is ready:

```bash
python extract_features.py --mesh testdress0.glb --garment-id testdress0 \
    --label "Test Dress 0" --out features.csv
```

Upserts one row per `--garment-id` into `features.csv` (re-running the same
ID replaces that row rather than duplicating it). Computes bounding box,
surface area, volume, and mean/std curvature; auto-corrects for a real
per-scan Z-up vs Y-up inconsistency confirmed across garments in this
project. `volume` is currently NaN for every garment — AutoRemesher's quad
retopology leaves a handful of non-manifold edges even after `weld_source.py`
closes all boundary edges, which fails `trimesh.is_watertight`'s stricter
check; `symmetry_score`/`drape_extent` are undefined placeholders pending a
methodology decision. See the project vault
(`concepts/garment-capture/garment-feature-extraction.md`) for the full
gotcha writeup.

### `pca_sanity_check.py`

Run once `features.csv` has a few rows, as a pipeline smoke test (not a
real statistical result until the 5-garment pilot target is reached):

```bash
python pca_sanity_check.py --features features.csv --out pca_sanity_check.png
```

Z-score standardizes the well-defined, non-NaN columns (`bbox_x/y/z`,
`surface_area`, `mean_curvature`, `std_curvature`) and runs PCA, printing
explained variance and component loadings and saving a labeled scatter
plot. Deliberately excludes `volume`/`symmetry_score`/`drape_extent`
(all-NaN so far — dropped rather than imputed, to avoid fabricating signal)
and `num_vertices`/`num_faces` (density isn't normalized across garments
yet, so these currently measure retopology resolution more than shape).
Requires `pandas`, `scikit-learn`, and `matplotlib` (in `requirements.txt`).
