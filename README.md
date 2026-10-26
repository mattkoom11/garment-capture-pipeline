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

Current flow (since 2026-09-23). Both branches start from the dense RealityScan
OBJ + its texture; AutoRemesher retopology is no longer used by either.

```
RealityScan export (dense OBJ + diffuse texture)
   |
   +-- display:     dense_to_glb.py  ->  GLB for the frontend
   |
   +-- statistics:  weld_source.py      <- only if the scan is fragmented
                       ↓                   (dense_features.py refuses those)
                    dense_features.py   <- decimate -> merge -> connectivity
                       ↓                   check -> 15k vertices ->
                       ↓                   split non-manifold edges ->
                       ↓                   extract_features.py
                    features.csv
                       ↓
                    pca_sanity_check.py <- PCA smoke test
                       ↓
                    export_portfolio.py <- PCA + k-means as JSON for the
                                           portfolio site's demo (run from
                                           the portfolio: npm run sync:garments)
```

Retired for the display and statistics paths (kept as history and in case
they're needed again): AutoRemesher retopology, `bake_texture.py`,
`assemble_textured_glb.py`, and `decimate_mesh.py` as a standalone step
(`dense_features.py` still calls it internally). Previous retopology-based
results are in `features_retopo_v1.csv`.

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

**Color: `--srgb-encode` (2026-09-23, tested on `testdress4` only).**
RealityScan's diffuse comes out dark, orange and oversaturated next to the
photos (testdress3: diffuse median RGB 146,87,25 vs. its Blender-baked atlas's
190,150,82; the sRGB curve applied to the former gives ~199,158,88). Same
shift measured on all five dresses. It
looks like linear values being read as sRGB. `--srgb-encode` applies the
linear->sRGB curve after the downscale. It is a workaround: if a RealityScan
export/color-profile setting is found that writes the texture correctly,
use that and drop the flag, or the correction applies twice. All five
dresses are fixed. `testdress4` was rebuilt with the flag; `testdress0`-`3`
were re-textured in place with `srgb_fix_glb.py` (below), because a rebuild
would have lost testdress1's vertical offset. Pre-fix GLBs are kept, gitignored,
as `textured/testdress4_orange_old.glb` and
`textured/testdressN_raw_old.glb` (`testdress0-repaired_raw_old.glb` for 0).

`srgb_fix_glb.py` swaps an sRGB-encoded 4K JPEG (downscaled from the original
diffuse, then encoded) into an existing GLB and leaves vertices, faces, UVs and
bounds untouched (verified identical):

```bash
python srgb_fix_glb.py --glb testdress1.glb \
  --texture TestDress1_u1_v1_diffuse.png --out-glb testdress1_fixed.glb
```

Don't run it on a GLB that was already built with `--srgb-encode`, or the
correction applies twice.

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
project. `symmetry_score` and `drape_extent` are implemented (see the
docstring). `volume` was NaN for every garment while features came from the
AutoRemesher mesh — its quad retopology leaves non-manifold edges that fail
`trimesh.is_watertight` — but is defined for meshes decimated from the dense
scan (see `dense_features.py` below). See the project vault
(`concepts/garment-capture/garment-feature-extraction.md`) for the full
gotcha writeup.

`--capture-method {photogrammetry,hybrid}` (default `photogrammetry`) tags
the row so PCA/clustering can check for a capture-method confound once
some garments are hybrid photogrammetry+LiDAR scans and some aren't — see
`concepts/garment-capture/hybrid-lidar-capture.md`. Rows written before this
flag existed are backfilled to `photogrammetry` automatically.

### `dense_features.py`

**How `features.csv` is now built (since 2026-09-23).** Builds a row straight
from a dense RealityScan scan, skipping AutoRemesher:

```bash
python dense_features.py --obj TestDress4.obj --garment-id testdress4 \
    --label "Test Dress 4" --out features.csv
```

Decimates the dense scan (5M -> 100k faces), merges vertices by position, checks
connectivity, decimates to `--target-vertices` (default 15,000), and runs
`extract_features`. Why: the retopologized mesh's smoothing biased the features
(`surface_area` ~10% low, curvature 0.6-1.7x off, `volume` undefined); see
`experiments/dense_vs_retopo/`. The **connectivity check refuses a fragmented
or open mesh** (raw `TestDress0.obj` decimates to 1,548 pieces — RealityScan's
fold-collapse defect), telling you to run `weld_source.py` first and pass the
welded OBJ, as was done for `testdress0`.

Density is held fixed deliberately: mean curvature drifts *systematically* with
mesh density (differently per garment: `testdress3` 0.81 -> 0.94 from 13k to 50k
vertices, `testdress1` 0.25 -> 0.22), but within 13k-17k vertices it varies
only ~4% per garment vs a between-garment spread ~20x larger (signal-to-noise
22-113 for every feature; `volume` is essentially exact). The 13k-17k band was
more stable than 25k-50k on symmetry and drape, so 15k stays the target.

**Non-manifold edges (added 2026-10-07).** After the 15k decimation, any edge
shared by more than 2 faces is repaired before features are computed. This
happens where two fabric layers touch: `ENS.2023.14` had one such edge, which
made trimesh report the mesh as not watertight, set `volume` to NaN, and
dropped `volume` from PCA for every garment. One endpoint of the edge is split
into one vertex per sheet, and each copy is nudged 1e-5 x the bbox diagonal so
trimesh's default vertex merge doesn't fuse them back. Only one endpoint is
split: ENS.2023.14's pinch is a crossing, where the faces pair up into sheets
differently at each end, so splitting both endpoints leaves 4 one-sided edges.
On ENS.2023.14 this added 1 vertex. `surface_area`, curvature, symmetry and
drape moved by under 0.3%, and `volume` became 650.5. The step does nothing
on a mesh that is already watertight, which covers the other 7 rows.

`features_retopo_v1.csv` / `pca_sanity_check_retopo_v1.png` preserve the
previous retopology-based results.

Also takes `--capture-method` (same as `extract_features.py` above) — pass
`--capture-method hybrid` for any garment whose OBJ includes a merged
LiDAR scan (see `concepts/garment-capture/hybrid-lidar-capture.md`).

### `pca_sanity_check.py`

Run once `features.csv` has a few rows, as a pipeline smoke test (not a
real statistical result until the 5-garment pilot target is reached):

```bash
python pca_sanity_check.py --features features.csv --out pca_sanity_check.png
```

Z-score standardizes eight columns (`bbox_x/y/z`, `surface_area`,
`mean_curvature`, `std_curvature`, `symmetry_score`, `drape_extent`), plus
`volume` when it has no NaNs, and runs PCA, printing explained variance and
component loadings and saving a labeled scatter plot. Any column with NaNs is
dropped rather than imputed, to avoid fabricating signal. `num_vertices` /
`num_faces` are excluded because every mesh is decimated to ~15k vertices, so
they're near-constant by construction and carry no shape signal. If
`features.csv` has a `capture_method` column, prints a breakdown and warns
if it's mixed (photogrammetry + hybrid) — a hybrid garment's LiDAR-derived
geometry may read systematically smoother than photogrammetry, which could
masquerade as a real PCA split; see
`concepts/garment-capture/hybrid-lidar-capture.md`.
Requires `pandas`, `scikit-learn`, and `matplotlib` (in `requirements.txt`).

### `clustering_analysis.py`

Pilot Plan phase 5. Run once `pca_sanity_check.py` looks clean; doesn't need
catalog metadata to be useful today:

```bash
python clustering_analysis.py --features features.csv
```

Runs k-means and hierarchical (Ward) clustering across a small range of k
(default 2..min(6, n-1)) on the same z-scored feature set as
`pca_sanity_check.py`, reports silhouette scores (an internal metric, no
ground truth needed), writes every k's cluster assignments to
`cluster_assignments.csv`, and saves a dendrogram
(`cluster_dendrogram.png`). Refuses to run below n=4. Same
`capture_method` breakdown/warning as `pca_sanity_check.py` above — check
it before trusting a cluster split once hybrid-captured garments exist.

**ARI/NMI validation against real catalog metadata** (curator-assigned
`silhouette`/`torso`/etc. from CollectiveAccess) activates once that data
exists — pass a CSV with a `garment_id` column matching `features.csv` plus
your label column:

```bash
python clustering_analysis.py --features features.csv \
    --metadata catalog_metadata.csv --metadata-column silhouette
```

Refuses to run the validation if any garment in `features.csv` is missing a
metadata value (a partial ground-truth set would silently bias ARI/NMI),
rather than silently dropping rows. Built and tested at n=6 (both the
unsupervised path and the ARI/NMI path, the latter against synthetic
placeholder labels used only to exercise the code — not a real result)
specifically so it's ready and debugged before the 15-20 garment Phase 4/5
target, per the project vault's recommendation not to leave this until
under time pressure. Requires `scipy`, `scikit-learn`, `matplotlib` (already
in `requirements.txt`).

**First real (non-synthetic) ARI/NMI run (2026-10-25):** `catalog_metadata.csv`
holds real `era` values (`pre-1920` / `1920-1950` / `1950-1980`) for the 12
garments that now have a known accession number in the collection
spreadsheet; `testdress0` still has none and is excluded. Since the script
refuses to run with a partial ground-truth set, this validation runs against
a filtered `features.csv` (no `testdress0`), saved separately as
`cluster_assignments_era_validated.csv` / `cluster_dendrogram_era_validated.png`
rather than overwriting the n=13 unsupervised baseline:

```bash
python -c "import pandas as pd; df = pd.read_csv('features.csv'); df[df.garment_id != 'testdress0'].to_csv('/tmp/features_era_subset.csv', index=False)"
python clustering_analysis.py --features /tmp/features_era_subset.csv \
    --metadata catalog_metadata.csv --metadata-column era \
    --out-clusters cluster_assignments_era_validated.csv \
    --out-dendrogram cluster_dendrogram_era_validated.png
```

Result: ARI near zero (-0.07 to 0.03) and low NMI (0.08-0.33) across k=2..6 —
no real correspondence between the shape-based clusters and era. Read this as
the ARI/NMI mechanics now proven correct on real labels, not as evidence the
geometry fails to predict era: at n=12 the era split is heavily imbalanced
(9 pre-1920 / 1 1920-1950 / 2 1950-1980), which caps how much any clustering
could score regardless of real-world correlation. Revisit once Phase 4's
15-20 garments are reached and the era distribution is less skewed; `era` is
also a coarse proxy for `silhouette`/`torso` and likely has a weaker geometry
relationship than those finer curator fields would.

**Silhouette validation (2026-10-25):** `catalog_metadata.csv` also has a
`silhouette` column, a 4-bucket taxonomy (`full-skirted` / `moderately-flared`
/ `straight-fitted` / `structural`) hand-derived from the same 12 curatorial
descriptions and confirmed with Matthew before encoding (silhouette grouping
is a curatorial judgment call, not something to infer silently). Run the
same way as the `era` validation above, substituting
`--metadata-column silhouette` and
`cluster_assignments_silhouette_validated.csv` /
`cluster_dendrogram_silhouette_validated.png`. Result: ARI still near zero
(-0.07 to 0.02), NMI modestly higher than `era`'s (0.18-0.44 vs. 0.08-0.33)
but still weak.

**Why ARI stays near zero for both labels — a real, diagnosed cause, not
just small-n noise:** `pca_sanity_check.py`'s component loadings show PC1
(66.6% of variance) loads almost uniformly (~0.36-0.40) across `bbox_x`,
`bbox_y`, `bbox_z`, `surface_area`, `std_curvature`, and `volume` — a single
"how big is this garment" factor. The features that should actually carry
silhouette information, `drape_extent` (0.717) and `symmetry_score` (0.420),
only dominate PC2, which explains just 16.1% of variance. Since clustering
runs on z-scored Euclidean distance across all features equally, overall
scale currently swamps shape by roughly 4:1. Likely fix, not yet tried:
replace the absolute `bbox_x/y/z`/`surface_area`/`volume` columns with
size-normalized ratios (e.g. `bbox_x / bbox_y`, `bbox_z / bbox_y`,
`surface_area / bbox_y**2`) so garment height stops dominating the distance
metric, and genuine proportion/shape differences can actually separate
clusters.

**Size normalization implemented and tested (2026-10-25):** both
`pca_sanity_check.py` and `clustering_analysis.py` now z-score
`bbox_aspect_xy`/`bbox_aspect_zy`/`surface_area_norm`/`volume_norm`
(garment-height-normalized ratios computed from the raw `features.csv`
columns, see `add_normalized_size_features` in either script) instead of
the raw `bbox_x/y/z`/`surface_area`/`volume`. The PCA diagnosis confirms
the fix did what it was supposed to: PC1 dropped from 66.6% to 44.2% of
variance, and drape_extent/symmetry_score's loadings strengthened
considerably in PC2 (now -0.460/-0.415, with PC2's share of variance up
from 16.1% to 30.4%) — absolute size no longer swamps shape the way it did.

**But re-running the era and silhouette ARI/NMI validation with the
normalized features did not meaningfully improve label recovery.** ARI is
still ~0 for both (era: -0.07 to 0.03; silhouette: -0.18 to 0.01). NMI
improved somewhat for era (0.20-0.37, vs. 0.08-0.33 before) but was mixed
for silhouette (0.18-0.43, a wider spread, not a clean gain). Read this as
a real, honest negative result, not a failed experiment: the normalization
was a correct fix for a real, diagnosed problem (confirmed via the PCA
loadings), and it's worth keeping regardless, but it wasn't the whole
story — at n=12, with 3-4 imbalanced ground-truth classes, ARI/NMI may
simply need more garments before any real relationship between shape and
curator-assigned categories (if one exists) becomes detectable above noise.
This doesn't rule out that the remaining features (mean_curvature,
std_curvature, symmetry_score, drape_extent) just don't capture silhouette
as directly as hoped, either — that's a separate open question from the
scale-confound one, which is now resolved.
