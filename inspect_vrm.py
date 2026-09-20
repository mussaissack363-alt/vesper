#!/usr/bin/env python3
"""VRM inventory — what animation capabilities does a .vrm file actually ship with?

Parses the glTF-binary JSON chunk (stdlib only, no deps) and reports:
  humanoid bones / expressions / spring bones / meshes & morph targets / materials
Usage: python3 inspect_vrm.py [path/to/model.vrm]
"""
import json
import os
import struct
import sys

# ── reference lists ──────────────────────────────────────────────────────────

CORE_BONES = [
    "hips", "spine", "chest", "upperChest", "neck", "head",
    "leftEye", "rightEye", "jaw",
    "leftShoulder", "rightShoulder",
    "leftUpperArm", "rightUpperArm", "leftLowerArm", "rightLowerArm",
    "leftHand", "rightHand",
    "leftUpperLeg", "rightUpperLeg", "leftLowerLeg", "rightLowerLeg",
    "leftFoot", "rightFoot", "leftToes", "rightToes",
]
FINGER_PARTS = ["Thumb", "Index", "Middle", "Ring", "Little"]
FINGER_JOINTS = ["Metacarpal", "Proximal", "Intermediate", "Distal"]

# 0.x preset -> 1.0 equivalent
LEGACY_PRESET_MAP = {
    "a": "aa", "i": "ih", "u": "ou", "e": "ee", "o": "oh",
    "joy": "happy", "angry": "angry", "sorrow": "sad", "fun": "relaxed",
    "blink": "blink", "blink_l": "blinkLeft", "blink_r": "blinkRight",
    "lookUp": "lookUp", "lookDown": "lookDown", "lookLeft": "lookLeft",
    "lookRight": "lookRight", "neutral": "neutral",
}
STANDARD_EXPRESSIONS = [
    "aa", "ih", "ou", "ee", "oh",                      # visemes (1.0 names)
    "blink", "blinkLeft", "blinkRight",
    "happy", "angry", "sad", "relaxed", "surprised",   # emotions
    "lookUp", "lookDown", "lookLeft", "lookRight", "neutral",
]

# ── glb parsing ──────────────────────────────────────────────────────────────

def load_gltf_json(path):
    with open(path, "rb") as f:
        data = f.read()
    if data[:4] != b"glTF":
        raise SystemExit("Not a glTF binary (.glb/.vrm)")
    total = struct.unpack("<I", data[8:12])[0]
    off, gltf, _bin = 12, None, b""
    while off < total:
        clen, ctype = struct.unpack("<I4s", data[off:off + 8])
        chunk = data[off + 8:off + 8 + clen]
        if ctype == b"JSON":
            gltf = json.loads(chunk.decode("utf-8").strip(" \0"))
        elif ctype == b"BIN":
            _bin = chunk
        off += 8 + clen
    return gltf, len(data)


def vrm_version(gltf):
    exts = gltf.get("extensions", {})
    if "VRMC_vrm" in exts:
        return "1.0", exts["VRMC_vrm"]
    if "VRM" in exts:
        return "0.x", exts["VRM"]
    return None, {}


def node_name(gltf, idx):
    nodes = gltf.get("nodes", [])
    return nodes[idx].get("name", f"node_{idx}") if 0 <= idx < len(nodes) else "?"


# ── sections ─────────────────────────────────────────────────────────────────

def report_humanoid(ver, ext):
    print("\n── HUMANOID BONES " + "─" * 33)
    if ver == "1.0":
        hb = ext.get("humanoid", {}).get("humanBones", {})
        found = {k: v.get("node") for k, v in hb.items() if isinstance(v, dict)}
    else:
        found = {}
        for b in ext.get("humanoid", {}).get("humanBones", []):
            found[b["bone"]] = b.get("node")
    if not found:
        print("  ✗ NO humanoid bones found — model can't be posed at all")
        return set()
    missing = [b for b in CORE_BONES if b not in found]
    have = [b for b in CORE_BONES if b in found]
    extra = sorted(set(found) - set(CORE_BONES) - {f"{s}{p}{j}".replace("ThumbMetacarpal", "ThumbProximal")
                                                   for s in ("left", "right")
                                                   for p in FINGER_PARTS for j in FINGER_JOINTS})
    print(f"  core bones: {len(have)}/{len(CORE_BONES)}")
    for b in have:
        print(f"    ✓ {b:16s} → {node_name(gltf, found[b])}")
    if missing:
        print(f"  ✗ MISSING core: {', '.join(missing)}")
    fingers = sorted(b for b in found if b not in CORE_BONES)
    print(f"  finger bones: {len(fingers)}" + (" — hand poses possible ✓" if fingers else " — no finger posing"))
    if extra:
        print(f"  extra mapped bones: {', '.join(extra)}")
    return set(found)


