import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { VRMLoaderPlugin, VRMUtils } from '@pixiv/three-vrm';

window.__vlog('showcase module loaded');

// ════════════════════════════════════════════════════════════════
//  RENDERER / SCENE / CAMERA
// ════════════════════════════════════════════════════════════════
const canvas = document.getElementById('c');
const stateChip = document.getElementById('state-chip');
const fpsChip = document.getElementById('fps-chip');
const noteEl = document.getElementById('fallback-note');

const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
renderer.outputColorSpace = THREE.SRGBColorSpace;

const scene = new THREE.Scene();

const camera = new THREE.PerspectiveCamera(24, 1, 0.1, 20);   // long lens = flattering portrait shot
const camFocus = new THREE.Vector3(0, 1.31, 0);
camera.position.set(0, 1.36, 2.05);
camera.lookAt(camFocus);

// ── vibrant three-point anime lighting ──
scene.add(new THREE.HemisphereLight(0xfff1ea, 0x584a78, 0.85));
const keyLight = new THREE.DirectionalLight(0xffffff, 1.35);
keyLight.position.set(0.7, 1.9, 1.7);
scene.add(keyLight);
const fillLight = new THREE.DirectionalLight(0xb39cff, 0.5);   // violet fill for richness
fillLight.position.set(-1.4, 0.9, 0.9);
scene.add(fillLight);
const rimLight = new THREE.DirectionalLight(0xffb37a, 1.15);   // warm rim pops her off the bg
rimLight.position.set(-0.5, 1.7, -1.6);
scene.add(rimLight);

// soft glow disc under her (pure shader — no textures to break)
const disc = new THREE.Mesh(
  new THREE.CircleGeometry(0.62, 48),
  new THREE.ShaderMaterial({
    transparent: true, depthWrite: false,
    vertexShader: 'varying vec2 vUv; void main(){ vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }',
    fragmentShader: 'varying vec2 vUv; void main(){ float d = length(vUv - 0.5) * 2.0; float a = smoothstep(1.0, 0.0, d) * 0.5; gl_FragColor = vec4(0.72, 0.55, 1.0, a); }',
  })
);
disc.rotation.x = -Math.PI / 2;
disc.position.y = 0.012;
scene.add(disc);

// sparkle particles drifting around her (vibrant stage feel)
const SPARKS = 90;
const sparkGeo = new THREE.BufferGeometry();
{
  const pos = new Float32Array(SPARKS * 3), seed = new Float32Array(SPARKS);
  for (let i = 0; i < SPARKS; i++) {
    const r = 1.1 + Math.random() * 1.6, a = Math.random() * Math.PI * 2;
    pos[i * 3] = Math.cos(a) * r;
    pos[i * 3 + 1] = 0.2 + Math.random() * 2.1;
    pos[i * 3 + 2] = Math.sin(a) * r;
    seed[i] = Math.random() * 100;
  }
  sparkGeo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
  sparkGeo.setAttribute('seed', new THREE.BufferAttribute(seed, 1));
}
const sparkMat = new THREE.ShaderMaterial({
  transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
  uniforms: { uTime: { value: 0 } },
  vertexShader: `
    attribute float seed; varying float vA; uniform float uTime;
    void main(){
      vec3 p = position;
      p.y += sin(uTime * 0.55 + seed) * 0.22;
      p.x += sin(uTime * 0.32 + seed * 1.7) * 0.1;
      vec4 mv = modelViewMatrix * vec4(p, 1.0);
      gl_PointSize = (2.4 + fract(seed) * 3.0) * (140.0 / -mv.z);
      vA = 0.35 + 0.45 * sin(uTime * (0.9 + fract(seed)) + seed * 3.0);
      gl_Position = projectionMatrix * mv;
    }`,
  fragmentShader: `
    varying float vA;
    void main(){
      vec2 c = gl_PointCoord - 0.5;
      float m = smoothstep(0.5, 0.05, length(c));
      gl_FragColor = vec4(0.85, 0.75, 1.0, m * vA);
    }`,
});
const sparks = new THREE.Points(sparkGeo, sparkMat);
scene.add(sparks);

// eye-contact target
const gazeTarget = new THREE.Object3D();
gazeTarget.position.copy(camera.position);
scene.add(gazeTarget);

function resize() {
  const w = window.innerWidth, h = window.innerHeight;
  renderer.setSize(w, h, false);
  camera.aspect = w / h;
  camera.updateProjectionMatrix();
}
window.addEventListener('resize', resize);
resize();

// manual strategy override: ?strategy=live | repair | statue
const qs = new URLSearchParams(location.search);
const forcedStrategy = qs.get('strategy') || '';

