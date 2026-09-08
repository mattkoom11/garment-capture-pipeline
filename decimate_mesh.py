"""
decimate_mesh.py -- normalize mesh density to a fixed target vertex count,
via Blender's Decimate modifier (Collapse type), run headless.

Why this exists: extract_features.py's surface_area and curvature columns
are density-sensitive -- a denser mesh has more surface area/curvature
signal purely from having more, smaller triangles, independent of the
garment's actual shape. This project's three test garments range from
21,872 to 30,303 vertices (all straight out of AutoRemesher, whose output
count isn't currently controlled), so those columns aren't apples-to-apples
across garments yet. This is the "decimate to fixed vertex count"
preprocessing step already called for in the project plan
(garment-capture's Pipeline Overview, step 3), implemented here for the
first time.

Run on the retopologized mesh, before feature extraction -- and on a
separate copy from whatever feeds bake_texture.py/the frontend, since
decimating after UV-unwrap + baking would invalidate the UV layout the
texture was baked against. This script's output is for
extract_features.py only, not for display.

Target vertex count default (15,000) is chosen below the lowest vertex
count seen so far (21,872, TestDress2) so every current garment can
actually reach it by decimating down -- a mesh can't be decimated up to a
higher count. Revisit this default if a future scan comes in below 15,000
vertices.

Blender's Decimate modifier (Collapse type) takes a ratio, not a target
vertex count directly, so this computes ratio = target_vertices /
current_vertex_count and applies it. Decimation ratios don't map exactly
1:1 to output vertex count (edge collapse can't hit an arbitrary count
precisely), so the actual post-decimation count is checked and a warning
is printed if it's off from the target by more than 15%.

Usage:
    blender --background --python decimate_mesh.py -- \\
        --input-obj testdress0.obj --output-obj testdress0_decimated.obj \\
        --target-vertices 15000
"""
import argparse
import sys

import bpy


def log(msg):
    print(f"[decimate] {msg}", flush=True)


def parse_args():
    argv = sys.argv
    if "--" in argv:
        argv = argv[argv.index("--") + 1:]
    else:
        argv = []
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input-obj", required=True, help="Retopologized OBJ to decimate (pre-bake, pre-UV -- see module docstring)")
    parser.add_argument("--output-obj", required=True, help="Path to write the decimated OBJ to")
    parser.add_argument("--target-vertices", type=int, default=15000, help="Target vertex count (default: 15000, chosen below every garment's vertex count seen so far)")
    return parser.parse_args(argv)


def main():
    args = parse_args()

    bpy.ops.wm.read_factory_settings(use_empty=True)

    log(f"importing {args.input_obj}...")
    bpy.ops.wm.obj_import(filepath=args.input_obj)
    objs = [o for o in bpy.context.selected_objects if o.type == "MESH"]
    if len(objs) != 1:
        raise RuntimeError(f"expected exactly one mesh object in {args.input_obj}, found {len(objs)}")
    obj = objs[0]

    current_verts = len(obj.data.vertices)
    log(f"  {current_verts} vertices, {len(obj.data.polygons)} faces")

    if current_verts <= args.target_vertices:
        log(f"  already at or below target ({args.target_vertices}) -- exporting unchanged, not upsampling")
    else:
        ratio = args.target_vertices / current_verts
        log(f"  decimating with ratio {ratio:.4f} (target {args.target_vertices} vertices)")

        mod = obj.modifiers.new(name="Decimate", type="DECIMATE")
        mod.decimate_type = "COLLAPSE"
        mod.ratio = ratio

        bpy.context.view_layer.objects.active = obj
        bpy.ops.object.modifier_apply(modifier=mod.name)

    result_verts = len(obj.data.vertices)
    log(f"  result: {result_verts} vertices, {len(obj.data.polygons)} faces")

    off_by = abs(result_verts - args.target_vertices) / args.target_vertices
    if off_by > 0.15:
        log(f"  WARNING: result is {off_by:.0%} off from the target of {args.target_vertices} -- "
            f"Blender's decimate ratio doesn't map exactly 1:1 to vertex count for every mesh topology; "
            f"rerun with an adjusted --target-vertices if exact density matching matters here")

    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    # export_normals=False: the Decimate modifier leaves flat/hard-shaded
    # normals at collapsed edges, and Blender's OBJ exporter otherwise
    # writes a separate vertex per unique (position, normal) face-corner
    # combo -- this alone inflated the on-disk vertex count from ~15,000
    # (Blender's actual mesh.vertices count) to ~70,000 on first attempt,
    # completely defeating the point of this script. Normals aren't
    # meaningful for the downstream geometric feature extraction anyway.
    bpy.ops.wm.obj_export(filepath=args.output_obj, export_selected_objects=True, export_normals=False, export_materials=False)
    log(f"exported: {args.output_obj}")


if __name__ == "__main__":
    main()
