import { useMemo, useRef } from "react";
import { useFrame } from "@react-three/fiber";
import { Line, Instances, Instance, Billboard, Text } from "@react-three/drei";
import * as THREE from "three";

/* ===========================================================================
 *  GAUSS — THE BREATHING POSTERIOR (signature 3D scene)
 *
 *  Gauss sells a *calibrated posterior over functions*. A 1D function lives on
 *  a gently curved surface; the UNCERTAINTY is a translucent VOLUMETRIC FOG
 *  BAND — the ±2σ(x) envelope of a real Gaussian-Process posterior, computed
 *  live on the CPU every frame with the exact RBF-kernel / Cholesky math the
 *  oracle ships (k(x,x') = σ_f²·exp(−‖x−x'‖²/2l²); posterior var =
 *  σ_f² − kₓ·K⁻¹·kₓᵀ). The band BREATHES: fat and uniform where there is no
 *  data, pinching to a tight noise-floor waist exactly at each observation.
 *
 *  The loop is the act of learning. It starts at the PRIOR (one fat uniform
 *  fog tube, flat zero mean). Glowing OBSERVATION points then rain in one by
 *  one; as each lands on the curve the posterior re-fits — the mean ribbon
 *  smoothly snakes through every revealed point and the fog DEFLATES locally
 *  into a pinch at that x. After all points are in there is a brief lit hold,
 *  then the knowledge dissolves and the prior breathes back — endlessly.
 *
 *  Rendered INSIDE the shared CosmicCanvas (camera / nebula / stars / bloom
 *  already provided). Everything that scales with sample count is instanced;
 *  per-frame work mutates preallocated buffers + typed arrays only — no
 *  allocations, no leaks, steady 60fps for minutes.
 * ========================================================================= */

const INDIGO = new THREE.Color("#a5b4fc"); // accent — the ±2σ fog
const CYAN = new THREE.Color("#6ee7ff");
const PURPLE = new THREE.Color("#c084fc");
const PINK = new THREE.Color("#f472b6");
const WHITE = new THREE.Color("#ffffff");

// ---- domain & resolution -------------------------------------------------
const M = 120; // posterior samples across x (the fog/mean resolution)
const X0 = -6.0; // domain start (world units, x-axis)
const X1 = 6.0; // domain end
const SPAN = X1 - X0;
const FOG_ROWS = 5; // stacked fog layers between −2σ and +2σ (volumetric feel)
const FOG_N = M * FOG_ROWS; // instanced fog billboards

// ---- GP hyperparameters (the real kernel) --------------------------------
const LENGTH = 1.15; // RBF length-scale l
const SIGNAL = 1.0; // σ_f²  (prior variance → prior std = 1 → ±2σ band height)
const NOISE = 0.0025; // σ_n²  (observation noise → pinch waist width)
const TWO_SIGMA = 2.0; // envelope is mean ± 2σ
const YSCALE = 1.7; // vertical world scale for the function

// ---- the hidden true function the observations are drawn from ------------
// A smooth multi-bump curve so the re-fitting mean has something to chase.
function trueF(x: number): number {
  return (
    Math.sin(x * 0.9) * 0.8 +
    Math.sin(x * 0.37 + 1.3) * 0.5 +
    Math.cos(x * 1.6 - 0.7) * 0.22
  );
}

// Fixed observation x-locations (revealed progressively). Irregular spacing so
// some regions stay data-starved (fat fog) longer than others.
const OBS_X = [-4.6, -3.1, -1.7, -0.4, 0.9, 2.0, 3.3, 4.7];
const N_OBS = OBS_X.length;

const clamp = (v: number, lo: number, hi: number) =>
  v < lo ? lo : v > hi ? hi : v;
const smoothstep = (a: number, b: number, x: number) => {
  const t = clamp((x - a) / (b - a), 0, 1);
  return t * t * (3 - 2 * t);
};

