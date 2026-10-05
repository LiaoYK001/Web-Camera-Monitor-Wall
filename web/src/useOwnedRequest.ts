import { useEffect, useRef, useState } from 'react';
import { ControlApiError } from './api';
import { withRequestTimeout } from './requestTimeout';

/** One synchronous owner for an editor operation; late results never write into a new owner. */
export function useOwnedRequest(report: (message: string) => void, beforeMutation?: () => void) {
  const active = useRef(false);
  const owner = useRef<{ controller: AbortController; mutation: boolean; name: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [mutating, setMutating] = useState(false);
  useEffect(() => {
    active.current = true;
    return () => { active.current = false; owner.current?.controller.abort(); owner.current = null; };
  }, []);
  const cancelRead = () => {
    if (!owner.current || owner.current.mutation) return;
    owner.current.controller.abort(); owner.current = null; setBusy(false); setMutating(false);
  };
  const run = async <T,>(name: string, operation: (signal: AbortSignal) => Promise<T>, apply: (value: T) => void,
    mutation = true, failed?: (reason: unknown) => void): Promise<boolean> => {
    if (!active.current || owner.current) return false;
    const current = { controller: new AbortController(), mutation, name }; owner.current = current;
    if (mutation) beforeMutation?.();
    setBusy(true); setMutating(mutation); report('');
    const owns = () => active.current && owner.current === current && !current.controller.signal.aborted;
    try {
      const value = await withRequestTimeout(20000, operation, current.controller.signal);
      if (!owns()) return false;
      apply(value); return true;
    } catch (reason) {
      if (owns()) {
        failed?.(reason);
        report(reason instanceof ControlApiError && reason.status === 403 ? `${name}失败：当前账号没有操作权限，请联系管理员。`
          : reason instanceof ControlApiError && reason.status === 401 ? `${name}失败：登录已失效，请重新登录。`
            : reason instanceof DOMException && reason.name === 'TimeoutError' ? mutation
              ? `${name}超时，结果尚未确认；请先刷新核对，勿立即重复提交。`
              : `${name}超时，请检查网络后重试。`
            : `${name}失败：${reason instanceof Error ? reason.message : '服务暂不可用'}。请检查网络或刷新状态后重试。`);
      }
      return false;
    } finally {
      if (active.current && owner.current === current) { owner.current = null; setBusy(false); setMutating(false); }
    }
  };
  return { run, busy, mutating, cancelRead, isMutating: () => owner.current?.mutation === true };
}
