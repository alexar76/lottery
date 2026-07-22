import { useEffect, useRef } from 'react';
import { monitorWsUrl } from '../monitorAuth';

type Mode = 'test' | 'real' | 'universe';

export function useWebSocket(
  mode: Mode | null,
  onStateUpdate: (state: any) => void,
  onModeChanged?: (mode: Mode) => void,
) {
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const unmountedRef = useRef(false);
  const modeRef = useRef<Mode | null>(mode);
  modeRef.current = mode;

  useEffect(() => {
    if (!mode || wsRef.current?.readyState !== WebSocket.OPEN) return;
    wsRef.current.send(JSON.stringify({ cmd: 'set_mode', mode }));
  }, [mode]);

  useEffect(() => {
    if (!mode) return;

    unmountedRef.current = false;
    const wsUrl = monitorWsUrl();

    function connect() {
      if (unmountedRef.current || !modeRef.current) return;
      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;

      ws.onopen = () => {
        if (modeRef.current) {
          ws.send(JSON.stringify({ cmd: 'set_mode', mode: modeRef.current }));
        }
      };

      ws.onmessage = (event) => {
        try {
          const msg = JSON.parse(event.data);
          if (msg.type === 'state_update' && msg.data) {
            onStateUpdate(msg.data);
          } else if (
            msg.type === 'mode_changed'
            && (msg.mode === 'test' || msg.mode === 'real' || msg.mode === 'universe')
          ) {
            onModeChanged?.(msg.mode);
          }
        } catch {
          // ignore parse errors
        }
      };

      ws.onclose = () => {
        wsRef.current = null;
        if (unmountedRef.current) return;
        reconnectTimerRef.current = setTimeout(connect, 2000);
      };

      ws.onerror = () => {
        ws.close();
      };
    }

    connect();

    return () => {
      unmountedRef.current = true;
      if (reconnectTimerRef.current) {
        clearTimeout(reconnectTimerRef.current);
        reconnectTimerRef.current = null;
      }
      if (wsRef.current) {
        wsRef.current.close();
        wsRef.current = null;
      }
    };
  }, [mode, onStateUpdate, onModeChanged]);
}
