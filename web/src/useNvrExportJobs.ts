import { useCallback, useEffect, useRef, useState } from 'react';
import { cancelNvrExportJob, ControlApiError, fetchAuthSession, fetchNvrExportJobs, submitNvrExportJob } from './api';
import { useDesktopWork } from './desktopRuntime';
import { withRequestTimeout } from './requestTimeout';
import type { NvrExportJob, NvrExportRequest } from './types';

type Submission = NvrExportRequest & { requestId: string };
export const exportActive = (job: NvrExportJob) => ['queued', 'running', 'cancelling'].includes(job.state);
export function exportError(error: unknown): string {
  const code = error instanceof ControlApiError ? error.code :
    typeof error === 'object' && error !== null && 'code' in error ? String(error.code) : '';
  const messages: Record<string, string> = {
    export_range_incomplete: '所选时间存在断档、缺少录像或片段重叠。请缩小范围；快速导出可保留已有片段并在清单中注明断档。',
    export_disk_full: '导出磁盘空间不足。请先腾出空间，再重试；导出不会自动删除原录像。',
    export_interrupted: '服务重启中断了任务。已有录像保留，可重新提交导出。',
    export_timeout: '导出超过处理时限。请缩短时间范围或减少摄像机后重试。',
    export_conversion_failed: '视频转换失败。请检查源片段是否可播放，或尝试较短范围。',
    export_duration_mismatch: '视频实际长度与时间范围不符，导出已取消。请检查录像完整性。',
    export_source_changed: '源录像与原始摘要不符，导出已停止。请检查录像完整性。',
    export_range_too_large: '范围内片段过多，请缩短导出时间。',
    export_scope_rejected: '导出权限或摄像机权限已变更，请联系管理员。',
    export_queue_full: '导出队列已满或服务正在停止，请稍后重试。',
    permission_rejected: '当前账号没有证据导出权限，请联系管理员分配 exporter 角色或导出权限。',
  };
  return messages[code] ?? (error instanceof Error ? error.message : '导出失败，请检查录像和存储状态。');
}

export function useNvrExportJobs() {
  const [jobs, setJobs] = useState<NvrExportJob[]>([]);
  const [pending, setPending] = useState<Submission | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [ready, setReady] = useState(false);
  const [allowed, setAllowed] = useState(true);
  const lifecycle = useRef<AbortController | null>(null);
  const storageKey = useRef('');
  const pendingRef = useRef<Submission | null>(null);
  const busyRef = useRef(false);
  const reading = useRef(false);
  const generation = useRef(0);
  const nextPoll = useRef(0);
  useDesktopWork('nvr-evidence', false, busy || jobs.some(exportActive));

  const savePending = useCallback((value: Submission | null) => {
    pendingRef.current = value; setPending(value);
    try {
      if (value) sessionStorage.setItem(storageKey.current, JSON.stringify(value));
      else sessionStorage.removeItem(storageKey.current);
    } catch { setError('浏览器暂时无法保存待确认请求；离开前请确认任务列表中已出现本次导出。'); }
  }, []);

  const refresh = useCallback(async () => {
    const owner = lifecycle.current;
    if (!owner || owner.signal.aborted || !storageKey.current || reading.current || busyRef.current) return;
    reading.current = true;
    const current = ++generation.current;
    try {
      const result = await withRequestTimeout(12_000, signal => fetchNvrExportJobs(signal), owner.signal);
      if (owner.signal.aborted || current !== generation.current) return;
      setJobs(result.jobs);
      setAllowed(true);
      nextPoll.current = Date.now() + (result.jobs.some(exportActive) ? 5000 : 30_000);
      if (pendingRef.current && result.jobs.some(job => job.requestId === pendingRef.current?.requestId)) savePending(null);
      if (!pendingRef.current) setError('');
    } catch (cause) {
      if (!owner.signal.aborted && current === generation.current) {
        if (cause instanceof ControlApiError && cause.status === 403) { setAllowed(false); setJobs([]); }
        nextPoll.current = Date.now() + 30_000;
        setError(`任务状态暂不可读取：${exportError(cause)}`);
      }
    } finally { reading.current = false; }
  }, [savePending]);

  useEffect(() => {
    const owner = new AbortController(); lifecycle.current = owner;
    storageKey.current = ''; setReady(false);
    void withRequestTimeout(10_000, signal => fetchAuthSession(signal), owner.signal).then(session => {
      if (owner.signal.aborted) return;
      storageKey.current = `webobs:nvr-submission:${session.user ?? 'local-only'}`;
      try {
        const raw = sessionStorage.getItem(storageKey.current);
        const value = raw && raw.length < 2048 ? JSON.parse(raw) as Submission : null;
        if (value && /^[a-f0-9-]{32,36}$/.test(value.requestId) && Array.isArray(value.cameraIds)
          && value.cameraIds.length >= 1 && value.cameraIds.length <= 4 && value.cameraIds.every(id => typeof id === 'string' && /^[A-Za-z0-9._-]{1,64}$/.test(id))
          && Number.isSafeInteger(value.fromUtcMs) && Number.isSafeInteger(value.toUtcMs)
          && value.toUtcMs > value.fromUtcMs && ['fast', 'exact'].includes(value.mode)) savePending(value);
      } catch { /* Corrupt private tab state cannot submit an export. */ }
      setReady(true); void refresh();
    }).catch(cause => { if (!owner.signal.aborted) setError(exportError(cause)); });
    const timer = window.setInterval(() => { if (!document.hidden && Date.now() >= nextPoll.current) void refresh(); }, 5000);
    const visible = () => { if (!document.hidden) void refresh(); };
    document.addEventListener('visibilitychange', visible);
    return () => { owner.abort(); window.clearInterval(timer); document.removeEventListener('visibilitychange', visible); };
  }, [refresh, savePending]);

  const action = useCallback(async (operation: (signal: AbortSignal) => Promise<NvrExportJob>, submitting = false) => {
    const owner = lifecycle.current;
    if (busyRef.current || !owner || owner.signal.aborted || !storageKey.current) return;
    busyRef.current = true; ++generation.current; setBusy(true); setError('');
    try {
      const job = await withRequestTimeout(12_000, operation, owner.signal);
      if (owner.signal.aborted) return;
      setJobs(current => [job, ...current.filter(item => item.id !== job.id)].sort((a, b) => b.createdUtcMs - a.createdUtcMs));
      if (submitting) savePending(null);
    } catch (cause) {
      if (owner.signal.aborted) return;
      if (submitting && cause instanceof ControlApiError && cause.status >= 400 && cause.status < 500) savePending(null);
      setError(submitting ? `提交结果待确认：${exportError(cause)} 请先刷新任务或恢复同一次提交。` : exportError(cause));
    } finally {
      busyRef.current = false;
      if (!owner.signal.aborted) { setBusy(false); void refresh(); }
    }
  }, [refresh, savePending]);

  const submit = useCallback((request: NvrExportRequest) => {
    if (busyRef.current || !storageKey.current || pendingRef.current) return;
    const value = { ...request, requestId: crypto.randomUUID() };
    savePending(value); void action(signal => submitNvrExportJob(value, signal), true);
  }, [action, savePending]);
  return { jobs, pending, error, busy, ready, allowed, refresh, submit,
    recover: () => { if (pendingRef.current) { const value = pendingRef.current; void action(signal => submitNvrExportJob(value, signal), true); } },
    cancel: (id: string) => { void action(signal => cancelNvrExportJob(id, signal)); } };
}
