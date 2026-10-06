import { useCallback, useEffect, useRef, useState } from 'react';
import { currentBrowserPairing, type BrowserPairingState } from './browserEnrollment';
import { loadSyncQueue, loadSyncState, type LocalSyncState } from './localRuntime';
import { useSecurityUpdateRecovery } from './pwaContinuity';
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
  // 'checking' is not "no update": uploads wait for a definitive answer so a
  // forced security replacement can never be followed by a silent recovery POST.
  const recovery = useSecurityUpdateRecovery();
  const recoveryState = recovery.state;
  const clearRecovery = recovery.clear;
  const read = useCallback(async () => {
    const revision = epoch.current;
    const [identity, cached, queue] = await Promise.all([currentBrowserPairing(), loadSyncState(), loadSyncQueue()]);
    if (!mounted.current || revision !== epoch.current) return;
    setPairing(identity); setState(cached); setPending(queue?.mutations.length ?? 0);
  }, []);
  /** `explicit` is the user pressing a sync control; only that clears the update record. */
  const sync = useCallback(async (choice?: 'local' | 'server', explicit = true) => {
    if (operation.current || !navigator.onLine) return;
    operation.current = true;
    const revision = epoch.current;
    setBusy(true); setError('');
    try {
      if (choice) await resolveSyncConflicts(choice);
      else await synchronizeBrowserState();
      // A completed explicit sync is the user's own confirmation that the
      // preserved queue is safe to upload, so automatic syncing may resume.
      if (explicit) await clearRecovery();
    } catch (reason) {
      if (mounted.current && revision === epoch.current)
        setError(reason instanceof Error ? reason.message : '同步失败；本机保存会保留，请稍后重试。');
    } finally {
      operation.current = false;
      if (mounted.current) { setBusy(false); await read().catch(() => undefined); }
    }
  }, [read, clearRecovery]);
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
    // After a forced security replacement the durable queue stays on the device
    // until the user explicitly syncs it: no mount-time upload, no timer upload.
    if (!approved || recoveryState !== 'none') return;
    const polling = startVisiblePolling(async () => { await sync(undefined, false); }, 30000);
    return () => polling.stop();
  }, [approved, recoveryState, sync]);
  return { pairing, state, pending, busy, error, sync, read };
}
export type DeviceSyncModel = ReturnType<typeof useDeviceSync>;
