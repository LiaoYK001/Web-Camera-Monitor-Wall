import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { acknowledgeOperationalIssue, fetchOperationalIssues } from './api';
import { subscribeLocalIssues } from './issueRuntime';
import type { OperationalIssue } from './types';
import Modal from './Modal';

const severityLabel = { info: '信息', warning: '警告', error: '错误' } as const;

function diagnosticDocument(issue: OperationalIssue) {
  return {
    code: issue.code, severity: issue.severity, state: issue.state, scopeKind: issue.scopeKind,
    scopeId: issue.scopeId, component: issue.component, firstSeenAt: issue.firstSeenAt,
    lastSeenAt: issue.lastSeenAt, occurrences: issue.occurrences,
    technicalDetails: issue.technicalDetails,
  };
}
export default function ProblemCenter() {
  const [open, setOpen] = useState(false);
  const [server, setServer] = useState<OperationalIssue[]>([]);
  const [local, setLocal] = useState<OperationalIssue[]>([]);
  const [severity, setSeverity] = useState('');
  const [component, setComponent] = useState('');
  const [scope, setScope] = useState('');
  const [state, setState] = useState('active');
  const [error, setError] = useState('');
  const [actionError, setActionError] = useState('');
  const [notice, setNotice] = useState('');
  const [busyId, setBusyId] = useState('');
  const [loading, setLoading] = useState(false);
  const request = useRef<AbortController | null>(null);
  const reload = useCallback(async () => {
    if (request.current) return;
    const controller = new AbortController(); request.current = controller; setLoading(true);
    try {
      const value = await fetchOperationalIssues('', controller.signal);
      if (!controller.signal.aborted) { setServer(value.issues); setError(''); }
    } catch { if (!controller.signal.aborted) setError('服务端问题列表暂时不可用，可点击刷新重试。'); }
    finally { if (request.current === controller) { request.current = null; setLoading(false); } }
  }, []);
  useEffect(() => {
    let active = true;
    let pending = false;
    const poll = async () => {
      if (!active || pending || document.hidden) return;
      pending = true;
      try { await reload(); } finally { pending = false; }
    };
    void poll();
    const visible = () => { if (!document.hidden) void poll(); };
    const timer = window.setInterval(() => void poll(), 10_000);
    document.addEventListener('visibilitychange', visible);
    return () => { active = false; request.current?.abort(); request.current = null; window.clearInterval(timer); document.removeEventListener('visibilitychange', visible); };
  }, [reload]);
  useEffect(() => subscribeLocalIssues(setLocal), []);
  useEffect(() => {
    const show = (event: Event) => {
      const value = (event as CustomEvent<{ scopeId?: string }>).detail?.scopeId ?? '';
      setScope(value); setState('active'); setSeverity(''); setComponent(''); setOpen(true);
    };
    window.addEventListener('webobs:open-issues', show);
    return () => window.removeEventListener('webobs:open-issues', show);
  }, []);
  const all = useMemo(() => {
    const merged = new Map<string, OperationalIssue>();
    [...server, ...local].forEach((issue) => merged.set(issue.id, issue));
    return [...merged.values()].sort((left, right) => {
      const rank = { open: 0, acknowledged: 1, resolved: 2 };
      return rank[left.state] - rank[right.state] || right.lastSeenAt - left.lastSeenAt;
    });
  }, [local, server]);
  const filtered = all.filter((issue) => (!severity || issue.severity === severity)
    && (!component || issue.component === component) && (!scope || issue.scopeId.includes(scope))
    && (state === 'all' || (state === 'active' ? issue.state !== 'resolved' : issue.state === state)));
  const active = all.filter((issue) => issue.state !== 'resolved').length;
  const components = [...new Set(all.map((issue) => issue.component))].sort();
  const acknowledge = async (id: string) => {
    if (busyId) return;
    setBusyId(id); setActionError(''); setNotice('');
    try {
      const updated = await acknowledgeOperationalIssue(id);
      // Discard a poll started before the acknowledgment so it cannot undo the new state.
      request.current?.abort(); request.current = null; setLoading(false);
      setServer((current) => current.map((issue) => issue.id === id ? updated : issue));
      setNotice('问题已确认');
    } catch (reason) { setActionError(reason instanceof Error ? reason.message : '确认失败，请重试。'); }
    finally { setBusyId(''); }
  };
  const copyDiagnostic = async (issue: OperationalIssue) => {
    setActionError(''); setNotice('');
    try { await navigator.clipboard.writeText(JSON.stringify(diagnosticDocument(issue), null, 2)); setNotice('脱敏诊断已复制'); }
    catch { setActionError('无法写入剪贴板。请展开“技术详情”手动选择并复制。'); }
  };
  return <>
    <button className="problem-toggle" type="button" aria-haspopup="dialog" aria-expanded={open} onClick={() => setOpen((value) => !value)}>
      问题中心 <span className={active === 0 ? 'no-issues' : ''}>{active}</span>
    </button>
    {open && <Modal className="problem-center" label="问题中心" onClose={() => setOpen(false)}>
      <header><div><span className="eyebrow">Operational issues</span><h2>问题中心</h2></div><div><button type="button" disabled={loading || !!busyId} onClick={() => void reload()}>{loading ? '刷新中…' : '刷新'}</button><button type="button" onClick={() => setOpen(false)}>关闭</button></div></header>
      <div className="problem-filters">
        <select aria-label="问题状态" value={state} onChange={(event) => setState(event.target.value)}><option value="active">未解决</option><option value="open">待确认</option><option value="acknowledged">已确认</option><option value="resolved">已解决</option><option value="all">全部状态</option></select>
        <select aria-label="严重级别" value={severity} onChange={(event) => setSeverity(event.target.value)}><option value="">全部级别</option><option value="error">错误</option><option value="warning">警告</option><option value="info">信息</option></select>
        <select aria-label="组件" value={component} onChange={(event) => setComponent(event.target.value)}><option value="">全部组件</option>{components.map((value) => <option key={value}>{value}</option>)}</select>
        <input aria-label="设备或来源" placeholder="设备/Profile" value={scope} onChange={(event) => setScope(event.target.value.slice(0, 64))} />
      </div>
      {error && <p className="problem-error" role="status">{error}</p>}
      {actionError && <p className="problem-error" role="alert">{actionError}</p>}
      {notice && <p role="status">{notice}</p>}
      <p className="problem-results">显示 {filtered.length} / {all.length} 条</p>
      <div className="problem-list">
        {filtered.length === 0 ? <p className="problem-empty">当前筛选条件下没有问题。</p> : filtered.map((issue) => <article className={`problem-card severity-${issue.severity}`} key={issue.id}>
          <header><div><span>{severityLabel[issue.severity]} · {issue.component}</span><strong>{issue.summary}</strong></div><time>{new Date(issue.lastSeenAt * (issue.lastSeenAt < 10_000_000_000 ? 1000 : 1)).toLocaleString()}</time></header>
          <p>{issue.explanation}</p>
          {issue.recommendedActions.length > 0 && <ol>{issue.recommendedActions.map((action) => <li key={action}>{action}</li>)}</ol>}
          <details><summary>技术详情</summary><pre>{JSON.stringify(diagnosticDocument(issue), null, 2)}</pre></details>
          <footer><span>{{ open: '待确认', acknowledged: '已确认', resolved: '已解决' }[issue.state]} · {issue.scopeId} · {issue.occurrences} 次</span><div>
            <button type="button" onClick={() => void copyDiagnostic(issue)}>复制脱敏诊断</button>
            {!issue.id.startsWith('local-') && issue.state === 'open' && <button type="button" disabled={!!busyId} onClick={() => void acknowledge(issue.id)}>{busyId === issue.id ? '确认中…' : '确认'}</button>}
          </div></footer>
        </article>)}
      </div>
    </Modal>}
  </>;
}