// ════════════════════════════════════════════════════════════════
//  MODEL LOAD + SELF-VERIFYING SKINNING STRATEGIES
//  Evidence from client_errors.log: with the inverse-bind "repair"
//  applied, the GPU draws 57k tris but 0.00% of pixels are opaque
//  (GPU skinning is broken on some drivers); the same geometry baked
//  as a static statue rendered 30% of the screen. So: try the model
//  EXACTLY as loaded first, verify with a pixel readback, and only
//  escalate to repair/statue when the previous strategy proves dead.
// ════════════════════════════════════════════════════════════════
let vrm = null;
let expressionManager = null;
let faceMeshes = [];
let statueMode = false;
let strategy = 'loading';          // live | repair | statue
let strategyLocked = false;
let probeFailures = 0;

let headNode = null, neckNode = null, chestNode = null, spineNode = null, hipsNode = null;
let lUp = null, rUp = null, lLo = null, rLo = null, lHand = null, rHand = null;
let lSh = null, rSh = null;

function setNote(text, bad) {
  if (!noteEl) return;
  noteEl.textContent = text;
  noteEl.style.display = text ? 'block' : 'none';
  noteEl.style.borderColor = bad ? 'rgba(255, 170, 120, 0.55)' : 'rgba(178, 146, 255, 0.32)';
  noteEl.style.color = bad ? '#ffd9b8' : '#cfc2f5';
}

// ── pixel probe: render and count strongly-opaque pixels ──
// alpha > 200 excludes the glow disc (a≈0.5) and additive sparks, so only
// the solid model body counts. The disc/sparks are hidden during the probe.
let probeBuf = null;
function probeVisible() {
  if (!vrm) return 0;
  const gl = renderer.getContext();
  const w = gl.drawingBufferWidth, h = gl.drawingBufferHeight;
  if (!w || !h) return 0;
  const sparksWas = sparks.visible, discWas = disc.visible;
  sparks.visible = false; disc.visible = false;
  vrm.scene.updateMatrixWorld(true);
  renderer.render(scene, camera);
  const n = w * h * 4;
  if (!probeBuf || probeBuf.length !== n) probeBuf = new Uint8Array(n);
  gl.readPixels(0, 0, w, h, gl.RGBA, gl.UNSIGNED_BYTE, probeBuf);
  sparks.visible = sparksWas; disc.visible = discWas;
  let opaque = 0;
  for (let i = 3; i < n; i += 4) if (probeBuf[i] > 200) opaque++;
  return opaque / (w * h);
}

// ── strategy B: the inverse-bind rebuild from the chat UI (helps some
//    machines, breaks others — only used if the untouched model fails) ──
function applySkinningRepair() {
  try { VRMUtils.removeUnnecessaryVertices(vrm.scene); } catch (e) { window.__vlog('rmv-vertices failed', e && e.message); }
  try { VRMUtils.combineSkeletons(vrm.scene); } catch (e) { window.__vlog('combineSkeletons failed', e && e.message); }
  vrm.scene.updateMatrixWorld(true);
  let repaired = 0;
  vrm.scene.traverse((obj) => {
    if (!obj.isSkinnedMesh || !obj.skeleton) return;
    const sk = obj.skeleton;
    if (!sk.boneInverses || sk.boneInverses.length !== sk.bones.length) {
      sk.boneInverses = sk.bones.map(() => new THREE.Matrix4());
    }
    for (let i = 0; i < sk.bones.length; i++) {
      if (sk.bones[i]) sk.boneInverses[i].copy(sk.bones[i].matrixWorld).invert();
    }
    if (obj.geometry && obj.geometry.attributes.skinWeight) obj.normalizeSkinWeights();
    obj.bindMode = 'attached';
    obj.frustumCulled = false;
    repaired++;
  });
  window.__vlog('skinning repair applied', `meshes=${repaired}`);
}

// ── strategy C: bake a static statue — guaranteed raster on any GPU.
//    Cloned geometry keeps morph targets, so blinks/visemes/expressions
//    still animate even in statue mode. ──
function bakeStatue() {
  vrm.scene.updateMatrixWorld(true);
  const skinned = [];
  vrm.scene.traverse((o) => { if (o.isSkinnedMesh && o.skeleton) skinned.push(o); });
  let frozen = 0;
  for (const o of skinned) {
    const baked = new THREE.Mesh(o.geometry.clone(), o.material);
    baked.applyMatrix4(o.matrixWorld);
    baked.frustumCulled = false;
    baked.name = (o.name || 'mesh') + '_statue';
    vrm.scene.add(baked);
    o.visible = false;
    frozen++;
  }
  statueMode = true;
  collectFaceMeshes();
  window.__vlog('statue baked', `frozen=${frozen}`);
  return frozen;
}

