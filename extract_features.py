"""
extract_features.py -- compute geometric features from a clean garment mesh
for the stats/ML pipeline's features.csv.

Per the project's Phase 1 MVP decision: a flat CSV joining garment ID to
geometric features, not a database -- this script is the tool that produces
one row of that CSV per garment.

Four features are well-defined and computed here:
  - bounding box extents (bbox_x, bbox_y, bbox_z)
  - surface area
  - volume (REQUIRES a watertight mesh -- this is the concrete payoff of
    weld_source.py: a mesh with real holes gives an undefined/garbage
    volume, not just a "gap you can see". If a mesh isn't watertight this
    column is written as NaN with a warning, not a silently wrong number.)
  - mean/std discrete mean curvature, sampled at vertices with a radius
    scaled to the mesh's own size (a fixed absolute radius would compare
    unfairly across garments of different physical scale)

Two more columns, symmetry_score and drape_extent, are now implemented
(methodology decided 2026-09-08 -- previously NaN placeholders since they
aren't off-the-shelf trimesh calls):

  - symmetry_score: deviation from a mirrored copy of the mesh reflected
    across its own centroid plane. The mesh's left-right axis isn't known
    a priori (per-scan rotation around the vertical axis isn't
    calibrated -- see normalize_up_axis for the related up-axis issue), so
    this tries both horizontal axes as the candidate mirror plane and
    reports the lower (more-symmetric) of the two: a garment is expected
    to be bilaterally symmetric across exactly one horizontal plane and
    NOT symmetric front-to-back, so the minimum finds the true left-right
    plane without needing to know which axis it is. Reported as a
    scale-invariant symmetric Chamfer distance to the mirrored copy,
    divided by the mesh's own bounding diagonal -- 0 is perfectly
    symmetric, larger is more asymmetric (despite the "_score" name, this
    is an asymmetry distance, not a 0-1 goodness score).
  - drape_extent: coefficient of variation (std/mean) of radial distance
    from the mesh's own central vertical axis, computed only over the
    lower 25% of the mesh's height (the hem/skirt region -- not the whole
    garment, since bodice/shoulder geometry isn't what "drape" means
    here). std/mean rather than raw variance, so it's comparable across
    garments of different physical size -- the same normalization
    rationale as mean_curvature's bounding-diagonal-scaled radius above.

Density normalization (2026-09-08): garments should be decimated to a
consistent target vertex count before extraction, so density-sensitive
features (surface_area, curvature) are apples-to-apples across garments --
now available as decimate_mesh.py (a separate Blender-headless script;
this script doesn't invoke it automatically, so it's still possible to
accidentally run extraction against a non-decimated mesh). All 3 current
`features.csv` rows were re-extracted from decimate_mesh.py's output
(~15,000 vertices each) as of this date.

Known, deliberately deferred (2026-09-08, not a bug): `volume` is NaN for
every garment run through this so far. AutoRemesher's own quad retopology
consistently leaves a small number of non-manifold edges at quad poles
(43-78 edges, seen on every garment tested) -- these are not holes (0
boundary edges every time) but trimesh's `is_watertight` requires zero
non-manifold edges too, so `volume` is left undefined rather than computed
from a technically-invalid state. A repair pass is possible but is real,
uncertain-effort mesh surgery (no existing script here handles this
specific defect class), not a quick fix -- deliberately deprioritized
while it's blocking only one column on a handful of test-scale rows.
Revisit if/when volume actually matters for a real analysis.

Usage:
    python extract_features.py --mesh testdress0.glb --garment-id testdress0 \\
        --label "Test Dress 0" --out features.csv

Re-running with the same --garment-id replaces that row rather than
duplicating it.
"""
import argparse
import csv
import os

import numpy as np
import trimesh
from scipy.spatial import cKDTree

COLUMNS = [
    "garment_id", "label", "num_vertices", "num_faces",
    "bbox_x", "bbox_y", "bbox_z",
    "surface_area", "volume", "is_watertight",
    "mean_curvature", "std_curvature",
    "symmetry_score", "drape_extent",
    "capture_method",
]


def load_mesh(path):
    loaded = trimesh.load(path)
    if hasattr(loaded, "to_geometry"):
        # a Scene (GLB) -- must apply node transforms, not read raw
        # per-geometry vertices (see garment-capture-pipeline history: this
        # exact mistake produced badly broken geometry once already)
        return loaded.to_geometry()
    return loaded


def normalize_up_axis(mesh, garment_id):
    """Different capture sessions in this project have exported in different
    up-axis conventions (Y-up vs Z-up -- confirmed happening in practice, not
    hypothetical). bbox_x/y/z must mean the same physical direction across
    every garment for cross-garment comparison to be valid, so auto-detect
    and correct Z-up meshes to Y-up here. Heuristic: assume the tallest
    standing-garment dimension is up; true for every garment seen so far,
    but would need revisiting for a scan where width could plausibly exceed
    height (e.g. a cape laid flat)."""
    extents = mesh.extents
    if extents[2] > extents[1]:
        print(f"  '{garment_id}': Z-span ({extents[2]:.2f}) > Y-span ({extents[1]:.2f}) -- treating as Z-up, rotating to Y-up for consistent bbox axes")
        R = np.array([[1, 0, 0], [0, 0, 1], [0, -1, 0]])
        mesh.vertices = (R @ mesh.vertices.T).T
    return mesh


