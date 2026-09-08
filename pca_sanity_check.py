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

Eight columns are used: bbox_x/y/z, surface_area, mean_curvature,
std_curvature, symmetry_score, and drape_extent (the latter two implemented
2026-09-08 -- see extract_features.py's docstring for their definitions).
`volume` is still all-NaN for every row (AutoRemesher's non-manifold quad
poles, deliberately deferred) and is dropped rather than imputed --
imputing a placeholder value would silently fabricate signal in a PCA.
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
    "bbox_x", "bbox_y", "bbox_z",
    "surface_area", "mean_curvature", "std_curvature",
    "symmetry_score", "drape_extent",
]


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--features", default="features.csv", help="Path to features.csv")
    parser.add_argument("--out", default="pca_sanity_check.png", help="Path to save the scatter plot")
    args = parser.parse_args()

    df = pd.read_csv(args.features)
    print(f"loaded {len(df)} rows from {args.features}")

    dropped = [c for c in df.columns if c not in FEATURE_COLUMNS and c not in ("garment_id", "label")]
    if dropped:
        print(f"  dropping (NaN or density-confounded, not yet usable): {dropped}")

    X = df[FEATURE_COLUMNS].to_numpy()
    if np.isnan(X).any():
        raise ValueError(f"unexpected NaN in {FEATURE_COLUMNS} -- these should all be well-defined columns")

    X_scaled = StandardScaler().fit_transform(X)

    n_components = min(2, len(df) - 1)
    pca = PCA(n_components=n_components)
    scores = pca.fit_transform(X_scaled)

    print(f"\nexplained variance ratio (PC1..PC{n_components}): {pca.explained_variance_ratio_}")
    print(f"cumulative: {np.cumsum(pca.explained_variance_ratio_)}")
    print(f"\nNOTE: n={len(df)} garments -- PCA rank-capped at {len(df) - 1} components.")
    print("This is a pipeline smoke test, not a statistically meaningful result.")
    print("Revisit once the 5-garment Pilot Plan phase-2 target is reached.")

    print("\ncomponent loadings (how much each feature contributes to each PC):")
    loadings = pd.DataFrame(pca.components_.T, index=FEATURE_COLUMNS,
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