function collectFaceMeshes() {
  faceMeshes = [];
  vrm.scene.traverse((obj) => {
    if (obj.isMesh && obj.visible && obj.morphTargetDictionary && Object.keys(obj.morphTargetDictionary).length) {
      faceMeshes.push(obj);
    }
  });
}

function adoptStrategy(name) {
  strategy = name;
  strategyLocked = true;
  probeFailures = 0;
  const label = name === 'live' ? 'GPU-skinned model'
    : name === 'repair' ? 'model (repaired skinning)'
    : 'static-pose fallback (face still animates)';
  setNote('Showing: ' + label + ' — verified by pixel check', name === 'statue');
  window.__vlog('strategy adopted', name);
  stateChip.textContent = 'ready';
}

const loader = new GLTFLoader();
loader.register((parser) => new VRMLoaderPlugin(parser));

stateChip.textContent = 'summoning ella…';
loader.load(
  '/model/ella.vrm?v=4',
  (gltf) => {
    vrm = gltf.userData.vrm;
    if (!vrm) { window.__vlog('VRM PLUGIN MISSING', 'gltf.userData.vrm undefined'); stateChip.textContent = 'avatar failed to load'; return; }
    scene.add(vrm.scene);

    expressionManager = vrm.expressionManager || null;
    const names = expressionManager && expressionManager.expressionMap ? Object.keys(expressionManager.expressionMap) : [];
    window.__vlog('morph probe', `${names.length} expressions`);
    collectFaceMeshes();

    if (vrm.lookAt) vrm.lookAt.target = gazeTarget;

    const H = vrm.humanoid;
    const node = (n) => (H ? H.getNormalizedBoneNode(n) : null);
    headNode = node('head'); neckNode = node('neck'); chestNode = node('chest');
    spineNode = node('spine'); hipsNode = node('hips');
    lUp = node('leftUpperArm'); rUp = node('rightUpperArm');
    lLo = node('leftLowerArm'); rLo = node('rightLowerArm');
    lHand = node('leftHand'); rHand = node('rightHand');
    lSh = node('leftShoulder'); rSh = node('rightShoulder');

    // frame on the head — frontal upper-body portrait
    camFocus.set(0, 1.31, 0);
    if (headNode) {
      vrm.scene.updateMatrixWorld(true);
      const hp = headNode.getWorldPosition(new THREE.Vector3());
      camFocus.y = hp.y - 0.06;
    }
    camera.position.set(0, camFocus.y + 0.05, 2.05);
    camera.lookAt(camFocus);
    gazeTarget.position.copy(camera.position);

    applyCelBoost();

    // ── strategy selection ──
    if (forcedStrategy === 'statue') { bakeStatue(); adoptStrategy('statue'); return; }
    if (forcedStrategy === 'repair') { applySkinningRepair(); collectFaceMeshes(); adoptStrategy('repair'); return; }
    if (forcedStrategy === 'live') { adoptStrategy('live'); return; }
    // default: trust the loader output first; probe decides, escalate if dead
    strategy = 'live';
    probeAt = performance.now() + 1500;
    window.__vlog('probe scheduled', 'strategy=live at +1.5s');
  },
  undefined,
  (err) => {
    console.error('VRM load failed:', err);
    window.__vlog('VRM LOAD FAILED', (err && err.message) || String(err));
    stateChip.textContent = 'avatar failed to load';
  }
);

// ── probe scheduler: verify the current strategy actually rasters ──
let probeAt = 0;
function runProbe(now) {
  if (!probeAt || now < probeAt || !vrm) return;
  probeAt = 0;
  const frac = probeVisible();
  window.__vlog('visibility probe', `strategy=${strategy} opaque=${(frac * 100).toFixed(2)}%`);
  if (frac > 0.02) { adoptStrategy(strategy); return; }        // something solid is on screen
  probeFailures++;
  if (probeFailures < 2) { probeAt = now + 900; return; }      // textures may still be landing — retry once
  if (strategyLocked) { setNote('Model is not rendering — probe found no solid pixels', true); return; }

  if (strategy === 'live') {
    window.__vlog('strategy live FAILED', 'escalating to inverse-bind repair');
    stateChip.textContent = 'repairing skinning…';
    applySkinningRepair();
    collectFaceMeshes();
    strategy = 'repair';
    probeFailures = 0;
    probeAt = performance.now() + 1200;
  } else if (strategy === 'repair') {
    window.__vlog('strategy repair FAILED', 'falling back to baked statue');
    stateChip.textContent = 'using fallback…';
    bakeStatue();
    probeAt = performance.now() + 800;
  } else {
    strategy = 'statue';
    adoptStrategy('statue');
  }
}

