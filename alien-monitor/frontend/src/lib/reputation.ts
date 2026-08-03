/**
 * Reputation graph model for the Alien Monitor.
 *
 * This is the SAME EigenTrust / PageRank kernel that powers the LUMEN oracle
 * (oracles/oracles/lumen/lumen/pagerank.py): reputation is the stationary
 * distribution of a damped random walk over a directed weighted trust graph
 * `i -> j` ("i trusts j"). Nodes trusted *by trusted nodes* score highest; the
 * `(1 - d)` teleport keeps the walk ergodic so sybil cliques cannot trap rank.
 *
 * Here the graph is the LIVE ecosystem the monitor already streams: nodes are
 * real ecosystem participants and edges are the real structural links between
 * them. In LIVE / UNI modes each node may also carry a real scalar `trust_score`
 * (from the Hub's federation crawl / the `reputation` plugin); when present it
 * biases the trust flow toward trusted nodes, so the ranking reflects real
 * reputation data rather than topology alone. In TEST mode the graph is the
 * simulated ecosystem, so the ranking is illustrative only.
 *
 * Kept free of three.js so it stays pure and unit-testable.
 */

import type { EcoNode, EcoLink } from '../App';

export const DEFAULT_DAMPING = 0.85;
const DEFAULT_TOL = 1e-10;
const DEFAULT_MAX_ITER = 500;
// A relationship confers standing BOTH ways: a well-connected node (e.g. the central
// Hub that routes to everything) should rank high, not sink to ~0 just because its
// links happen to point outward. We feed the PageRank kernel a reduced reverse edge
// for each real link (only where no real reverse exists), so direction still dominates
// but raw connectivity counts. The displayed graph edges remain the real structural ones.
const REVERSE_TRUST_W = 0.4;

export interface PageRankResult {
  scores: number[];
  iterations: number;
  converged: boolean;
}

/**
 * PageRank / EigenTrust via power iteration on the Google matrix, in edge-list
 * form (no dense N×N matrix). Mirrors lumen's `pagerank.py`:
 *   r_{k+1}[j] = (1-d)/n  +  d · Σ_dangling r/n  +  d · Σ_{i→j} r[i]·w/outW[i]
 * Dangling nodes (no outgoing trust) teleport uniformly so no rank mass leaks.
 * Scores are non-negative and sum to 1.
 */
export function pagerank(
  n: number,
  edges: Array<[number, number, number]>,
  damping: number = DEFAULT_DAMPING,
  tol: number = DEFAULT_TOL,
  maxIter: number = DEFAULT_MAX_ITER,
): PageRankResult {
  if (n <= 0) return { scores: [], iterations: 0, converged: true };
  if (n === 1) return { scores: [1], iterations: 0, converged: true };

  const outW = new Array<number>(n).fill(0);
  for (const [i, j, w] of edges) {
    if (i < 0 || i >= n || j < 0 || j >= n || i === j || w <= 0) continue;
    outW[i] += w;
  }

  const teleport = (1 - damping) / n;
  let r = new Array<number>(n).fill(1 / n);
  let iterations = 0;
  let converged = false;

  for (let iter = 0; iter < maxIter; iter++) {
    const next = new Array<number>(n).fill(teleport);

    // Dangling mass (sources with no outgoing trust) redistributed uniformly.
    let dangling = 0;
    for (let i = 0; i < n; i++) if (outW[i] === 0) dangling += damping * r[i] / n;
    if (dangling > 0) for (let i = 0; i < n; i++) next[i] += dangling;

    for (const [i, j, w] of edges) {
      if (i < 0 || i >= n || j < 0 || j >= n || i === j || w <= 0) continue;
      if (outW[i] > 0) next[j] += damping * r[i] * (w / outW[i]);
    }

    let sum = 0;
    for (let i = 0; i < n; i++) sum += next[i];
    let delta = 0;
    if (sum > 0) {
      for (let i = 0; i < n; i++) {
        next[i] /= sum;
        delta += Math.abs(next[i] - r[i]);
      }
    }
    r = next;
    iterations = iter + 1;
    if (delta < tol) {
      converged = true;
      break;
    }
  }

  return { scores: r, iterations, converged };
}

