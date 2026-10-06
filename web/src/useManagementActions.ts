import { useEffect, useRef, useState } from 'react';
import { ControlApiError } from './api';
import { desktopTask } from './desktopRuntime';
import { withRequestTimeout } from './requestTimeout';

export type ManagementActionState = { phase: 'pending' | 'unknown' | 'conflict' | 'failed'; message: string; identity: string };
export type Reconciliation = { resolved: boolean; message: string; apply?: () => void };

/** Page-memory only. An aborted transport is not a server-side rollback. */
export function useManagementActions(beforeMutation: () => void) {
  const active = useRef(false);
  const owners = useRef(new Map<string, AbortController>());
  const records = useRef<Record<string, ManagementActionState>>({});
  const [states, setStates] = useState<Record<string, ManagementActionState>>({});
  const before = useRef(beforeMutation); before.current = beforeMutation;
  const publish = (key: string, state?: ManagementActionState) => {
    const next = { ...records.current };
    if (state) next[key] = state; else delete next[key];
    records.current = next; setStates(next);
  };
  useEffect(() => {
    active.current = true;
    // The ref also guards same-event navigation, before React commits disabled buttons.
    const leave = (event: Event) => { if (owners.current.size) event.preventDefault(); };
    window.addEventListener('webobs:before-navigate', leave);
    return () => {
      active.current = false;
      owners.current.forEach(controller => controller.abort()); owners.current.clear();
      window.removeEventListener('webobs:before-navigate', leave);
    };
  }, []);
  const blocked = (key: string) => owners.current.has(key) || records.current[key]?.phase === 'unknown';
  const run = async <T,>(key: string, name: string, identity: string,
    operation: (signal: AbortSignal) => Promise<T>, apply: (value: T) => void, related: string[] = []): Promise<boolean> => {
    const keys = [key, ...related];
    if (!active.current || keys.some(blocked)) return false;
    const controller = new AbortController();
    keys.forEach(item => owners.current.set(item, controller));
    const finishWork = desktopTask('management-action:' + key);
    const owns = () => active.current && owners.current.get(key) === controller && !controller.signal.aborted;
    before.current(); publish(key, { phase: 'pending', message: name + '处理中…', identity });
    try {
      const result = await withRequestTimeout(20000, operation, controller.signal);
      if (!owns()) return false;
      before.current(); // Invalidate refreshes started while the mutation was in flight.
      publish(key); apply(result); return true;
    } catch (reason) {
      if (!owns()) return false;
      const status = reason instanceof ControlApiError ? reason.status : 0;
      const conflict = status === 409 || status === 412;
      const definite = status >= 400 && status < 500 && status !== 408;
      const phase = conflict ? 'conflict' : definite ? 'failed' : 'unknown';
      const message = conflict ? name + '发生 revision / 状态冲突；请刷新核对，草稿已保留。'
        : status === 403 ? name + '失败：当前账号没有操作权限。'
          : status === 401 ? name + '失败：登录已失效，请重新登录。'
            : definite ? name + '被服务端拒绝；请检查输入并刷新核对。'
              : name + '结果尚未确认；请求超时或响应丢失不代表服务端撤销。请只读核对，勿重复提交。';
      publish(key, { phase, message, identity });
      // Keep related resources locked too (e.g. approval replacing an existing client).
      if (phase === 'unknown') related.forEach(item => publish(item, { phase, message, identity }));
      return false;
    } finally {
      keys.forEach(item => { if (owners.current.get(item) === controller) owners.current.delete(item); });
      finishWork();
    }
  };
  const reconcile = async (key: string, read: (signal: AbortSignal) => Promise<Reconciliation>, related: string[] = []) => {
    const previous = records.current[key];
    if (!active.current || !previous || owners.current.has(key)) return;
    const controller = new AbortController(); owners.current.set(key, controller);
    publish(key, { ...previous, phase: 'pending', message: '只读核对中…' });
    try {
      const result = await withRequestTimeout(15000, read, controller.signal);
      if (!active.current || owners.current.get(key) !== controller || controller.signal.aborted) return;
      result.apply?.();
      if (result.resolved) { publish(key); related.forEach(item => publish(item)); }
      else publish(key, { ...previous, message: result.message });
    } catch {
      if (active.current && owners.current.get(key) === controller && !controller.signal.aborted)
        publish(key, { ...previous, message: '核对失败；原结果仍未确认，未重发修改请求。' });
    } finally { if (owners.current.get(key) === controller) owners.current.delete(key); }
  };
  return { states, run, reconcile, blocked, clear: (key: string) => { if (!blocked(key)) publish(key); },
    pending: Object.values(states).some(state => state.phase === 'pending'),
    uncertain: Object.values(states).some(state => state.phase === 'unknown') };
}
export type ManagementActions = ReturnType<typeof useManagementActions>;