// ════════════════════════════════════════════════════════════════
//  MORPH TABLE (VRoid Fcl_* names — all confirmed present on ella.vrm)
// ════════════════════════════════════════════════════════════════
const MORPH = {
  blink: 'Fcl_EYE_Close', blinkL: 'Fcl_EYE_Close_L', blinkR: 'Fcl_EYE_Close_R',
  joy: 'Fcl_ALL_Joy', angry: 'Fcl_ALL_Angry', sorrow: 'Fcl_ALL_Sorrow', surprised: 'Fcl_ALL_Surprised',
  browAngry: 'Fcl_BRW_Angry', browJoy: 'Fcl_BRW_Joy', browSorrow: 'Fcl_BRW_Sorrow',
  mouthA: 'Fcl_MTH_A', mouthI: 'Fcl_MTH_I', mouthU: 'Fcl_MTH_U', mouthE: 'Fcl_MTH_E', mouthO: 'Fcl_MTH_O',
  smile: 'Fcl_MTH_Fun', mouthDown: 'Fcl_MTH_Down', mouthSmall: 'Fcl_MTH_Small', spread: 'Fcl_EYE_Spread',
};
const morphAvail = new Set();
function probeMorphs() {
  try {
    if (expressionManager && expressionManager.expressionMap) {
      for (const k of Object.keys(expressionManager.expressionMap)) morphAvail.add(k);
    }
    for (const mesh of faceMeshes) {
      for (const k of Object.keys(mesh.morphTargetDictionary || {})) morphAvail.add(k);
    }
  } catch (e) { /* tolerate probe failures */ }
}
function setMorph(name, weight) {
  if (!vrm) return;
  // statue mode: the expression manager drives the hidden live meshes —
  // write raw morph influences to the visible baked meshes instead
  if (!statueMode && expressionManager && expressionManager.getExpression && expressionManager.getExpression(name)) {
    expressionManager.setValue(name, weight);
    return;
  }
  if (!morphAvail.has(name)) return;
  for (const mesh of faceMeshes) {
    const idx = mesh.morphTargetDictionary ? mesh.morphTargetDictionary[name] : undefined;
    if (idx !== undefined && mesh.morphTargetInfluences) mesh.morphTargetInfluences[idx] = weight;
  }
}

// ════════════════════════════════════════════════════════════════
//  STATE
// ════════════════════════════════════════════════════════════════
let sceneMode = 0;                 // 0 = auto scold→playful loop, 1 = scold hold, 2 = playful hold
const SPEED_STEPS = [0.5, 1.0, 1.5, 2.0];
let speedIdx = 1;
let celBoost = false;
let muted = false;
let energy = 0.55;                 // smoothed 0..1 — higher while scolding, mid while playful

// smoothed facial channels — every visual value lerps, nothing snaps
const F = { joy:0, smile:0, browAngry:0, browJoy:0, angry:0, sorrow:0, browSorrow:0,
            mouthSmall:0, mouthDown:0, squint:0, blink:0, winkR:0, spread:0 };

// expression timeline
const SCOLD = 5.0, PLAY = 5.5, GAP = 1.0;   // seconds per phase (scaled by speed)
let phaseT = 0;
let phase = 'scold';               // 'scold' | 'gap1' | 'play' | 'gap2'
const rand = (a, b) => a + Math.random() * (b - a);
let nextBlinkAt = rand(1200, 3500), blinkT = -1;
let dblBlink = false;
let nextGlanceAt = rand(2500, 6000), glanceYaw = 0, glanceUntil = 0, glanceSide = 1;
let nextSaccadeAt = 1000;
const saccade = { x: 0, y: 0 };
let nextTiltAt = rand(3000, 7000), tiltDir = 1, tiltTarget = 0, tiltCur = 0, tiltUntil = 0;
let breathT = 0, bobPhase = 0, swayPhase = 0;
let talking = false, nextTalkAt = 2000, talkUntil = 0, visemeTimer = 0, visemeIdx = 0;
const VISEME_CYCLE = ['mouthA', 'mouthI', 'mouthU', 'mouthE', 'mouthO'];
let visemeWeights = [0, 0, 0, 0, 0], visemeTargets = [0, 0, 0, 0, 0];
let mouthOpenT = 0;
const cursor = { nx: 0, ny: 0, active: false, lastMove: -1e9 };
const headVel = { y: 0, x: 0, z: 0 };
const headRot = { y: 0, x: 0, z: 0 };

