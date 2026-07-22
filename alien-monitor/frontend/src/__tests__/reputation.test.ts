import { describe, it, expect } from 'vitest';
import { pagerank, buildReputationGraph, reputationSignature } from '../lib/reputation';
import type { EcoNode, EcoLink } from '../App';

function node(id: string, extra: Partial<EcoNode> = {}): EcoNode {
  return {
    id,
    label: id.toUpperCase(),
    group: 'core',
    icon: 'x',
    description: '',
    metrics: {},
    status: 'active',
    position: { x: 0, y: 0, z: 0 },
    ...extra,
  };
}

const link = (source: string, target: string): EcoLink => ({ source, target, label: '' });

describe('pagerank (EigenTrust kernel)', () => {
  it('returns a probability distribution (non-negative, sums to 1)', () => {
    const edges: Array<[number, number, number]> = [
      [0, 3, 1],
      [1, 3, 1],
      [2, 3, 1],
      [4, 3, 1],
      [3, 0, 1],
    ];
    const { scores } = pagerank(5, edges);
    expect(scores).toHaveLength(5);
    for (const s of scores) expect(s).toBeGreaterThanOrEqual(0);
    const sum = scores.reduce((a, b) => a + b, 0);
    expect(sum).toBeCloseTo(1, 6);
  });

  it('ranks the most-trusted node highest', () => {
    const edges: Array<[number, number, number]> = [
      [0, 3, 1],
      [1, 3, 1],
      [2, 3, 1],
      [4, 3, 1],
    ];
    const { scores } = pagerank(5, edges);
    const top = scores.indexOf(Math.max(...scores));
    expect(top).toBe(3);
  });

  it('handles dangling nodes without leaking rank mass', () => {
    // node 1 has no outgoing trust (dangling)
    const { scores, converged } = pagerank(3, [[0, 1, 1]]);
    expect(converged).toBe(true);
    expect(scores.reduce((a, b) => a + b, 0)).toBeCloseTo(1, 6);
  });

  it('returns [1] for a single node and [] for none', () => {
    expect(pagerank(1, [])).toMatchObject({ scores: [1] });
    expect(pagerank(0, [])).toMatchObject({ scores: [] });
  });
});

