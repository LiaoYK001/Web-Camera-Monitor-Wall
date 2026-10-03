import { useCallback, useEffect, useRef, useState } from 'react';
import { currentBrowserPairing, type BrowserPairingState } from './browserEnrollment';
import { loadSyncQueue, loadSyncState, type LocalSyncState } from './localRuntime';
import { resolveSyncConflicts, synchronizeBrowserState } from './syncRuntime';
import { startVisiblePolling } from './visiblePolling';

/** Owned by the main workspace, never by projector windows or individual panels. */
export function useDeviceSync() {
  const [pairing, setPairing] = useState<BrowserPairingState | null>(null);
  const [state, setState] = useState<LocalSyncState | null>(null);
  const [pending, setPending] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const mounted = useRef(false);
  const operation = useRef(false);
  const epoch = useRef(0);
  const read = useCallback(async () => {
    const revision = epoch.current;
    const [identity, cached, queue] = await Promise.all([currentBrowserPairing(), loadSyncState(), loadSyncQueue()]);
    if (!mounted.current || revision !== epoch.current) return;
    setPairing(identity); setState(cached); setPending(queue?.mutations.length ?? 0);
  }, []);
  const sync = useCallback(async (choice?: 'local' | 'server') => {
    if (operation.current || !navigator.onLine) return;
    operation.current = true;
    const revision = epoch.current;
    setBusy(true); setError('');
    try {
      if (choice) await resolveSyncConflicts(choice);
      else await synchronizeBrowserState();
    } catch (reason) {
      if (mounted.current && revision === epoch.current)
        setError(reason instanceof Error ? reason.message : '同步失败；本机保存会保留，请稍后重试。');
    } finally {
      operation.current = false;
      if (mounted.current) { setBusy(false); await read().catch(() => undefined); }
    }
  }, [read]);
  useEffect(() => {
    mounted.current = true;
    const refresh = () => { void read().catch(() => undefined); };
    const clear = () => { epoch.current++; setPairing(null); setState(null); setPending(0); setError(''); };
    refresh();
    const events = ['webobs:browser-authorization-changed', 'webobs:sync-state', 'webobs:sync-pending'];
    events.forEach(event => window.addEventListener(event, refresh));
    window.addEventListener('webobs:account-clearing', clear);
    return () => {
      mounted.current = false;
      events.forEach(event => window.removeEventListener(event, refresh));
      window.removeEventListener('webobs:account-clearing', clear);
    };
  }, [read]);
  const approved = pairing?.state === 'approved';
  useEffect(() => {
    if (!approved) return;
    const polling = startVisiblePolling(async () => { await sync(); }, 30000);
    return () => polling.stop();
  }, [approved, sync]);
  return { pairing, state, pending, busy, error, sync, read };
}
export type DeviceSyncModel = ReturnType<typeof useDeviceSync>;
