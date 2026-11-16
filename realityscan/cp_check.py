#!/usr/bin/env python3
"""Crop sheet for checking control points by eye before importing them.

One row per point, one tile per measurement, crosshair at the measured pixel.
Every crosshair in a row must sit on the same physical feature; drop points
that drift, sit on plain fabric, or sit on a repeating pattern. Then remove
those rows from the CSV (grep -v ',auto 05,').

    cp_check.py IMGDIR CSV sheet.jpg [--points "auto 00,auto 03"] [--first 04845,04846]

--first puts measurements in those frames at the start of each row (useful
when the point exists to attach those frames).
"""
import argparse, collections
import cv2, numpy as np

CROP = 12.0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('imgdir'); ap.add_argument('csv'); ap.add_argument('out')
    ap.add_argument('--points'); ap.add_argument('--first', default='')
    ap.add_argument('--tiles', type=int, default=8); ap.add_argument('--radius', type=int, default=110)
    a = ap.parse_args()
    rows = collections.defaultdict(list)
    for line in open(a.csv):
        if not line.strip():
            continue
        im, pn, x, y = [s.strip() for s in line.split(',')]
        rows[pn].append((im[3:8], float(x), float(y)))
    first = set(a.first.split(','))
    pts = a.points.split(',') if a.points else sorted(rows)
    cache, out, r = {}, [], a.radius
    for pn in pts:
        meas = sorted(rows[pn], key=lambda m: (m[0] not in first, m[0]))[:a.tiles]
        tiles = []
        for name, x, y in meas:
            if name not in cache:
                cache[name] = cv2.imread(f'{a.imgdir}/DSC{name}.JPG', cv2.IMREAD_COLOR | cv2.IMREAD_IGNORE_ORIENTATION)
            pad = cv2.copyMakeBorder(cache[name], r, r, r, r, cv2.BORDER_CONSTANT)
            xi, yi = int(round(x - CROP)), int(round(y - CROP))
            c = pad[yi:yi + 2 * r, xi:xi + 2 * r].copy()
            for (dx, dy) in ((0, -1), (0, 1), (-1, 0), (1, 0)):
                cv2.line(c, (r + 6 * dx, r + 6 * dy), (r + 25 * dx, r + 25 * dy), (0, 0, 255), 2)
            cv2.putText(c, f'{pn.split()[-1]} {name}', (3, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)
            tiles.append(c)
        while len(tiles) < a.tiles:
            tiles.append(np.zeros((2 * r, 2 * r, 3), np.uint8))
        out.append(np.hstack(tiles))
    cv2.imwrite(a.out, np.vstack(out))
    print('wrote', a.out, f'({len(out)} points)')


if __name__ == '__main__':
    main()
