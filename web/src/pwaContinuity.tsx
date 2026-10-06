import { type CSSProperties, useCallback, useEffect, useState } from 'react';
import { projectorModeFromHash } from './projector';
import { clearSecurityUpdateMarker, readSecurityUpdateMarker } from './securityUpdateMarker';

/**
 * Post-security-update continuity.
 *
 * A forced security replacement (see ./sw.ts) navigates every window into the
 * new shell without asking.  The new document owes the user three things:
 *
 *  1. an immediate, persistent explanation of what the replacement cost;
 *  2. a truthful split between what was lost (unsaved in-page input) and what
 *     survived (the encrypted local profile and the durable encrypted sync
 *     queue);
 *  3. no silent recovery mutations - the preserved queue is uploaded only after
 *     an explicit user action, and a lost evidence-export response is reconciled
 *     by reading the job list instead of re-posting.
 *
 * The durable record therefore stays a *suspend automatic syncing* flag until a
 * user action clears it.  Nothing here stores draft text or credentials.
 */
export type SecurityUpdateRecoveryState = 'checking' | 'active' | 'none';

const RECOVERY_EVENT = 'webobs:security-update-recovery';
const RECOVERY_CHANNEL = 'webobs-security-update';

let channel: BroadcastChannel | null = null;

function recoveryChannel(): BroadcastChannel | null {
  if (typeof BroadcastChannel === 'undefined') return null;
  try { channel ??= new BroadcastChannel(RECOVERY_CHANNEL); } catch { channel = null; }
  return channel;
}

/** Other windows and other components re-read the durable record on this signal. */
function announceRecovery(): void {
  window.dispatchEvent(new Event(RECOVERY_EVENT));
  try { recoveryChannel()?.postMessage('changed'); } catch { /* channel unavailable: same-window event still fires */ }
}

export interface SecurityUpdateRecoveryModel {
  /** 'checking' must never be treated as "no update": auto sync waits for a real answer. */
  state: SecurityUpdateRecoveryState;
  requiredAt: number | null;
  /** Explicit user action only (acknowledgement or a completed explicit sync). */
  clear: () => Promise<void>;
}

export function useSecurityUpdateRecovery(): SecurityUpdateRecoveryModel {
  const [state, setState] = useState<SecurityUpdateRecoveryState>('checking');
  const [requiredAt, setRequiredAt] = useState<number | null>(null);
  useEffect(() => {
    let live = true;
    const refresh = () => {
      void readSecurityUpdateMarker().then(
        (marker) => { if (!live) return; setRequiredAt(marker?.requiredAt ?? null); setState(marker ? 'active' : 'none'); },
        () => { if (live) { setRequiredAt(null); setState('none'); } },
      );
    };
    refresh();
    window.addEventListener(RECOVERY_EVENT, refresh);
    const broadcast = recoveryChannel();
    broadcast?.addEventListener('message', refresh);
    const visibility = () => { if (document.visibilityState === 'visible') refresh(); };
    document.addEventListener('visibilitychange', visibility);
    return () => {
      live = false;
      window.removeEventListener(RECOVERY_EVENT, refresh);
      broadcast?.removeEventListener('message', refresh);
      document.removeEventListener('visibilitychange', visibility);
    };
  }, []);
  const clear = useCallback(async () => {
    await clearSecurityUpdateMarker().catch(() => undefined);
    announceRecovery();
  }, []);
  return { state, requiredAt, clear };
}

const noticeStyle: CSSProperties = {
  display: 'grid', gap: '6px', margin: '0 auto', padding: '12px 16px',
  width: 'min(100%, 1180px)', boxSizing: 'border-box',
  border: '1px solid rgba(255, 176, 60, 0.55)', borderLeft: '4px solid #ffb03c',
  borderRadius: '10px', background: 'rgba(40, 28, 9, 0.97)', color: '#ffe6b8',
};
const actionStyle: CSSProperties = { display: 'flex', gap: '8px', flexWrap: 'wrap' };

/**
 * Persistent notice rendered by the shell owner (LoginGate) so it also covers the
 * authentication gate that a security update must replace immediately.
 */
export function SecurityUpdateRecoveryNotice() {
  const { state, requiredAt, clear } = useSecurityUpdateRecovery();
  const [projector] = useState(() => Boolean(projectorModeFromHash(window.location.hash)));
  if (projector || state !== 'active') return null;
  const openSync = () => {
    // The hash change goes through App's own guard, so a dirty Studio is never
    // silently discarded by this navigation.
    window.history.replaceState(null, '', '#/settings');
    window.dispatchEvent(new Event('hashchange'));
  };
  return <section className="notice security-update-notice" role="status" aria-labelledby="security-update-notice-title" style={noticeStyle}>
    <h2 id="security-update-notice-title" style={{ margin: 0, fontSize: '1rem' }}>安全更新恢复提示</h2>
    <p style={{ margin: 0 }}>旧版本页面已被安全更新强制替换并重新载入{requiredAt ? `（${new Date(requiredAt).toLocaleString()}）` : ''}。本机已保存的数据没有被删除，但旧页面里尚未保存的输入无法找回。</p>
    <ul style={{ margin: 0, paddingLeft: '20px', display: 'grid', gap: '4px' }}>
      <li><strong>未保存</strong>：旧页面中输入但未提交的内容（例如 Studio 的场景名称、画布、来源改动）随页面一起丢失，<strong>无法恢复</strong>，请重新输入或重新导入。</li>
      <li><strong>已保留</strong>：已保存的加密本机配置与离线同步队列仍在设备上。为避免再次覆盖，恢复期间不会自动上传；请先核对内容，再打开“同步与配对”并点击“立即同步”显式提交。</li>
      <li><strong>服务器任务</strong>：导出、备份等服务器端任务请到“导出任务”等任务列表核对实际状态，不要重复提交。</li>
    </ul>
    <div style={actionStyle}>
      <button type="button" className="primary-button" onClick={openSync}>查看同步与配对</button>
      <button type="button" className="ghost-button" onClick={() => void clear()}>我已了解，恢复自动同步</button>
    </div>
  </section>;
}
