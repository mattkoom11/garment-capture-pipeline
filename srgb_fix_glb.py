"""
srgb_fix_glb.py -- swap an sRGB-encoded texture into an existing display GLB,
leaving its geometry, UVs and transform untouched.

RealityScan's diffuse holds linear values that get read as sRGB (dark, orange,
oversaturated; see README "Color"). dense_to_glb.py --srgb-encode fixes that for
new builds; this script fixes a GLB that is already built and installed, which
matters when the geometry can't be cheaply reproduced (e.g. testdress1's old
GLB has a +7.81 vertical offset that a fresh build would lose).

The texture is downscaled from the original full-size diffuse (not decoded from
the GLB's own JPEG, to avoid a second round of JPEG loss), then encoded.

Usage:
    python srgb_fix_glb.py --glb testdress1.glb \\
        --texture TestDress1_u1_v1_diffuse.png --out-glb testdress1_fixed.glb
"""
import argparse, os

import trimesh
from PIL import Image

from dense_to_glb import srgb_encode

Image.MAX_IMAGE_PIXELS = None


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--glb", required=True)
    p.add_argument("--texture", required=True)
    p.add_argument("--out-glb", required=True)
    p.add_argument("--jpeg-quality", type=int, default=88)
    a = p.parse_args()

    scene = trimesh.load(a.glb)
    geoms = list(scene.geometry.values())
    assert len(geoms) == 1, f"expected one mesh, found {len(geoms)}"
    g = geoms[0]
    size = g.visual.material.baseColorTexture.size

    tex = srgb_encode(Image.open(a.texture).convert("RGB").resize(size, Image.LANCZOS))
    tmp = a.out_glb + ".tex.jpg"
    tex.save(tmp, quality=a.jpeg_quality)
    old = g.visual.material
    g.visual.material = trimesh.visual.material.PBRMaterial(
        baseColorFactor=[255, 255, 255, 255], baseColorTexture=Image.open(tmp),  # stays a lazy JPEG so trimesh embeds JPEG, not PNG
        metallicFactor=old.metallicFactor, roughnessFactor=old.roughnessFactor, doubleSided=True)
    scene.export(a.out_glb)
    os.remove(tmp)
    print(f"wrote {a.out_glb} ({os.path.getsize(a.out_glb) / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
