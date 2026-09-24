"""
bake_texture.py -- bake real high-resolution diffuse color from the original
dense RealityScan mesh onto a clean, retopologized (welded + AutoRemesher)
mesh that has no UVs of its own.

Why this exists: AutoRemesher's retopology produces entirely new geometry
with no UV coordinates, so there is no way to carry the original photo
texture over directly. This script UV-unwraps the clean mesh (Blender's
Smart UV Project) and bakes real per-pixel detail from the dense source
mesh's actual diffuse photo onto that new UV layout (Cycles, selected-to-
active baking -- the standard game-dev "high-poly to low-poly" technique),
instead of the coarse per-vertex-color approximation that would otherwise
be the only option.

MUST run via Blender's own Python, not a plain interpreter:

    blender --background --python bake_texture.py -- \\
        --source-obj TestDress0.obj \\
        --diffuse-png TestDress0/TestDress0_LowPoly_u0_v0_diffuse.png \\
        --target-obj TestDress0_Resmeshed.obj \\
        --out-obj TestDress0_Resmeshed_UV.obj \\
        --out-texture TestDress0_Baked_Diffuse.png \\
        --resolution 2048

Deliberately exports OBJ, not GLB: Blender's glTF exporter can fail to
embed the baked image (an OCIO colorspace-version mismatch caused this
exactly once), and GLB's scene-graph node transforms are an easy way to
accidentally read raw untransformed geometry if post-processed with a
generic loader. Plain OBJ has no material-embedding step and no scene
graph -- just a text file with faces referencing UV coordinates -- which
sidesteps both failure modes. Run assemble_textured_glb.py next to build
the actual web-ready GLB from this OBJ + the baked PNG.
"""
import argparse
import sys

import bpy


def log(msg):
    print(f"[bake] {msg}", flush=True)


def parse_args():
    argv = sys.argv
    if "--" in argv:
        argv = argv[argv.index("--") + 1:]
    else:
        argv = []
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-obj", required=True, help="Original dense RealityScan OBJ (geometry only; its own .mtl need not reference a real image)")
    parser.add_argument("--diffuse-png", required=True, help="The real captured diffuse texture image to bake from")
    parser.add_argument("--target-obj", required=True, help="Clean, welded + AutoRemesher-retopologized OBJ to receive the bake (must have no pre-existing UVs, or they will be replaced)")
    parser.add_argument("--out-obj", required=True, help="Path to write the UV-unwrapped target mesh to")
    parser.add_argument("--out-texture", required=True, help="Path to write the baked diffuse PNG to")
    parser.add_argument("--resolution", type=int, default=2048, help="Bake texture size in pixels, square (default: 2048)")
    parser.add_argument("--angle-limit", type=float, default=66.0, help="Smart UV Project angle_limit in degrees (default: 66.0, Blender's own default). Lower values create more, smaller UV islands -- reduces max texture stretch on doubly-curved surfaces at the cost of more visible seams.")
    parser.add_argument("--island-margin", type=float, default=0.02, help="Smart UV Project island_margin (default: 0.02)")
    parser.add_argument("--cage-extrusion", type=float, default=0.1, help="Bake cage_extrusion in scene units (default: 0.1)")
    parser.add_argument("--max-ray-distance", type=float, default=1.0, help="Bake max_ray_distance in scene units (default: 1.0)")
    return parser.parse_args(argv)


def main():
    args = parse_args()

    bpy.ops.wm.read_factory_settings(use_empty=True)

    log("importing old dense (textured-source) mesh...")
    bpy.ops.wm.obj_import(filepath=args.source_obj)
    old_obj = bpy.context.selected_objects[0]
    old_obj.name = "OldDense"
    log(f"  old mesh: {len(old_obj.data.vertices)} verts, bbox={old_obj.dimensions}")

    log("assigning the real diffuse texture to the old mesh...")
    mat = bpy.data.materials.new(name="RealDiffuse")
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    tex_image_node = mat.node_tree.nodes.new("ShaderNodeTexImage")
    tex_image_node.image = bpy.data.images.load(args.diffuse_png)
    mat.node_tree.links.new(bsdf.inputs["Base Color"], tex_image_node.outputs["Color"])
    old_obj.data.materials.clear()
    old_obj.data.materials.append(mat)

    log("importing target clean (retopologized) mesh...")
    bpy.ops.wm.obj_import(filepath=args.target_obj)
    new_obj = [o for o in bpy.context.selected_objects if o is not old_obj][0]
    new_obj.name = "TargetClean"
    log(f"  target mesh: {len(new_obj.data.vertices)} verts, bbox={new_obj.dimensions}")
    log(f"  old bbox min/max: {[round(v, 3) for v in old_obj.bound_box[0]]} / {[round(v, 3) for v in old_obj.bound_box[6]]}")
    log(f"  target bbox min/max: {[round(v, 3) for v in new_obj.bound_box[0]]} / {[round(v, 3) for v in new_obj.bound_box[6]]}")
    log("  (these two bboxes should closely match -- if not, the source/target don't correspond to the same scan)")

    log("UV unwrapping the target mesh (Smart UV Project)...")
    bpy.context.view_layer.objects.active = new_obj
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.smart_project(angle_limit=args.angle_limit, island_margin=args.island_margin)
    bpy.ops.object.mode_set(mode="OBJECT")

    log(f"creating {args.resolution}x{args.resolution} bake target image + material...")
    bake_img = bpy.data.images.new("BakedDiffuse", width=args.resolution, height=args.resolution)
    bake_mat = bpy.data.materials.new(name="BakedMat")
    bake_mat.use_nodes = True
    bake_tex_node = bake_mat.node_tree.nodes.new("ShaderNodeTexImage")
    bake_tex_node.image = bake_img
    new_obj.data.materials.clear()
    new_obj.data.materials.append(bake_mat)
    bake_mat.node_tree.nodes.active = bake_tex_node

    log("configuring Cycles bake (selected-to-active, diffuse color only)...")
    bpy.context.scene.render.engine = "CYCLES"
    try:
        bpy.context.scene.cycles.device = "CPU"
    except Exception as e:
        log(f"  (could not force CPU device, continuing with default: {e})")
    bpy.context.scene.render.bake.use_pass_direct = False
    bpy.context.scene.render.bake.use_pass_indirect = False
    bpy.context.scene.render.bake.use_pass_color = True
    bpy.context.scene.render.bake.use_selected_to_active = True
    bpy.context.scene.render.bake.cage_extrusion = args.cage_extrusion
    bpy.context.scene.render.bake.max_ray_distance = args.max_ray_distance

    bpy.ops.object.select_all(action="DESELECT")
    old_obj.select_set(True)
    new_obj.select_set(True)
    bpy.context.view_layer.objects.active = new_obj

    log("baking...")
    bpy.ops.object.bake(type="DIFFUSE")
    log("bake complete.")

    bake_img.filepath_raw = args.out_texture
    bake_img.file_format = "PNG"
    bake_img.save()
    log(f"saved baked texture: {args.out_texture}")

    log("exporting UV-mapped target mesh as OBJ (not GLB -- see module docstring for why)...")
    bpy.ops.object.select_all(action="DESELECT")
    new_obj.select_set(True)
    bpy.context.view_layer.objects.active = new_obj
    bpy.ops.wm.obj_export(filepath=args.out_obj, export_selected_objects=True, export_uv=True, export_materials=False)
    log(f"exported: {args.out_obj}")
    log("next: run assemble_textured_glb.py to build the final web-ready GLB from this OBJ + the baked PNG.")


if __name__ == "__main__":
    main()
