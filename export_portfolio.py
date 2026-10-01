"""
export_portfolio.py -- write the pilot PCA + k-means results as one JSON file
for the portfolio site's garment-capture demo.

Same features, scaling and k-means settings as clustering_analysis.py (it
imports load_features from there), so the numbers on the site are the
numbers this repo produces. Two things are pinned so the site's plot
doesn't jump around between runs as garments are added:

  - Component direction. PCA can return a component or its mirror image.
    Each component is flipped, if needed, so its ANCHORS feature loads
    positively (PC1: bigger surface area is to the right; PC2: more hem
    drape is up).
  - Cluster numbering. k-means numbers clusters arbitrarily; here cluster 0
    is the one with the highest mean PC1 score (the largest garments), then
    downward, so colours stay put when the grouping itself doesn't change.

The two features loading most heavily on each component are exported as
`drivers`; the site only shows its hand-written axis description while the
drivers still match the ones it was written for, and falls back to naming
the drivers otherwise.

Usage:
    python export_portfolio.py --features features.csv --out portfolio_pca.json
"""
import argparse
import datetime
import json
import subprocess
import sys

import numpy as np
from sklearn.cluster import KMeans
from sklearn.decomposition import PCA
from sklearn.metrics import silhouette_score

from clustering_analysis import load_features

ANCHORS = ["surface_area", "drape_extent"]
K_MAX = 4


def kind_of(garment_id):
    return "test" if garment_id.startswith("testdress") else "archive"


def source_commit():
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=True)
        return out.stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--features", default="features.csv")
    parser.add_argument("--out", default="portfolio_pca.json")
    args = parser.parse_args()

    df, feature_columns, X = load_features(args.features)
    n = len(df)
    if n < 4:
        sys.exit(f"ERROR: only {n} garments -- clustering needs at least 4 (see clustering_analysis.py).")

    pca = PCA(n_components=2)
    scores = pca.fit_transform(X)
    loadings = pca.components_.copy()
    for i, anchor in enumerate(ANCHORS):
        if loadings[i, feature_columns.index(anchor)] < 0:
            loadings[i] *= -1
            scores[:, i] *= -1

    drivers = [[feature_columns[j] for j in np.argsort(-np.abs(row))[:2]] for row in loadings]

    clusterings = {}
    for k in range(2, min(K_MAX, n - 1) + 1):
        labels = KMeans(n_clusters=k, n_init=10, random_state=0).fit(X).labels_
        order = sorted(range(k), key=lambda c: -scores[labels == c, 0].mean())
        relabel = {old: new for new, old in enumerate(order)}
        clusterings[str(k)] = {
            "labels": [relabel[c] for c in labels],
            "silhouette": round(float(silhouette_score(X, labels)), 3),
        }

    out = {
        "generated": datetime.date.today().isoformat(),
        "source_commit": source_commit(),
        "features": feature_columns,
        "variance": [round(float(v), 4) for v in pca.explained_variance_ratio_],
        "drivers": drivers,
        "loadings": [[round(float(v), 3) for v in row] for row in loadings],
        "garments": [
            {
                "id": gid,
                "label": label,
                "kind": kind_of(gid),
                "pc": [round(float(a), 3), round(float(b), 3)],
                "z": [round(float(v), 2) for v in z],
            }
            for gid, label, (a, b), z in zip(df["garment_id"], df["label"], scores, X)
        ],
        "kmeans": clusterings,
    }
    with open(args.out, "w") as f:
        json.dump(out, f, indent=2)
        f.write("\n")

    best = max(clusterings, key=lambda k: clusterings[k]["silhouette"])
    print(f"wrote {args.out}: {n} garments, {len(feature_columns)} features")
    print(f"  variance explained: PC1 {out['variance'][0]:.0%}, PC2 {out['variance'][1]:.0%}")
    for i, d in enumerate(drivers):
        print(f"  PC{i + 1} driven most by: {', '.join(d)}")
    print(f"  best k by silhouette: {best} ({clusterings[best]['silhouette']:.2f})")


if __name__ == "__main__":
    main()
