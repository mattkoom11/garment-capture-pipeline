"""
dense_to_glb.py -- build a display GLB straight from a dense RealityScan scan,
skipping retopology and texture baking (which smeared fine detail and produced
black blocks on complex fabric, see README).

Runs decimate_dense_textured.py in Blender (Collapse decimate, keeps
RealityScan's own UVs), rotates the result, and assembles a GLB with a 4K JPEG
of the original diffuse texture.

Orientation, either:
  --rotate-x DEG        explicit rotation about X (RealityScan exports here have
                        been either Y-up: 0, or Z-up: -90)
  --reference-glb PATH  auto-pick the axis-aligned rotation whose bounds best
                        match an existing GLB (prints the residual; a large
                        residual means an offset or non-axis-aligned transform)

Usage:
    python dense_to_glb.py --obj TestDress4.obj --texture TestDress4_u1_v1_diffuse.png \\
        --out-glb testdress4.glb --rotate-x -90
"""
import argparse, itertools, os, subprocess, sys, tempfile

import numpy as np
import trimesh
from PIL import Image

Image.MAX_IMAGE_PIXELS = None
HERE = os.path.dirname(os.path.abspath(__file__))


def srgb_encode(img):
    c = np.asarray(img, dtype=np.float32) / 255.0
    c = np.where(c <= 0.0031308, 12.92 * c, 1.055 * np.power(c, 1 / 2.4) - 0.055)
    return Image.fromarray((np.clip(c, 0, 1) * 255 + 0.5).astype(np.uint8))


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--obj", required=True)
    p.add_argument("--texture", required=True)
    p.add_argument("--out-glb", required=True)
    p.add_argument("--faces", type=int, default=100000)
    p.add_argument("--texture-size", type=int, default=4096)
    p.add_argument("--jpeg-quality", type=int, default=88)
    p.add_argument("--rotate-x", type=float, default=None)
    p.add_argument("--reference-glb", default=None)
    p.add_argument("--srgb-encode", action="store_true",
                   help="apply the linear->sRGB curve to the diffuse (RealityScan's texture comes out "
                        "dark/orange/oversaturated when it holds linear values that get read as sRGB)")
    a = p.parse_args()

    with tempfile.TemporaryDirectory() as tmp:
        dec = os.path.join(tmp, "dec.obj")
        subprocess.run(["blender", "--background", "--python", os.path.join(HERE, "decimate_dense_textured.py"),
                        "--", a.obj, dec, str(a.faces)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        m = trimesh.load(dec, process=False, force="mesh")

        if a.reference_glb:
            s = trimesh.load(a.reference_glb)
            ref = s.to_geometry() if hasattr(s, "to_geometry") else s
            best = None
            for perm in itertools.permutations(range(3)):
                for signs in itertools.product([1, -1], repeat=3):
                    R = np.zeros((3, 3))
                    for i, (pi, sg) in enumerate(zip(perm, signs)):
                        R[i, pi] = sg
                    if np.linalg.det(R) < 0:
                        continue
                    v = m.vertices @ R.T
                    err = np.abs(np.array([v.min(0), v.max(0)]) - ref.bounds).max()
                    if best is None or err < best[0]:
                        best = (err, R)
            print(f"best axis-aligned rotation, bounds residual {best[0]:.3f}:\n{best[1].astype(int)}")
            T = np.eye(4); T[:3, :3] = best[1]
        else:
            T = trimesh.transformations.rotation_matrix(np.radians(a.rotate_x or 0.0), [1, 0, 0])
        m.apply_transform(T)

        jpg = os.path.join(tmp, "tex.jpg")
        tex = Image.open(a.texture).convert("RGB").resize((a.texture_size,) * 2, Image.LANCZOS)
        if a.srgb_encode:
            tex = srgb_encode(tex)
        tex.save(jpg, quality=a.jpeg_quality)
        m.visual = trimesh.visual.TextureVisuals(uv=m.visual.uv, material=trimesh.visual.material.PBRMaterial(
            baseColorFactor=[255, 255, 255, 255], baseColorTexture=Image.open(jpg),
            metallicFactor=0.0, roughnessFactor=0.9, doubleSided=True))
        m.export(a.out_glb)
    print(f"wrote {a.out_glb} ({os.path.getsize(a.out_glb) / 1e6:.1f} MB, {len(m.faces)} faces)")


if __name__ == "__main__":
    main()
