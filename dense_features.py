"""
dense_features.py -- build one features.csv row straight from a dense
RealityScan scan, skipping AutoRemesher retopology.

Why: features from the retopologized mesh inherit its smoothing (surface_area
~10% low, curvature magnitudes off by 0.6-1.7x, and volume undefined because
of non-manifold quad poles). Decimating the dense scan instead keeps the real
geometry and gives watertight meshes, so volume is defined. See
experiments/dense_vs_retopo/ for the comparison.

Pipeline: decimate_dense_textured.py (5M -> 100k faces) -> merge vertices by
position (drops UV-seam splits so curvature sees a connected surface) ->
connectivity check -> decimate_mesh.py to --target-vertices -> extract_features.

Density is held fixed on purpose: curvature drifts systematically with mesh
density (in a different direction per garment), but within 13k-17k vertices
it varies only ~4% per garment vs a between-garment spread ~20x larger.

The connectivity check fails on a fragmented scan (RealityScan's fold-collapse
defect: coincident duplicate vertices leave the mesh in many pieces). Run
weld_source.py on the raw scan first and pass the welded OBJ. Use
--allow-open to override.

Usage:
    python dense_features.py --obj TestDress4.obj --garment-id testdress4 \\
        --label "Test Dress 4" --out features.csv
"""
import argparse
import os
import subprocess
import sys
import tempfile

import numpy as np
import trimesh
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components

import extract_features as ef

HERE = os.path.dirname(os.path.abspath(__file__))


def run_blender(script, *args):
    subprocess.run(["blender", "--background", "--python", os.path.join(HERE, script), "--", *args],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)


def connectivity(mesh):
    f, n = mesh.faces, len(mesh.vertices)
    a = np.concatenate([f[:, 0], f[:, 1], f[:, 2]])
    b = np.concatenate([f[:, 1], f[:, 2], f[:, 0]])
    _, labels = connected_components(coo_matrix((np.ones(len(a)), (a, b)), shape=(n, n)), directed=False)
    sizes = np.bincount(labels[f[:, 0]])
    edges = np.sort(mesh.edges, axis=1)
    _, counts = np.unique(edges, axis=0, return_counts=True)
    return int((sizes > 0).sum()), int((counts == 1).sum())


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--obj", required=True, help="Dense RealityScan OBJ (welded if the raw scan is fragmented)")
    p.add_argument("--garment-id", required=True)
    p.add_argument("--label", default="")
    p.add_argument("--out", required=True, help="features.csv (row upserted)")
    p.add_argument("--target-vertices", type=int, default=15000)
    p.add_argument("--faces", type=int, default=100000, help="Intermediate dense decimation target (faces)")
    p.add_argument("--allow-open", action="store_true", help="Continue even if the mesh is fragmented or has boundary edges")
    p.add_argument("--capture-method", default="photogrammetry", choices=["photogrammetry", "hybrid"],
                   help="'hybrid' if a supplementary LiDAR scan was merged into this OBJ via RealityScan "
                        "(see the project vault's hybrid-lidar-capture page) -- flows into features.csv so "
                        "PCA/clustering can be checked for a capture-method confound later.")
    a = p.parse_args()

    with tempfile.TemporaryDirectory() as tmp:
        dense, merged, final = (os.path.join(tmp, n) for n in ("dense.obj", "merged.obj", "final.obj"))
        run_blender("decimate_dense_textured.py", a.obj, dense, str(a.faces))
        raw = trimesh.load(dense, process=False, force="mesh")
        m = trimesh.Trimesh(vertices=raw.vertices, faces=raw.faces, process=True)
        components, boundary = connectivity(m)
        print(f"  {a.garment_id}: {len(m.vertices)} verts, {len(m.faces)} faces, "
              f"{components} component(s), {boundary} boundary edge(s), watertight={m.is_watertight}")
        if (components > 1 or boundary > 0) and not a.allow_open:
            sys.exit(f"ERROR: '{a.obj}' decimates to a fragmented/open mesh ({components} components, {boundary} boundary "
                     "edges) -- curvature would be unreliable. Run weld_source.py on the raw scan and pass the welded OBJ, "
                     "or use --allow-open to override.")
        m.export(merged)
        run_blender("decimate_mesh.py", "--input-obj", merged, "--output-obj", final, "--target-vertices", str(a.target_vertices))
        row = ef.compute_features(ef.load_mesh(final), a.garment_id, a.label, a.capture_method)
        ef.upsert_row(a.out, row)
    print(f"wrote row for '{a.garment_id}' to {a.out}")


if __name__ == "__main__":
    main()
