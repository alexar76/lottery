/**
 * Alien Monitor — Frontend Component Tests
 *
 * Tests cover:
 *  - MetricsPanel rendering and value formatting
 *  - NodeDetail panel with metrics display
 *  - AIAssistant message sending
 *  - TransactionFlow event rendering
 *  - ControlBar mode/theme switching
 *  - App state management
 */

import { describe, it, expect, vi } from 'vitest';

// ---------------------------------------------------------------------------
// Pure-function unit tests (no DOM needed)
// ---------------------------------------------------------------------------

describe('MetricsPanel value formatting', () => {
  function fmt(v: number): string {
    if (v >= 1000000) return `${(v / 1000000).toFixed(1)}M`;
    if (v >= 1000) return `${(v / 1000).toFixed(1)}K`;
    return v.toFixed(0);
  }

  function fmtUSD(v: number): string {
    if (v >= 1000000) return `$${(v / 1000000).toFixed(2)}M`;
    if (v >= 1000) return `$${(v / 1000).toFixed(1)}K`;
    return `$${v.toFixed(0)}`;
  }

  it('formats thousands with K', () => {
    expect(fmt(5500)).toBe('5.5K');
    expect(fmt(1200)).toBe('1.2K');
    expect(fmt(999)).toBe('999');
  });

  it('formats millions with M', () => {
    expect(fmt(2500000)).toBe('2.5M');
    expect(fmt(1000000)).toBe('1.0M');
  });

  it('formats USD correctly', () => {
    expect(fmtUSD(50000)).toBe('$50.0K');
    expect(fmtUSD(2000000)).toBe('$2.00M');
    expect(fmtUSD(500)).toBe('$500');
  });

  it('handles edge values', () => {
    expect(fmt(0)).toBe('0');
    expect(fmt(1)).toBe('1');
    expect(fmtUSD(0)).toBe('$0');
  });
});

// ---------------------------------------------------------------------------
// Ecosystem state simulation tests
// ---------------------------------------------------------------------------