/** Fibonacci-sphere point i of n — organic, evenly spread 3D layout. */
export function fibSpherePoint(i: number, n: number, radius: number): [number, number, number] {
  if (n <= 1) return [0, 0, 0];
  const golden = Math.PI * (3 - Math.sqrt(5));
  const y = 1 - (i / (n - 1)) * 2;
  const rad = Math.sqrt(Math.max(0, 1 - y * y));
  const theta = golden * i;
  return [Math.cos(theta) * rad * radius, y * radius, Math.sin(theta) * rad * radius];
}

export interface RankedNode {
  index: number;
  id: string;
  label: string;
  group: string;
  status: string;
  score: number;
  rank: number; // 0..1 normalized
  trust: number | null; // real scalar trust_score when available
}

export interface ReputationGraph {
  count: number;
  /** 'lumen' when scores came from the real LUMEN oracle, else local PageRank. */
  source: 'local' | 'lumen';
  ids: string[];
  labels: string[];
  groups: string[];
  statuses: string[];
  positions: Array<[number, number, number]>;
  edges: Array<{ i: number; j: number; w: number }>;
  scores: number[];
  rank: number[]; // 0..1 normalized (max -> 1)
  trust: Array<number | null>;
  topNode: number;
  hasLiveTrust: boolean;
  liveTrustCount: number;
  ranked: RankedNode[]; // sorted by score desc
  iterations: number;
  converged: boolean;
}

const LAYOUT_RADIUS = 5.4;

function emptyGraph(): ReputationGraph {
  return {
    count: 0,
    source: 'local',
    ids: [],
    labels: [],
    groups: [],
    statuses: [],
    positions: [],
    edges: [],
    scores: [],
    rank: [],
    trust: [],
    topNode: -1,
    hasLiveTrust: false,
    liveTrustCount: 0,
    ranked: [],
    iterations: 0,
    converged: true,
  };
}

function clamp01(v: number): number {
  if (!Number.isFinite(v)) return 0;
  return v < 0 ? 0 : v > 1 ? 1 : v;
}

/** Best-effort: read a real scalar trust value off a node's live metrics. */
function nodeTrust(node: EcoNode): number | null {
  const m = node.metrics || {};
  const raw = m.trust_score ?? m.trust ?? m.reputation;
  if (typeof raw !== 'number' || !Number.isFinite(raw)) return null;
  // Some sources report 0..1, some 0..100 — normalize to 0..1.
  return raw > 1 ? clamp01(raw / 100) : clamp01(raw);
}

const STATUS_ACTIVITY: Record<string, number> = { active: 1, idle: 0.55, error: 0.3, unknown: 0.15 };

/**
 * Live "is this node actually doing things" signal in 0..1, from status + common
 * activity metrics. This is what makes reputation differ ACROSS modes and over
 * time: a busy LIVE network, a quiet TEST sim, and an evolving UNI universe have
 * different activity profiles, so trust flows toward different nodes — instead of
 * the ranking being fixed by the (mode-invariant) link topology alone.
 */
export function nodeActivity(node: EcoNode): number {
  const s = STATUS_ACTIVITY[String(node.status ?? 'unknown')] ?? 0.15;
  const m = node.metrics || {};
  const raw =
    (Number(m.invocations_24h ?? m.invocations ?? 0) || 0) +
    (Number(m.agents ?? 0) || 0) * 50 +
    (Number(m.peers ?? 0) || 0) * 30 +
    (Number(m.tasks ?? 0) || 0) * 20 +
    (Number(m.activity ?? 0) || 0) * 10;
  const act = raw > 0 ? Math.min(1, Math.log10(raw + 1) / 5) : 0;
  return clamp01(0.45 * s + 0.55 * act);
}

