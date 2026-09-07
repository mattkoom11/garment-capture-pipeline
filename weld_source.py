#!/usr/bin/env python3
"""
weld_source.py -- weld unmerged coincident-duplicate vertices left by
RealityScan's mesh reconstruction at thin/self-touching fold regions
(tight fabric creases, straps, rolled edges).

Why this exists: RealityScan can reconstruct a tight fold as two separate
surface patches sitting at (or extremely near) identical 3D positions,
rather than one connected manifold surface. Visually this looks fine in
Blender or in AutoRemesher's own source-mesh viewer -- but AutoRemesher's
retopology algorithm can't resolve the ambiguity and leaves a real,
unfillable hole exactly at the seam. Confirmed 2026-09-06 on a test dress
scan: 100% of sampled hole-boundary vertices had an exact-position
duplicate that was itself also a boundary vertex, versus normal spacing
for a random non-boundary sample. See the project vault
(concepts/realityscan-wine-workflow.md) for the full diagnostic writeup.

MUST run before retopology (AutoRemesher). The duplicate-vertex signature
this script relies on does not survive AutoRemesher's resampling -- once a
mesh has already been retopologized, this can't fix it downstream.

Usage:
    python weld_source.py input.obj output.obj [--eps 1e-6]

The printed boundary-edge count before/after is a built-in pass/fail
signal: after welding, it should land at or near zero. If a future scan
still shows a large residual boundary-edge count after welding, that scan
likely has a different defect (a genuine occlusion hole with no nearby
duplicate, not this fold-collapse pattern) and needs manual inspection
rather than trusting this script alone.
"""
import argparse
import sys
import time
from collections import defaultdict

import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
from scipy.spatial import cKDTree


def parse_obj(path):
    verts = []
    faces = []
    t0 = time.time()
    with open(path, "r") as f:
        for line in f:
            if line[0:2] == "v ":
                p = line.split()
                verts.append((float(p[1]), float(p[2]), float(p[3])))
            elif line[0:2] == "f ":
                p = line.split()[1:]
                idx = []
                for tok in p:
                    vi = int(tok.split("/")[0])
                    idx.append(vi - 1 if vi > 0 else vi)
                faces.append(idx)
    verts = np.array(verts, dtype=np.float64)
    nv = len(verts)
    for face in faces:
        for i, vi in enumerate(face):
            if vi < 0:
                face[i] = nv + vi
    print(f"  parsed {len(verts)} verts, {len(faces)} faces in {time.time()-t0:.1f}s", flush=True)
    return verts, faces


def edge_key(a, b):
    return (a, b) if a < b else (b, a)


def build_edge_counts(faces):
    ec = defaultdict(int)
    for face in faces:
        n = len(face)
        for i in range(n):
            ec[edge_key(face[i], face[(i + 1) % n])] += 1
    return ec


def write_obj(path, verts, faces):
    with open(path, "w") as f:
        for v in verts:
            f.write(f"v {v[0]:.6f} {v[1]:.6f} {v[2]:.6f}\n")
        for face in faces:
            f.write("f " + " ".join(str(i + 1) for i in face) + "\n")


def weld(in_path, out_path, eps):
    verts, faces = parse_obj(in_path)

    t0 = time.time()
    ec = build_edge_counts(faces)
    boundary = [e for e, c in ec.items() if c == 1]
    boundary_verts = np.array(sorted(set(v for e in boundary for v in e)))
    print(f"  boundary edges: {len(boundary)}, boundary verts: {len(boundary_verts)} ({time.time()-t0:.1f}s)", flush=True)

    if len(boundary) == 0:
        print("  mesh already has zero boundary edges -- nothing to weld.", flush=True)
        write_obj(out_path, verts, faces)
        return

    t0 = time.time()
    tree = cKDTree(verts)
    print(f"  KDTree built in {time.time()-t0:.1f}s", flush=True)

    boundary_set = set(boundary_verts.tolist())
    t0 = time.time()
    pts = verts[boundary_verts]
    neighbor_lists = tree.query_ball_point(pts, r=eps)
    print(f"  neighbor queries done in {time.time()-t0:.1f}s", flush=True)

    pair_a, pair_b = [], []
    for bv, neighbors in zip(boundary_verts, neighbor_lists):
        for nb in neighbors:
            if nb != bv and nb in boundary_set:
                pair_a.append(bv)
                pair_b.append(nb)
    print(f"  weld candidate pairs: {len(pair_a)}", flush=True)

    nverts = len(verts)
    if pair_a:
        rows = np.array(pair_a + pair_b)
        cols = np.array(pair_b + pair_a)
        data = np.ones(len(rows), dtype=np.int8)
        graph = coo_matrix((data, (rows, cols)), shape=(nverts, nverts))
        _, labels = connected_components(graph, directed=False)
    else:
        labels = np.arange(nverts)

    group_members = defaultdict(list)
    involved = set(pair_a) | set(pair_b)
    for v in involved:
        group_members[labels[v]].append(v)

    remap = np.arange(nverts)
    n_groups_welded = 0
    for members in group_members.values():
        if len(members) > 1:
            canonical = min(members)
            for m in members:
                remap[m] = canonical
            n_groups_welded += 1
    print(f"  welded {n_groups_welded} groups covering {len(involved)} vertices", flush=True)

    t0 = time.time()
    new_faces = []
    degenerate = 0
    for face in faces:
        nf = [int(remap[v]) for v in face]
        if len(set(nf)) < len(nf):
            degenerate += 1
            continue
        new_faces.append(nf)
    print(f"  remapped faces in {time.time()-t0:.1f}s, dropped {degenerate} degenerate faces", flush=True)

    ec2 = build_edge_counts(new_faces)
    boundary2 = [e for e, c in ec2.items() if c == 1]
    nonman2 = [e for e, c in ec2.items() if c >= 3]
    print(f"  AFTER WELD: boundary edges: {len(boundary2)} (was {len(boundary)}), non-manifold edges: {len(nonman2)}", flush=True)
    if len(boundary2) > 0.05 * len(boundary):
        print(
            "  WARNING: residual boundary edges are still a large fraction of the "
            "original count. This scan may have a different defect (a genuine "
            "occlusion hole with no nearby duplicate) that this script can't fix -- "
            "inspect manually rather than trusting this output as fully closed.",
            flush=True,
        )

    write_obj(out_path, verts, new_faces)
    print(f"  wrote {out_path}: {len(verts)} verts, {len(new_faces)} faces", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("input_obj", help="Raw RealityScan OBJ export (before retopology)")
    parser.add_argument("output_obj", help="Path to write the welded OBJ to")
    parser.add_argument(
        "--eps",
        type=float,
        default=1e-6,
        help="Distance threshold for treating two boundary vertices as coincident duplicates (default: 1e-6)",
    )
    args = parser.parse_args()
    weld(args.input_obj, args.output_obj, args.eps)


if __name__ == "__main__":
    main()
