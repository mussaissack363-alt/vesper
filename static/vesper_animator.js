// ════════════════════════════════════════════════════════════════
//  VESPER ANIMATOR — reusable procedural animation module for ella.vrm
// ════════════════════════════════════════════════════════════════
// Self-contained ES module: rendering-bug fixes, animation-track sanitizing,
// procedural breathing/sway, camera/cursor lookAt, auto-blinking, expression
// and viseme controllers. Import it, hand it a THREE namespace, and call
// `.update(delta)` once per frame AFTER your bone posing but BEFORE
// vrm.update(delta), so expression weights land in that frame's application.
//
//   import { createVesperAnimator } from '/vesper_animator.js';
//   const animator = createVesperAnimator(THREE);
//   animator.attach(vrm);
//   // per frame:  your bone posing → animator.update(delta) → vrm.update(delta)
//
// Nothing here needs .vrma clips or external assets.

export function createVesperAnimator(THREE) {
  const clamp01 = (v) => Math.min(1, Math.max(0, v));

  // layered-sine noise ≈ smooth pseudo-random drift in [-1, 1]
  const noise1 = (t, seed = 0) =>
    Math.sin(t * 0.63 + seed * 12.9) * 0.5 +
    Math.sin(t * 1.37 + seed * 7.1) * 0.3 +
    Math.sin(t * 2.71 + seed * 3.7) * 0.2;

  const state = {
    vrm: null,
    clock: null,
    time: 0,
    // breathing
    breathT: Math.random() * 10,
    // blinking
    nextBlinkAt: 1.5 + Math.random() * 2.5,   // seconds since attach
    blinkPhase: -1,
    blinkW: 0,
    // visemes
    visemes: { aa: 0, ih: 0, ou: 0, ee: 0, oh: 0 },
    // expressions
    targets: {},          // name → target weight
    current: {},          // name → eased weight
    // lookAt
    lookAtTarget: null,   // Object3D the eyes/head follow (defaults to camera)
    cursor: { x: 0, y: 0, influence: 0, lastMoveAt: -1e9 },
    headAim: { yaw: 0, pitch: 0, roll: 0 },
    headVel: { yaw: 0, pitch: 0, roll: 0 },
    mixer: null,          // AnimationMixer on normalizedHumanBonesRoot
    mixerRoot: null,
    clipRootMotion: false,// true → pose sanitizer preserves hips position
    currentAction: null,  // crossfade source for playClip/stopClips
    // tuneables (all optional, safe defaults)
    energy: 0.4,          // 0..1 — overall liveliness of idle motion
    speaking: false,      // flips viseme gate + livelier head motion
    blinkInterval: [3, 5],// seconds
    breathScale: 1,       // hosts with their own breathing layer dial this down
    autonomous: true      // false = host drives breathing/blink/gaze itself;
                          // module then only handles fixes, expressions, visemes
  };

  // raw-morph flash sets for moods with no single VRM preset (VRoid names).
  // Bound morphs (Fcl_ALL_*) are cleared+re-applied by the expression manager
  // each vrm.update(), so these writes compose WITH preset expressions instead
  // of being wiped by them.
  const FACE_PRESETS = {
    laughing:  { 'Fcl_ALL_Joy': 0.95, 'Fcl_EYE_Close': 0.55, 'Fcl_MTH_Up': 0.5 },
    playful:   { 'Fcl_MTH_Fun': 0.4, 'Fcl_EYE_Half': 0.25 },
    wink:      { 'Fcl_EYE_Close_R': 0.9, 'Fcl_MTH_Fun': 0.45 },
    smug:      { 'Fcl_MTH_Fun': 0.5, 'Fcl_MTH_Up': 0.4, 'Fcl_EYE_Close_R': 0.25 },
    embarrassed:{ 'Fcl_BRW_Sorrow': 0.4, 'Fcl_MTH_Small': 0.5, 'Fcl_EYE_Spread': 0.3 },
    jealous:   { 'Fcl_BRW_Angry': 0.35, 'Fcl_MTH_Small': 0.4, 'Fcl_BRW_Sorrow': 0.3 },
    confused:  { 'Fcl_BRW_Surprised': 0.55, 'Fcl_MTH_Small': 0.4 },
    disgusted: { 'Fcl_MTH_Down': 0.6, 'Fcl_BRW_Sorrow': 0.4, 'Fcl_EYE_Close': 0.25 },
    proud:     { 'Fcl_MTH_Up': 0.45, 'Fcl_BRW_Joy': 0.3 },
    love:      { 'Fcl_ALL_Joy': 0.6, 'Fcl_EYE_Close': 0.2 },
    worried:   { 'Fcl_BRW_Sorrow': 0.45, 'Fcl_EYE_Spread': 0.3 },
    sleepy:    { 'Fcl_EYE_Half': 0.6, 'Fcl_MTH_Small': 0.3 },
    crying:    { 'Fcl_ALL_Sorrow': 0.9, 'Fcl_BRW_Sorrow': 0.8, 'Fcl_EYE_Close': 0.4, 'Fcl_MTH_Down': 0.6 },
    annoyed:   { 'Fcl_ALL_Angry': 0.5, 'Fcl_BRW_Angry': 0.55, 'Fcl_MTH_Small': 0.35 },
    calm:      {}   // clears flashes
  };
  let flashMorphs = {};   // name → expiry timestamp (seconds in state.time)

  // ── 1. RENDERING FIXES ─────────────────────────────────────────
  // Called once after load. Order matters: sanitize first, then reset springs.
  function applyRenderFixes(vrm) {
    if (!vrm) return;
    if (!vrm.userData) vrm.userData = {};   // tolerate bare scene-graph nodes
    if (vrm.userData.__vesperFixed) return;

    // 1a. frustum culling off — skinned meshes are animated by bones outside
    // their (bind-pose) bounding box, so the renderer can cull her mid-motion.
    // The camera never needs culling help for a single-avatar scene.
    let culled = 0;
    vrm.scene.traverse((obj) => {
      if (obj.isMesh || obj.isSkinnedMesh) {
        obj.frustumCulled = false;
        culled++;
      }
    });
    log('frustum culling disabled', `meshes=${culled}`);

    // 1b. no spring-bone explosion at spawn: springs start from the bind pose
    // with zero velocity instead of integrating the load-time snap as motion.
    try {
      if (vrm.springBoneManager && vrm.springBoneManager.reset) {
        vrm.springBoneManager.reset();
        log('springBoneManager.reset()', 'hair/coat start at rest');
      }
    } catch (e) {
      log('springBoneManager.reset failed', e && e.message);
    }

    // 1c. some VRM files contain a stale last-update timestamp; force a first
    // update with a tiny delta so every frame after is a normal-sized step.
    try { if (vrm.update) vrm.update(1 / 120); } catch (e) { /* non-fatal */ }

    vrm.userData.__vesperFixed = true;
  }

  // ── 2. ANIMATION RETARGETING + TRACK SANITIZER ─────────────────
  // Retargets external clips (Mixamo/FBX/BVH) onto this VRM's NORMALIZED
  // humanoid rig and sanitizes the classic "flew away / deformed" offenders:
  //   • position tracks stripped EXCEPT the hips translation track
  //   • ALL scale tracks stripped
  //   • rotation tracks rebound from source node names to the normalized rig's
  //     per-bone Object3D nodes — three-vrm-animation compatible: play the
  //     retargeted clips through createMixer()/updateMixer() (a mixer rooted
  //     at vrm.humanoid.normalizedHumanBonesRoot) and vrm.update() transfers
  //     the rig pose onto the raw bones every frame, so clips authored for any
  //     source skeleton land without arm/shoulder twisting from T-pose binds.
  // Mixamo normalization: 'mixamorig:' prefix stripped, Armature/Root wrappers
  // collapsed into the hips track, hips position keys kept (in-place motion).
  function retargetClips(clips, opts = {}) {
    const clipsArr = Array.isArray(clips) ? clips : [clips];
    const report = { clips: 0, removed: 0, rebound: 0, keptHips: 0 };
    const vrm = state.vrm;
    const rig = vrm && vrm.humanoid && vrm.humanoid.normalizedHumanBones;
    if (!rig) {
      log('retargetClips: no normalized rig', 'load the VRM first — clips untouched');
      return report;
    }

    // canonical lowercase VRM name → normalized rig node (the retarget targets)
    const rigNodes = {};
    for (const [boneName, bone] of Object.entries(rig)) {
      if (bone && bone.node) rigNodes[boneName.toLowerCase()] = bone.node;
    }
    // source fragment → VRM-name fragment. ORDER MATTERS: 'forearm' must be
    // tested before 'arm', 'upleg'/'lowerleg' before 'leg' (substring traps).
    const alias = Object.assign({
      forearm: 'lowerarm', lowerarm: 'lowerarm',
      upleg: 'upperleg', upperleg: 'upperleg',
      lowerleg: 'lowerleg', leg: 'lowerleg',
      clavicle: 'shoulder', shoulder: 'shoulder',
      arm: 'upperarm', upperarm: 'upperarm',
      toe: 'toes', foot: 'foot',
      // Mixamo spine chain → VRM segments (Spine → spine, Spine1 → chest,
      // Spine2 → upperChest — matches VRoid exports like ella.vrm)
      spine1: 'chest', spine2: 'upperchest',
    }, opts.aliases || {});
    const mixamoPrefix = /^(mixamorig:?)/i;
    const wrapperRe = /^(armature|root|normalnode)$/;
    const HIPS_ALIASES = new Set(['hips', 'j_bip_c_hips', 'j_bip_c_hips_end',
      'root', 'mixamorig:hips', 'mixamorighips', 'armature', 'normalnode']);

    const canonicalize = (nodeName) => {
      let n = nodeName.toLowerCase().replace(mixamoPrefix, '');
      if (wrapperRe.test(n)) return 'hips';
      for (const [frag, vrmFrag] of Object.entries(alias)) {
        if (n.includes(frag)) {
          return n.includes('left') ? 'left' + vrmFrag
               : n.includes('right') ? 'right' + vrmFrag
               : vrmFrag;
        }
      }
      return n;
    };

    for (const clip of clipsArr) {
      if (!clip || !clip.tracks) continue;
      report.clips++;
      const keep = [];
      for (const track of clip.tracks) {
        const rawName = track.name || '';
        const dot = rawName.indexOf('.');
        const nodeName = (dot >= 0 ? rawName.slice(0, dot) : rawName).toLowerCase();
        const prop = (dot >= 0 ? rawName.slice(dot + 1) : '').toLowerCase();
        const vrmName = canonicalize(nodeName);

        // scale: strip everywhere — a scale track on any ancestor deforms her
        if (prop === 'scale') { report.removed++; continue; }

        // position: keep ONLY the hips translation (in-place root motion)
        if (prop === 'position') {
          if (HIPS_ALIASES.has(nodeName) || HIPS_ALIASES.has(vrmName)) {
            const t = track.clone();
            t.name = 'hips.position';
            keep.push(t);
            report.keptHips++;
          } else {
            report.removed++;   // child-body-bone translation = deformation
          }
          continue;
        }

        // rotation: rebind to the normalized rig node when we know the bone
        if (prop === 'quaternion' || prop === 'rotation' || /euler/i.test(prop)) {
          const rigNode = rigNodes[vrmName];
          if (rigNode && track.values && track.values.length && track.values.length % 4 === 0) {
            const t = track.clone();
            for (let i = 0; i < t.values.length; i++) {
              if (!Number.isFinite(t.values[i])) t.values[i] = 0;   // NaN guard
            }
            t.name = `${rigNode.name}.quaternion`;
            keep.push(t);
            report.rebound++;
          } else {
            report.removed++;   // unknown bone or malformed track
          }
          continue;
        }
        report.removed++;   // morph/mismatched tracks don't belong on a rig clip
      }
      clip.tracks = keep;
      if (clip.resetDuration && clip.tracks.length) clip.resetDuration();
    }
    log('clips retargeted to normalized rig',
      `clips=${report.clips} rebound=${report.rebound} hipsKept=${report.keptHips} dropped=${report.removed}`);
    return report;
  }

  // legacy API kept: sanitize-in-place (no retargeting of unknown sources).
  // NOTE: per the retargeting contract, hips position is now KEPT, not dropped.
  function sanitizeAnimationTracks(vrmIgnored, clips, opts = {}) {
    const r = retargetClips(clips, opts);
    return { clips: r.clips, removed: r.removed, clamped: r.rebound + r.keptHips };
  }

  // ── 2b. MIXER LIFECYCLE — clips play on the normalized rig ──────────
  // mixer.update() must run FIRST in the frame (before procedural posing and
  // vrm.update) so clips set the base pose that everything else layers onto.
  function createMixer(TH) {
    const vrm = state.vrm;
    const root = vrm && vrm.humanoid && vrm.humanoid.normalizedHumanBonesRoot;
    if (!root) { log('createMixer: no normalized rig root', ''); return null; }
    const Namespace = TH || THREE;
    if (state.mixer) { state.mixer.stopAllAction(); }
    state.mixer = new Namespace.AnimationMixer(root);
    state.mixerRoot = root;
    log('mixer created on normalizedHumanBonesRoot', '');
    return state.mixer;
  }

  function updateMixer(delta) {
    if (state.mixer && delta && Number.isFinite(delta)) state.mixer.update(delta);
  }

  function stopAllClipActions() {
    if (state.mixer) state.mixer.stopAllAction();
  }

  // when retargeted clips with a hips position track are playing, set this so
  // the pose sanitizer preserves clip root motion instead of restoring rest
  function setClipRootMotion(v) { state.clipRootMotion = !!v; }

  // ── POSE SANITIZER — procedural layers only touch rotations ──────────
  // Captures the normalized rig's rest pose at attach. Every frame after the
  // host's procedural posing: position/scale drift on body bones is restored
  // to rest. Rotation edits are never touched. hips position is restored too
  // (procedural bounce must be rotation-based) UNLESS clip root motion is on.
  let rigRest = null;   // lowercase boneName → { position, scale }
  function captureRigRest() {
    rigRest = null;
    const rig = state.vrm && state.vrm.humanoid && state.vrm.humanoid.normalizedHumanBones;
    if (!rig) return;
    rigRest = {};
    for (const [name, bone] of Object.entries(rig)) {
      if (!bone || !bone.node || !bone.node.position || !bone.node.scale) continue;
      rigRest[name.toLowerCase()] = {
        position: bone.node.position.clone(),
        scale: bone.node.scale.clone(),
      };
    }
    log('rig rest pose captured', `bones=${Object.keys(rigRest).length}`);
  }

  function sanitizeProceduralPose() {
    const rig = state.vrm && state.vrm.humanoid && state.vrm.humanoid.normalizedHumanBones;
    if (!rig || !rigRest) return;
    for (const [name, bone] of Object.entries(rig)) {
      if (!bone || !bone.node) continue;
      const key = name.toLowerCase();
      const rest = rigRest[key];
      const node = bone.node;
      if (!rest || !node.position || !node.scale) continue;
      // hips position is the ONE legal translation channel (clip root motion);
      // every child body bone must never translate or scale — restore rest
      if (key !== 'hips' || !state.clipRootMotion) {
        const p = node.position, r = rest.position;
        if (p.x !== r.x || p.y !== r.y || p.z !== r.z) node.position.copy(r);
      }
      const s = node.scale, rs = rest.scale;
      if (s.x !== rs.x || s.y !== rs.y || s.z !== rs.z) node.scale.copy(rs);
    }
  }

  // ── 2c. HANDS & FINGERS — smooth, clamped, rest-relative curl ───────
  // Fingers get: (1) rest-relative curl targets in FLEXION space, (2) slerp
  // damping toward targets (no snapping), (3) per-joint clamps so joints can
  // never hyperextend backward or twist unnaturally.
  const FINGER_SETS = ['thumb', 'index', 'middle', 'ring', 'little'];
  // per-joint limits in radians, in flexion space (VRM normalized rig: fingers
  // curl around +Z for left hand, mirrored −Z for right; 0 = straight).
  const FINGER_LIMITS = {
    thumb:  { proximal: [0, 0.8], intermediate: [0, 0.9], distal: [0, 0.8] },
    index:  { proximal: [0, 1.5], intermediate: [0, 1.4], distal: [0, 0.9] },
    middle: { proximal: [0, 1.5], intermediate: [0, 1.4], distal: [0, 0.9] },
    ring:   { proximal: [0, 1.4], intermediate: [0, 1.3], distal: [0, 0.8] },
    little: { proximal: [0, 1.2], intermediate: [0, 1.1], distal: [0, 0.7] },
  };
  const HAND_POSES = {
    open:     { thumb: 0.05, index: 0.02, middle: 0.02, ring: 0.02, little: 0.02 },
    relaxed:  { thumb: 0.30, index: 0.38, middle: 0.42, ring: 0.45, little: 0.40 },   // natural resting curl
    fist:     { thumb: 0.85, index: 0.98, middle: 1.0, ring: 0.98, little: 0.90 },
    point:    { thumb: 0.35, index: 0.05, middle: 0.85, ring: 0.95, little: 0.90 },
    wave:     { thumb: 0.15, index: 0.10, middle: 0.12, ring: 0.12, little: 0.10 },   // fingers spread, loose
    heart:    { thumb: 0.55, index: 0.55, middle: 0.75, ring: 0.95, little: 0.95 },
  };

  // target = { pose: 'relaxed', spread: 0 } — eased internally per joint
  state.fingers = { pose: 'relaxed', spread: 0 };
  state.fingerCur = {};   // 'left.index.proximal' → current flexion 0..1

  function fingerNodes(hand, finger) {
    const H = state.vrm && state.vrm.humanoid;
    if (!H) return [];
    // VRM 1.0 canonical names are camelCase: leftIndexProximal, rightThumbMetacarpal, …
    const caps = finger.charAt(0).toUpperCase() + finger.slice(1);
    const names = [`${hand}${caps}Proximal`, `${hand}${caps}Intermediate`, `${hand}${caps}Distal`];
    if (finger === 'thumb') names[0] = `${hand}ThumbMetacarpal`;   // VRoid alias for the thumb root
    const nodes = [];
    for (const n of names) {
      const node = H.getNormalizedBoneNode ? H.getNormalizedBoneNode(n)
        : (state.vrm.humanoid.normalizedHumanBones[n] || {}).node;
      if (node) nodes.push(node);
    }
    return nodes;
  }

  // clamp flexion into the safe range and convert to local-space rotation
  function applyFingerJoint(node, side, finger, jointIdx, flexion) {
    const fingerLimits = FINGER_LIMITS[finger];
    const joint = ['proximal', 'intermediate', 'distal'][jointIdx];
    const [min, max] = fingerLimits[joint];
    const f = Math.max(min, Math.min(max, flexion));   // no backward bending
    // flexion space → local rotation: curl around the hand's Z axis
    const z = side === 'left' ? f : -f;
    node.rotation.x = 0;
    node.rotation.y = 0;
    node.rotation.z = z;
  }

  // call once per frame AFTER arm posing; dampens toward state.fingers targets
  function updateFingers(delta) {
    if (!state.vrm || !state.vrm.humanoid) return;
    const pose = HAND_POSES[state.fingers.pose] || HAND_POSES.relaxed;
    const dampK = 1 - Math.exp(-delta * 8);   // exp smoothing ≈ continuous slerp for single-axis curls (~190ms transition)
    for (const hand of ['left', 'right']) {
      for (const finger of FINGER_SETS) {
        const nodes = fingerNodes(hand, finger);
        for (let j = 0; j < nodes.length; j++) {
          const key = `${hand}.${finger}.${j}`;
          // distal joints mirror their parent at reduced amplitude (real curl)
          const taper = [1, 0.85, 0.7][j] || 0.7;
          const spreadBoost = state.fingers.spread * (1 - j * 0.25);
          const target = Math.max(0, (pose[finger] || 0.4) * taper - spreadBoost);
          const cur = state.fingerCur[key] || 0;
          const next = cur + (target - cur) * dampK;
          state.fingerCur[key] = next;
          applyFingerJoint(nodes[j], hand, finger, j, next);
        }
      }
    }
  }

  function setHandTargets(poseName, opts = {}) {
    if (HAND_POSES[poseName]) state.fingers.pose = poseName;
    if (opts.spread !== undefined) state.fingers.spread = Math.max(0, Math.min(1, opts.spread));
  }

  // clamp + smooth WRIST rotations too (hands contort when arms layers fight)
  function clampHandWrists() {
    const H = state.vrm && state.vrm.humanoid;
    if (!H) return;
    for (const side of ['left', 'right']) {
      const node = H.getNormalizedBoneNode ? H.getNormalizedBoneNode(`${side}Hand`) : null;
      if (!node) continue;
      node.rotation.x = THREE.MathUtils.clamp(node.rotation.x, -0.6, 0.6);
      node.rotation.y = THREE.MathUtils.clamp(node.rotation.y, -0.5, 0.5);
      node.rotation.z = THREE.MathUtils.clamp(node.rotation.z, -0.9, 0.9);
    }
  }

  // ── 2d. CLIP PLAYBACK — cross-faded transitions, never abrupt ──────
  // playClip(clip) / playClip(clip, { fade: 0.35 }) — switching clips (or
  // returning to procedural-only) cross-fades instead of snapping.
  function playClip(clip, opts = {}) {
    if (!state.mixer) createMixer();
    if (!state.mixer) { log('playClip: no mixer', ''); return null; }
    const fade = opts.fade !== undefined ? opts.fade : 0.35;
    const nextAction = state.mixer.clipAction(clip);
    nextAction.reset();
    nextAction.setLoop(opts.loop !== undefined ? opts.loop : THREE.LoopRepeat, Infinity);
    nextAction.clampWhenFinished = !!opts.clampWhenFinished;
    nextAction.enabled = true;
    nextAction.setEffectiveWeight(1);
    const prev = state.currentAction;
    if (prev && prev !== nextAction && fade > 0) {
      nextAction.play();
      nextAction.crossFadeFrom(prev, fade, true);   // warp = sync clip phases
    } else {
      nextAction.play();
    }
    state.currentAction = nextAction;
    if (clip.tracks.some((t) => t.name === 'hips.position')) setClipRootMotion(true);
    log('clip playing (cross-faded)', `${clip.name || 'unnamed'} fade=${fade}s`);
    return nextAction;
  }

  // fade out all clip motion back to the procedural idle
  function stopClips(fade = 0.35) {
    if (!state.mixer || !state.currentAction) return;
    state.currentAction.fadeOut(fade);
    const action = state.currentAction;
    setTimeout(() => { try { action.stop(); } catch (e) { /* mixer gone */ } }, fade * 1000 + 50);
    state.currentAction = null;
    setClipRootMotion(false);
    log('clips fading out to procedural idle', `fade=${fade}s`);
  }

  // ── 3. PROCEDURAL IDLE: BREATHING + SWAY ───────────────────────
  function updateBreathing(delta) {
    const vrm = state.vrm;
    if (!vrm || !vrm.humanoid) return;
    const H = vrm.humanoid;
    const get = (n) => H.getNormalizedBoneNode(n);

    // breathe faster while speaking (up to ~2.6x base rate)
    const e = state.energy;
    state.breathT += delta * (0.21 + 0.12 * e + (state.speaking ? 0.12 : 0));
    const t = state.breathT;
    const breathe = Math.sin(t);
    const sway = Math.sin(t * 0.5 + 1.3);          // slower secondary sway

    const spine = get('spine'), chest = get('chest'), neck = get('neck'), head = get('head');
    // subtle ADDITIVE layer on whatever the host wrote this frame — hosts with
    // their own breathing engine set breathScale < 1 so the layers compose
    const s = state.breathScale;
    if (spine) {
      spine.rotation.x += breathe * 0.014 * (0.6 + 0.8 * e) * s;
      spine.rotation.z += sway * 0.006 * e * s;
    }
    if (chest) {
      chest.rotation.x += breathe * 0.011 * (0.6 + 0.8 * e) * s;
      chest.rotation.z += noise1(state.time * 0.09, 7) * 0.012 * (0.5 + 0.5 * e) * s;
    }
    if (neck) {
      neck.rotation.x += Math.sin(t + 0.7) * 0.004 * e * s;   // head rides the breath
      neck.rotation.z += noise1(state.time * 0.13, 3) * 0.005 * e * s;
    }
    if (head) {
      head.rotation.x += Math.sin(t + 1.1) * 0.003 * e * s;
      head.rotation.z += noise1(state.time * 0.11, 5) * 0.004 * e * s;
    }
  }

  // ── 4. LOOKAT — smooth camera/cursor tracking ──────────────────
  function setLookAtTarget(obj) { state.lookAtTarget = obj || null; }

  function updateLookAt(delta) {
    const vrm = state.vrm;
    if (!vrm) return;
    // wire the built-in VRM lookAt applier to the target (eyes follow exactly)
    if (vrm.lookAt && state.lookAtTarget) {
      if (vrm.lookAt.target !== state.lookAtTarget) vrm.lookAt.target = state.lookAtTarget;
    }

    // procedural head aim: spring-damped yaw/pitch toward the target + cursor
    const v = state.vrm;
    const headNode = v && v.humanoid && v.humanoid.getNormalizedBoneNode('head');
    if (!headNode || !state.lookAtTarget) return;

    const cam = state.camera;
    // cursor "weight" fades a few seconds after the mouse stops moving
    const now = state.time;
    const cursorWanted = now - state.cursor.lastMoveAt < 2.6 && cam ? 1 : 0;
    state.cursor.influence += (cursorWanted - state.cursor.influence) * (1 - Math.exp(-delta * 2.5));

    const hp = headNode.getWorldPosition(animator._v1);
    const tp = state.lookAtTarget.getWorldPosition(animator._v2);
    const dir = animator._v3.subVectors(tp, hp);
    const yaw = Math.atan2(dir.x, dir.z);
    const pitch = -Math.atan2(dir.y, Math.hypot(dir.x, dir.z));
    // cursor adds a gentle extra pull (±~9°) on top of aiming at the target
    const tYaw = clamp(yaw, -0.8, 0.8) + state.cursor.x * 0.16 * state.cursor.influence;
    const tPitch = clamp(pitch, -0.45, 0.45) - state.cursor.y * 0.10 * state.cursor.influence;

    // spring-damped: slightly underdamped so turns carry a hint of overshoot
    const k = 60, c = 13;
    const hv = state.headVel, ha = state.headAim;
    hv.yaw += ((tYaw - ha.yaw) * k - hv.yaw * c) * delta;
    ha.yaw += hv.yaw * delta;
    hv.pitch += ((tPitch - ha.pitch) - hv.pitch * (c / k)) * k * delta;
    ha.pitch += hv.pitch * delta;

    // split between neck and head so the motion reads natural, not owl-like
    const neck = v.humanoid.getNormalizedBoneNode('neck');
    if (neck) {
      neck.rotation.y += ha.yaw * 0.35;
      neck.rotation.x += ha.pitch * 0.35;
    }
    if (headNode) {
      headNode.rotation.y += ha.yaw * 0.65;
      headNode.rotation.x += ha.pitch * 0.65;
    }
  }

  // ── 5. AUTO-BLINK TIMER (3–5 s, natural double-blinks) ─────────
  function updateBlinking(delta) {
    const vrm = state.vrm;
    if (!vrm) return;
    const now = state.time;

    if (state.blinkPhase < 0 && now >= state.nextBlinkAt) {
      state.blinkPhase = 0;
      // 15% chance of an immediate second blink (the human tell)
      state.nextBlinkAt = now +
        (Math.random() < 0.15
          ? 0.18
          : state.blinkInterval[0] + Math.random() * (state.blinkInterval[1] - state.blinkInterval[0]));
    }
    if (state.blinkPhase >= 0) {
      state.blinkPhase += delta / 0.16;              // ~160ms blink
      const p = Math.min(state.blinkPhase, 1);
      state.blinkW = p < 0.4 ? p / 0.4 : (1 - p) / 0.6;
      if (state.blinkPhase >= 1) { state.blinkPhase = -1; state.blinkW = 0; }
    }

    // weight can be raised externally (e.g. sleepy) before we write it
    if (state.blinkW > 0) setExpression('blink', Math.min(1, state.blinkW), { instant: true });
  }

  // ── 6. EXPRESSION MANAGER ──────────────────────────────────────
  // VRoid raw morph → VRM 1.0 preset. Morphs bound to a declared preset are
  // OWNED by the expression manager (three-vrm clears + re-applies them every
  // vrm.update()), so raw morphTargetInfluences writes to them are wiped each
  // frame — writes must be routed through the preset weight to stick.
  const RAW_TO_PRESET = {
    'Fcl_EYE_Close': 'blink', 'Fcl_EYE_Close_L': 'blinkLeft', 'Fcl_EYE_Close_R': 'blinkRight',
    'Fcl_ALL_Joy': 'happy', 'Fcl_ALL_Angry': 'angry', 'Fcl_ALL_Sorrow': 'sad',
    'Fcl_ALL_Fun': 'relaxed', 'Fcl_ALL_Surprised': 'surprised',
    'Fcl_MTH_A': 'aa', 'Fcl_MTH_I': 'ih', 'Fcl_MTH_U': 'ou', 'Fcl_MTH_E': 'ee', 'Fcl_MTH_O': 'oh'
  };
  // setExpression('happy', 0.8)        → eased over ~120ms, permanent until changed
  // setExpression('happy', 0, {fade})  → fades out
  // setExpression('blink', w, {instant:true}) is used by the blink timer
  function setExpression(name, weight, opts = {}) {
    const vrm = state.vrm;
    if (!vrm) return false;
    weight = clamp01(weight);

    // VRM presets win when the model declares them; else raw morph fallback
    const em = vrm.expressionManager;
    const viaManager = em && (em.getExpression
      ? em.getExpression(name)
      : (em.expressionMap && em.expressionMap[name]));
    if (viaManager) {
      if (opts.instant) { em.setValue(name, weight); return true; }
      state.targets[name] = weight;                  // eased in update()
      return true;
    }
    // raw morph-target fallback (VRoid-style names live on the face mesh)
    return setMorphWeight(vrm, name, weight, opts.instant);
  }

  // fire-and-forget flash (surprise on errors, etc.)
  function flashExpression(name, seconds = 1.2) {
    setExpression(name, 1);
    setTimeout(() => { if (state.targets[name] === undefined) return; setExpression(name, 0); },
      seconds * 1000);
  }

  // ── 7. VISEME / LIP-SYNC CONTROLLER ────────────────────────────
  // driveVisemes('aa', 0.9) sets the target; update() lerps toward it so the
  // mouth glides between shapes instead of snapping. All other visemes ease out.
  function driveVisemes(phoneme, value = 1) {
    for (const k of Object.keys(state.visemes)) {
      state.visemes[k] = (k === phoneme) ? clamp01(value) : 0;
    }
    // fire-and-forget callers (gesture mouths, yawns) stop calling when their
    // animation ends — targets expire so the mouth never sticks open
    state.visemeHoldUntil = state.time + 0.25;
  }

  // gate mode for hosts that know only "mouth open right now" (TTS word
  // boundaries). While open, a random viseme pulses at syllable rhythm; while
  // closed all visemes ease shut. Call driveVisemes() yourself instead if you
  // have real phoneme data — the gate only runs while nothing else drives lips.
  let gateHeld = false;
  let nextGateVisemeAt = 0;
  function setVisemeGate(open) {
    gateHeld = !!open;
    if (!open) driveVisemes(null, 0);
  }
  function updateVisemeGate() {
    if (!gateHeld || state.visemes.aa || state.visemes.ih || state.visemes.ou || state.visemes.ee || state.visemes.oh) return;
    if (state.time < nextGateVisemeAt) return;
    nextGateVisemeAt = state.time + 0.07 + Math.random() * 0.07;
    const vis = ['aa', 'ih', 'ou', 'ee', 'oh'];
    driveVisemes(vis[Math.floor(Math.random() * vis.length)], 0.45 + Math.random() * 0.55);
  }

  // fire a mood flash with no single VRM preset (laughing, smug, wink, …).
  // Composes additively with preset expressions; clears after `seconds`.
  function flashFace(name, seconds = 1.6) {
    const set = FACE_PRESETS[name];
    if (!set) { flashExpression(name, seconds); return; }
    state.flashName = name;
    for (const morph of Object.keys(set)) flashMorphs[morph] = state.time + seconds;
  }

  // text-driven fallback for engines without phoneme events: pulses plausible
  // visemes from the actual characters being "spoken"
  function speakText(text) {
    const vis = ['aa', 'ih', 'ou', 'ee', 'oh'];
    const map = { a: 'aa', e: 'ee', i: 'ih', o: 'oh', u: 'ou' };
    let i = 0;
    const step = () => {
      if (i >= text.length) { driveVisemes(null, 0); return; }
      const ch = text[i++].toLowerCase();
      driveVisemes(map[ch] || vis[Math.floor(Math.random() * vis.length)], 0.4 + Math.random() * 0.5);
      setTimeout(step, 90 + Math.random() * 90);
    };
    step();
  }

  function setMorphWeight(vrm, name, weight, instant) {
    // 1) raw VRoid name bound to a preset → write the preset weight (sticks)
    const em = vrm.expressionManager;
    const preset = RAW_TO_PRESET[name];
    if (preset && em && em.getExpression && em.getExpression(preset)) {
      em.setValue(preset, clamp01(weight));
      return true;
    }
    // 2) name IS a declared expression → write it directly
    if (em && em.expressionMap && em.expressionMap[name]) {
      em.setValue(name, weight);
      return true;
    }
    // 3) unbound morph → safe to write influences directly (persists)
    let wrote = false;
    vrm.scene.traverse((o) => {
      if (!o.isMesh || !o.morphTargetDictionary) return;
      const idx = o.morphTargetDictionary[name];
      if (idx !== undefined && o.morphTargetInfluences) {
        o.morphTargetInfluences[idx] = weight;
        wrote = true;
      }
    });
    return wrote;
  }

  // ── per-frame easing + writes ──────────────────────────────────
  function updateExpressions(delta) {
    const vrm = state.vrm;
    if (!vrm) return;
    const em = vrm.expressionManager;
    const k = 1 - Math.exp(-delta * 9);
    for (const name of Object.keys(state.targets)) {
      const cur = state.current[name] || 0;
      const tgt = state.targets[name];
      const next = cur + (tgt - cur) * k;
      state.current[name] = next;
      if (em && (em.getExpression ? em.getExpression(name) : em.expressionMap && em.expressionMap[name])) {
        em.setValue(name, next);
      } else {
        setMorphWeight(vrm, name, next);
      }
      // settle: drop fully-settled zero targets from the map
      if (Math.abs(next - tgt) < 0.001 && tgt === 0) {
        delete state.targets[name];
        state.current[name] = 0;
        if (em) em.setValue(name, 0);
      }
    }

    // raw-morph flashes: hold, then ease back out
    for (const name of Object.keys(flashMorphs)) {
      if (state.time > flashMorphs[name]) {
        delete flashMorphs[name];
        setMorphWeight(vrm, name, 0);
        continue;
      }
      setMorphWeight(vrm, name, FACE_PRESETS[state.flashName] && FACE_PRESETS[state.flashName][name] || 0);
    }

    // visemes: ease toward driveVisemes()/setVisemeGate() targets — smooth TTS sync.
    // Targets older than the 250ms hold window decay shut (fire-and-forget safety).
    if (state.time > (state.visemeHoldUntil || 0)) {
      for (const k of Object.keys(state.visemes)) state.visemes[k] = 0;
    }
    for (const [name, tgt] of Object.entries(state.visemes)) {
      const cur = state.visemeCur && state.visemeCur[name] || 0;
      const next = cur + (tgt - cur) * (1 - Math.exp(-delta * 14));
      if (!state.visemeCur) state.visemeCur = {};
      state.visemeCur[name] = next;
      if (next > 0.01) setMorphWeight(vrm, name, next);
      else if (cur > 0.01) setMorphWeight(vrm, name, 0);
    }
  }

  // ── housekeeping ───────────────────────────────────────────────
  function log(msg, detail) {
    try { (window.__vlog || console.log)('[animator] ' + msg, detail || ''); } catch (e) { /* noop */ }
  }

  function attach(vrm, camera) {
    state.vrm = vrm;
    if (camera) state.camera = camera;
    // fresh start — a rebooted avatar must not inherit the old face state
    state.targets = {}; state.current = {}; state.visemeCur = {}; state.flashName = null;
    flashMorphs = {};
    state.time = 0;
    state.nextBlinkAt = 1.5 + Math.random() * 2.5;
    state.blinkPhase = -1; state.blinkW = 0;
    state.cursor.influence = 0; state.cursor.lastMoveAt = -1e9;
    state.headAim.yaw = state.headAim.pitch = state.headAim.roll = 0;
    state.headVel.yaw = state.headVel.pitch = state.headVel.roll = 0;
    state.mixer = null; state.mixerRoot = null; state.clipRootMotion = false;
    state.currentAction = null;
    state.fingers = { pose: 'relaxed', spread: 0 };
    state.fingerCur = {};
    applyRenderFixes(vrm);
    captureRigRest();
    log('attached', `expressions=${vrm.expressionManager ? Object.keys(vrm.expressionManager.expressionMap || {}).length : 0}`);
  }

  function detach() {
    state.vrm = null;
    state.targets = {};
    state.current = {};
    state.visemeCur = {};
    if (state.mixer) { try { state.mixer.stopAllAction(); } catch (e) { /* disposed */ } }
    state.mixer = null; state.mixerRoot = null; state.clipRootMotion = false;
    rigRest = null;
  }

  // main per-frame entry — call AFTER your bone posing, BEFORE vrm.update(delta)
  // so expression weights land in the same frame's vrm.update() application.
  function update(delta) {
    if (!state.vrm || !delta || !Number.isFinite(delta)) return;
    delta = Math.min(delta, 0.05);                   // tab-back frame spikes
    state.time += delta;
    updateVisemeGate();
    sanitizeProceduralPose();   // restore any position/scale drift on body bones
    if (state.autonomous) {                          // bone layers — hosts with their
      updateBreathing(delta);                        // own engine set autonomous=false
      updateLookAt(delta);
      updateBlinking(delta);
    }
    clampHandWrists();          // wrists can't contort no matter who posed them
    updateFingers(delta);       // clamped, damped finger curls
    updateExpressions(delta);
  }

  const animator = {
    attach, detach, update,
    setExpression, flashExpression, driveVisemes, speakText,
    setVisemeGate, flashFace,
    retargetClips, sanitizeAnimationTracks, createMixer, updateMixer,
    stopAllClipActions, setClipRootMotion, applyRenderFixes,
    playClip, stopClips, setHandTargets,
    setLookAtTarget,
    setMorph: (name, weight) => state.vrm ? setMorphWeight(state.vrm, name, weight, true) : false,
    setAutonomous(v) { state.autonomous = !!v; },
    setBreathScale(v) { state.breathScale = Math.max(0, Math.min(1, v)); },
    setCamera(cam) { state.camera = cam; },
    setEnergy(v) { state.energy = clamp01(v); },
    setSpeaking(v) { state.speaking = !!v; },
    get time() { return state.time; },
    // internals exposed for the host page's richer emotion engine
    _state: state,
    _v1: new THREE.Vector3(), _v2: new THREE.Vector3(), _v3: new THREE.Vector3()
  };
  return animator;
}
