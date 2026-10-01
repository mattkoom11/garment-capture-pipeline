"""
clustering_analysis.py -- Pilot Plan phase 5: k-means/hierarchical clustering
on features.csv, with optional ARI/NMI validation against real catalog
metadata once it exists.

Real catalog ground truth (curator-assigned `silhouette`/`torso`/`condition`
from CollectiveAccess) isn't collected yet as of 2026-09-28 -- see
garment-capture's Near-Term To-Do in the project vault. This script is
useful without it: it runs k-means and hierarchical (Ward) clustering across
a small range of k, reports internal validation (silhouette score, no
ground truth needed) and saves a dendrogram, so the mechanics are built and
tested now (at n=6) rather than written under time pressure once the 15-20
garment target is reached. The ARI/NMI path activates automatically the
moment a --metadata CSV is supplied.

Same feature set and NaN-handling as pca_sanity_check.py (kept in sync
deliberately -- both scripts should agree on what "the features" are):
bbox_x/y/z, surface_area, mean_curvature, std_curvature, symmetry_score,
drape_extent, plus volume when it has no NaNs.

Usage (unsupervised only, today):
    python clustering_analysis.py --features features.csv

Usage (once catalog metadata exists -- CSV needs a `garment_id` column
matching features.csv's garment_id, plus your label column):
    python clustering_analysis.py --features features.csv \\
        --metadata catalog_metadata.csv --metadata-column silhouette
"""
import argparse
import sys

import numpy as np
import pandas as pd
from scipy.cluster.hierarchy import dendrogram, linkage
from sklearn.cluster import AgglomerativeClustering, KMeans
from sklearn.metrics import (
    adjusted_rand_score,
    normalized_mutual_info_score,
    silhouette_score,
)
from sklearn.preprocessing import StandardScaler

FEATURE_COLUMNS = [
    "bbox_x", "bbox_y", "bbox_z",
    "surface_area", "mean_curvature", "std_curvature",
    "symmetry_score", "drape_extent",
]


