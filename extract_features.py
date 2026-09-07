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

Two columns are intentionally left as NaN placeholders: symmetry_score and
drape_extent. These aren't off-the-shelf trimesh calls -- they're
project-specific metrics that need an actual methodology decision (e.g.
"symmetry" could mean deviation from a reflected copy across the centroid
plane; "drape" could mean variance in the lower portion's radial extent).
Don't guess at these silently; decide the definition first, then implement.

Known limitation, not yet addressed: garments in this pipeline aren't
currently decimated to an identical target vertex count before extraction,
so density-sensitive features (surface_area, curvature) aren't perfectly
apples-to-apples across garments yet. Fine for proving the extraction code
works; worth fixing (per the project's own documented preprocessing step)
before treating cross-garment comparisons as rigorous.

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

COLUMNS = [
    "garment_id", "label", "num_vertices", "num_faces",
    "bbox_x", "bbox_y", "bbox_z",
    "surface_area", "volume", "is_watertight",
    "mean_curvature", "std_curvature",
    "symmetry_score", "drape_extent",
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


def compute_features(mesh, garment_id, label):
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
        "symmetry_score": float("nan"),  # not yet defined -- see module docstring
        "drape_extent": float("nan"),    # not yet defined -- see module docstring
    }


def upsert_row(csv_path, row):
    rows = []
    if os.path.exists(csv_path):
        with open(csv_path, "r", newline="") as f:
            rows = list(csv.DictReader(f))
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
    args = parser.parse_args()

    print(f"loading {args.mesh}...")
    mesh = load_mesh(args.mesh)
    print(f"  {len(mesh.vertices)} verts, {len(mesh.faces)} faces, watertight={mesh.is_watertight}")

    row = compute_features(mesh, args.garment_id, args.label)
    upsert_row(args.out, row)
    print(f"wrote row for '{args.garment_id}' to {args.out}")


if __name__ == "__main__":
    main()
