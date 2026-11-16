#!/usr/bin/env python3
"""Check RealityScan masks: coverage table + overlay sheet of suspect frames.

AI masking works on wide shots and fails on close-ups: with no silhouette in
frame it keeps one lace/tassel patch and masks the fabric around it. This
lists the fraction of each frame each mask keeps and renders every frame
below --below as an overlay (masked-out area tinted red) to look at.
Close-ups that turn out wrong get a full-frame mask with
`rs_headless.py white-masks PROJECT --frames ...`; low-angle shots where the
masked area is really floor are fine as they are.

    mask_qa.py PROJECT.rsproj IMGDIR sheet.jpg [--below 0.45]

Masks are read through the .rsproj, so frames already switched to an external
(white) mask show their current mask, not the stale AI one on disk.
"""
import argparse, re
from pathlib import Path
import cv2, numpy as np

CROP = 12


def mask_paths(proj):
    proj = Path(proj)
    text = proj.read_text(errors='ignore')
    data = proj.parent / proj.stem
    out = {}
    for m in re.finditer(r'<input fileName="[^"]*?DSC(\d+)\.\w+"[^>]*>\s*<layer type="mask" fileName="([^"]+)"', text):
        n, f = m.group(1), m.group(2)
        if f.startswith('resource:'):
            hits = list(data.glob('vil' + f.split('\\')[-1] + '.dat'))
            out[n] = hits[0] if hits else None
        else:
            out[n] = (proj.parent / f.replace('\\', '/')).resolve()
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('project'); ap.add_argument('imgdir'); ap.add_argument('out')
    ap.add_argument('--below', type=float, default=0.45)
    a = ap.parse_args()
    paths = mask_paths(a.project)
    if not paths:
        raise SystemExit('no mask layers in this project')
    cov = {}
    for n, p in sorted(paths.items()):
        m = cv2.imdecode(np.fromfile(p, np.uint8), cv2.IMREAD_GRAYSCALE)
        cov[n] = (cv2.resize(m, (602, 402), interpolation=cv2.INTER_AREA) > 127).mean()
    v = np.array(list(cov.values()))
    print(f'{len(cov)} masks; kept fraction median {np.median(v):.2f}, min {v.min():.2f}')
    low = sorted((n for n in cov if cov[n] < a.below), key=cov.get)
    print(f'below {a.below}:', ' '.join(f'{n}:{cov[n]:.2f}' for n in low))
    tiles = []
    for n in low:
        m = cv2.imdecode(np.fromfile(paths[n], np.uint8), cv2.IMREAD_GRAYSCALE)
        im = cv2.imread(f'{a.imgdir}/DSC{n}.JPG', cv2.IMREAD_COLOR | cv2.IMREAD_IGNORE_ORIENTATION)
        m = m[CROP:CROP + im.shape[0], CROP:CROP + im.shape[1]]
        red = np.zeros_like(im); red[:] = (0, 0, 255)
        ov = np.where((m > 127)[..., None], im, cv2.addWeighted(im, 0.35, red, 0.65, 0))
        ov = cv2.resize(ov, (360, 240), interpolation=cv2.INTER_AREA)
        cv2.putText(ov, f'{n} {cov[n]:.2f}', (5, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
        tiles.append(ov)
    if tiles:
        while len(tiles) % 6:
            tiles.append(np.zeros_like(tiles[0]))
        cv2.imwrite(a.out, np.vstack([np.hstack(tiles[i:i + 6]) for i in range(0, len(tiles), 6)]))
        print('wrote', a.out, '(sensor orientation, so tiles may appear rotated)')


if __name__ == '__main__':
    main()
