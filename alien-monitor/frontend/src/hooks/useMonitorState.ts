import { useCallback, useEffect, useRef, useState } from 'react';
import type { EcosystemState } from '../App';
import { apiUrl } from '../api';
import { monitorAuthHeaders } from '../monitorAuth';
import { useWebSocket } from './useWebSocket';

type Mode = 'test' | 'real' | 'universe';

type TopologyPayload = {
  nodes: EcosystemState['nodes'];
  links: EcosystemState['links'];
};

function topologyToState(
  topology: TopologyPayload,
  summary: Partial<EcosystemState['summary']> | null,
  mode: Mode,
): EcosystemState {
  const now = new Date().toISOString();
  return {
    tick: summary?.tick ?? 0,
    ts: now,
    nodes: topology.nodes ?? [],
    links: topology.links ?? [],
    events: [],
    transactions: [],
    channels: [],
    summary: {
      total_invocations_24h: summary?.total_invocations_24h ?? 0,
      total_volume_usd: summary?.total_volume_usd ?? 0,
      active_channels: summary?.active_channels ?? 0,
      tvl_usd: summary?.tvl_usd ?? 0,
      agents_online: summary?.agents_online ?? 0,
      apps_online: summary?.apps_online ?? 0,
      tps_solana: summary?.tps_solana ?? 0,
      gas_gwei: summary?.gas_gwei ?? 0,
      mode: summary?.mode ?? mode,
      tick: summary?.tick ?? 0,
      blockchain_ready: summary?.blockchain_ready,
      products_created: summary?.products_created,
      entities_total: summary?.entities_total,
      evm_rpc: summary?.evm_rpc,
      usdt_contract: summary?.usdt_contract,
      scenario_phase: summary?.scenario_phase,
      block_number: summary?.block_number,
      onchain_tx_count: summary?.onchain_tx_count,
    },
  };
}

/** WebSocket stream with HTTP /api/state fallback (fixes blank graph when WS is slow or blocked). */
export function useMonitorState(mode: Mode | null) {
  const [state, setState] = useState<EcosystemState | null>(null);
  const [wsConnected, setWsConnected] = useState(false);
  const [connectionError, setConnectionError] = useState<string | null>(null);
  const lastWsAt = useRef(0);
  const hasState = useRef(false);

  const handleStateUpdate = useCallback((newState: EcosystemState) => {
    lastWsAt.current = Date.now();
    hasState.current = true;
    setWsConnected(true);
    setConnectionError(null);
    setState(newState);
  }, []);

  const mergeIfRicher = useCallback((incoming: EcosystemState) => {
    setState((prev) => {
      if (!prev?.nodes?.length) return incoming;
      const prevOracles = prev.nodes.filter((n) => n.group === 'oracle').length;
      const nextOracles = incoming.nodes.filter((n) => n.group === 'oracle').length;
      if (nextOracles < prevOracles || incoming.nodes.length + 4 < prev.nodes.length) {
        return prev;
      }
      return incoming;
    });
  }, []);

  useWebSocket(mode, handleStateUpdate);

  useEffect(() => {
    if (!mode) return;
    let cancelled = false;

    const pullTopologyFallback = async (): Promise<EcosystemState | null> => {
      const headers = monitorAuthHeaders();
      const [topRes, sumRes] = await Promise.all([
        fetch(apiUrl(`/api/topology?mode=${mode}`), { cache: 'no-store', headers }),
        fetch(apiUrl(`/api/summary?mode=${mode}`), { cache: 'no-store', headers }),
      ]);
      if (!topRes.ok) return null;
      const topology = (await topRes.json()) as TopologyPayload;
      if (!topology?.nodes?.length) return null;
      let summary: Partial<EcosystemState['summary']> | null = null;
      if (sumRes.ok) {
        summary = (await sumRes.json()) as Partial<EcosystemState['summary']>;
      }
      return topologyToState(topology, summary, mode);
    };

    const pull = async () => {
      try {
        const res = await fetch(apiUrl(`/api/state?mode=${mode}`), {
          cache: 'no-store',
          headers: monitorAuthHeaders(),
        });
        if (res.ok) {
          const data = (await res.json()) as EcosystemState;
          if (cancelled || !data?.nodes?.length) return;
          const staleWs = Date.now() - lastWsAt.current > 4000;
          if (staleWs || !hasState.current) {
            hasState.current = true;
            setConnectionError(null);
            mergeIfRicher(data);
          }
          return;
        }

        const fallback = await pullTopologyFallback();
        if (cancelled || !fallback?.nodes?.length) {
          if (!hasState.current && (res.status === 401 || res.status === 403 || res.status === 503)) {
            setConnectionError('auth');
          }
          return;
        }
        const staleWs = Date.now() - lastWsAt.current > 4000;
        if (staleWs || !hasState.current) {
          hasState.current = true;
          setConnectionError(null);
          mergeIfRicher(fallback);
        }
      } catch {
        if (!hasState.current) setConnectionError('network');
      }
    };

    pull();
    const id = window.setInterval(pull, 3000);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, [mode, mergeIfRicher]);

  return { state, setState, wsConnected, connectionError };
}
