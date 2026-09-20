#!/usr/bin/env python3
"""Which morph targets do the VRM's preset expressions own?

three-vrm's VRMExpressionMorphTargetBind does `influences[i] += w` on apply and
zeroes it on clear, re-running every vrm.update() — so any morph bound to a
declared expression is fully owned by the expression manager. Direct
morphTargetInfluences writes to those morphs are wiped each frame.

This script maps every preset expression to the morph targets it binds.
"""
import json
import struct
import sys

path = sys.argv[1] if len(sys.argv) > 1 else "model/ella.vrm"
with open(path, "rb") as f:
    data = f.read()

total = struct.unpack("<I", data[8:12])[0]
off, gltf = 12, None
while off < total:
    clen, ctype = struct.unpack("<I4s", data[off:off + 8])
    if ctype == b"JSON":
        gltf = json.loads(data[off + 8:off + 8 + clen].decode("utf-8").strip(" \0"))
    off += 8 + clen

nodes = gltf.get("nodes", [])
meshes = gltf.get("meshes", [])
ext = gltf["extensions"]["VRMC_vrm"]

# node -> mesh name lookup
node_mesh = {}
for mi, m in enumerate(meshes):
    for ni, n in enumerate(nodes):
        if n.get("mesh") == mi:
            node_mesh[ni] = m.get("name", f"mesh{mi}")

# all morph target names per mesh (extras.targetNames)
mesh_targets = {}
for m in meshes:
    names = m.get("extras", {}).get("targetNames", [])
    mesh_targets[m.get("name", f"mesh{mi}")] = names

expressions = ext.get("expressions", {})
presets = expressions.get("preset", {})
customs = expressions.get("custom", [])

print(f"preset expressions: {len(presets)} | custom: {len(customs)}\n")

bound_morphs = {}   # morphName -> [expression names]
for ename, edef in presets.items():
    binds = edef.get("morphTargetBinds", [])
    print(f"[{ename}]  (override blink={edef.get('overrideBlinkAmount', 0)}, "
          f"mouth={edef.get('overrideMouthAmount', 0)})")
    if not binds:
        print("    (no morph binds — material/texture expression only)")
    for b in binds:
        ni, ti = b.get("node"), b.get("index")
        mname = node_mesh.get(ni, f"node{ni}")
        tnames = mesh_targets.get(mname, [])
        tname = tnames[ti] if ti < len(tnames) else f"targetIndex{ti}"
        print(f"    {mname}[{ti}] = {tname}")
        bound_morphs.setdefault(tname, []).append(ename)
    print()

for c in customs:
    print(f"[custom:{c.get('name', '?')}] binds={len(c.get('morphTargetBinds', []))}")

print("\n── SUMMARY: morphs owned by the expression manager ──")
for tname, owners in sorted(bound_morphs.items()):
    print(f"  {tname:28s} ← {', '.join(owners)}")
