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
Blender preprocessing (crop/align/decimate)
   ↓
trimesh feature extraction
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
  --out-texture baked_diffuse.png

python assemble_textured_glb.py \
  --mesh-obj retopologized_uv.obj \
  --texture-png baked_diffuse.png \
  --out-glb final.glb
```

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