def report_expressions(ver, ext):
    print("\n── EXPRESSIONS " + "─" * 36)
    names = {}
    if ver == "1.0":
        expr = ext.get("expressions", {})
        for name in expr:
            if name in ("preset", "custom"):  # defensive; some tools nest
                for n in expr[name]:
                    names[n] = "custom-grouped"
            else:
                names[name] = "custom" if name not in STANDARD_EXPRESSIONS else "preset"
    else:
        for g in ext.get("blendShapeMaster", {}).get("blendShapeGroups", []):
            preset = g.get("presetName", "")
            names[LEGACY_PRESET_MAP.get(preset, preset)] = g.get("name", preset)
    if not names:
        print("  ✗ NO expressions — no blinking, lip sync, or emotion faces")
        return
    visemes = [v for v in ("aa", "ih", "ou", "ee", "oh") if v in names]
    blink = [b for b in ("blink", "blinkLeft", "blinkRight") if b in names]
    emotions = [e for e in ("happy", "angry", "sad", "relaxed", "surprised", "neutral") if e in names]
    lookat = [l for l in ("lookUp", "lookDown", "lookLeft", "lookRight") if l in names]
    custom = sorted(k for k, v in names.items() if v.startswith("custom") and k not in STANDARD_EXPRESSIONS)
    print(f"  visemes: {', '.join(visemes) or '✗ none (no lip sync)'}")
    print(f"  blink:   {', '.join(blink) or '✗ none'}")
    print(f"  emotions:{' ' + ', '.join(emotions) if emotions else ' ✗ none'}")
    print(f"  look-at: {', '.join(lookat) or 'none'}")
    if custom:
        print(f"  custom shapes ({len(custom)}): {', '.join(custom)}")
    missing = [e for e in STANDARD_EXPRESSIONS if e not in names]
    if missing:
        print(f"  ✗ missing standard presets: {', '.join(missing)}")


def report_springbones(ver, ext, gltf):
    print("\n── SPRING BONES " + "─" * 36)
    if ver == "1.0":
        # VRMC_springBone is its own glTF extension, NOT nested in VRMC_vrm
        sb = gltf.get("extensions", {}).get("VRMC_springBone", {}) or ext.get("springBone", {})
        springs = sb.get("springs", [])
        colliders = sb.get("colliders", [])
        joints = sum(len(s.get("joints", [])) for s in springs)
        for s in springs:
            nodes = [j.get("node") for j in s.get("joints", [])]
            label = s.get("name", "?")
            if nodes:
                print(f"  • {label}: {len(nodes)} joints (root → {node_name(gltf, nodes[0])})")
        print(f"  collider groups: {len(colliders)}")
    else:
        groups = ext.get("secondaryAnimation", {}).get("boneGroups", [])
        colliders = ext.get("secondaryAnimation", {}).get("colliderGroups", [])
        for g in groups:
            bones = g.get("bones", [])
            comment = (g.get("comment") or g.get("name") or "?").strip() or "?"
            if bones:
                print(f"  • {comment}: {len(bones)} joints (root → {node_name(gltf, bones[0])})")
        print(f"  collider groups: {len(colliders)}")
    total = joints if ver == "1.0" else sum(len(g.get("bones", [])) for g in groups)
    if total == 0:
        print("  ✗ NO spring bones — hair/cloth will be static")