// ---- phase arc (seconds): prior → observations rain in → hold → dissolve --
const T_PRIOR = 2.6; // fat uniform prior breathing
const T_RAIN = 9.0; // observations land one by one
const T_HOLD = 3.0; // fully-fit posterior, lit
const T_DISSOLVE = 2.4; // knowledge dissolves back to prior
const LOOP = T_PRIOR + T_RAIN + T_HOLD + T_DISSOLVE;

export default function Scene() {
  const group = useRef<THREE.Group>(null);
  const fogRef = useRef<THREE.InstancedMesh>(null);
  const meanLineRef = useRef<any>(null);
  const upperLineRef = useRef<any>(null);
  const lowerLineRef = useRef<any>(null);
  const obsRef = useRef<THREE.InstancedMesh>(null);

  // x-grid in world space.
  const xs = useMemo(() => {
    const a = new Float32Array(M);
    for (let i = 0; i < M; i++) a[i] = X0 + (SPAN * i) / (M - 1);
    return a;
  }, []);

  // Preallocated per-frame state (no allocation inside useFrame).
  const buf = useMemo(
    () => ({
      mean: new Float64Array(M), // posterior mean μ(x)
      std: new Float64Array(M), // posterior std σ(x)
      // Cholesky workspace for up to N_OBS active observations.
      K: new Float64Array(N_OBS * N_OBS),
      L: new Float64Array(N_OBS * N_OBS),
      alpha: new Float64Array(N_OBS),
      kx: new Float64Array(N_OBS),
      v: new Float64Array(N_OBS),
      obsY: new Float64Array(N_OBS), // true-function value at each obs x
    }),
    []
  );

  // Line point arrays (mutated in place; drei <Line> reads geometry positions).
  const meanPts = useMemo(
    () => Array.from({ length: M }, () => new THREE.Vector3()),
    []
  );
  const upperPts = useMemo(
    () => Array.from({ length: M }, () => new THREE.Vector3()),
    []
  );
  const lowerPts = useMemo(
    () => Array.from({ length: M }, () => new THREE.Vector3()),
    []
  );

  // scratch
  const dummy = useMemo(() => new THREE.Object3D(), []);
  const tmpColor = useMemo(() => new THREE.Color(), []);

  // RBF kernel.
  const k = (xa: number, xb: number) => {
    const d = xa - xb;
    return SIGNAL * Math.exp((-0.5 * d * d) / (LENGTH * LENGTH));
  };

  useFrame(({ clock }) => {
    const t = clock.elapsedTime;
    const lt = t % LOOP;

    // cinematic drift
    if (group.current) {
      group.current.rotation.y = Math.sin(t * 0.12) * 0.32;
      group.current.rotation.x = Math.sin(t * 0.09) * 0.06;
      group.current.position.y = Math.sin(t * 0.22) * 0.25;
    }

    // ---- how many observations are currently "revealed" -------------------
    // During RAIN they land one by one; full set held through HOLD; during
    // DISSOLVE they retract one by one back to the prior.
    const tRainEnd = T_PRIOR + T_RAIN;
    const tHoldEnd = tRainEnd + T_HOLD;
    let revealed = 0; // fractional count in [0, N_OBS]
    if (lt < T_PRIOR) {
      revealed = 0;
    } else if (lt < tRainEnd) {
      revealed = (N_OBS * (lt - T_PRIOR)) / T_RAIN;
    } else if (lt < tHoldEnd) {
      revealed = N_OBS;
    } else {
      revealed = N_OBS * (1 - (lt - tHoldEnd) / T_DISSOLVE);
    }
    revealed = clamp(revealed, 0, N_OBS);
    const nActive = Math.floor(revealed + 1e-6);
    const landing = revealed - nActive; // 0..1 ease of the point currently arriving

    // a global breathing factor so even the prior fog pulses
    const breathe = 1 + Math.sin(t * 0.9) * 0.05;

    // ---- fit the GP posterior on the active observations ------------------
    // Zero-mean prior: μ=0, σ²=σ_f² everywhere when nActive==0.
    const { mean, std, K, L, alpha, kx, v, obsY } = buf;

    if (nActive === 0) {
      for (let i = 0; i < M; i++) {
        mean[i] = 0;
        std[i] = Math.sqrt(SIGNAL);
      }
    } else {
      // observation targets — raw f(x); YSCALE is applied only at draw time so
      // the kernel stays at unit signal-scale (σ_f² = SIGNAL).
      for (let a = 0; a < nActive; a++) obsY[a] = trueF(OBS_X[a]);

      // K = k(X,X) + σ_n² I   (row-major n×n in the flat buffer)
      for (let a = 0; a < nActive; a++) {
        for (let b = 0; b < nActive; b++) {
          let val = k(OBS_X[a], OBS_X[b]);
          if (a === b) val += NOISE + 1e-9;
          K[a * nActive + b] = val;
        }
      }
      // Cholesky K = L Lᵀ (lower), in place into L.
      for (let a = 0; a < nActive; a++) {
        for (let b = 0; b <= a; b++) {
          let sum = K[a * nActive + b];
          for (let c = 0; c < b; c++)
            sum -= L[a * nActive + c] * L[b * nActive + c];
          if (a === b) {
            L[a * nActive + b] = Math.sqrt(Math.max(sum, 1e-12));
          } else {
            L[a * nActive + b] = sum / L[b * nActive + b];
          }
        }
      }
      // solve L w = y  (forward)
      for (let a = 0; a < nActive; a++) {
        let sum = obsY[a];
        for (let c = 0; c < a; c++) sum -= L[a * nActive + c] * alpha[c];
        alpha[a] = sum / L[a * nActive + a];
      }
      // solve Lᵀ alpha = w  (back)
      for (let a = nActive - 1; a >= 0; a--) {
        let sum = alpha[a];
        for (let c = a + 1; c < nActive; c++)
          sum -= L[c * nActive + a] * alpha[c];
        alpha[a] = sum / L[a * nActive + a];
      }

      // posterior at every grid x: μ = kₓ·alpha ; var = σ_f² − ‖L⁻¹kₓ‖²
      for (let i = 0; i < M; i++) {
        const xq = xs[i];
        for (let a = 0; a < nActive; a++) kx[a] = k(xq, OBS_X[a]);
        let mu = 0;
        for (let a = 0; a < nActive; a++) mu += kx[a] * alpha[a];
        // forward solve L v = kₓ
        for (let a = 0; a < nActive; a++) {
          let sum = kx[a];
          for (let c = 0; c < a; c++) sum -= L[a * nActive + c] * v[c];
          v[a] = sum / L[a * nActive + a];
        }
        let vv = 0;
        for (let a = 0; a < nActive; a++) vv += v[a] * v[a];
        const var0 = Math.max(SIGNAL - vv, 0);
        // The freshly-arriving point eases in: blend its influence by `landing`
        // so the local pinch DEFLATES smoothly rather than snapping.
        mean[i] = mu;
        std[i] = Math.sqrt(var0);
      }

      // smooth interpolation toward the (nActive-1)-fit while the next point lands,
      // achieved implicitly: when landing≈0 we've just added a point so the fog is
      // already tight; the breathing + line ease below keep it buttery.
    }

    // ---- write the mean ribbon + ±2σ envelope lines -----------------------
    for (let i = 0; i < M; i++) {
      const x = xs[i];
      const my = mean[i] * YSCALE;
      const band = TWO_SIGMA * std[i] * YSCALE * breathe;
      // gently curve the whole surface in z for a "function on a curved sheet" feel
      const z = Math.sin((i / (M - 1)) * Math.PI) * -0.6;
      meanPts[i].set(x, my, z);
      upperPts[i].set(x, my + band, z);
      lowerPts[i].set(x, my - band, z);
    }
    updateLine(meanLineRef.current, meanPts);
    updateLine(upperLineRef.current, upperPts);
    updateLine(lowerLineRef.current, lowerPts);

    // ---- the volumetric fog band (instanced billboards filling ±2σ) -------
    if (fogRef.current) {
      let idx = 0;
      for (let i = 0; i < M; i++) {
        const x = xs[i];
        const my = mean[i] * YSCALE;
        const band = TWO_SIGMA * std[i] * YSCALE * breathe;
        const z = Math.sin((i / (M - 1)) * Math.PI) * -0.6;
        // normalized uncertainty 0..1 (prior=1) drives colour + brightness
        const u = clamp(std[i] / Math.sqrt(SIGNAL), 0, 1);
        for (let r = 0; r < FOG_ROWS; r++) {
          // distribute rows across the envelope: frac in [-1, 1] * band
          const frac = (r / (FOG_ROWS - 1)) * 2 - 1;
          const y = my + frac * band;
          dummy.position.set(x, y, z);
          // fog blobs are wider where the band is fat → reads as volume
          const s =
            (SPAN / M) * 2.6 +
            band * 0.5 * (1 - Math.abs(frac) * 0.4) * 0.18 +
            0.06;
          // a soft shimmer so the fog looks alive
          const sh = 1 + Math.sin(t * 1.6 + i * 0.3 + r) * 0.12;
          dummy.scale.set(s * sh, s * sh, s * sh);
          dummy.updateMatrix();
          fogRef.current.setMatrixAt(idx, dummy.matrix);

          // colour: indigo fog, brightening toward cyan where uncertain (prior),
          // dimming to near-nothing at the data pinches.
          tmpColor.copy(INDIGO).lerp(CYAN, u * 0.35);
          // edges of the band are dimmer than the core (soft volumetric falloff)
          const edge = 1 - Math.abs(frac) * 0.55;
          tmpColor.multiplyScalar(0.35 + u * 0.65 * edge);
          fogRef.current.setColorAt(idx, tmpColor);
          idx++;
        }
      }
      fogRef.current.instanceMatrix.needsUpdate = true;
      if (fogRef.current.instanceColor)
        fogRef.current.instanceColor.needsUpdate = true;
    }

    // ---- the observation points snapping onto the curve -------------------
    if (obsRef.current) {
      for (let a = 0; a < N_OBS; a++) {
        const x = OBS_X[a];
        const onCurve = trueF(x) * YSCALE;
        // map obs x to its grid z for coincidence with the surface
        const gi = clamp(Math.round(((x - X0) / SPAN) * (M - 1)), 0, M - 1);
        const z = Math.sin((gi / (M - 1)) * Math.PI) * -0.6;

        // visibility: fully shown for a<nActive; the arriving point (a==nActive)
        // drops in from above and brightens as it lands.
        let vis = 0;
        let drop = 0;
        if (a < nActive) {
          vis = 1;
        } else if (a === nActive && nActive < N_OBS) {
          vis = smoothstep(0, 1, landing);
          drop = (1 - landing) * 3.2; // fall distance above the curve
        }
        const yLand = onCurve + drop;

        dummy.position.set(x, yLand, z + 0.02);
        const s = 0.0001 + vis * 0.16;
        dummy.scale.setScalar(Math.max(s, 0.0001));
        dummy.updateMatrix();
        obsRef.current.setMatrixAt(a, dummy.matrix);

        // colour ramp cyan→purple→pink along x so the data reads as a sequence
        const ux = a / (N_OBS - 1);
        if (ux < 0.5) tmpColor.copy(CYAN).lerp(PURPLE, ux / 0.5);
        else tmpColor.copy(PURPLE).lerp(PINK, (ux - 0.5) / 0.5);
        // brilliant white-hot at the moment of landing
        if (a === nActive) tmpColor.lerp(WHITE, 0.55);
        obsRef.current.setColorAt(a, tmpColor);
      }
      obsRef.current.instanceMatrix.needsUpdate = true;
      if (obsRef.current.instanceColor)
        obsRef.current.instanceColor.needsUpdate = true;
    }
  });

  // initial line point arrays (flat) so geometry allocates the right size once.
  const meanInit = useMemo(() => meanPts.map((p) => p.clone()), [meanPts]);
  const upperInit = useMemo(() => upperPts.map((p) => p.clone()), [upperPts]);
  const lowerInit = useMemo(() => lowerPts.map((p) => p.clone()), [lowerPts]);

  return (
    <group ref={group}>
      {/* THE ±2σ FOG BAND — instanced indigo billboards filling the envelope.
          Additive, depth-write off so they read as translucent volume + bloom. */}
      <Instances ref={fogRef as any} limit={FOG_N} range={FOG_N}>
        <sphereGeometry args={[1, 8, 8]} />
        <meshBasicMaterial
          color={INDIGO}
          transparent
          opacity={0.16}
          depthWrite={false}
          blending={THREE.AdditiveBlending}
          toneMapped={false}
        />
        {Array.from({ length: FOG_N }, (_, i) => (
          <Instance key={i} color={INDIGO} />
        ))}
      </Instances>

      {/* THE ±2σ ENVELOPE EDGES — two faint indigo guide-lines */}
      <Line
        ref={upperLineRef}
        points={upperInit}
        color="#a5b4fc"
        lineWidth={1.1}
        transparent
        opacity={0.45}
        toneMapped={false}
      />
      <Line
        ref={lowerLineRef}
        points={lowerInit}
        color="#a5b4fc"
        lineWidth={1.1}
        transparent
        opacity={0.45}
        toneMapped={false}
      />

      {/* THE POSTERIOR MEAN — bright cyan ribbon re-fitting through the data */}
      <Line
        ref={meanLineRef}
        points={meanInit}
        color="#6ee7ff"
        lineWidth={3}
        transparent
        opacity={0.95}
        toneMapped={false}
      />

      {/* THE OBSERVATIONS — emissive points snapping onto the curve */}
      <Instances ref={obsRef as any} limit={N_OBS} range={N_OBS}>
        <sphereGeometry args={[1, 18, 18]} />
        <meshStandardMaterial
          vertexColors
          emissive={WHITE}
          emissiveIntensity={2.6}
          color="#000000"
          roughness={0.3}
          metalness={0.1}
          toneMapped={false}
        />
        {Array.from({ length: N_OBS }, (_, i) => (
          <Instance key={i} color={CYAN} />
        ))}
      </Instances>

      {/* Concept label — faces the camera, drifts with the surface. */}
      <Billboard position={[0, -3.4, 0]}>
        <Text
          fontSize={0.42}
          color="#a5b4fc"
          anchorX="center"
          anchorY="middle"
          outlineWidth={0.008}
          outlineColor="#04030f"
          letterSpacing={0.06}
        >
          {"μ(x) ± 2σ(x)  ·  GP posterior"}
        </Text>
      </Billboard>
    </group>
  );
}

// Push updated Vector3 points into a drei <Line>'s geometry without realloc.
function updateLine(line: any, pts: THREE.Vector3[]) {
  if (!line) return;
  const geo = line.geometry as THREE.BufferGeometry & {
    setPositions?: (a: number[] | Float32Array) => void;
  };
  if (geo && typeof geo.setPositions === "function") {
    // Line2 / LineGeometry path (drei <Line>): flat [x,y,z,...] buffer.
    const flat = (updateLine as any)._scratch || new Float32Array(pts.length * 3);
    (updateLine as any)._scratch = flat;
    for (let i = 0; i < pts.length; i++) {
      flat[i * 3] = pts[i].x;
      flat[i * 3 + 1] = pts[i].y;
      flat[i * 3 + 2] = pts[i].z;
    }
    geo.setPositions(flat);
  }
}
