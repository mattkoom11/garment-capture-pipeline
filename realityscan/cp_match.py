#!/usr/bin/env python3
"""SIFT features + geometrically verified pairwise matches for a capture.

Coordinates are written in RealityScan's control-point measurement frame:
the raw sensor-orientation pixel (EXIF rotation NOT applied) plus the ARW
crop origin (12, 12 on the Sony A7III: the ARW decodes to 6024x4024, the
camera JPG is that image cropped to 6000x4000). Verified on DR.2024.121 and
RB.2025.528, including frames with opposite EXIF orientation tags.

    cp_match.py IMGDIR WORK                      # neighbors +-1..3 and loop pairs 12..22 apart
    cp_match.py IMGDIR WORK --targets 04845,04846   # add: these frames vs every frame

Matching uses JPGs (same pixels as the ARW minus the border). Features are
cached in WORK/feat/, matches merged into WORK/matches.npz.
"""
import argparse, os
from multiprocessing import Pool
from pathlib import Path
import cv2, numpy as np

SCALE = 0.5       # SIFT on half-res images
NFEAT = 8000
CROP = 12.0       # ARW DefaultCropOrigin; check with `exiftool -DefaultCropOrigin x.ARW`
IMGDIR = WORK = None


def init(imgdir, work):
    global IMGDIR, WORK
    IMGDIR, WORK = Path(imgdir), Path(work)


def feat(name):
    p = WORK / 'feat' / f'{name}.npz'
    if p.exists():
        return
    im = cv2.imread(str(IMGDIR / f'DSC{name}.JPG'), cv2.IMREAD_GRAYSCALE | cv2.IMREAD_IGNORE_ORIENTATION)
    sm = cv2.resize(im, None, fx=SCALE, fy=SCALE, interpolation=cv2.INTER_AREA)
    kp, des = cv2.SIFT_create(nfeatures=NFEAT, contrastThreshold=0.02).detectAndCompute(sm, None)
    xy = (np.array([k.pt for k in kp], np.float32) + 0.5) / SCALE - 0.5 + CROP
    des = np.sqrt(des / (des.sum(1, keepdims=True) + 1e-7)).astype(np.float32)   # RootSIFT
    np.savez(p, xy=xy, des=des)


def load(name):
    z = np.load(WORK / 'feat' / f'{name}.npz')
    return z['xy'], z['des']


def match(args):
    a, b, na, nb = args
    xa, da = load(na); xb, db = load(nb)
    empty = (a, b, np.zeros((0, 2), np.int32))
    fl = cv2.FlannBasedMatcher(dict(algorithm=1, trees=4), dict(checks=64))
    best = lambda ms: {m[0].queryIdx: m[0].trainIdx for m in ms
                       if len(m) == 2 and m[0].distance < 0.8 * m[1].distance}
    fwd, bwd = best(fl.knnMatch(da, db, k=2)), best(fl.knnMatch(db, da, k=2))
    mut = [(i, j) for i, j in fwd.items() if bwd.get(j) == i]        # mutual + ratio test
    if len(mut) < 20:
        return empty
    ij = np.array(mut, np.int32)
    F, inl = cv2.findFundamentalMat(xa[ij[:, 0]], xb[ij[:, 1]], cv2.USAC_MAGSAC, 2.0, 0.9999, 20000)
    if F is None:
        return empty
    ij = ij[inl.ravel().astype(bool)]
    return (a, b, ij) if len(ij) >= 15 else empty


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('imgdir'); ap.add_argument('work')
    ap.add_argument('--targets', help='frames to match against every other frame')
    ap.add_argument('--near', type=int, default=3, help='match frames up to this many apart (default 3)')
    ap.add_argument('--loop', default='12-22', help='also match frames this far apart (orbit loops); "" to skip')
    ap.add_argument('--procs', type=int, default=10)
    a = ap.parse_args()
    Path(a.work, 'feat').mkdir(parents=True, exist_ok=True)
    names = sorted(p.stem[3:] for p in Path(a.imgdir).glob('DSC*.JPG'))
    n = len(names)
    with Pool(a.procs, initializer=init, initargs=(a.imgdir, a.work)) as pool:
        pool.map(feat, names)
        print('features:', n, flush=True)
        out = Path(a.work) / 'matches.npz'
        A, B, I, J = [], [], [], []
        done = set()
        if out.exists():
            z = np.load(out)
            A, B, I, J = list(z['a']), list(z['b']), list(z['i']), list(z['j'])
            done = set(zip(A, B))
        if a.targets:
            idx = {m: i for i, m in enumerate(names)}
            pairs = {tuple(sorted((idx[t], j))) for t in a.targets.split(',') for j in range(n) if j != idx[t]}
        else:
            ds = list(range(1, a.near + 1))
            if a.loop:
                lo, hi = map(int, a.loop.split('-')); ds += list(range(lo, hi + 1))
            pairs = {(i, i + d) for i in range(n) for d in ds if i + d < n}
        pairs = sorted(p for p in pairs if p not in done)
        print('pairs to match:', len(pairs), flush=True)
        good = 0
        for a_, b_, ij in pool.imap_unordered(match, [(i, j, names[i], names[j]) for i, j in pairs], chunksize=8):
            if len(ij):
                good += 1
                A += [a_] * len(ij); B += [b_] * len(ij); I += list(ij[:, 0]); J += list(ij[:, 1])
    np.savez(out, names=np.array(names), a=np.array(A, np.int32), b=np.array(B, np.int32),
             i=np.array(I, np.int32), j=np.array(J, np.int32))
    print(f'new verified pairs: {good}; total verified matches: {len(A)} -> {out}')


if __name__ == '__main__':
    main()