// voice for the playful giggle / scold mutter
let voices = [];
function loadVoices() {
  if ('speechSynthesis' in window) voices = window.speechSynthesis.getVoices();
}
if ('speechSynthesis' in window) { loadVoices(); window.speechSynthesis.onvoiceschanged = loadVoices; }
function pickVoice() {
  return voices.find((v) => /female|zira|samantha|kyoko/i.test(v.name)) || voices[0] || null;
}
function giggle() {
  if (muted || !('speechSynthesis' in window)) return;
  try {
    window.speechSynthesis.cancel();
    const u = new SpeechSynthesisUtterance('hehe!');
    const v = pickVoice(); if (v) u.voice = v;
    u.pitch = 1.6; u.rate = 1.15; u.volume = 0.85;
    window.speechSynthesis.speak(u);
  } catch (e) { /* ignore */ }
}
function hmph() {
  if (muted || !('speechSynthesis' in window)) return;
  try {
    window.speechSynthesis.cancel();
    const u = new SpeechSynthesisUtterance('hm!');
    const v = pickVoice(); if (v) u.voice = v;
    u.pitch = 0.6; u.rate = 0.95; u.volume = 0.8;
    window.speechSynthesis.speak(u);
  } catch (e) { /* ignore */ }
}

// ════════════════════════════════════════════════════════════════
//  UI CHIPS
// ════════════════════════════════════════════════════════════════
const chipScene = document.getElementById('chip-scene');
const chipSpeed = document.getElementById('chip-speed');
const chipCel = document.getElementById('chip-cel');
const chipMute = document.getElementById('chip-mute');

function applyCelBoost() {
  if (!vrm) return;
  vrm.scene.traverse((obj) => {
    if (!(obj.isMesh || obj.isSkinnedMesh) || !obj.material) return;
    const mats = Array.isArray(obj.material) ? obj.material : [obj.material];
    for (const m of mats) {
      if (m.isMToonMaterial) {
        m.shadingToonyFactor = celBoost ? 0.99 : 0.85;    // harder cel step
        m.shadingShiftFactor = celBoost ? -0.18 : 0.0;
        if (m.parametricRimColorFactor) {
          m.parametricRimColorFactor = celBoost
            ? new THREE.Color(1.0, 0.9, 0.75)
            : new THREE.Color(0.55, 0.5, 0.6);
        }
        m.needsUpdate = true;
      }
    }
  });
}

function syncChips() {
  chipScene.textContent = '🎭 Scene: ' + (sceneMode === 0 ? 'auto scold ⇄ playful' : sceneMode === 1 ? 'scold hold' : 'playful hold');
  chipSpeed.textContent = '⏩ Speed: ' + SPEED_STEPS[speedIdx].toFixed(1) + '×';
  chipCel.classList.toggle('on', celBoost);
  chipCel.textContent = '🎨 Cel Boost: ' + (celBoost ? 'on' : 'off');
  chipMute.textContent = muted ? '🔇 Voice: off' : '🔊 Voice: on';
  applyCelBoost();
}
chipScene.addEventListener('click', () => { sceneMode = (sceneMode + 1) % 3; phaseT = 0; syncChips(); });
chipSpeed.addEventListener('click', () => { speedIdx = (speedIdx + 1) % SPEED_STEPS.length; syncChips(); });
chipCel.addEventListener('click', () => { celBoost = !celBoost; syncChips(); });
chipMute.addEventListener('click', () => { muted = !muted; if (muted && 'speechSynthesis' in window) window.speechSynthesis.cancel(); syncChips(); });
syncChips();

window.addEventListener('keydown', (e) => {
  const k = e.key.toLowerCase();
  if (k === ' ') { e.preventDefault(); sceneMode = (sceneMode + 1) % 3; phaseT = 0; syncChips(); }
  else if (k === 's') { speedIdx = (speedIdx + 1) % SPEED_STEPS.length; syncChips(); }
  else if (k === 'c') { celBoost = !celBoost; syncChips(); }
  else if (k === 'm') { muted = !muted; if (muted && 'speechSynthesis' in window) window.speechSynthesis.cancel(); syncChips(); }
});

window.addEventListener('mousemove', (e) => {
  cursor.nx = (e.clientX / window.innerWidth) * 2 - 1;
  cursor.ny = (e.clientY / window.innerHeight) * 2 - 1;
  cursor.active = true;
  cursor.lastMove = performance.now();
});
window.addEventListener('mouseleave', () => { cursor.active = false; });

// layered sine "noise" — smooth organic drift in [-1, 1]
function noise1(t, s) {
  return Math.sin(t * 0.63 + s * 12.9) * 0.5
       + Math.sin(t * 1.37 + s * 7.1) * 0.3
       + Math.sin(t * 2.71 + s * 3.7) * 0.2;
}
const damp = (cur, target, lambda, dt) => THREE.MathUtils.damp(cur, target, lambda, dt);

