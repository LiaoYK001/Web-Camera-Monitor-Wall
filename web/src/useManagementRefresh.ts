import { useCallback, useEffect, useRef, useState } from 'react';
import { withRequestTimeout } from './requestTimeout';

export type ManagementRead = { key: string; label: string; load: (signal: AbortSignal) => Promise<() => void> };
export function managementRead<T>(key: string, label: string, read: (signal: AbortSignal) => Promise<T>, apply: (value: T) => void): ManagementRead {
  return { key, label, load: async signal => { const value = await read(signal); return () => apply(value); } };
}
/** Apply each successful section independently; no result can outlive its refresh generation. */
export function useManagementRefresh() {
  const active = useRef(false), owner = useRef<AbortController | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const cancel = useCallback(() => { owner.current?.abort(); owner.current = null; }, []);
  useEffect(() => { active.current = true; return () => { active.current = false; cancel(); }; }, [cancel]);
  const run = useCallback(async (reads: ManagementRead[], parent?: AbortSignal) => {
    cancel();
    if (!active.current || parent?.aborted) return;
    const controller = new AbortController(); owner.current = controller;
    const abort = () => controller.abort(); parent?.addEventListener('abort', abort, { once: true });
    const owns = () => active.current && owner.current === controller && !controller.signal.aborted;
    try {
      await Promise.all(reads.map(async read => {
        try {
          const apply = await withRequestTimeout(15000, read.load, controller.signal);
          if (!owns()) return;
          apply(); setErrors(current => { const next = { ...current }; delete next[read.key]; return next; });
        } catch {
          if (owns()) setErrors(current => ({ ...current, [read.key]: read.label + '读取失败或超时；保留上次数据，请刷新重试。' }));
        }
      }));
    } finally { parent?.removeEventListener('abort', abort); }
  }, [cancel]);
  return { run, cancel, errors };
}
