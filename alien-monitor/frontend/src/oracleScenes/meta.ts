/**
 * Per-oracle preview metadata (camera framing, accent colour, render kind),
 * mirrored from the Oracle Family portal's `oracles.ts`. Keep slugs in sync with
 * the backend node ids ("oracle-<slug>") and the scene loaders.
 */
export interface OracleSceneMeta {
  /** Camera position the scene was authored for. */
  camera: [number, number, number];
  /** Signature accent colour for the poster / glow fallback. */
  accent: string;
  /** True → self-contained HTML-canvas visual under public/ambient/<slug>/. */
  ambient?: boolean;
  /** One-line mathematical primitive shown under the preview. */
  primitive: string;
}

export const ORACLE_SCENE_META: Record<string, OracleSceneMeta> = {
  platon: { camera: [0, 1.5, 11], accent: '#6ee7ff', primitive: 'Coupled Stuart-Landau / Kuramoto oscillators on a Fibonacci sphere' },
  chronos: { camera: [0, 3, 16], accent: '#c084fc', primitive: 'Wesolowski VDF — sequential squaring over an RSA-2048 modulus' },
  lattice: { camera: [0, 2, 13], accent: '#7dd3fc', primitive: 'Halton low-discrepancy sequence · van der Corput radical inverse' },
  murmuration: { camera: [0, 4, 16], accent: '#f472b6', primitive: 'DeGroot consensus dynamics · Tukey-biweight robust aggregation' },
  lumen: { camera: [0, 2, 14], accent: '#fbbf24', primitive: 'EigenTrust / PageRank power iteration over the trust graph' },
  colony: { camera: [0, 8, 14], accent: '#34d399', primitive: 'Nearest-neighbour + 2-opt TSP tour with an optimality-gap bound' },
  turing: { camera: [0, 2, 13], accent: '#a78bfa', primitive: 'Mitchell best-candidate blue-noise — maximal minimum distance' },
  percola: { camera: [0, 2, 14], accent: '#22d3ee', ambient: true, primitive: 'Bond percolation · giant-component collapse at f_c' },
  fermat: { camera: [0, 2, 14], accent: '#f97316', ambient: true, primitive: "Eikonal / Fermat least-time front over a service graph" },
  ablation: { camera: [0, 2, 14], accent: '#ef4444', ambient: true, primitive: 'Abelian sandpile · self-organized criticality · avalanche τ' },
  landauer: { camera: [0, 2, 14], accent: '#fb7185', ambient: true, primitive: "Landauer's principle · kT·ln2 erasure-energy floor" },
  sortes: { camera: [0, 2, 14], accent: '#fde047', primitive: 'ECVRF-EDWARDS25519-SHA512-TAI (RFC 9381) verifiable draw' },
  gauss: { camera: [0, 2, 13], accent: '#a5b4fc', primitive: 'Gaussian-Process posterior · RBF kernel · Expected Improvement' },
  aestus: { camera: [0, 2, 14], accent: '#5eead4', primitive: 'Rivest-Shamir-Wagner time-lock · b = a^(2^T) mod N' },
  betti: { camera: [0, 2, 18], accent: '#f0abfc', primitive: 'Vietoris-Rips persistent homology · Betti numbers b0/b1/b2' },
  kantor: { camera: [0, 2, 16], accent: '#e879f9', primitive: 'Kantorovich optimal transport · min-cost flow · Wasserstein W_p' },
  fourier: { camera: [0, 2, 16], accent: '#60a5fa', primitive: 'Graph Laplacian spectrum · Fiedler value λ₂ · spectral cut' },
};

export function oracleSceneMeta(slug: string): OracleSceneMeta | undefined {
  return ORACLE_SCENE_META[slug];
}
