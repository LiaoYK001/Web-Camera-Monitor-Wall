import { useCallback, useEffect, useMemo, useState } from 'react';
import { fetchAnalyticsStatus, fetchV3AnalyticsPolicies, patchV3AnalyticsPolicies } from './api';
import type { AnalyticsPolicy, AnalyticsRuntimePlan, AnalyticsStatus } from './types';

const executionLabel: Record<AnalyticsRuntimePlan['execution'], string> = {
  native: 'Camera event', 'browser-webgpu': 'Browser WebGPU', 'browser-wasm': 'Browser WASM',
  worker: 'Server Worker', unsupported: '不支持', off: '关闭',
};

function planLabel(plan: AnalyticsRuntimePlan | undefined): string {
  if (!plan) return '—';
  return `${executionLabel[plan.execution]}${plan.reason ? ` · ${plan.reason}` : ''}`;
}

export default function AnalyticsWorkspace() {
  const [policies, setPolicies] = useState<AnalyticsPolicy[]>([]);
  const [statuses, setStatuses] = useState<AnalyticsStatus[]>([]);
  const [revision, setRevision] = useState(1);
  const [selected, setSelected] = useState<'all' | 'enabled' | 'unsupported'>('all');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const reload = useCallback(() => {
    const controller = new AbortController();
    void Promise.all([fetchV3AnalyticsPolicies(controller.signal), fetchAnalyticsStatus(controller.signal)])
      .then(([policyResult, statusResult]) => {
        setPolicies(policyResult.policies); setRevision(policyResult.revision); setStatuses(statusResult.statuses); setError('');
      })
      .catch((reason: unknown) => { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : '分析状态暂时不可用'); });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    const cancel = reload();
    const timer = window.setInterval(() => { cancel(); reload(); }, 10_000);
    return () => { cancel(); window.clearInterval(timer); };
  }, [reload]);

  const statusMap = useMemo(() => new Map(statuses.map((value) => [`${value.cameraId}/${value.profileId}`, value])), [statuses]);
  const visible = policies.filter((policy) => {
    if (selected === 'enabled') return policy.motionEnabled || policy.sceneChangeEnabled || policy.personEnabled;
    if (selected === 'unsupported') {
      const value = statusMap.get(`${policy.cameraId}/${policy.profileId}`);
      return [value?.motion, value?.sceneChange, value?.person].some((plan) => plan?.execution === 'unsupported');
    }
    return true;
  });

  const update = async (policy: AnalyticsPolicy, key: 'motionEnabled' | 'sceneChangeEnabled' | 'personEnabled', value: boolean) => {
    setBusy(true); setError('');
    try {
      // Send only the changed Camera/Profile.  Besides reducing the request,
      // this lets a scoped operator update an authorized profile without
      // accidentally submitting unrelated cameras from the list.
      const result = await patchV3AnalyticsPolicies(revision, [{ ...policy, [key]: value }]);
      setPolicies(result.policies); setRevision(result.revision);
    } catch (reason) { setError(reason instanceof Error ? reason.message : '策略更新失败，请刷新后重试'); }
    finally { setBusy(false); }
  };

  return <section className="page-panel analytics-workspace">
    <header className="page-heading"><div><span className="eyebrow">v3-M1 / v3-M2</span><h1>分析策略</h1><p>按 Camera/Profile 独立控制。默认关闭；帧只在浏览器本地内存处理。</p></div><button type="button" onClick={() => { reload(); }}>刷新</button></header>
    <div className="analytics-toolbar"><span>策略 revision {revision}</span><select aria-label="分析状态筛选" value={selected} onChange={(event) => setSelected(event.target.value as typeof selected)}><option value="all">全部 Profile</option><option value="enabled">已启用</option><option value="unsupported">运行时不支持</option></select><span className="muted-copy">浏览器优先 · Worker 仅管理员显式允许</span></div>
    {error && <div className="alert conflict-alert" role="alert">{error}</div>}
    {visible.length === 0 ? <div className="empty-state"><h2>暂无分析策略</h2><p>请先在设备与来源中添加并探测 Profile。</p></div> : <div className="analytics-policy-list">{visible.map((policy) => {
      const status = statusMap.get(`${policy.cameraId}/${policy.profileId}`);
      return <article className="analytics-policy-card" key={`${policy.cameraId}/${policy.profileId}`}>
        <header><div><strong>{policy.cameraId}</strong><span>Profile · {policy.profileId}</span></div><span className="muted-copy">{policy.forceAnalyticsAlwaysOn ? '始终运行' : '低功耗可抑制'}</span></header>
        <div className="analytics-policy-grid">
          {([['motionEnabled', '运动', status?.motion], ['sceneChangeEnabled', '画面变化', status?.sceneChange], ['personEnabled', '人物框', status?.person]] as const).map(([key, label, plan]) => <label className="analytics-policy-toggle" key={key}><input type="checkbox" checked={policy[key]} disabled={busy} onChange={(event) => void update(policy, key, event.target.checked)} /><span><strong>{label}</strong><small>{planLabel(plan)}</small></span></label>)}
        </div>
        <footer><span>采样：{policy.motion?.sampleFps ?? 2} / {policy.person?.sampleFps ?? 1} FPS</span><span>最近运行：{status ? '已规划' : '—'}</span><span>服务器媒体：{[status?.motion, status?.sceneChange, status?.person].some((plan) => plan?.serverMediaExpected) ? '可能增加（Worker）' : '不预期'}</span></footer>
      </article>;
    })}</div>}
  </section>;
}