describe('buildReputationGraph', () => {
  it('is empty-safe on null / empty input', () => {
    expect(buildReputationGraph(null).count).toBe(0);
    expect(buildReputationGraph({ nodes: [], links: [] }).count).toBe(0);
  });

  it('maps nodes/links and picks the most-linked-to node as the sun', () => {
    const nodes = ['a', 'b', 'c', 'hub'].map((id) => node(id));
    const links = [link('a', 'hub'), link('b', 'hub'), link('c', 'hub'), link('hub', 'a')];
    const g = buildReputationGraph({ nodes, links });
    expect(g.count).toBe(4);
    expect(g.edges).toHaveLength(4);
    expect(g.ids[g.topNode]).toBe('hub');
    // ranked sorted by score desc, top is the hub
    expect(g.ranked[0].id).toBe('hub');
    expect(g.ranked[0].score).toBeGreaterThanOrEqual(g.ranked[1].score);
  });

  it('skips links whose endpoints are unknown and ignores self-loops', () => {
    const nodes = [node('a'), node('b')];
    const links = [link('a', 'b'), link('a', 'ghost'), link('a', 'a')];
    const g = buildReputationGraph({ nodes, links });
    expect(g.edges).toHaveLength(1);
    expect(g.edges[0]).toMatchObject({ i: 0, j: 1 });
  });

  it('surfaces real scalar trust from node metrics and federation overlay', () => {
    const nodes = [
      node('hub', { metrics: { trust_score: 0.9 } }),
      node('peer', { url: 'http://78.17.126.214', metrics: {} }),
    ];
    const links = [link('peer', 'hub')];
    const g = buildReputationGraph({ nodes, links }, { peerTrust: { 'http://78.17.126.214': 0.42 } });
    expect(g.hasLiveTrust).toBe(true);
    expect(g.liveTrustCount).toBe(2);
    expect(g.trust[0]).toBeCloseTo(0.9, 6);
    expect(g.trust[1]).toBeCloseTo(0.42, 6);
  });

  it('normalizes a 0..100 trust metric into 0..1', () => {
    const g = buildReputationGraph({ nodes: [node('x', { metrics: { trust_score: 80 } })], links: [] });
    expect(g.trust[0]).toBeCloseTo(0.8, 6);
  });

  it('uses real LUMEN oracle scores when they cover every node (else local)', () => {
    const nodes = ['a', 'b', 'c'].map((id) => node(id));
    const links = [link('a', 'b'), link('b', 'c')];
    const g = buildReputationGraph({ nodes, links }, { externalScores: { a: 0.1, b: 0.2, c: 0.7 } });
    expect(g.source).toBe('lumen');
    expect(g.ids[g.topNode]).toBe('c');
    // incomplete oracle coverage → fall back to local PageRank
    const g2 = buildReputationGraph({ nodes, links }, { externalScores: { a: 0.1 } });
    expect(g2.source).toBe('local');
  });

  it('a central hub that links OUT to everything still ranks top (mutual standing)', () => {
    // hub -> a,b,c,d only (purely outgoing, 0 incoming) — the real-world Hub case.
    const nodes = ['hub', 'a', 'b', 'c', 'd'].map((id) => node(id));
    const links = ['a', 'b', 'c', 'd'].map((tgt) => link('hub', tgt));
    const g = buildReputationGraph({ nodes, links });
    expect(g.ids[g.topNode]).toBe('hub'); // not sunk to ~0 despite 0 incoming links
    expect(g.rank[g.ids.indexOf('hub')]).toBeCloseTo(1, 6); // top => 100%
    expect(g.edges).toHaveLength(4); // real structural edges preserved (no synthetic reverse leak)
  });

  it('does not force the lowest node to exactly 0% (score/maxScore, not min-max)', () => {
    const nodes = ['a', 'b', 'c'].map((id) => node(id));
    const links = [link('a', 'b'), link('a', 'c'), link('b', 'c')];
    const g = buildReputationGraph({ nodes, links });
    expect(Math.min(...g.rank)).toBeGreaterThan(0); // min-max would have pinned this to 0
    expect(Math.max(...g.rank)).toBeCloseTo(1, 6);
  });

  it('weights reputation toward more active nodes (per-mode / per-tick dynamics)', () => {
    // Two equally-linked-to targets; only "active" carries live activity.
    const active = node('active', { status: 'active', metrics: { invocations_24h: 100000, agents: 50 } });
    const idle = node('idle', { status: 'unknown', metrics: {} });
    const srcs = ['s1', 's2', 's3'].map((id) => node(id, { status: 'idle', metrics: {} }));
    const nodes = [active, idle, ...srcs];
    const links = srcs.flatMap((s) => [link(s.id, 'active'), link(s.id, 'idle')]);
    const g = buildReputationGraph({ nodes, links });
    const sActive = g.scores[g.ids.indexOf('active')];
    const sIdle = g.scores[g.ids.indexOf('idle')];
    expect(sActive).toBeGreaterThan(sIdle);
    expect(g.ids[g.topNode]).toBe('active');
  });
});

describe('reputationSignature', () => {
  it('changes with mode and topology', () => {
    const state = { nodes: [node('a'), node('b')], links: [link('a', 'b')] };
    expect(reputationSignature('test', state)).not.toBe(reputationSignature('real', state));
    const more = { nodes: [node('a'), node('b'), node('c')], links: [link('a', 'b')] };
    expect(reputationSignature('test', state)).not.toBe(reputationSignature('test', more));
  });

  it('is stable across identical snapshots', () => {
    const a = { nodes: [node('a')], links: [] };
    const b = { nodes: [node('a')], links: [] };
    expect(reputationSignature('real', a)).toBe(reputationSignature('real', b));
  });
});
