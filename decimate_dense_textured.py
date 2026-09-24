import bpy, sys
argv = sys.argv[sys.argv.index("--")+1:]
src, out, target_faces = argv[0], argv[1], int(argv[2])
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.wm.obj_import(filepath=src, forward_axis='NEGATIVE_Y', up_axis='Z')
obj = bpy.context.selected_objects[0]
bpy.context.view_layer.objects.active = obj
nf = len(obj.data.polygons); print("[dd] faces before:", nf, flush=True)
mod = obj.modifiers.new("D", "DECIMATE"); mod.decimate_type = "COLLAPSE"
mod.ratio = target_faces / nf; mod.use_collapse_triangulate = True
bpy.ops.object.modifier_apply(modifier="D")
print("[dd] faces after:", len(obj.data.polygons), "verts:", len(obj.data.vertices), flush=True)
bpy.ops.wm.obj_export(filepath=out, export_selected_objects=True, export_uv=True, export_normals=False,
                      export_materials=False, forward_axis='NEGATIVE_Y', up_axis='Z')
