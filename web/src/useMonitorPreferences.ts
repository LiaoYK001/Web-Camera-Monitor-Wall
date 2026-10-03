import { isPageVisible, subscribePageVisibility } from './pageVisibility';
import { useCallback, useEffect, useRef, useState, type SetStateAction } from 'react';
import { flushMonitorView, loadMonitorView, saveMonitorView } from './localRuntime';
import { defaultMonitorView, normalizeMonitorView, type MonitorView } from './monitorView';
import { mergeMonitorEdits } from './monitorPreferenceMerge';

/** Account preferences outlive the current scene and must not be trimmed to its sources. */
export function useMonitorPreferences(compact: boolean, skipLoad = false, requireAccount = true) {
  const [view, applyView] = useState<MonitorView>(defaultMonitorView);
  const [loaded, setLoaded] = useState(skipLoad);
  const [restored, setRestored] = useState(skipLoad);
  const [error, setError] = useState('');
  const [retry, setRetry] = useState(0);
  const latest = useRef(view);
  const baseline = useRef<MonitorView | undefined>(defaultMonitorView());
  const lastQueued = useRef('');
  const lastSaved = useRef('');
  const saveGeneration = useRef(0);
  const writable = useRef(false);
  const editable = useRef(loaded);
  editable.current = loaded;
  writable.current = loaded && !compact && !skipLoad;
  const timer = useRef<number | null>(null);
  const mounted = useRef(false);
  const clearing = useRef(false);
  const setView = useCallback((update: SetStateAction<MonitorView>, seedBaseline?: (base: MonitorView) => MonitorView) => {
    if (!editable.current || clearing.current) return;
    // A source not yet stored inherits Scene/default controls. Preserve those
    // effective pre-edit values so creating its first preference edits only
    // the selected control, rather than resetting another window's controls.
    if (seedBaseline && baseline.current) baseline.current = normalizeMonitorView(seedBaseline(baseline.current), 16);
    const next = normalizeMonitorView(typeof update === 'function' ? update(latest.current) : update, 16);
    // Capture the edit during the input event, before pagehide or React effects.
    latest.current = next;
    applyView(next);
  }, []);
  useEffect(() => {
    let active = true; mounted.current = true;
    if (skipLoad) { setLoaded(true); return () => { active = false; mounted.current = false; }; }
    setLoaded(false);
    void loadMonitorView(false, requireAccount).then((stored) => {
      if (!active) return;
      const next = normalizeMonitorView(stored.view, 16);
      baseline.current = stored.baseValue === undefined ? undefined : normalizeMonitorView(stored.baseValue, 16);
      latest.current = next;
      lastQueued.current = stored.pending ? '' : JSON.stringify(next);
      lastSaved.current = stored.pending ? baseline.current ? JSON.stringify(baseline.current) : '' : JSON.stringify(next);
      applyView(next); setLoaded(true); setRestored(true);
      setError(stored.pending ? '监控偏好保存失败，请再次调整或稍后重试。' : '');
    }).catch(() => { if (active) setError('监控偏好读取失败，请重试。'); });
    return () => { active = false; mounted.current = false; };
  }, [compact, skipLoad, retry, requireAccount]);
  const persist = useCallback(() => {
    if (clearing.current || !writable.current) return;
    const next = normalizeMonitorView(latest.current, 16);
    const encoded = JSON.stringify(next);
    if (encoded === lastQueued.current) return;
    lastQueued.current = encoded;
    const generation = ++saveGeneration.current;
    void saveMonitorView(next, baseline.current).then((saved) => {
      if (generation !== saveGeneration.current) return;
      baseline.current = saved;
      lastQueued.current = lastSaved.current = JSON.stringify(saved);
      const merged = mergeMonitorEdits(saved, next, latest.current);
      if (JSON.stringify(merged) !== JSON.stringify(latest.current)) {
        latest.current = merged;
        if (mounted.current) applyView(merged);
      }
      if (mounted.current) setError('');
    }).catch(() => {
      if (generation !== saveGeneration.current || clearing.current) return;
      if (lastQueued.current === encoded) lastQueued.current = '';
      if (mounted.current) setError('监控偏好保存失败，请再次调整或稍后重试。');
    });
  }, []);
  useEffect(() => {
    latest.current = view;
    if (!loaded || compact || JSON.stringify(view) === lastQueued.current) return;
    timer.current = window.setTimeout(() => { timer.current = null; persist(); }, 250);
    return () => { if (timer.current !== null) window.clearTimeout(timer.current); };
  }, [view, loaded, compact, persist]);
  useEffect(() => {
    const flush = () => {
      if (timer.current === null) return;
      window.clearTimeout(timer.current); timer.current = null; persist();
    };
    const hidden = () => { if (!isPageVisible()) flush(); };
    const pagehide = () => {
      if (clearing.current || !writable.current || JSON.stringify(latest.current) === lastSaved.current) return;
      if (timer.current !== null) window.clearTimeout(timer.current);
      timer.current = null;
      saveGeneration.current++;
      void flushMonitorView(latest.current, baseline.current).catch(() => undefined);
    };
    const clear = () => { clearing.current = true; if (timer.current !== null) window.clearTimeout(timer.current); timer.current = null; };
    const unlistenHidden = subscribePageVisibility(hidden);
    window.addEventListener('pagehide', pagehide);
    window.addEventListener('webobs:account-clearing', clear);
    return () => { unlistenHidden(); window.removeEventListener('pagehide', pagehide); window.removeEventListener('webobs:account-clearing', clear); flush(); };
  }, [persist]);
  useEffect(() => {
    if (!loaded || skipLoad) return;
    let active = true; let reading = false;
    const refresh = async () => {
      if (!active || clearing.current || reading || !isPageVisible()) return;
      const before = JSON.stringify(latest.current);
      if (before !== lastSaved.current) { if (lastQueued.current === '') persist(); return; }
      reading = true;
      try {
        const stored = await loadMonitorView(true);
        if (!active || clearing.current || JSON.stringify(latest.current) !== before) return;
        const next = normalizeMonitorView(stored.view, 16);
        const encoded = JSON.stringify(next);
        // Retain object identity when another window has not changed the account.
        // Replacing it needlessly rebuilds layouts, rotation timers and media props.
        if (encoded !== before) { latest.current = next; applyView(next); }
        lastQueued.current = lastSaved.current = encoded;
        baseline.current = stored.baseValue === undefined ? undefined : normalizeMonitorView(stored.baseValue, 16);
        setError('');
      } catch { /* Keep the current preference while the server is unavailable. */ }
      finally { reading = false; }
    };
    const visible = () => { if (isPageVisible()) void refresh(); };
    const interval = window.setInterval(() => void refresh(), 5000);
    window.addEventListener('focus', visible); window.addEventListener('online', visible);
    const unlistenVisible = subscribePageVisibility(visible);
    return () => { active = false; window.clearInterval(interval); window.removeEventListener('focus', visible); window.removeEventListener('online', visible); unlistenVisible(); };
  }, [loaded, skipLoad, persist]);
  const retryPreferences = useCallback(() => {
    // Capture any input newer than the last failed request before reloading the
    // pending private cache. loadMonitorView waits for this serialized write.
    persist();
    setError('');
    setRetry((value) => value + 1);
  }, [persist]);
  return { view, setView, loaded, restored, error, retry: retryPreferences };
}
