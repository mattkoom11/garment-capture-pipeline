"""
Compare features.csv (retopologized mesh, ~15k verts) against the same
garments' features extracted from the dense RealityScan scan decimated to
~15k verts (features_dense15k.csv) and to 100k faces (features_dense100k.csv).

Inputs were built by: decimate_dense_textured.py (5M -> 100k faces; testdress0
from its *welded* scan because the raw one is fragmented into ~1.5k pieces),
trimesh merge-by-position (drops UV seam splits), decimate_mesh.py
(--target-vertices 15000), then extract_features.py.

Run from the repo root: python experiments/dense_vs_retopo/compare_feature_sources.py
"""
import pandas as pd
from scipy.stats import pearsonr, spearmanr
from sklearn.decomposition import PCA
from sklearn.preprocessing import StandardScaler

D = "experiments/dense_vs_retopo/"
base = pd.read_csv("features.csv").set_index("garment_id").sort_index()
d15 = pd.read_csv(D + "features_dense15k.csv").set_index("garment_id").sort_index()
d100 = pd.read_csv(D + "features_dense100k.csv").set_index("garment_id").sort_index()
feats = ["bbox_x", "bbox_y", "bbox_z", "surface_area", "mean_curvature", "std_curvature", "symmetry_score", "drape_extent"]
pd.set_option("display.width", 200)

print("ratio dense15k / retopo15k:\n", (d15[feats] / base[feats]).round(3))
print("\nper-feature agreement retopo vs dense15k:")
for f in feats:
    print(f"  {f:15s} pearson {pearsonr(base[f], d15[f])[0]:.3f}  spearman {spearmanr(base[f], d15[f])[0]:.3f}")
print("\ndensity sensitivity dense100k / dense15k:\n", (d100[feats[3:6]] / d15[feats[3:6]]).round(3))
for name, df in (("retopo15k", base), ("dense15k", d15)):
    p = PCA().fit(StandardScaler().fit_transform(df[feats]))
    print(f"\n{name} PCA explained variance:", p.explained_variance_ratio_[:3].round(3))
print("\nvolume (dense15k):", d15["volume"].round(0).to_dict())