/** Normalize a url/name to a comparable host token (scheme + path stripped). */
function hostToken(s: string): string {
  const str = String(s).toLowerCase().trim();
  if (!str) return '';
  return str.replace(/^[a-z]+:\/\//, '').split('/')[0].split('?')[0];
}

/**
 * Match a federation peer's trust_score onto a node by EXACT id/label/url or by
 * host equality. Deliberately strict — loose substring matching let short ids
 * (e.g. "ai", "hub") collide with unrelated peer urls and mis-attribute trust.
 */
function overlayPeerTrust(
  node: EcoNode,
  peerTrust: Record<string, number> | undefined,
): number | null {
  if (!peerTrust) return null;
  const keys = new Set<string>();
  for (const raw of [node.id, node.label, node.url || '']) {
    const s = String(raw).toLowerCase().trim();
    if (!s) continue;
    keys.add(s);
    keys.add(hostToken(s));
  }
  keys.delete('');
  for (const [key, val] of Object.entries(peerTrust)) {
    const k = key.toLowerCase().trim();
    if (!k) continue;
    if (keys.has(k) || keys.has(hostToken(k))) {
      return clamp01(val > 1 ? val / 100 : val);
    }
  }
  return null;
}

export interface BuildOptions {
  /** Real federation trust scores keyed by peer url/name/id (LIVE / UNI). */
  peerTrust?: Record<string, number>;
  /** Real per-node reputation from the LUMEN oracle (id -> score). When it covers
   *  every node it replaces the local PageRank result (the monitor then renders
   *  the genuine oracle output); otherwise local PageRank is used. */
  externalScores?: Record<string, number>;
}

/**
 * Build the reputation graph from a monitor snapshot. Nodes become graph nodes,
 * `links` become directed trust edges, and each edge is weighted toward trusted
 * targets when real `trust_score` data is available. Returns ranked nodes plus
 * everything the 3D scene needs. Safe on null / empty input.
 */
export function buildReputationGraph(
  state: { nodes: EcoNode[]; links: EcoLink[] } | null | undefined,
  opts: BuildOptions = {},
): ReputationGraph {
  if (!state || !Array.isArray(state.nodes) || state.nodes.length === 0) return emptyGraph();

  // Top-level nodes only (clusters/children are summarized by their parent node).
  const nodes = state.nodes;
  const n = nodes.length;
  const indexOf = new Map<string, number>();
  nodes.forEach((node, i) => indexOf.set(node.id, i));

  // Real per-node trust: live metric first, federation-peer overlay second.
  const trust: Array<number | null> = nodes.map((node) => {
    const overlay = overlayPeerTrust(node, opts.peerTrust);
    const metric = nodeTrust(node);
    return overlay ?? metric;
  });
  const liveTrustCount = trust.reduce<number>((acc, t) => acc + (t != null ? 1 : 0), 0);
  const hasLiveTrust = liveTrustCount > 0;

  // Live activity per node (status + metrics) — drives the per-mode / per-tick variation.
  const activity = nodes.map((node) => nodeActivity(node));

  // Links -> directed weighted trust edges; bias weight toward trusted + active targets.
  const edges: Array<{ i: number; j: number; w: number }> = [];
  const seen = new Set<string>();
  for (const link of state.links || []) {
    const i = indexOf.get(String(link.source));
    const j = indexOf.get(String(link.target));
    if (i == null || j == null || i === j) continue;
    const key = `${i}:${j}`;
    if (seen.has(key)) continue;
    seen.add(key);
    const targetTrust = trust[j];
    const w = 1 + (targetTrust != null ? targetTrust * 1.5 : 0) + activity[j] * 1.5;
    edges.push({ i, j, w });
  }

  // Kernel input = the real edges PLUS a reduced reverse edge wherever no real reverse
  // exists, so connectivity (not just outward link direction) builds reputation. The
  // `edges` array above stays the real structural graph (display + inbound/outbound counts).
  const realKeys = new Set(edges.map((e) => `${e.i}:${e.j}`));
  const prEdges: Array<[number, number, number]> = edges.map((e) => [e.i, e.j, e.w]);
  for (const e of edges) {
    const rk = `${e.j}:${e.i}`;
    if (realKeys.has(rk)) continue; // a real reverse link already carries the trust
    realKeys.add(rk);
    const srcTrust = trust[e.i];
    const w = REVERSE_TRUST_W * (1 + (srcTrust != null ? srcTrust * 1.5 : 0) + activity[e.i] * 1.5);
    prEdges.push([e.j, e.i, w]);
  }

  const local = pagerank(n, prEdges);
  let scores = local.scores;
  let { iterations, converged } = local;
  let source: 'local' | 'lumen' = 'local';
  // Prefer the real LUMEN oracle's scores when they cover every node.
  if (opts.externalScores) {
    const ext = nodes.map((nd) => opts.externalScores![nd.id]);
    if (ext.length === n && ext.every((v) => typeof v === 'number' && Number.isFinite(v))) {
      scores = ext as number[];
      source = 'lumen';
      converged = true;
    }
  }

  // Reputation % = share of the TOP node's score (top → 100%). Min–max normalization
  // would force the lowest-scoring node to EXACTLY 0% — misleading (a central hub could
  // read "0%"); score/maxScore shows each node's true standing relative to the leader.
  const maxScore = scores.length ? Math.max(...scores) : 0;
  const denom = maxScore > 0 ? maxScore : 1;
  const rank = scores.map((s) => clamp01(s / denom));

  let topNode = -1;
  for (let i = 0; i < n; i++) if (topNode < 0 || scores[i] > scores[topNode]) topNode = i;

  const positions = nodes.map((_, i) => fibSpherePoint(i, n, LAYOUT_RADIUS));
  const ids = nodes.map((nd) => nd.id);
  const labels = nodes.map((nd) => nd.label);
  const groups = nodes.map((nd) => nd.group);
  const statuses = nodes.map((nd) => String(nd.status ?? 'unknown'));

  const ranked: RankedNode[] = nodes
    .map((nd, i) => ({
      index: i,
      id: ids[i],
      label: labels[i],
      group: groups[i],
      status: statuses[i],
      score: scores[i] ?? 0,
      rank: rank[i] ?? 0,
      trust: trust[i],
    }))
    .sort((a, b) => b.score - a.score);

  return {
    count: n,
    source,
    ids,
    labels,
    groups,
    statuses,
    positions,
    edges,
    scores,
    rank,
    trust,
    topNode,
    hasLiveTrust,
    liveTrustCount,
    ranked,
    iterations,
    converged,
  };
}

/**
 * Stable signature so the (relatively expensive) graph rebuild + layout only
 * re-runs when the topology or mode changes — not on every metric tick. A
 * coarse trust bucket is folded in so live trust shifts still refresh.
 */
export function reputationSignature(
  mode: string,
  state: { nodes: EcoNode[]; links: EcoLink[] } | null | undefined,
  peerTrust?: Record<string, number>,
  externalScores?: Record<string, number>,
): string {
  if (!state || !Array.isArray(state.nodes)) return `${mode}|empty`;
  // Include label + status so a rename / status flip refreshes the popup, and
  // a coarse trust bucket so live trust shifts still re-rank.
  const nodeSig = state.nodes
    .map((n) => {
      const t = nodeTrust(n);
      const a = Math.round(nodeActivity(n) * 12);
      return `${n.id}:${n.label}:${n.status}:${t == null ? '' : Math.round(t * 20)}:${a}`;
    })
    .join(',');
  // Fold peer-trust VALUES (not just keys) so a refreshed federation score rebuilds.
  const peerKey = peerTrust
    ? Object.entries(peerTrust)
        .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))
        .map(([k, v]) => `${k}=${Math.round((v > 1 ? v / 100 : v) * 100)}`)
        .join(',')
    : '';
  const lumenKey = externalScores
    ? Object.entries(externalScores)
        .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))
        .map(([k, v]) => `${k}=${Math.round(v * 1e6)}`)
        .join(',')
    : '';
  return `${mode}|${state.nodes.length}|${(state.links || []).length}|${nodeSig}|${peerKey}|${lumenKey}`;
}