def load_features(path):
    df = pd.read_csv(path)
    feature_columns = list(FEATURE_COLUMNS)
    if "volume" in df.columns and not df["volume"].isna().any():
        feature_columns.append("volume")

    X = df[feature_columns].to_numpy()
    if np.isnan(X).any():
        raise ValueError(f"unexpected NaN in {feature_columns} -- these should all be well-defined columns")

    return df, feature_columns, StandardScaler().fit_transform(X)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--features", default="features.csv", help="Path to features.csv")
    parser.add_argument("--metadata", default=None,
                        help="Optional CSV with a garment_id column plus a ground-truth label column, "
                             "for ARI/NMI validation. Skipped entirely if not supplied.")
    parser.add_argument("--metadata-column", default=None,
                        help="Column in --metadata to validate against (required if --metadata is given)")
    parser.add_argument("--k-min", type=int, default=2)
    parser.add_argument("--k-max", type=int, default=None, help="Default: min(6, n_garments - 1)")
    parser.add_argument("--out-clusters", default="cluster_assignments.csv")
    parser.add_argument("--out-dendrogram", default="cluster_dendrogram.png")
    args = parser.parse_args()

    df, feature_columns, X_scaled = load_features(args.features)
    n = len(df)
    print(f"loaded {n} rows from {args.features}, {len(feature_columns)} features: {feature_columns}")

    if "capture_method" in df.columns:
        counts = df["capture_method"].value_counts().to_dict()
        print(f"  capture method breakdown: {counts}")
        if len(counts) > 1:
            print("  NOTE: mixed capture methods present -- check whether cluster assignments split along "
                  "capture_method before trusting them as a real shape grouping (hybrid LiDAR-merged garments "
                  "may read systematically smoother than pure photogrammetry ones).")

    if n < 4:
        sys.exit(f"ERROR: only {n} garments -- clustering needs at least 4 for even k=2 vs. k=3 to be "
                  "distinguishable. Come back once more garments are scanned.")

    k_max = args.k_max if args.k_max is not None else min(6, n - 1)
    if k_max > n - 1:
        sys.exit(f"ERROR: --k-max {k_max} exceeds n_garments - 1 ({n - 1}); a cluster needs at least one member.")
    if args.k_min < 2 or args.k_min > k_max:
        sys.exit(f"ERROR: --k-min must be >= 2 and <= --k-max ({k_max}), got {args.k_min}")

    print(f"\n=== Unsupervised model selection (k={args.k_min}..{k_max}), internal validation only -- "
          "no ground truth used ===")
    results = []
    for k in range(args.k_min, k_max + 1):
        km = KMeans(n_clusters=k, n_init=10, random_state=0).fit(X_scaled)
        agg = AgglomerativeClustering(n_clusters=k, linkage="ward").fit(X_scaled)
        km_sil = silhouette_score(X_scaled, km.labels_)
        agg_sil = silhouette_score(X_scaled, agg.labels_)
        results.append({"k": k, "kmeans_labels": km.labels_, "agglomerative_labels": agg.labels_,
                         "kmeans_silhouette": km_sil, "agglomerative_silhouette": agg_sil})
        print(f"  k={k}: KMeans silhouette={km_sil:.3f} | Agglomerative(ward) silhouette={agg_sil:.3f}")

    best = max(results, key=lambda r: r["kmeans_silhouette"])
    print(f"\nhighest KMeans silhouette: k={best['k']} ({best['kmeans_silhouette']:.3f})")
    print(f"NOTE: at n={n}, picking 'best k' by silhouette alone is not a validated model-selection "
          "procedure -- treat this as a starting point for eyeballing the dendrogram, not a result. "
          "Real validation needs the ARI/NMI path below once catalog metadata exists.")

    out_df = df[["garment_id", "label"]].copy()
    for r in results:
        out_df[f"kmeans_k{r['k']}"] = r["kmeans_labels"]
        out_df[f"agglomerative_k{r['k']}"] = r["agglomerative_labels"]
    out_df.to_csv(args.out_clusters, index=False)
    print(f"\nwrote cluster assignments (every k tried) to {args.out_clusters}")

    Z = linkage(X_scaled, method="ward")
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(8, 5))
    dendrogram(Z, labels=df["garment_id"].tolist(), ax=ax)
    ax.set_title(f"Hierarchical clustering dendrogram (n={n} -- pipeline smoke test, not a validated result)")
    ax.set_ylabel("Ward distance")
    fig.tight_layout()
    fig.savefig(args.out_dendrogram, dpi=150)
    print(f"saved dendrogram to {args.out_dendrogram}")

    if not args.metadata:
        print("\nNo --metadata supplied -- skipping ARI/NMI validation against real catalog ground truth.")
        print("This is expected right now: catalog metadata collection is still in progress.")
        print("Once a garment_id -> label CSV exists (e.g. curator-assigned `silhouette` from "
              "CollectiveAccess), run:")
        print(f"    python {sys.argv[0]} --features {args.features} "
              "--metadata catalog_metadata.csv --metadata-column silhouette")
        return

    if not args.metadata_column:
        sys.exit("ERROR: --metadata given without --metadata-column")

    meta = pd.read_csv(args.metadata)
    if "garment_id" not in meta.columns:
        sys.exit(f"ERROR: {args.metadata} needs a 'garment_id' column matching features.csv's garment_id")
    if args.metadata_column not in meta.columns:
        sys.exit(f"ERROR: {args.metadata} has no column '{args.metadata_column}'")

    merged = df[["garment_id"]].merge(meta[["garment_id", args.metadata_column]], on="garment_id", how="left")
    missing = merged.loc[merged[args.metadata_column].isna(), "garment_id"].tolist()
    if missing:
        sys.exit(f"ERROR: no '{args.metadata_column}' value for: {missing} -- fill these in before "
                  "running validation (a partial ground-truth set would silently bias ARI/NMI)")

    y_true = merged[args.metadata_column].to_numpy()
    n_true_classes = len(set(y_true))
    print(f"\n=== ARI/NMI validation against real catalog metadata ('{args.metadata_column}', "
          f"{n_true_classes} distinct classes) ===")
    for r in results:
        ari_km = adjusted_rand_score(y_true, r["kmeans_labels"])
        nmi_km = normalized_mutual_info_score(y_true, r["kmeans_labels"])
        ari_agg = adjusted_rand_score(y_true, r["agglomerative_labels"])
        nmi_agg = normalized_mutual_info_score(y_true, r["agglomerative_labels"])
        print(f"  k={r['k']}: KMeans ARI={ari_km:.3f} NMI={nmi_km:.3f} | "
              f"Agglomerative ARI={ari_agg:.3f} NMI={nmi_agg:.3f}")
    print(f"\nNOTE: n={n} is still far below the Pilot Plan's 15-20 garment phase-4/5 target -- read these "
          "numbers as a pipeline check (does the validation code run and produce sane, boundable [-1,1]/[0,1] "
          "scores), not as evidence the geometry actually predicts curator labels yet.")


if __name__ == "__main__":
    main()
