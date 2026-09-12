/**
 * THE POOL — cinematic WebGL arena.
 * Tithe core, three agent orbits, Hub particle inflow, bloom, draw phases.
 * Same three.js stack as SKOPOS / LOGOS (jsDelivr 0.185 + addons).
 */
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { EffectComposer } from "three/addons/postprocessing/EffectComposer.js";
import { RenderPass } from "three/addons/postprocessing/RenderPass.js";
import { UnrealBloomPass } from "three/addons/postprocessing/UnrealBloomPass.js";

const CY = 0x38e0ff;
const PK = 0xf472b6;
const PP = 0xc084fc;
const GD = 0xffd56a;
const GR = 0x5dffb0;

function glowTex() {
  const c = document.createElement("canvas");
  c.width = c.height = 128;
  const g = c.getContext("2d");
  const r = g.createRadialGradient(64, 64, 2, 64, 64, 62);
  r.addColorStop(0, "rgba(255,255,255,1)");
  r.addColorStop(0.22, "rgba(255,220,245,0.9)");
  r.addColorStop(0.5, "rgba(180,140,255,0.28)");
  r.addColorStop(1, "rgba(0,0,0,0)");
  g.fillStyle = r;
  g.fillRect(0, 0, 128, 128);
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  return t;
}

function hubLabelTex() {
  const c = document.createElement("canvas");
  c.width = 256;
  c.height = 64;
  const g = c.getContext("2d");
  g.fillStyle = "rgba(93,255,176,0.95)";
  g.font = "700 28px ui-monospace, monospace";
  g.textAlign = "center";
  g.shadowColor = "rgba(93,255,176,0.8)";
  g.shadowBlur = 12;
  g.fillText("HUB TITHE", 128, 42);
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  return t;
}

