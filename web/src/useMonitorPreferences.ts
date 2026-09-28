import { useCallback, useEffect, useRef, useState } from 'react';
import { loadMonitorView, saveMonitorView } from './localRuntime';
import { defaultMonitorView, normalizeMonitorView, type MonitorView } from './monitorView';

/** Account preferences outlive the current scene and must not be trimmed to its sources. */
export function useMonitorPreferences(compact: boolean, skipLoad = false) {
  const [view, setView] = useState<MonitorView>(defaultMonitorView);
  const [loaded, setLoaded] = useState(skipLoad);
  const [error, setError] = useState('');
  const [retry, setRetry] = useState(0);
  const latest = useRef(view);
  const lastQueued = useRef('');
  const timer = useRef<number | null>(null);
  const mounted = useRef(false);
  const clearing = useRef(false);
  useEffect(() => {
    let active = true; mounted.current = true;
    if (skipLoad) { setLoaded(true); return () => { active = false; mounted.current = false; }; }
    setLoaded(false);
    void loadMonitorView().then((stored) => {
      if (!active) return;
      const next = normalizeMonitorView(stored, 16);
      latest.current = next; lastQueued.current = JSON.stringify(next);
      setView(next); setLoaded(true); setError('');
    }).catch(() => { if (active) setError('监控偏好读取失败，请重试。'); });
    return () => { active = false; mounted.current = false; };
  }, [compact, skipLoad, retry]);
  const persist = useCallback(() => {
    if (clearing.current) return;
    const next = normalizeMonitorView(latest.current, 16);
    const encoded = JSON.stringify(next);
    if (encoded === lastQueued.current) return;
    lastQueued.current = encoded;
    void saveMonitorView(next).then(() => { if (mounted.current) setError(''); }).catch(() => {
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
    const hidden = () => { if (document.hidden) flush(); };
    const clear = () => { clearing.current = true; if (timer.current !== null) window.clearTimeout(timer.current); timer.current = null; };
    document.addEventListener('visibilitychange', hidden);
    window.addEventListener('webobs:account-clearing', clear);
    return () => { document.removeEventListener('visibilitychange', hidden); window.removeEventListener('webobs:account-clearing', clear); flush(); };
  }, [persist]);
  return { view, setView, loaded, error, retry: () => setRetry((value) => value + 1) };
}
