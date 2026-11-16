#!/usr/bin/env python3
"""Which images are in which RealityScan component.

Reads the .rsalign files written by `rs_headless.py align|import-cps|components`
(image paths are stored as UTF-16 strings inside them) and writes a membership
file `name|count|DSC numbers` that cp_select.py uses. Prints a summary with
frame ranges, plus every image in IMGDIR that no component contains.

    components.py EXPORT_DIR IMGDIR [-o membership.txt]
"""
import argparse, re
from pathlib import Path


def images_in(rsalign):
    data = Path(rsalign).read_bytes()
    found = set()
    for off in (0, 1):   # UTF-16 strings can start at either byte parity in the binary
        found |= set(re.findall(r'DSC(\d{5})\.\w{3}', data[off:].decode('utf-16-le', errors='ignore')))
    return sorted(found)


def ranges(nums):
    nums = sorted(int(n) for n in nums)
    out, start = [], None
    for i, n in enumerate(nums):
        if start is None:
            start = n
        if i + 1 == len(nums) or nums[i + 1] != n + 1:
            out.append(f'{start:05d}' if start == n else f'{start:05d}-{n:05d}')
            start = None
    return ' '.join(out)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('export_dir')
    ap.add_argument('imgdir')
    ap.add_argument('-o', '--out')
    a = ap.parse_args()
    exp = Path(a.export_dir)
    names = {}
    nf = exp / 'component_names.txt'
    if nf.exists():
        names = dict(l.split('|', 1) for l in nf.read_text().splitlines())
    rows = []
    for f in sorted(exp.glob('*.rsalign')):
        imgs = images_in(f)
        rows.append((names.get(f.stem, f.stem).strip(), imgs))
    rows.sort(key=lambda r: -len(r[1]))
    out = Path(a.out) if a.out else exp / 'membership.txt'
    out.write_text(''.join(f'{n}|{len(i)}|{" ".join(i)}\n' for n, i in rows))
    allimgs = sorted(p.stem[3:] for p in Path(a.imgdir).glob('DSC*.ARW'))
    seen = {i for _, imgs in rows for i in imgs}
    for n, imgs in rows:
        print(f'{n:<22} {len(imgs):4d}  {ranges(imgs)}')
    lost = [i for i in allimgs if i not in seen]
    print(f'{len(seen)}/{len(allimgs)} images in components; unaligned ({len(lost)}): {" ".join(lost)}')
    print('membership written to', out)


if __name__ == '__main__':
    main()