def count_expressions(ver, ext):
    if ver == "1.0":
        expr = ext.get("expressions", {})
        n = len(expr.get("preset", {})) if isinstance(expr.get("preset"), dict) else 0
        n += len(expr.get("custom", [])) if isinstance(expr.get("custom"), list) else 0
        if not n:  # flat layout fallback
            n = sum(1 for k in expr if k not in ("preset", "custom"))
        return n
    return len(ext.get("blendShapeMaster", {}).get("blendShapeGroups", []))


def report_meshes(gltf):
    print("\n── MESHES & MORPH TARGETS " + "─" * 27)
    meshes = gltf.get("meshes", [])
    skins = gltf.get("skins", [])
    morphed = 0
    for i, m in enumerate(meshes):
        nprim = len(m.get("primitives", []))
        tcount = len(m["primitives"][0].get("targets", [])) if m.get("primitives") else 0
        tnames = m.get("extras", {}).get("targetNames")
        skin = gltf.get("nodes", [{}])[m["primitives"][0].get("nodes", [None])[0] or 0].get("skin") if m.get("primitives") else None
        if tcount:
            morphed += 1
        label = m.get("name", f"mesh_{i}")
        info = f"{nprim} prim"
        if tcount:
            names = f" [{', '.join(tnames[:6])}{'…' if len(tnames) > 6 else ''}]" if tnames else ""
            info += f", {tcount} morphs{names}"
        print(f"  {label}: {info}" + ("  [skinned]" if skin is not None else ""))
    total_joints = sum(len(s.get("joints", [])) for s in skins)
    print(f"  → {len(meshes)} meshes ({morphed} with morph targets), {len(skins)} skins, {total_joints} skin joints")


def report_materials(gltf):
    print("\n── MATERIALS " + "─" * 38)
    mats = gltf.get("materials", [])
    kinds = {}
    for m in mats:
        exts = m.get("extensions", {})
        kind = "MToon (anime cel)" if "VRMC_materials_mtoon" in exts else \
               "KHR_unlit" if "KHR_materials_unlit" in exts else "standard PBR"
        kinds[kind] = kinds.get(kind, 0) + 1
    for k, v in kinds.items():
        print(f"  {v} × {k}")
    print(f"  textures: {len(gltf.get('textures', []))} | images: {len(gltf.get('images', []))}")


# ── main ─────────────────────────────────────────────────────────────────────

path = sys.argv[1] if len(sys.argv) > 1 else "model/ella.vrm"
if not os.path.exists(path):
    raise SystemExit(f"file not found: {path}")

gltf, fsize = load_gltf_json(path)
ver, ext = vrm_version(gltf)
asset = gltf.get("asset", {})

print(f"{'═' * 20} VRM INVENTORY: {path} {'═' * 20}")
print(f"file size: {fsize / 1024 / 1024:.1f} MB")
print(f"generator: {asset.get('generator', '?')}")
print(f"VRM spec:  {ver or 'none — plain glTF, not a VRM!'}")
meta = ext.get("meta", gltf.get("extensions", {}).get("VRM", {}).get("meta", {}))
if meta:
    print(f"title:     {meta.get('title', meta.get('name', '?'))}")
    print(f"author:    {meta.get('author', meta.get('authorisedUser', '?'))}")

bones = report_humanoid(ver, ext)
report_expressions(ver, ext)
report_springbones(ver, ext, gltf)
report_meshes(gltf)
report_materials(gltf)

print(f"\n{'═' * 20} ANIMATION READINESS VERDICT {'═' * 18}")
if ver is None:
    print("✗ Not a VRM — animation via humanoid/emotions impossible.")
else:
    ok = lambda n, t: f"  {'✓' if n else '✗'} {t}: {n or 'none found'}"
    print(ok(len(bones), "humanoid rig"))
    n_expr = count_expressions(ver, ext)
    print(ok(n_expr, "expressions"))
    if ver == "1.0":
        sb = gltf.get("extensions", {}).get("VRMC_springBone", {}) or ext.get("springBone", {})
        n_spring = sum(len(s.get("joints", [])) for s in sb.get("springs", []))
    else:
        n_spring = sum(len(g.get("bones", [])) for g in ext.get("secondaryAnimation", {}).get("boneGroups", []))
    print(ok(n_spring, "spring-bone joints (secondary motion)"))
