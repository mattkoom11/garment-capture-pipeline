"""crop_below.py -- remove a floor slab / stand base that RealityScan reconstructed under a garment.

Drops every face with a vertex below CUT on the up axis (Z, for the Z-up exports seen so far) and writes:
  1. a display OBJ that keeps RealityScan's UVs and material (feed to dense_to_glb.py; the open
     cut ends sit inside the hem and aren't visible), and
  2. a statistics OBJ, geometry only, with each open loop capped by a centroid fan so the mesh
     stays watertight and volume stays defined (feed to dense_features.py).

Pick CUT from a height profile of the scan: the slab shows as a thin band whose width jumps far
past the garment's. First used on RB.2025.528 (2026-11-16): cut 2.0, 4 loops capped (stand legs).
Proper fix is upstream (mask images / tighten the Reconstruction Region in RealityScan).

Usage:
    python crop_below.py scan.obj display.obj stats.obj 2.0
Copy the .mtl and diffuse texture next to display.obj.
"""
import sys, numpy as np, trimesh
from trimesh.grouping import group_rows
src, out_disp, out_stats, cut = sys.argv[1], sys.argv[2], sys.argv[3], float(sys.argv[4])
V, VT, F = [], [], []
hdr = []
for l in open(src):
    if l.startswith('v '): V.append(l.split()[1:4])
    elif l.startswith('vt '): VT.append(l.split()[1:3])
    elif l.startswith(('mtllib', 'usemtl')): hdr.append(l)
    elif l.startswith('f '):
        F.append([int(x) for c in l.split()[1:] for x in c.split('/')])
V = np.array(V, float); VT = np.array(VT, float); F = np.array(F, np.int64) - 1  # cols: v,vt,v,vt,v,vt
fv, ft = F[:, 0::2], F[:, 1::2]
keep = V[fv][:, :, 2].min(axis=1) >= cut
fv, ft = fv[keep], ft[keep]
uv_, iv = np.unique(fv, return_inverse=True); ut_, it = np.unique(ft, return_inverse=True)
fv2, ft2 = iv.reshape(-1, 3), it.reshape(-1, 3)
with open(out_disp, 'w') as o:
    o.write(''.join(hdr))
    np.savetxt(o, V[uv_], fmt='v %.6f %.6f %.6f')
    np.savetxt(o, VT[ut_], fmt='vt %.6f %.6f')
    np.savetxt(o, np.column_stack([fv2[:, 0], ft2[:, 0], fv2[:, 1], ft2[:, 1], fv2[:, 2], ft2[:, 2]]) + 1, fmt='f %d/%d %d/%d %d/%d')
print('display faces', len(fv2), 'of', len(F))
# stats copy: merge by position, cap boundary loops
m = trimesh.Trimesh(V[uv_], fv2, process=False); m.merge_vertices(); m.remove_unreferenced_vertices()
e = m.edges  # directed, per face
b = group_rows(m.edges_sorted, require_count=1)
be = e[b]  # boundary edges keep the face's winding; the cap must run opposite
nxt = {a: c for a, c in be}
seen, loops = set(), []
for s in nxt:
    if s in seen: continue
    loop, cur = [], s
    while cur not in seen:
        seen.add(cur); loop.append(cur); cur = nxt.get(cur)
        if cur is None: break
    loops.append(loop)
verts, faces = list(m.vertices), list(m.faces)
for loop in loops:
    c = len(verts); verts.append(m.vertices[loop].mean(axis=0))
    for i in range(len(loop)):
        faces.append([loop[(i + 1) % len(loop)], loop[i], c])  # reversed winding
cap = trimesh.Trimesh(np.array(verts), np.array(faces), process=False)
print('loops', len(loops), 'sizes', sorted(len(l) for l in loops)[::-1][:10], 'watertight', cap.is_watertight, 'winding', cap.is_winding_consistent)
cap.export(out_stats)
