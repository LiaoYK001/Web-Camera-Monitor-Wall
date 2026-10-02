import { useEffect, useMemo, useRef } from 'react';
import { startVisiblePolling } from './visiblePolling';

export function useVisiblePolling(task: (signal: AbortSignal) => Promise<void>, intervalMs: number) {
  const current = useRef<ReturnType<typeof startVisiblePolling> | null>(null);
  useEffect(() => {
    const poll = startVisiblePolling(task, intervalMs); current.current = poll;
    return () => { current.current = null; poll.stop(); };
  }, [task, intervalMs]);
  return useMemo(() => ({
    refresh: () => current.current?.refresh() ?? Promise.resolve(),
    pause: () => current.current?.pause(),
    resume: () => current.current?.resume() ?? Promise.resolve(),
  }), []);
}
