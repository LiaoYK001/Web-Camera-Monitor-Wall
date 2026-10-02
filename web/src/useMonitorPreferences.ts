import { isPageVisible, subscribePageVisibility } from './pageVisibility';
import { useCallback, useEffect, useRef, useState, type SetStateAction } from 'react';
import { flushMonitorView, loadMonitorView, saveMonitorView } from './localRuntime';
import { defaultMonitorView, normalizeMonitorView, type MonitorView } from './monitorView';

/** Account preferences outlive the current scene and must not be trimmed to its sources. */
export function useMonitorPreferences(compact: boolean, skipLoad = false) {
  const [view, applyView] = useState<MonitorView>(defaultMonitorView);
  const [loaded, setLoaded] = useState(skipLoad);
  const [error, setError] = useState('');
  const [retry, setRetry] = useState(0);
  const latest = useRef(view);
  const lastQueued = useRef('');
  const lastSaved = useRef('');
  const saveGeneration = useRef(0);
  const writable = useRef(false);
  writable.current = loaded && !compact && !skipLoad;
  const timer = useRef<number | null>(null);
  const mounted = useRef(false);
  const clearing = useRef(false);
  const setView = useCallback((update: SetStateAction<MonitorView>) => {
    const next = normalizeMonitorView(typeof update === 'function' ? update(latest.current) : update, 16);
    // Capture the edit during the input event, before pagehide or React effects.
    latest.current = next;
    applyView(next);
  }, []);
  useEffect(() => {
    let active = true; mounted.current = true;
    if (skipLoad) { setLoaded(true); return () => { active = false; mounted.current = false; }; }
    setLoaded(false);
    void loadMonitorView().then((stored) => {
      if (!active) return;
      const next = normalizeMonitorView(stored, 16);
      latest.current = next; lastQueued.current = lastSaved.current = JSON.stringify(next);
      applyView(next); setLoaded(true); setError('');
    }).catch(() => { if (active) setError('监控偏好读取失败，请重试。'); });
    return () => { active = false; mounted.current = false; };
  }, [compact, skipLoad, retry]);
  const persist = useCallback(() => {
    if (clearing.current || !writable.current) return;
    const next = normalizeMonitorView(latest.current, 16);
    const encoded = JSON.stringify(next);
    if (encoded === lastQueued.current) return;
    lastQueued.current = encoded;
    const generation = ++saveGeneration.current;
    void saveMonitorView(next).then(() => {
      if (generation !== saveGeneration.current) return;
      lastSaved.current = encoded;
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
      void flushMonitorView(latest.current).catch(() => undefined);
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
        const next = normalizeMonitorView(stored, 16);
        const encoded = JSON.stringify(next);
        // Retain object identity when another window has not changed the account.
        // Replacing it needlessly rebuilds layouts, rotation timers and media props.
        if (encoded !== before) { latest.current = next; applyView(next); }
        lastQueued.current = lastSaved.current = encoded;
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
  return { view, setView, loaded, error, retry: () => setRetry((value) => value + 1) };
}
