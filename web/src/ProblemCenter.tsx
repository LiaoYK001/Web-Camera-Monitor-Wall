import { useEffect, useMemo, useState } from 'react';
import { acknowledgeOperationalIssue, fetchOperationalIssues } from './api';
import { subscribeLocalIssues } from './issueRuntime';
import type { OperationalIssue } from './types';

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
  const [error, setError] = useState('');
  const reload = () => fetchOperationalIssues().then((value) => { setServer(value.issues); setError(''); })
    .catch(() => setError('服务端问题列表暂时不可用'));
  useEffect(() => {
    void reload();
    const timer = window.setInterval(reload, 10_000);
    return () => window.clearInterval(timer);
  }, []);
  useEffect(() => subscribeLocalIssues(setLocal), []);
  useEffect(() => {
    const show = (event: Event) => {
      const value = (event as CustomEvent<{ scopeId?: string }>).detail?.scopeId ?? '';
      setScope(value); setOpen(true);
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
    && (!component || issue.component === component) && (!scope || issue.scopeId.includes(scope)));
  const active = all.filter((issue) => issue.state !== 'resolved').length;
  const components = [...new Set(all.map((issue) => issue.component))].sort();
  return <>
    <button className="problem-toggle" type="button" aria-expanded={open} onClick={() => setOpen((value) => !value)}>
      问题中心 <span>{active}</span>
    </button>
    {open && <aside className="problem-center" aria-label="问题中心">
      <header><div><span className="eyebrow">Operational issues</span><h2>问题中心</h2></div><button type="button" onClick={() => setOpen(false)}>收起</button></header>
      <div className="problem-filters">
        <select aria-label="严重级别" value={severity} onChange={(event) => setSeverity(event.target.value)}><option value="">全部级别</option><option value="error">错误</option><option value="warning">警告</option><option value="info">信息</option></select>
        <select aria-label="组件" value={component} onChange={(event) => setComponent(event.target.value)}><option value="">全部组件</option>{components.map((value) => <option key={value}>{value}</option>)}</select>
        <input aria-label="设备或来源" placeholder="设备/Profile" value={scope} onChange={(event) => setScope(event.target.value.slice(0, 64))} />
      </div>
      {error && <p className="problem-error" role="status">{error}</p>}
      <div className="problem-list">
        {filtered.length === 0 ? <p className="problem-empty">当前筛选条件下没有问题。</p> : filtered.map((issue) => <article className={`problem-card severity-${issue.severity}`} key={issue.id}>
          <header><div><span>{severityLabel[issue.severity]} · {issue.component}</span><strong>{issue.summary}</strong></div><time>{new Date(issue.lastSeenAt * (issue.lastSeenAt < 10_000_000_000 ? 1000 : 1)).toLocaleString()}</time></header>
          <p>{issue.explanation}</p>
          {issue.recommendedActions.length > 0 && <ol>{issue.recommendedActions.map((action) => <li key={action}>{action}</li>)}</ol>}
          <details><summary>技术详情</summary><pre>{JSON.stringify(diagnosticDocument(issue), null, 2)}</pre></details>
          <footer><span>{issue.scopeKind} · {issue.scopeId} · {issue.occurrences} 次</span><div>
            <button type="button" onClick={() => void navigator.clipboard.writeText(JSON.stringify(diagnosticDocument(issue), null, 2))}>复制脱敏诊断</button>
            {!issue.id.startsWith('local-') && issue.state === 'open' && <button type="button" onClick={() => void acknowledgeOperationalIssue(issue.id).then(reload)}>确认</button>}
          </div></footer>
        </article>)}
      </div>
    </aside>}
  </>;
}