export function createArena(canvas) {
  const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const renderer = new THREE.WebGLRenderer({
    canvas,
    antialias: true,
    alpha: true,
    powerPreference: "high-performance",
  });
  renderer.setPixelRatio(Math.min(devicePixelRatio || 1, 2));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.18;
  renderer.setClearColor(0x000000, 0);

  const scene = new THREE.Scene();
  scene.fog = new THREE.FogExp2(0x03040a, 0.038);

  const camera = new THREE.PerspectiveCamera(38, 1, 0.12, 140);
  camera.position.set(0.15, 3.4, 9.5);

  const GLOW = glowTex();
  const root = new THREE.Group();
  scene.add(root);

  scene.add(new THREE.AmbientLight(0x6a7aa8, 0.28));
  const coreLight = new THREE.PointLight(PK, 3.2, 22, 1.5);
  scene.add(coreLight);
  const rim = new THREE.PointLight(CY, 1.6, 28, 1.3);
  rim.position.set(-6, 3.4, 5);
  scene.add(rim);
  const fill = new THREE.PointLight(PP, 0.7, 24, 1.6);
  fill.position.set(5, -2, -4);
  scene.add(fill);

  // stars
  {
    const n = 3400;
    const pos = new Float32Array(n * 3);
    const c = new Float32Array(n * 3);
    const pal = [
      new THREE.Color(CY),
      new THREE.Color(0xe8f1ff),
      new THREE.Color(PP),
      new THREE.Color(GD),
    ];
    for (let i = 0; i < n; i++) {
      const r = 16 + Math.random() * 60;
      const th = Math.random() * Math.PI * 2;
      const ph = Math.acos(2 * Math.random() - 1);
      pos[i * 3] = r * Math.sin(ph) * Math.cos(th);
      pos[i * 3 + 1] = r * Math.cos(ph) * 0.72;
      pos[i * 3 + 2] = r * Math.sin(ph) * Math.sin(th);
      const col = pal[(Math.random() * pal.length) | 0];
      const k = 0.45 + Math.random() * 0.55;
      c[i * 3] = col.r * k;
      c[i * 3 + 1] = col.g * k;
      c[i * 3 + 2] = col.b * k;
    }
    const geo = new THREE.BufferGeometry();
    geo.setAttribute("position", new THREE.BufferAttribute(pos, 3));
    geo.setAttribute("color", new THREE.BufferAttribute(c, 3));
    scene.add(
      new THREE.Points(
        geo,
        new THREE.PointsMaterial({
          size: 0.05,
          vertexColors: true,
          transparent: true,
          opacity: 0.9,
          depthWrite: false,
        }),
      ),
    );
  }

  // faint floor disc
  {
    const disc = new THREE.Mesh(
      new THREE.RingGeometry(1.4, 6.2, 96),
      new THREE.MeshBasicMaterial({
        color: CY,
        transparent: true,
        opacity: 0.05,
        side: THREE.DoubleSide,
        blending: THREE.AdditiveBlending,
        depthWrite: false,
      }),
    );
    disc.rotation.x = -Math.PI / 2;
    disc.position.y = -1.35;
    root.add(disc);
  }

  const core = new THREE.Group();
  root.add(core);
  const inner = new THREE.Mesh(
    new THREE.IcosahedronGeometry(0.38, 1),
    new THREE.MeshBasicMaterial({ color: 0xfff6ff }),
  );
  const shell = new THREE.Mesh(
    new THREE.IcosahedronGeometry(0.98, 1),
    new THREE.MeshStandardMaterial({
      color: 0x140610,
      emissive: PK,
      emissiveIntensity: 1.55,
      metalness: 0.4,
      roughness: 0.18,
      wireframe: true,
    }),
  );
  const atmos = new THREE.Mesh(
    new THREE.IcosahedronGeometry(1.28, 2),
    new THREE.MeshBasicMaterial({
      color: PK,
      transparent: true,
      opacity: 0.12,
      side: THREE.BackSide,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    }),
  );
  const halo = new THREE.Sprite(
    new THREE.SpriteMaterial({
      map: GLOW,
      color: PK,
      blending: THREE.AdditiveBlending,
      transparent: true,
      depthWrite: false,
    }),
  );
  halo.scale.set(6.2, 5.4, 1);
  core.add(inner, shell, atmos, halo);
  const spine = new THREE.Mesh(
    new THREE.TorusGeometry(1.55, 0.012, 8, 180),
    new THREE.MeshBasicMaterial({
      color: PP, transparent: true, opacity: 0.55,
      blending: THREE.AdditiveBlending, depthWrite: false,
    }),
  );
  spine.rotation.x = 1.15;
  core.add(spine);
  const goldRing = new THREE.Mesh(
    new THREE.TorusGeometry(1.12, 0.008, 8, 160),
    new THREE.MeshBasicMaterial({
      color: GD, transparent: true, opacity: 0.35,
      blending: THREE.AdditiveBlending, depthWrite: false,
    }),
  );
  goldRing.rotation.x = 0.4;
  goldRing.rotation.y = 0.7;
  core.add(goldRing);

  const RING_R = [2.15, 3.25, 4.45];
  const RING_TILT = [0.38, -0.22, 0.51];
  const RING_COL = [CY, PP, PK];
  const rings = RING_R.map((r, i) => {
    const g = new THREE.Group();
    g.rotation.x = RING_TILT[i];
    const tube = new THREE.Mesh(
      new THREE.TorusGeometry(r, 0.014, 10, 180),
      new THREE.MeshBasicMaterial({
        color: RING_COL[i],
        transparent: true,
        opacity: 0.42,
        blending: THREE.AdditiveBlending,
        depthWrite: false,
      }),
    );
    const ghost = new THREE.Mesh(
      new THREE.TorusGeometry(r, 0.06, 8, 96),
      new THREE.MeshBasicMaterial({
        color: RING_COL[i],
        transparent: true,
        opacity: 0.07,
        blending: THREE.AdditiveBlending,
        depthWrite: false,
      }),
    );
    g.add(tube, ghost);
    root.add(g);
    return g;
  });

  const STREAM_N = 780;
  const streamPos = new Float32Array(STREAM_N * 3);
  const streamSeed = Array.from({ length: STREAM_N }, () => Math.random());
  const streamGeo = new THREE.BufferGeometry();
  streamGeo.setAttribute("position", new THREE.BufferAttribute(streamPos, 3));
  const stream = new THREE.Points(
    streamGeo,
    new THREE.PointsMaterial({
      size: 0.09,
      color: GR,
      map: GLOW,
      blending: THREE.AdditiveBlending,
      transparent: true,
      depthWrite: false,
      opacity: 0.95,
    }),
  );
  scene.add(stream);

  const hubAnchor = new THREE.Vector3(-4.6, 1.35, 2.2);
  const hubMark = new THREE.Mesh(
    new THREE.OctahedronGeometry(0.22, 0),
    new THREE.MeshStandardMaterial({
      color: GR,
      emissive: GR,
      emissiveIntensity: 2.2,
      metalness: 0.4,
      roughness: 0.22,
    }),
  );
  hubMark.position.copy(hubAnchor);
  scene.add(hubMark);
  const hubHalo = new THREE.Sprite(
    new THREE.SpriteMaterial({
      map: GLOW,
      color: GR,
      blending: THREE.AdditiveBlending,
      transparent: true,
      depthWrite: false,
    }),
  );
  hubHalo.position.copy(hubAnchor);
  hubHalo.scale.set(2.1, 2.1, 1);
  scene.add(hubHalo);
  const hubTag = new THREE.Sprite(
    new THREE.SpriteMaterial({
      map: hubLabelTex(),
      transparent: true,
      depthWrite: false,
    }),
  );
  hubTag.position.set(hubAnchor.x, hubAnchor.y + 0.55, hubAnchor.z);
  hubTag.scale.set(2.4, 0.6, 1);
  scene.add(hubTag);

  const beamMat = new THREE.MeshBasicMaterial({
    color: GD,
    transparent: true,
    opacity: 0,
    blending: THREE.AdditiveBlending,
    depthWrite: false,
  });
  const beam = new THREE.Mesh(new THREE.CylinderGeometry(0.03, 0.11, 1, 10, 1, true), beamMat);
  beam.visible = false;
  scene.add(beam);

  const shock = new THREE.Mesh(
    new THREE.SphereGeometry(1, 40, 28),
    new THREE.MeshBasicMaterial({
      color: GR,
      transparent: true,
      opacity: 0,
      wireframe: true,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    }),
  );
  scene.add(shock);

  const agents = new THREE.Group();
  root.add(agents);
  /** @type {{mesh:THREE.Group, weight:number, ring:number, ticket:boolean, agent:string}[]} */
  let seats = [];
  let phase = "idle";
  let phaseT0 = performance.now();
  let winner = null;
  let running = false;

  const host = canvas.parentElement || canvas;
  host.classList.add("webgl-on");

  const controls = new OrbitControls(camera, canvas);
  controls.enableDamping = true;
  controls.dampingFactor = 0.06;
  controls.enablePan = false;
  controls.autoRotate = !reduce;
  controls.autoRotateSpeed = 0.55;
  controls.minDistance = 4.4;
  controls.maxDistance = 14;
  controls.minPolarAngle = 0.45;
  controls.maxPolarAngle = 1.48;
  controls.target.set(0, 0.12, 0);

  const composer = new EffectComposer(renderer);
  composer.addPass(new RenderPass(scene, camera));
  const bloom = new UnrealBloomPass(new THREE.Vector2(1, 1), 1.02, 0.58, 0.18);
  composer.addPass(bloom);

  function pe() {
    return (performance.now() - phaseT0) / 1000;
  }

  function clearSeats() {
    while (agents.children.length) {
      const ch = agents.children[0];
      agents.remove(ch);
      ch.traverse((o) => {
        o.geometry?.dispose?.();
        if (o.material) {
          const m = o.material;
          if (Array.isArray(m)) m.forEach((x) => x.dispose());
          else m.dispose?.();
        }
      });
    }
    seats = [];
  }

  const bodyGeo = new THREE.IcosahedronGeometry(0.16, 0);

  function sync(list) {
    clearSeats();
    list.forEach((n, i) => {
      const g = new THREE.Group();
      const ticket = !!n.ticket;
      const c = ticket ? PK : n.weight > 1.15 ? PP : CY;
      const body = new THREE.Mesh(
        bodyGeo,
        new THREE.MeshStandardMaterial({
          color: 0x0a1018,
          emissive: c,
          emissiveIntensity: 1.85,
          metalness: 0.5,
          roughness: 0.22,
        }),
      );
      const spr = new THREE.Sprite(
        new THREE.SpriteMaterial({
          map: GLOW,
          color: c,
          blending: THREE.AdditiveBlending,
          transparent: true,
          depthWrite: false,
        }),
      );
      spr.scale.set(0.95 + n.weight * 0.28, 0.95 + n.weight * 0.28, 1);
      g.add(body, spr);
      if (ticket) {
        const band = new THREE.Mesh(
          new THREE.TorusGeometry(0.3, 0.02, 8, 32),
          new THREE.MeshBasicMaterial({
            color: GD,
            blending: THREE.AdditiveBlending,
            transparent: true,
            opacity: 0.95,
          }),
        );
        band.rotation.x = Math.PI / 2;
        g.add(band);
      }
      agents.add(g);
      seats.push({
        mesh: g,
        weight: n.weight,
        ring: n.ring ?? i % 3,
        ticket,
        agent: n.agent,
      });
    });
    layout(0);
    paintLabels();
  }

  function layout(t) {
    const ringMem = [[], [], []];
    seats.forEach((s) => ringMem[s.ring].push(s));
    ringMem.forEach((mem, ri) => {
      const cnt = mem.length || 1;
      const dir = ri % 2 ? -1 : 1;
      const r = RING_R[ri];
      mem.forEach((s, j) => {
        const a = t * 0.24 * dir + (j / cnt) * Math.PI * 2 + RING_TILT[ri];
        const y = Math.sin(a * 2 + ri) * 0.2;
        s.mesh.position.set(Math.cos(a) * r, y, Math.sin(a) * r);
        s.mesh.rotation.y = a + t;
        s.mesh.rotation.z = Math.sin(t * 1.4 + j) * 0.22;
        const hit = winner && s.agent === winner.agent && phase === "reveal";
        const sc = hit ? 1.95 : 0.88 + Math.min(1.4, s.weight) * 0.3;
        s.mesh.scale.setScalar(sc);
      });
    });
  }

  const labelRoot = canvas.parentElement?.querySelector("#arenaLabels");

  function paintLabels() {
    if (!labelRoot) return;
    const w = canvas.clientWidth || 1;
    const h = canvas.clientHeight || 1;
    const show = seats.length <= 18 && phase !== "platon";
    labelRoot.innerHTML = show
      ? seats
          .map((s) => {
            const v = s.mesh.position.clone().project(camera);
            if (v.z > 1) return "";
            const x = (v.x * 0.5 + 0.5) * w;
            const y = (-v.y * 0.5 + 0.5) * h;
            const gold = s.ticket ? " ticket" : "";
            return `<span class="alab${gold}" style="left:${x}px;top:${y}px">${esc(s.agent)}</span>`;
          })
          .join("")
      : "";
  }

  function esc(s) {
    return String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
  }

  function setPhase(p, w) {
    phase = p;
    phaseT0 = performance.now();
    winner = w || null;
    beam.visible = p === "select" || p === "reveal";
    controls.autoRotate = !reduce && (p === "idle" || p === "reveal");
    if (p === "platon") bloom.strength = 1.22;
    else if (p === "reveal") bloom.strength = 1.12;
    else bloom.strength = 0.88;
    if (p === "idle") {
      beam.visible = false;
      shock.scale.setScalar(1);
      shock.material.opacity = 0;
    }
  }

  function resize() {
    const w = Math.max(1, canvas.clientWidth || host.clientWidth || 900);
    const h = Math.max(1, canvas.clientHeight || host.clientHeight || 560);
    renderer.setSize(w, h, false);
    composer.setSize(w, h);
    camera.aspect = w / h;
    camera.fov = w / h < 0.85 ? 46 : 38;
    camera.updateProjectionMatrix();
  }

  function updateStream(t) {
    const dest = new THREE.Vector3(0, 0, 0);
    for (let i = 0; i < STREAM_N; i++) {
      const u = (streamSeed[i] + t * 0.09) % 1;
      const p = u * u;
      streamPos[i * 3] = hubAnchor.x + (dest.x - hubAnchor.x) * p + Math.sin(i + t) * 0.14;
      streamPos[i * 3 + 1] = hubAnchor.y + (dest.y - hubAnchor.y) * p + Math.sin(t * 2 + i) * 0.1;
      streamPos[i * 3 + 2] = hubAnchor.z + (dest.z - hubAnchor.z) * p + Math.cos(i * 0.3) * 0.14;
    }
    streamGeo.attributes.position.needsUpdate = true;
  }

  function aimBeam() {
    if (!winner) return;
    const seat = seats.find((s) => s.agent === winner.agent);
    if (!seat) return;
    const to = seat.mesh.position;
    const mid = to.clone().multiplyScalar(0.5);
    const len = to.length();
    beam.position.copy(mid);
    beam.scale.set(1, len, 1);
    beam.lookAt(to);
    beam.rotateX(Math.PI / 2);
  }

  function frame() {
    if (!running) return;
    requestAnimationFrame(frame);
    const t = performance.now() / 1000;
    const idle = phase === "idle";
    if (idle || phase === "reveal") layout(reduce ? 0 : t);
    else layout(t * 0.15);

    const pulse = 1 + Math.sin(t * 1.7) * 0.1;
    halo.scale.setScalar(5.2 * pulse);
    atmos.scale.setScalar(1 + Math.sin(t * 1.2) * 0.04);
    inner.rotation.y = t * 0.75;
    inner.rotation.x = t * 0.21;
    shell.rotation.y = -t * 0.38;
    shell.rotation.x = t * 0.18;
    spine.rotation.z = t * 0.22;
    spine.rotation.y = t * 0.08;
    goldRing.rotation.z = -t * 0.18;
    goldRing.rotation.x = 0.4 + Math.sin(t * 0.3) * 0.08;
    rings.forEach((g, i) => {
      g.rotation.z = t * (i % 2 ? -0.13 : 0.1);
    });
    coreLight.intensity = 2.6 + Math.sin(t * 2.2) * 0.7;
    hubHalo.scale.setScalar(2 + Math.sin(t * 2.4) * 0.25);
    hubMark.rotation.y = t * 1.5;
    hubMark.rotation.x = t * 0.4;

    if (phase === "platon") {
      coreLight.color.set(CY);
      shell.material.emissive.set(CY);
      atmos.material.color.set(CY);
    } else if (phase === "vdf") {
      coreLight.color.set(PP);
      shell.material.emissive.set(PP);
      atmos.material.color.set(PP);
    } else if (phase === "verify") {
      coreLight.color.set(GR);
      shell.material.emissive.set(GR);
      atmos.material.color.set(GR);
      const p = Math.min(1, pe() / 0.85);
      shock.material.opacity = 0.62 * (1 - p);
      shock.scale.setScalar(1 + p * 7);
    } else if (phase === "select") {
      coreLight.color.set(GD);
      beamMat.opacity = 0.82;
      aimBeam();
    } else if (phase === "reveal") {
      coreLight.color.set(PK);
      beamMat.opacity = 0.58 + Math.sin(t * 9) * 0.22;
      aimBeam();
    } else {
      coreLight.color.set(PK);
      shell.material.emissive.set(PK);
      atmos.material.color.set(PK);
      shock.material.opacity *= 0.9;
    }
    updateStream(t);
    controls.update();
    paintLabels();
    composer.render();
  }

  function start() {
    running = true;
    resize();
    requestAnimationFrame(frame);
  }

  const ro = new ResizeObserver(resize);
  ro.observe(host);
  addEventListener("resize", resize);

  canvas.addEventListener("webglcontextlost", (e) => {
    e.preventDefault();
    running = false;
    host.classList.remove("webgl-on");
  });

  return { sync, setPhase, resize, start, clearSeats };
}
