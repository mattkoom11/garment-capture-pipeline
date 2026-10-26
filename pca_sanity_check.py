"""
pca_sanity_check.py -- quick PCA smoke test on features.csv.

This is deliberately NOT the real Pilot Plan phase-3 analysis (that needs
the full 5-garment set per garment-capture's Pilot Plan). With only 3 rows,
PCA has at most 2 meaningful components (rank is capped at n_samples - 1)
and any "clustering" would be meaningless -- 3 points trivially separate
into as many groups as you ask for. The point of this script is to catch
pipeline/schema bugs in features.csv early (does PCA run cleanly, do the
z-scored features look sane), not to draw a real conclusion about these
three garments.

Seven columns are used: bbox_aspect_xy, bbox_aspect_zy, surface_area_norm,
mean_curvature, std_curvature, symmetry_score, and drape_extent.
`volume_norm` is added as an eighth column only when `volume` has no NaNs
(it was all-NaN for every row while features came from AutoRemesher's
non-manifold retopology; meshes decimated from the dense scan are
watertight so it is defined). If any row is NaN it is dropped rather than
imputed -- imputing a placeholder value would silently fabricate signal in
a PCA.

Size normalization (2026-10-25): bbox_x/y/z, surface_area, and volume are
raw columns in features.csv, but z-scoring them directly for PCA/clustering
makes "how big is this garment" the dominant signal -- confirmed on the
real 12-garment set, where PC1 (66.6% of variance) loaded almost uniformly
(~0.36-0.40) across those five columns, while drape_extent/symmetry_score
(the features that should actually carry silhouette) only showed up in PC2
at 16.1%. `add_normalized_size_features` below replaces them with
garment-height-normalized ratios (bbox_aspect_xy = bbox_x/bbox_y,
bbox_aspect_zy = bbox_z/bbox_y, surface_area_norm = surface_area/bbox_y**2,
volume_norm = volume/bbox_y**3) so a tall garment and a short garment with
the same proportions land at the same point in feature space. See the
README's "Silhouette validation" section for the full writeup.
num_vertices/num_faces are also excluded, for a different reason as of
2026-09-08: now that every mesh is decimated to ~15,000 vertices before
extraction (decimate_mesh.py), these columns are nearly constant across
garments by construction and carry no shape signal -- not "density-
confounded" anymore, just uninformative.

Usage:
    python pca_sanity_check.py --features features.csv --out pca_sanity_check.png
"""
import argparse

import numpy as np
import pandas as pd
from sklearn.decomposition import PCA
from sklearn.preprocessing import StandardScaler

FEATURE_COLUMNS = [
    "bbox_aspect_xy", "bbox_aspect_zy",
    "surface_area_norm", "mean_curvature", "std_curvature",
    "symmetry_score", "drape_extent",
]
RAW_SIZE_COLUMNS = ["bbox_x", "bbox_y", "bbox_z", "surface_area", "volume"]


def add_normalized_size_features(df):
    """Replace absolute-scale columns with garment-height-normalized ratios --
    see module docstring's "Size normalization" note for why."""
    df = df.copy()
    df["bbox_aspect_xy"] = df["bbox_x"] / df["bbox_y"]
    df["bbox_aspect_zy"] = df["bbox_z"] / df["bbox_y"]
    df["surface_area_norm"] = df["surface_area"] / df["bbox_y"] ** 2
    if "volume" in df.columns:
        df["volume_norm"] = df["volume"] / df["bbox_y"] ** 3
    return df


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--features", default="features.csv", help="Path to features.csv")
    parser.add_argument("--out", default="pca_sanity_check.png", help="Path to save the scatter plot")
    args = parser.parse_args()

    df = pd.read_csv(args.features)
    print(f"loaded {len(df)} rows from {args.features}")
    df = add_normalized_size_features(df)

    feature_columns = list(FEATURE_COLUMNS)
    if "volume_norm" in df.columns and not df["volume_norm"].isna().any():
        feature_columns.append("volume_norm")

    dropped = [c for c in df.columns if c not in feature_columns and c not in ("garment_id", "label", "capture_method", *RAW_SIZE_COLUMNS)]
    if dropped:
        print(f"  dropping (NaN or uninformative, not used): {dropped}")

    if "capture_method" in df.columns:
        counts = df["capture_method"].value_counts().to_dict()
        print(f"  capture method breakdown: {counts}")
        if len(counts) > 1:
            print("  NOTE: mixed capture methods present -- a hybrid photogrammetry+LiDAR scan may read "
                  "systematically smoother (lower curvature) than pure photogrammetry due to LiDAR's coarser "
                  "native resolution. If PC1/PC2 scores split cleanly along capture_method, treat that as a "
                  "capture-method artifact, not a real shape finding, until checked.")

    X = df[feature_columns].to_numpy()
    if np.isnan(X).any():
        raise ValueError(f"unexpected NaN in {feature_columns} -- these should all be well-defined columns")

    X_scaled = StandardScaler().fit_transform(X)

    n_components = min(2, len(df) - 1)
    pca = PCA(n_components=n_components)
    scores = pca.fit_transform(X_scaled)

    print(f"\nexplained variance ratio (PC1..PC{n_components}): {pca.explained_variance_ratio_}")
    print(f"cumulative: {np.cumsum(pca.explained_variance_ratio_)}")
    print(f"\nNOTE: n={len(df)} garments -- PCA rank-capped at {len(df) - 1} components.")
    print("This is a pipeline smoke test, not a statistically meaningful result.")

    print("\ncomponent loadings (how much each feature contributes to each PC):")
    loadings = pd.DataFrame(pca.components_.T, index=feature_columns,
                             columns=[f"PC{i+1}" for i in range(n_components)])
    print(loadings.round(3).to_string())

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(6, 5))
    if n_components >= 2:
        ax.scatter(scores[:, 0], scores[:, 1])
        for i, gid in enumerate(df["garment_id"]):
            ax.annotate(gid, (scores[i, 0], scores[i, 1]), xytext=(5, 5), textcoords="offset points")
        ax.set_xlabel(f"PC1 ({pca.explained_variance_ratio_[0]:.0%} var)")
        ax.set_ylabel(f"PC2 ({pca.explained_variance_ratio_[1]:.0%} var)")
    else:
        ax.scatter(scores[:, 0], np.zeros(len(scores)))
        for i, gid in enumerate(df["garment_id"]):
            ax.annotate(gid, (scores[i, 0], 0), xytext=(5, 5), textcoords="offset points")
        ax.set_xlabel(f"PC1 ({pca.explained_variance_ratio_[0]:.0%} var)")
    ax.set_title(f"PCA sanity check (n={len(df)} -- pipeline smoke test, not a real result)")
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(args.out, dpi=150)
    print(f"\nsaved plot to {args.out}")


if __name__ == "__main__":
    main()