def compute_symmetry_score(mesh):
    """Symmetric Chamfer distance to the mesh's own best-fit mirror image,
    normalized by bounding diagonal (0 = perfectly symmetric). Tries both
    horizontal axes as the mirror plane (mesh assumed Y-up already) and
    keeps the lower distance -- see module docstring for why."""
    verts = mesh.vertices
    centered = verts - verts.mean(axis=0)
    diag = float(np.linalg.norm(mesh.extents))

    best = None
    for axis in (0, 2):  # X and Z -- axis 1 (Y) is up, not a mirror candidate
        mirrored = centered.copy()
        mirrored[:, axis] *= -1
        d_to_mirrored, _ = cKDTree(mirrored).query(centered)
        d_to_centered, _ = cKDTree(centered).query(mirrored)
        chamfer = float((np.mean(d_to_mirrored) + np.mean(d_to_centered)) / 2.0)
        asymmetry = chamfer / diag
        if best is None or asymmetry < best:
            best = asymmetry
    return best


def compute_drape_extent(mesh, lower_fraction=0.25):
    """Coefficient of variation (std/mean) of radial distance from the
    mesh's central vertical axis, over the lower `lower_fraction` of the
    mesh's height only (the hem/skirt region) -- see module docstring."""
    verts = mesh.vertices
    y = verts[:, 1]
    threshold = y.min() + lower_fraction * mesh.extents[1]
    lower_verts = verts[y <= threshold]
    if len(lower_verts) < 10:
        print(f"  WARNING: only {len(lower_verts)} vertices in the lower {lower_fraction:.0%} of the mesh -- drape_extent may be noisy")

    centroid_xz = lower_verts[:, [0, 2]].mean(axis=0)
    radial = np.linalg.norm(lower_verts[:, [0, 2]] - centroid_xz, axis=1)
    mean_r = radial.mean()
    if mean_r == 0:
        return float("nan")
    return float(radial.std() / mean_r)


def compute_features(mesh, garment_id, label, capture_method="photogrammetry"):
    mesh = normalize_up_axis(mesh, garment_id)
    bbox = mesh.extents  # [x, y, z] extents, now Y-up-consistent
    watertight = bool(mesh.is_watertight)

    if watertight:
        volume = float(mesh.volume)
    else:
        volume = float("nan")
        print(f"  WARNING: '{garment_id}' is not watertight -- volume is undefined, writing NaN")

    scale = float(np.linalg.norm(bbox))
    radius = scale * 0.02  # 2% of the mesh's own bounding-diagonal, so this scales with garment size
    try:
        curv = trimesh.curvature.discrete_mean_curvature_measure(mesh, mesh.vertices, radius)
        mean_curv = float(np.mean(curv))
        std_curv = float(np.std(curv))
    except Exception as e:
        print(f"  WARNING: curvature computation failed for '{garment_id}': {e}")
        mean_curv = float("nan")
        std_curv = float("nan")

    return {
        "garment_id": garment_id,
        "label": label,
        "num_vertices": len(mesh.vertices),
        "num_faces": len(mesh.faces),
        "bbox_x": bbox[0], "bbox_y": bbox[1], "bbox_z": bbox[2],
        "surface_area": float(mesh.area),
        "volume": volume,
        "is_watertight": watertight,
        "mean_curvature": mean_curv,
        "std_curvature": std_curv,
        "symmetry_score": compute_symmetry_score(mesh),
        "drape_extent": compute_drape_extent(mesh),
        "capture_method": capture_method,
    }


def upsert_row(csv_path, row):
    rows = []
    if os.path.exists(csv_path):
        with open(csv_path, "r", newline="") as f:
            rows = list(csv.DictReader(f))
    for r in rows:
        # backfill rows written before capture_method existed -- every garment
        # captured before 2026-10-01 was pure photogrammetry, not a guess
        r.setdefault("capture_method", "photogrammetry")
    rows = [r for r in rows if r["garment_id"] != row["garment_id"]]
    rows.append({k: row[k] for k in COLUMNS})
    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--mesh", required=True, help="Path to the clean garment mesh (GLB or OBJ)")
    parser.add_argument("--garment-id", required=True, help="Unique garment identifier (used as the CSV row key)")
    parser.add_argument("--label", default="", help="Human-readable label for this garment")
    parser.add_argument("--out", required=True, help="Path to features.csv (created if missing, row updated if garment-id already present)")
    parser.add_argument("--capture-method", default="photogrammetry", choices=["photogrammetry", "hybrid"],
                        help="'hybrid' if a supplementary LiDAR scan was merged into this mesh via RealityScan "
                             "(see the project vault's hybrid-lidar-capture page) -- flows into features.csv so "
                             "PCA/clustering can be checked for a capture-method confound later.")
    args = parser.parse_args()

    print(f"loading {args.mesh}...")
    mesh = load_mesh(args.mesh)
    print(f"  {len(mesh.vertices)} verts, {len(mesh.faces)} faces, watertight={mesh.is_watertight}")

    row = compute_features(mesh, args.garment_id, args.label, args.capture_method)
    upsert_row(args.out, row)
    print(f"wrote row for '{args.garment_id}' to {args.out}")


if __name__ == "__main__":
    main()