// ════════════════════════════════════════════════════════════════
//  MAIN LOOP
// ════════════════════════════════════════════════════════════════
const clock = new THREE.Clock();
let fpsFrames = 0, fpsLast = performance.now();
let morphsProbed = false;

function tick() {
  requestAnimationFrame(tick);
  const rawDelta = Math.min(clock.getDelta(), 0.05);
  const speed = SPEED_STEPS[speedIdx];
  const dt = rawDelta * speed;          // animation timescale
  const now = performance.now();
  const t = clock.elapsedTime;

  // fps chip
  fpsFrames++;
  if (now - fpsLast >= 500) {
    fpsChip.textContent = Math.round((fpsFrames * 1000) / (now - fpsLast)) + ' fps';
    fpsFrames = 0; fpsLast = now;
  }

  if (!vrm) { renderer.render(scene, camera); return; }
  runProbe(now);

  if (!morphsProbed && faceMeshes.length) { probeMorphs(); morphsProbed = true; }

  // ── scene mode / phase machine ──
  if (sceneMode === 0) {
    phaseT += dt;
    const span = phase === 'scold' ? SCOLD : phase === 'play' ? PLAY : GAP;
    if (phaseT >= span) {
      phaseT = 0;
      if (phase === 'scold') { phase = 'gap1'; hmph(); }
      else if (phase === 'gap1') { phase = 'play'; giggle(); }
      else if (phase === 'play') { phase = 'gap2'; }
      else { phase = 'scold'; }
    }
  } else if (phase !== (sceneMode === 1 ? 'scold' : 'play')) {
    phase = sceneMode === 1 ? 'scold' : 'play';
    phaseT = 0;
    if (sceneMode === 1) hmph(); else giggle();
  }
  const transitioning = phase.startsWith('gap');
  const targetEnergy = transitioning ? 0.75 : phase === 'scold' ? 0.95 : 0.6;
  energy = damp(energy, targetEnergy, 2.5, rawDelta);
  const e = energy;

  // ── body motion (skinned strategies only — a statue can't move) ──
  if (!statueMode) {
    breathT += dt * (0.22 + 0.10 * (e - 0.55));
    bobPhase += dt * (0.9 + 0.25 * e);
    swayPhase += dt * (0.55 + 0.15 * e);

    const breath = Math.sin(breathT * Math.PI * 2);
    const bob = breath * (0.006 + 0.010 * e);                                 // chest-led vertical bob
    const swayX = Math.sin(swayPhase * Math.PI * 2) * (0.012 + 0.020 * e) + noise1(t * 0.3, 5.2) * 0.006;
    const swayY = Math.sin(swayPhase * Math.PI * 2 + 1.1) * (0.005 + 0.008 * e);
    const swayRz = Math.sin(swayPhase * Math.PI * 2 + 0.5) * (0.012 + 0.022 * e);

    if (hipsNode) {
      hipsNode.position.x = swayX * 0.55;
      hipsNode.position.y = bob * 0.35;
      hipsNode.rotation.set(swayY * 0.3, swayX * 1.4, swayRz * 0.35, 'YXZ');
    }
    if (spineNode) spineNode.rotation.set(breath * 0.012 * e, swayX * 0.8, swayRz * 0.5, 'YXZ');
    if (chestNode) {
      chestNode.rotation.set(
        breath * (0.014 + 0.010 * e) + (phase === 'scold' ? 0.035 : 0),       // scold: chest leans in, imposing
        swayX * 0.7,
        swayRz * 0.5,
        'YXZ'
      );
    }
    if (neckNode) neckNode.rotation.set(-breath * 0.010 * e + swayY * 0.25, swayX * 0.5, swayRz * 0.35, 'YXZ');

    // ── head: dynamic tilts + cursor tracking, damped springs ──
    const useCursor = cursor.active && now - cursor.lastMove < 4000;
    // signs match the proven chat-UI convention: yaw positive right, pitch negative down
    const aimYaw = useCursor ? cursor.nx * 0.30 : 0;
    const aimPit = useCursor ? -cursor.ny * 0.20 : 0;

    if (now > nextTiltAt) {
      nextTiltAt = now + rand(2800, 6500) / speed;
      tiltDir = Math.random() < 0.5 ? -1 : 1;
      tiltTarget = tiltDir * (0.12 + Math.random() * 0.12) * (phase === 'play' ? 1.35 : 0.7);
      tiltUntil = now + rand(1400, 2600);
    }
    tiltCur = damp(tiltCur, now < tiltUntil ? tiltTarget : 0, 2.8, rawDelta);

    const leanIn = phase === 'scold' ? 0.055 : 0;
    const playfulCock = phase === 'play' ? -tiltDir * 0.10 : 0;
    const driftY = noise1(t * 0.35, 1.1) * 0.05 * (0.6 + 0.4 * e);
    const driftX = noise1(t * 0.4, 2.2) * 0.028;

    const hy = aimYaw + driftY + glanceYaw + saccade.x * 0.6;
    const hx = aimPit + driftX + leanIn + saccade.y * 0.4;
    const hz = tiltCur + playfulCock + noise1(t * 0.5, 3.3) * 0.014;

    // damped springs — fluid with a touch of overshoot
    const springTo = (cur, vel, target, freq, dtm) => {
      const omega = freq * Math.PI * 2;
      const accel = -2 * omega * 0.9 * vel - omega * omega * (cur - target);
      return [cur + vel * dtm, vel + accel * dtm];
    };
    [headRot.y, headVel.y] = springTo(headRot.y, headVel.y, hy, 3.2, rawDelta);
    [headRot.x, headVel.x] = springTo(headRot.x, headVel.x, hx, 3.0, rawDelta);
    [headRot.z, headVel.z] = springTo(headRot.z, headVel.z, hz, 2.6, rawDelta);
    if (headNode) headNode.rotation.set(headRot.x, headRot.y, headRot.z, 'YXZ');

    // glance-aside scheduler
    if (now > nextGlanceAt) {
      nextGlanceAt = now + rand(4000, 9000) / speed;
      glanceSide = -glanceSide;
      glanceYaw = glanceSide * rand(0.15, 0.35);
      glanceUntil = now + rand(700, 1400);
    }
    if (now > glanceUntil) glanceYaw = damp(glanceYaw, 0, 6, rawDelta);

    // ── arms: gentle anime stance (proven ZXY conventions) ──
    const swing = Math.sin(breathT * Math.PI * 2) * 0.02 * e;
    const fist = phase === 'scold' ? 0.05 : 0;
    if (lUp) lUp.rotation.set(-fist, -0.16, -1.10 + swing, 'ZXY');
    if (rUp) rUp.rotation.set(fist, 0.16, 1.10 - swing, 'ZXY');
    if (lLo) lLo.rotation.set(0, -0.34, -0.14, 'ZXY');
    if (rLo) rLo.rotation.set(0, 0.34, 0.14, 'ZXY');
    if (lHand) lHand.rotation.set(0, 0, -0.06, 'ZXY');
    if (rHand) rHand.rotation.set(0, 0, 0.06, 'ZXY');
    if (lSh) lSh.rotation.set(0, 0, -0.02 + breath * 0.008 * e, 'ZXY');
    if (rSh) rSh.rotation.set(0, 0, 0.02 - breath * 0.008 * e, 'ZXY');
  } else {
    // statue: keep the phase machine + sway clocks alive so the face show continues
    swayPhase += dt * (0.55 + 0.15 * e);
  }

  // ── BLINKS ──
  if (blinkT < 0 && now > nextBlinkAt) {
    blinkT = 0;
    dblBlink = Math.random() < 0.18;
  }
  if (blinkT >= 0) {
    blinkT += rawDelta;
    const D = 0.16;
    const p = blinkT / D;
    F.blink = p >= 1 ? 0 : Math.sin(Math.min(p, 1) * Math.PI);   // close & reopen
    if (p >= 1) {
      blinkT = -1;
      F.blink = 0;
      nextBlinkAt = now + (dblBlink ? rand(180, 320) : rand(2200, 5800) / speed);
      dblBlink = false;
    }
  }

  // saccades: tiny eye darts
  if (now > nextSaccadeAt) {
    nextSaccadeAt = now + rand(700, 2800);
    saccade.x = rand(-0.06, 0.06);
    saccade.y = rand(-0.03, 0.03);
  }
  saccade.x = damp(saccade.x, 0, 5, rawDelta);
  saccade.y = damp(saccade.y, 0, 5, rawDelta);

  // ── EMOTION PHASE → face targets ──
  let tgt = null;
  if (phase === 'scold') {
    tgt = { joy: 0, smile: 0, browAngry: 0.92, angry: 0.72, browSorrow: 0, browJoy: 0,
            mouthSmall: 0.42, mouthDown: 0.30, squint: 0.42, sorrow: 0, winkR: 0, spread: 0 };
  } else if (phase === 'play') {
    tgt = { joy: 0.62, smile: 0.58, browAngry: 0, angry: 0, browSorrow: 0, browJoy: 0.42,
            mouthSmall: 0, mouthDown: 0, squint: 0.28, sorrow: 0, winkR: 0, spread: 0.12 };
  } else {
    tgt = { joy: 0.14, smile: 0.1, browAngry: 0, angry: 0, browSorrow: 0, browJoy: 0.12,
            mouthSmall: 0.1, mouthDown: 0, squint: 0.1, sorrow: 0, winkR: 0, spread: 0.06 };
  }

  // eyebrow accent flashes during scold (extra heat)
  if (phase === 'scold' && Math.sin(t * 1.8) > 0.985) tgt.browAngry = 1.0;
  if (phase === 'scold') tgt.browAngry = Math.min(1, tgt.browAngry + noise1(t * 3.1, 8.8) * 0.06);
  if (phase === 'play') tgt.joy = Math.min(1, tgt.joy + Math.max(0, Math.sin(swayPhase * Math.PI * 2)) * 0.12);

  // wink: scheduled only during playful phases
  if (phase === 'play' && blinkT < 0 && Math.random() < rawDelta * 0.22) {
    F.winkR = 1;
    setTimeout(() => { F.winkR = 0; }, 420);
  }

  // smooth every channel — shifting expressions, never snaps
  const faceLam = transitioning ? 1.6 : 3.4;
  for (const k of Object.keys(tgt)) F[k] = damp(F[k], tgt[k], faceLam, rawDelta);

  // ── MOUTH: talking bursts (synchronized visemes) ──
  if (!talking && now > nextTalkAt) {
    talking = true;
    talkUntil = now + rand(900, 2100);
    visemeIdx = Math.floor(Math.random() * VISEME_CYCLE.length);
    nextTalkAt = talkUntil + rand(1400, 3600) / speed;
  }
  if (talking && now > talkUntil) talking = false;
  if (talking) {
    visemeTimer -= rawDelta;
    if (visemeTimer <= 0) {
      visemeTimer = 0.11 + Math.random() * 0.07;
      visemeIdx = (visemeIdx + 1 + Math.floor(Math.random() * 2)) % VISEME_CYCLE.length;
      for (let i = 0; i < 5; i++) visemeTargets[i] = i === visemeIdx ? 0.75 + Math.random() * 0.2 : 0;
    }
    mouthOpenT = damp(mouthOpenT, 0.3 + noise1(now * 0.012, 4.4) * 0.12, 10, rawDelta);
  } else {
    for (let i = 0; i < 5; i++) visemeTargets[i] = 0;
    mouthOpenT = damp(mouthOpenT, 0, 8, rawDelta);
  }
  for (let i = 0; i < 5; i++) visemeWeights[i] = damp(visemeWeights[i], visemeTargets[i], 14, rawDelta);

  // ── APPLY FACE ──
  setMorph(MORPH.joy, F.joy);
  setMorph(MORPH.angry, F.angry);
  setMorph(MORPH.sorrow, F.sorrow);
  setMorph(MORPH.smile, F.smile);
  setMorph(MORPH.browAngry, F.browAngry);
  setMorph(MORPH.browJoy, F.browJoy);
  setMorph(MORPH.browSorrow, F.browSorrow);
  setMorph(MORPH.mouthSmall, F.mouthSmall);
  setMorph(MORPH.mouthDown, F.mouthDown);
  setMorph(MORPH.spread, F.spread);
  setMorph(MORPH.surprised, 0);
  // per-eye lids: blink hits both, wink closes only her right eye,
  // subtle lid narrowing doubles as the scold squint
  const blinkR = Math.max(F.blink, F.winkR, F.squint * 0.3);
  const blinkL = Math.max(F.blink, F.squint * 0.3);
  setMorph(MORPH.blinkL, blinkL);
  setMorph(MORPH.blinkR, blinkR);
  // visemes
  setMorph(MORPH.mouthA, visemeWeights[0]);
  setMorph(MORPH.mouthI, visemeWeights[1]);
  setMorph(MORPH.mouthU, visemeWeights[2]);
  setMorph(MORPH.mouthE, visemeWeights[3]);
  setMorph(MORPH.mouthO, visemeWeights[4]);
  if (talking) {
    setMorph(MORPH.mouthA, Math.max(visemeWeights[0], mouthOpenT * 0.5));
  }

  // ── CAMERA: breathing micro-drift ──
  camera.position.x = Math.sin(t * 0.4) * 0.012;
  camera.position.y = camFocus.y + 0.05 + Math.sin(t * 0.53) * 0.008;
  camera.lookAt(camFocus);

  // ── springs update hair/skirt/tassels (VRM spring bones) ──
  if (!statueMode) {
    try { vrm.update(rawDelta); } catch (err) {
      if (!window.__showcaseWarned) { window.__showcaseWarned = true; window.__vlog('vrm.update error', err && err.message); }
    }
  }

  sparkMat.uniforms.uTime.value = t;
  renderer.render(scene, camera);
}

tick();
