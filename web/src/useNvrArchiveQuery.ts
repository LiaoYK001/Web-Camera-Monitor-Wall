import { useCallback, useEffect, useRef, useState } from 'react';
import { ControlApiError, fetchNvrStatus, fetchNvrTimeline } from './api';
import { withRequestTimeout } from './requestTimeout';
import type { NvrTimeline } from './types';

type TimelineQuery = { key: string; loading: boolean; document: NvrTimeline | null; error: string };
export function archiveError(cause: unknown): string {
  if (cause instanceof ControlApiError) {
    if (cause.status === 401) return '登录已失效，请返回 Studio 重新登录。';
    if (cause.status === 403) return '当前账号没有此操作或摄像机的权限，请联系管理员。';
    if (cause.code === 'segment_conflict') return '片段已锁定，或仍被回放、导出使用。请处理相关播放或任务，再刷新时间线重试。';
    if (cause.status === 404) return '录像片段已不可用，请刷新时间线。';
    if (cause.status === 503) return '录像服务暂不可用，请检查服务状态后重试。';
  }
  if (cause instanceof Error && cause.name === 'TimeoutError') return '查询超时，请检查服务连接后重试。';
  if (cause instanceof TypeError) return '连接失败，请检查网络与服务状态后重试。';
  return cause instanceof Error ? cause.message : '查询失败，请检查服务连接后重试。';
}

/** Bind archive data to its exact selection so delayed responses cannot drive another camera/day. */
export function useNvrArchiveQuery(from: number, to: number) {
  const [cameraIds, setCameraIds] = useState<string[]>([]);
  const [availableIds, setAvailableIds] = useState<string[]>([]);
  const [diskPressure, setDiskPressure] = useState(false);
  const [catalogLoading, setCatalogLoading] = useState(true);
  const [catalogError, setCatalogError] = useState('');
  const [result, setResult] = useState<TimelineQuery | null>(null);
  const catalog = useRef<AbortController | null>(null);
  const query = useRef<AbortController | null>(null);
  const initialized = useRef(false);
  const key = JSON.stringify([from, to, cameraIds]);

  const reloadCatalog = useCallback(() => {
    catalog.current?.abort();
    const owner = new AbortController(); catalog.current = owner;
    setCatalogLoading(true); setCatalogError('');
    void withRequestTimeout(12_000, signal => fetchNvrStatus(signal), owner.signal).then(status => {
      if (owner.signal.aborted) return;
      const ids = status.cameras.map(camera => camera.id);
      setAvailableIds(ids); setDiskPressure(status.diskPressure);
      const first = !initialized.current; initialized.current = true;
      setCameraIds(current => {
        const next = first ? ids.slice(0, 4) : current.filter(id => ids.includes(id)).slice(0, 4);
        return next.length === current.length && next.every((id, index) => id === current[index]) ? current : next;
      });
    }).catch(cause => { if (!owner.signal.aborted) setCatalogError(archiveError(cause)); })
      .finally(() => { if (!owner.signal.aborted) setCatalogLoading(false); });
  }, []);

  const reload = useCallback(() => {
    query.current?.abort();
    const owner = new AbortController(); query.current = owner;
    if (!cameraIds.length) { setResult({ key, loading: false, document: null, error: '' }); return; }
    setResult({ key, loading: true, document: null, error: '' });
    void withRequestTimeout(12_000, signal => fetchNvrTimeline(from, to, cameraIds, signal), owner.signal)
      .then(document => { if (!owner.signal.aborted) setResult({ key, loading: false, document, error: '' }); })
      .catch(cause => { if (!owner.signal.aborted) setResult({ key, loading: false, document: null, error: archiveError(cause) }); });
  }, [cameraIds, from, to, key]);

  useEffect(() => { reloadCatalog(); return () => catalog.current?.abort(); }, [reloadCatalog]);
  useEffect(() => { reload(); return () => query.current?.abort(); }, [reload]);
  const current = result?.key === key ? result : null;
  return { cameraIds, setCameraIds, availableIds, diskPressure, catalogLoading, catalogError, reloadCatalog,
    timeline: current?.document ?? null, loading: !!cameraIds.length && (!current || current.loading),
    error: current?.error ?? '', reload, selectionKey: key };
}
