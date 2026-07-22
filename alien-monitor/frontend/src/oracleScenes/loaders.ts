import type { ComponentType } from 'react';

/**
 * One lazily-imported R3F scene module per oracle, ported verbatim from the
 * Oracle Family portal (`oracles/frontend/src/scenes/`). Each module
 * default-exports a `<Scene/>` that renders its mathematical primitive and
 * expects the parent to supply the <Canvas>, lights and post-processing — see
 * OraclePrimitive3D.
 *
 * Code-split (one chunk per scene) so opening a node only pulls the one oracle's
 * scene, never all 17. The four "ambient" oracles (percola/fermat/ablation/
 * landauer) are NOT here — they ship as self-contained HTML-canvas visuals under
 * public/ambient/<slug>/ and render through a local iframe instead.
 */
export const SCENE_LOADERS: Record<string, () => Promise<{ default: ComponentType }>> = {
  platon: () => import('./platon'),
  chronos: () => import('./chronos'),
  lattice: () => import('./lattice'),
  murmuration: () => import('./murmuration'),
  lumen: () => import('./lumen'),
  colony: () => import('./colony'),
  turing: () => import('./turing'),
  sortes: () => import('./sortes'),
  gauss: () => import('./gauss'),
  aestus: () => import('./aestus'),
  betti: () => import('./betti'),
  kantor: () => import('./kantor'),
  fourier: () => import('./fourier'),
};