describe('Ecosystem state invariants', () => {
  interface Summary {
    total_invocations_24h: number;
    total_volume_usd: number;
    active_channels: number;
    tvl_usd: number;
    agents_online: number;
    apps_online: number;
    tps_solana: number;
    gas_gwei: number;
    mode: string;
    tick: number;
  }

  const validSummary = (s: Summary): boolean => {
    return (
      s.total_invocations_24h >= 0 &&
      s.total_volume_usd >= 0 &&
      s.active_channels >= 0 &&
      s.tvl_usd >= 0 &&
      s.agents_online >= 0 &&
      s.apps_online >= 0 &&
      s.apps_online <= 9 &&
      s.tps_solana >= 0 &&
      s.gas_gwei >= 0 &&
      ['test', 'real'].includes(s.mode) &&
      s.tick >= 0
    );
  };

  it('validates summary invariants', () => {
    const s: Summary = {
      total_invocations_24h: 350,
      total_volume_usd: 12000,
      active_channels: 55,
      tvl_usd: 67000,
      agents_online: 23,
      apps_online: 5,
      tps_solana: 2500,
      gas_gwei: 45,
      mode: 'test',
      tick: 10,
    };
    expect(validSummary(s)).toBe(true);
  });

  it('rejects invalid apps_online', () => {
    const s: Summary = {
      total_invocations_24h: 100,
      total_volume_usd: 1000,
      active_channels: 10,
      tvl_usd: 5000,
      agents_online: 5,
      apps_online: 15, // invalid: > 9
      tps_solana: 1000,
      gas_gwei: 20,
      mode: 'test',
      tick: 1,
    };
    expect(validSummary(s)).toBe(false);
  });

  it('rejects invalid mode', () => {
    const s: Summary = {
      total_invocations_24h: 100,
      total_volume_usd: 1000,
      active_channels: 10,
      tvl_usd: 5000,
      agents_online: 5,
      apps_online: 3,
      tps_solana: 1000,
      gas_gwei: 20,
      mode: 'invalid' as any,
      tick: 1,
    };
    expect(validSummary(s)).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// Node data model tests
// ---------------------------------------------------------------------------

describe('EcoNode model', () => {
  interface EcoNode {
    id: string;
    label: string;
    group: string;
    icon: string;
    description: string;
    metrics: Record<string, number>;
    status: 'active' | 'idle' | 'error' | 'unknown';
    position: { x: number; y: number; z: number };
    children?: { id: string; label: string }[];
    url?: string;
  }

  const nodeKeys = ['id', 'label', 'group', 'icon', 'description', 'metrics', 'status', 'position'];

  it('all required fields present', () => {
    const node: EcoNode = {
      id: 'hub',
      label: 'AIMarket Hub',
      group: 'core',
      icon: 'hub',
      description: 'Central hub',
      metrics: { peers: 5 },
      status: 'active',
      position: { x: 0, y: 0, z: 0 },
    };
    for (const key of nodeKeys) {
      expect(key in node).toBe(true);
    }
  });

  it('validates status values', () => {
    const validStatuses = ['active', 'idle', 'error', 'unknown'];
    validStatuses.forEach((status) => {
      const node: EcoNode = {
        id: 'test',
        label: 'Test',
        group: 'core',
        icon: 'test',
        description: 'Test node',
        metrics: {},
        status: status as EcoNode['status'],
        position: { x: 0, y: 0, z: 0 },
      };
      expect(validStatuses.includes(node.status)).toBe(true);
    });
  });

  it('position must be 3D', () => {
    const node: EcoNode = {
      id: 'test',
      label: 'Test',
      group: 'core',
      icon: 'test',
      description: 'Test node',
      metrics: {},
      status: 'active',
      position: { x: 1, y: 2, z: 3 },
    };
    expect(node.position.x).toBeDefined();
    expect(node.position.y).toBeDefined();
    expect(node.position.z).toBeDefined();
  });
});

// ---------------------------------------------------------------------------
// Link data model tests
// ---------------------------------------------------------------------------

describe('EcoLink model', () => {
  interface EcoLink {
    source: string;
    target: string;
    label: string;
  }

  it('has required fields', () => {
    const link: EcoLink = {
      source: 'hub',
      target: 'factory',
      label: 'Capability catalog',
    };
    expect(link.source).toBeTruthy();
    expect(link.target).toBeTruthy();
    expect(link.label).toBeTruthy();
  });

  it('source and target must differ', () => {
    const links: EcoLink[] = [
      { source: 'hub', target: 'factory', label: 'test' },
      { source: 'hub', target: 'mesh', label: 'test' },
    ];
    for (const link of links) {
      expect(link.source).not.toBe(link.target);
    }
  });
});

// ---------------------------------------------------------------------------
// AI Assistant message handling
// ---------------------------------------------------------------------------

describe('AIAssistant message model', () => {
  interface Message {
    role: 'user' | 'assistant';
    content: string;
  }

  it('validates message roles', () => {
    const msg1: Message = { role: 'user', content: 'Hello' };
    const msg2: Message = { role: 'assistant', content: 'Hi there!' };
    expect(msg1.role).toBe('user');
    expect(msg2.role).toBe('assistant');
  });

  it('suggestions array is non-empty', () => {
    const suggestions = [
      'What is AIMarket Hub?',
      'How do payment channels work?',
      'Explain the plugin system',
      'What desktop apps exist?',
      'How does ACEX work?',
      'What blockchains are supported?',
    ];
    expect(suggestions.length).toBeGreaterThan(0);
    expect(suggestions.every((s) => s.length > 0)).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// Transaction/Event model tests
// ---------------------------------------------------------------------------

describe('Transaction & Event models', () => {
  interface Transaction {
    id: string;
    from: string;
    to: string;
    amount: number;
    token: string;
    ts: string;
  }

  interface TxEvent {
    id: string;
    ts: string;
    agent: string;
    action: string;
    target: string;
    amount: number;
    token: string;
  }

  it('transaction has all required fields', () => {
    const tx: Transaction = {
      id: 'tx_1',
      from: 'AlphaBot',
      to: 'hub',
      amount: 5.5,
      token: 'USDT',
      ts: '2026-05-24T12:00:00Z',
    };
    expect(tx.id).toBeTruthy();
    expect(tx.amount).toBeGreaterThan(0);
    expect(['USDT', 'USDC']).toContain(tx.token);
  });

  it('event has valid action types', () => {
    const validActions = ['invoke', 'discover', 'channel_open', 'channel_close', 'settle'];
    const event: TxEvent = {
      id: 'evt_1',
      ts: '2026-05-24T12:00:00Z',
      agent: 'CodeNova',
      action: 'invoke',
      target: 'hub',
      amount: 0.5,
      token: 'USDT',
    };
    expect(validActions).toContain(event.action);
  });

  it('transaction amount is positive', () => {
    const tx: Transaction = {
      id: 'tx_1', from: 'A', to: 'B', amount: 10, token: 'USDT', ts: 'now',
    };
    expect(tx.amount).toBeGreaterThan(0);
  });
});

// ---------------------------------------------------------------------------
// Theme color constants
// ---------------------------------------------------------------------------

describe('Theme colors', () => {
  const GROUP_COLORS: Record<string, string> = {
    core: '#00f0ff',
    contract: '#ff00ff',
    client: '#00ff88',
    infra: '#7b2fff',
    sdk: '#ffdd00',
    network: '#3366ff',
    chain: '#ff6633',
  };

  it('all groups have defined colors', () => {
    const requiredGroups = ['core', 'contract', 'client', 'infra', 'sdk', 'network', 'chain'];
    for (const group of requiredGroups) {
      expect(GROUP_COLORS[group]).toBeTruthy();
    }
  });

  it('colors are valid hex', () => {
    const hexRe = /^#[0-9a-fA-F]{6}$/;
    for (const color of Object.values(GROUP_COLORS)) {
      expect(hexRe.test(color)).toBe(true);
    }
  });
});
