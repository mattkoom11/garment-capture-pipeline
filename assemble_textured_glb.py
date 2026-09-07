"""
assemble_textured_glb.py -- build a correct, web-ready GLB from a UV-mapped
OBJ (from bake_texture.py) and its baked diffuse texture.

Why this is a separate step from bake_texture.py: Blender's own glTF
exporter can fail to embed the baked image and silently fall back to a flat
gray material, so this script builds the GLB itself with trimesh instead,
using logic already verified to work correctly against this exact viewer:
- explicit white baseColorFactor + baseColorTexture (a primitive with no
  material at all rendered solid black in the target viewer instead of
  falling back to the GLTF spec's white default)
- doubleSided material (guards against backface-culling artifacts)

Usage:
    python assemble_textured_glb.py \\
        --mesh-obj TestDress0_Resmeshed_UV.obj \\
        --texture-png TestDress0_Baked_Diffuse.png \\
        --out-glb TestDress0_Resmeshed_HighRes.glb
"""
import argparse

import trimesh
from PIL import Image


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--mesh-obj", required=True, help="UV-mapped OBJ from bake_texture.py")
    parser.add_argument("--texture-png", required=True, help="Baked diffuse PNG from bake_texture.py")
    parser.add_argument("--out-glb", required=True, help="Path to write the final GLB to")
    parser.add_argument("--roughness", type=float, default=0.9, help="Material roughness factor (default: 0.9, matte fabric-like)")
    args = parser.parse_args()

    mesh = trimesh.load(args.mesh_obj, process=False)
    if mesh.visual.uv is None:
        raise SystemExit(
            f"'{args.mesh_obj}' has no UV coordinates. It must be the OBJ "
            "produced by bake_texture.py (with --export-uv), not the plain "
            "pre-bake retopologized mesh."
        )
    print(f"mesh: {len(mesh.vertices)} verts, {len(mesh.faces)} faces, uv shape {mesh.visual.uv.shape}")

    tex_img = Image.open(args.texture_png).convert("RGB")
    material = trimesh.visual.material.PBRMaterial(
        baseColorFactor=[255, 255, 255, 255],
        baseColorTexture=tex_img,
        metallicFactor=0.0,
        roughnessFactor=args.roughness,
        doubleSided=True,
    )
    mesh.visual = trimesh.visual.TextureVisuals(uv=mesh.visual.uv, material=material)
    mesh.export(args.out_glb)
    print(f"wrote {args.out_glb}")

    # verify the round trip before trusting it -- this exact class of bug
    # (an export that "succeeds" but produces a broken material) has
    # happened before with this pipeline.
    check = trimesh.load(args.out_glb)
    check_mesh = list(check.geometry.values())[0]
    tex = check_mesh.visual.material.baseColorTexture
    print(f"verify: bbox={check_mesh.bounds.tolist()}")
    print(f"verify: texture present={'yes, ' + str(tex.size) if tex is not None else 'NO -- broken export, do not use this file'}")


if __name__ == "__main__":
    main()
