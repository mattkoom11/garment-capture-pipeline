#!/usr/bin/env python3
"""Chain verified matches into tracks and pick control points that bridge components.

    cp_select.py WORK MEMBERSHIP [--main "Component 5"] [-o auto_cpm.csv]

A track is a feature seen in 3+ images with exactly one keypoint per image.
It is a candidate when it touches 2+ different labels, where a label is a
component name or, for an unaligned image, that image itself. With --main, a
candidate must also have 2+ images in the main component (attach the rest to it).

Picking is greedy by track length, at most --quota points per label, keeping
points at least --spacing px apart within an image. Output is RealityScan's
"Image, Point, X, Y" CSV (`-importControlPointsMeasurements`). Always run
cp_check.py on the result: repeating textures (net, mesh, weave) can pass the
epipolar check while sitting one cell off.
"""
import argparse, collections
from pathlib import Path
import numpy as np


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('work'); ap.add_argument('membership')
    ap.add_argument('--main')
    ap.add_argument('--quota', type=int, default=6, help='max points per label (default 6)')
    ap.add_argument('--spacing', type=float, default=150)
    ap.add_argument('--loop-closure', action='store_true',
                    help='require a redundant match edge in each track (stricter; fine for well-matched sets)')
    ap.add_argument('--max', type=int, default=60)
    ap.add_argument('--prefix', default='auto')
    ap.add_argument('-o', '--out')
    a = ap.parse_args()

    work = Path(a.work)
    z = np.load(work / 'matches.npz')
    names = list(z['names'])
    xy = {n: np.load(work / 'feat' / f'{n}.npz')['xy'] for n in names}

    memb = {}
    for line in Path(a.membership).read_text().splitlines():
        cname, _, imgs = line.split('|')
        for im in imgs.split():
            memb.setdefault(im, cname)
    label = lambda i: memb.get(names[i], 'unaligned ' + names[i])

    par = {}
    def find(x):
        par.setdefault(x, x)
        while par[x] != x:
            par[x] = par[par[x]]; x = par[x]
        return x
    edges = []
    for a_, b_, i, j in zip(z['a'], z['b'], z['i'], z['j']):
        u, v = (int(a_), int(i)), (int(b_), int(j))
        par[find(u)] = find(v); edges.append(u)
    tracks = collections.defaultdict(list)
    for node in list(par):
        tracks[find(node)].append(node)
    n_edges = collections.Counter(find(u) for u in edges)

    cands = []
    for root, nodes in tracks.items():
        imgs = [i for i, _ in nodes]
        if len(nodes) < 3 or len(set(imgs)) != len(imgs):
            continue
        if n_edges[root] < len(nodes) - 1 + int(a.loop_closure):
            continue
        labs = collections.Counter(label(i) for i in imgs)
        if len(labs) < 2 or (a.main and labs.get(a.main, 0) < 2):
            continue
        cands.append((nodes, labs))
    print('candidate tracks:', len(cands))

    other = lambda labs: [l for l in labs if l != a.main]
    cands.sort(key=lambda t: len(t[0]) + 3 * sum(v for l, v in t[1].items() if l != a.main), reverse=True)
    used = collections.defaultdict(list)
    per = collections.Counter()
    chosen = []
    for nodes, labs in cands:
        keys = other(labs)
        if all(per[k] >= a.quota for k in keys):
            continue
        pts = [(i, xy[names[i]][k]) for i, k in nodes]
        if any(np.hypot(*(p - q)) < a.spacing for i, p in pts for q in used[i]):
            continue
        chosen.append((nodes, labs))
        for k in keys:
            per[k] += 1
        for i, p in pts:
            used[i].append(p)
        if len(chosen) >= a.max:
            break

    rows = []
    for t, (nodes, labs) in enumerate(chosen):
        pn = f'{a.prefix} {t:02d}'
        for i, k in sorted(nodes):
            x, y = xy[names[i]][k]
            rows.append(f'DSC{names[i]}.ARW,{pn},{x:.2f},{y:.2f}')
        print(pn, dict(labs), ' '.join(names[i] for i, _ in sorted(nodes)))
    out = Path(a.out) if a.out else work / 'auto_cpm.csv'
    out.write_text('\n'.join(rows) + '\n')
    print(f'{len(chosen)} points, {len(rows)} measurements -> {out}')
    print('per label:', dict(per))


if __name__ == '__main__':
    main()
