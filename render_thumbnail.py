"""render_thumbnail.py -- front-on collection-card thumbnail from a garment's display GLB.

Blender script, run headless:

    blender --background --python render_thumbnail.py -- \
        --glb dr-2026-118.glb --rotation-y 140 --out dr-2026-118.png

--rotation-y is the frontend's `model3d_rotationY` (degrees). The frontend's
convention (lib/orientation.ts): after that yaw about glTF +Y, the garment's
front faces glTF +Z. Blender's glTF importer maps glTF (x, y, z) to Blender
(x, -z, y), so the same yaw is a rotation about Blender Z by the same angle,
and a camera on glTF +Z sits on Blender -Y looking toward +Y.

Look: the record page's default "photo" view -- the texture unlit (emission,
no tone mapping), so the capture's own lighting shows, as in RealityScan.
Background is transparent so the card's surface colour shows through. Output
is 3:4 (the card's aspect box), garment height filling --fill of the frame.
"""
import argparse
import math
import sys

import bpy
from mathutils import Vector

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
ap = argparse.ArgumentParser()
ap.add_argument("--glb", required=True)
ap.add_argument("--rotation-y", type=float, default=0.0, help="model3d_rotationY, degrees")
ap.add_argument("--out", required=True, help="PNG path")
ap.add_argument("--width", type=int, default=600)
ap.add_argument("--height", type=int, default=800)
ap.add_argument("--fill", type=float, default=0.9, help="fraction of the frame the garment spans")
args = ap.parse_args(argv)

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=args.glb)
meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"]
if not meshes:
    sys.exit(f"no mesh in {args.glb}")

# Yaw the whole import (parent the roots to one empty so node transforms survive).
pivot = bpy.data.objects.new("pivot", None)
bpy.context.scene.collection.objects.link(pivot)
for o in bpy.context.scene.objects:
    if o.parent is None and o is not pivot:
        o.parent = pivot
pivot.rotation_euler = (0, 0, math.radians(args.rotation_y))
bpy.context.view_layer.update()

# Unlit: route each material's base-colour texture straight to an emission shader.
for o in meshes:
    for slot in o.material_slots:
        mat = slot.material
        if mat is None or not mat.use_nodes:
            continue
        nt = mat.node_tree
        bsdf = next((n for n in nt.nodes if n.type == "BSDF_PRINCIPLED"), None)
        out = next((n for n in nt.nodes if n.type == "OUTPUT_MATERIAL"), None)
        if bsdf is None or out is None:
            continue
        emit = nt.nodes.new("ShaderNodeEmission")
        src = bsdf.inputs["Base Color"]
        if src.is_linked:
            nt.links.new(src.links[0].from_socket, emit.inputs["Color"])
        else:
            emit.inputs["Color"].default_value = src.default_value
        nt.links.new(emit.outputs["Emission"], out.inputs["Surface"])

pts = [o.matrix_world @ Vector(c) for o in meshes for c in o.bound_box]
lo = Vector([min(p[i] for p in pts) for i in range(3)])
hi = Vector([max(p[i] for p in pts) for i in range(3)])
ctr, ext = (lo + hi) / 2, hi - lo

sc = bpy.context.scene
engines = [e.identifier for e in bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items]
sc.render.engine = "BLENDER_EEVEE_NEXT" if "BLENDER_EEVEE_NEXT" in engines else "BLENDER_EEVEE"
sc.render.resolution_x, sc.render.resolution_y = args.width, args.height
sc.render.film_transparent = True
sc.render.image_settings.file_format = "PNG"
sc.render.image_settings.color_mode = "RGBA"
sc.view_settings.view_transform = "Standard"
sc.view_settings.look = "None"
sc.world = bpy.data.worlds.new("w")
sc.world.color = (0, 0, 0)

cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
sc.collection.objects.link(cam)
sc.camera = cam
cam.data.type = "ORTHO"
aspect = args.width / args.height
# Ortho scale spans the frame's longer side (height here); fit height and width.
cam.data.ortho_scale = max(ext.z, ext.x / aspect) / args.fill
cam.location = ctr + Vector((0, -max(ext) * 3, 0))
cam.rotation_euler = (math.radians(90), 0, 0)
cam.data.clip_end = max(ext) * 10

sc.render.filepath = args.out
bpy.ops.render.render(write_still=True)
print(f"wrote {args.out}")
