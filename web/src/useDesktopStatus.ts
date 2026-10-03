import { useCallback, useEffect, useRef, useState } from 'react';
import type { DesktopStatus } from './desktopRuntime';

/** Push notifications supersede earlier IPC snapshots, including the initial read. */
export function useDesktopStatus() {
  const bridge = window.webobsDesktop;
  const [state, setState] = useState<DesktopStatus | null>(null);
  const [loading, setLoading] = useState(Boolean(bridge));
  const [error, setError] = useState('');
  const lifecycle = useRef(0), events = useRef(0), reads = useRef(0);
  const refresh = useCallback(async () => {
    if (!bridge) return;
    const epoch = lifecycle.current, event = events.current, request = ++reads.current;
    setLoading(true);
    try {
      const value = await bridge.status();
      if (lifecycle.current === epoch && reads.current === request && events.current === event) {
        setState(value); setError('');
      }
    } catch (reason) {
      if (lifecycle.current !== epoch || reads.current !== request || events.current !== event) return;
      setError('无法读取客户端状态，请稍后重试。');
      throw reason;
    } finally {
      if (lifecycle.current === epoch && reads.current === request) setLoading(false);
    }
  }, [bridge]);
  useEffect(() => {
    if (!bridge) return;
    const epoch = ++lifecycle.current;
    const unsubscribe = bridge.onStatus((value) => {
      if (lifecycle.current !== epoch) return;
      events.current++; setState(value); setError(''); setLoading(false);
    });
    void refresh().catch(() => undefined);
    return () => { lifecycle.current++; unsubscribe(); };
  }, [bridge, refresh]);
  return { bridge, state, loading, error, refresh };
}
