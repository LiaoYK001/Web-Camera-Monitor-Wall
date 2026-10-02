import { useEffect, useState, type FormEvent } from 'react';
import { fetchRuntimeSettings, patchRuntimeSettings } from './api';
import ConfigProfiles from './ConfigProfiles';
import DesktopSettings from './DesktopSettings';
import AboutSettings from './AboutSettings';
import { useDesktopWork } from './desktopRuntime';
import { useMonitorPreferences } from './useMonitorPreferences';
import type { RuntimeSettings } from './types';
import type { LocalConfigProfile } from './localRuntime';
import type { StudioDocument } from './types';

export default function SettingsWorkspace({ studio, onProfileSelected }: {
  studio?: StudioDocument | null;
  onProfileSelected?: (profile: LocalConfigProfile) => void;
}) {
  const { view, setView, loaded: preferencesLoaded, error: preferenceError } = useMonitorPreferences(false);
  const [settings, setSettings] = useState<RuntimeSettings | null>(null);
  const [draft, setDraft] = useState<RuntimeSettings['values'] | null>(null);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [reload, setReload] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    void fetchRuntimeSettings(controller.signal).then((value) => {
      if (controller.signal.aborted) return;
      setSettings(value); setDraft(value.values); setError('');
    }).catch((reason: unknown) => {
      if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : '设置不可用');
    }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [reload]);
  const dirty = Boolean(settings && draft && JSON.stringify(settings.values) !== JSON.stringify(draft));
  useDesktopWork('runtime-settings', dirty, busy);
  const valid = draft && Number.isInteger(draft.probeTimeoutSeconds) && draft.probeTimeoutSeconds >= 2 && draft.probeTimeoutSeconds <= 30
    && Number.isInteger(draft.issueRetentionLimit) && draft.issueRetentionLimit >= 128 && draft.issueRetentionLimit <= 4096;
  useEffect(() => {
    if (!dirty) return;
    const warn = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = ''; };
    const leave = (event: Event) => {
      if (busy) { event.preventDefault(); setNotice('正在保存，请稍候再切换页面'); }
      else if (!window.confirm('运行设置尚未保存，离开会丢弃这些修改，继续？')) event.preventDefault();
    };
    window.addEventListener('beforeunload', warn);
    window.addEventListener('webobs:before-navigate', leave);
    return () => { window.removeEventListener('beforeunload', warn); window.removeEventListener('webobs:before-navigate', leave); };
  }, [dirty, busy]);
  const update = (change: Partial<RuntimeSettings['values']>) => {
    setDraft((current) => current ? { ...current, ...change } : current); setNotice('');
  };
  const save = async (event: FormEvent) => {
    event.preventDefault();
    if (!settings || !draft || !dirty || !valid || busy) return;
    const changes = Object.fromEntries(Object.entries(draft).filter(([key, value]) => value !== settings.values[key as keyof typeof draft]));
    setBusy(true); setError(''); setNotice('');
    try {
      const result = await patchRuntimeSettings(settings.revision, changes);
      setSettings(result); setDraft(result.values); setNotice('系统设置已保存');
    } catch (reason) { setError(`${reason instanceof Error ? reason.message : '设置更新失败'}。输入已保留，可重试；若提示版本冲突，请重新读取设置后修改。`); }
    finally { setBusy(false); }
  };
  const reloadSettings = () => {
    if (dirty && !window.confirm('重新读取会丢弃尚未保存的系统设置，继续？')) return;
    setNotice(''); setReload((value) => value + 1);
  };
  return <section className="settings-workspace page-panel">
    <header className="page-heading"><div><span className="eyebrow">Settings</span><h1>系统设置</h1><p>管理账号配置档案和服务端运行设置。修改运行设置后，点击保存生效。</p></div></header>
    <ConfigProfiles studio={studio ?? null} onProfileSelected={onProfileSelected} />
    <DesktopSettings />
    <AboutSettings />
    <section className="playback-optimization-settings" aria-label="自动播放优化"><h2>弱网与慢速流自动优化</h2>
      <p>默认开启，按当前账号自动保存。适应低帧率来源，减少误判重连；持续丢包或抖动时优先使用设备已有子码流，网络稳定后恢复。不会为此修改设备配置或强制转码。</p>
      {preferenceError && <p role="alert">{preferenceError}</p>}
      <fieldset disabled={!preferencesLoaded}>
        <label><input type="checkbox" checked={view.playbackOptimization.enabled} onChange={(event) => setView((value) => ({ ...value, playbackOptimization: { ...value.playbackOptimization, enabled: event.target.checked } }))} />自动优化视频播放（默认开启）</label>
        {([['slowStreamTolerance', '自动检测慢速流，调整卡顿等待时间'], ['adaptiveProfiles', '弱网时自动选择已有低带宽 Profile'], ['catchUp', '自动调整缓冲并追赶实时画面']] as const).map(([key, label]) => <label key={key}>
          <input type="checkbox" disabled={!view.playbackOptimization.enabled} checked={view.playbackOptimization[key]} onChange={(event) => setView((value) => ({ ...value, playbackOptimization: { ...value.playbackOptimization, [key]: event.target.checked } }))} />{label}</label>)}
      </fieldset><small>设置立即保存。关闭总开关后保留所选 Profile 和常规连接恢复；画面源本身的帧率、编码和带宽仍决定可展示的效果。</small>
    </section>
    <form className="runtime-settings-form" onSubmit={(event) => void save(event)} aria-label="运行设置" aria-busy={loading || busy}>
      <header><h2>运行设置</h2><button type="button" disabled={busy || loading} onClick={reloadSettings}>重新读取设置</button></header>
      {error && <div className="alert conflict-alert" role="alert">{error}</div>}
      {loading && <p role="status">正在读取运行设置…</p>}
      {draft && <fieldset disabled={busy || loading}>
        <legend className="sr-only">服务端运行设置</legend>
        <div className="settings-grid">
          <article><h3>视频与播放</h3>
            <label>默认传输方式<select value={draft.defaultTransportMode} onChange={(event) => update({ defaultTransportMode: event.target.value as RuntimeSettings['values']['defaultTransportMode'] })}><option value="auto">自动</option><option value="rtsp-tcp">RTSP TCP</option><option value="rtsp-udp">RTSP UDP</option></select></label>
            <label>探测超时（秒）<input type="number" required min="2" max="30" step="1" value={Number.isNaN(draft.probeTimeoutSeconds) ? '' : draft.probeTimeoutSeconds} onChange={(event) => update({ probeTimeoutSeconds: event.currentTarget.valueAsNumber })} /></label>
            <p>允许 2–30 秒。网络较慢时可适当增加。</p>
          </article>
          <article><h3>诊断与恢复</h3>
            <label>问题保留上限<input type="number" required min="128" max="4096" step="1" value={Number.isNaN(draft.issueRetentionLimit) ? '' : draft.issueRetentionLimit} onChange={(event) => update({ issueRetentionLimit: event.currentTarget.valueAsNumber })} /></label>
            <label className="settings-checkbox"><input type="checkbox" checked={draft.sourceRecoveryEnabled} onChange={(event) => update({ sourceRecoveryEnabled: event.target.checked })} />来源自动恢复</label>
            <p>问题记录保留 128–4096 条。</p>
          </article>
        </div>
        <footer className="settings-save-bar"><span role="status">{busy ? '正在保存…' : dirty ? '有未保存的修改' : notice || '设置已载入'}</span>
          <button type="button" disabled={!dirty} onClick={() => { setDraft(settings!.values); setError(''); setNotice('已撤销未保存的修改'); }}>撤销修改</button>
          <button className="primary-button" type="submit" disabled={!dirty || !valid}>保存设置</button>
        </footer>
      </fieldset>}
    </form>
    {settings && <article className="deployment-readonly"><h2>部署配置（只读）</h2><p>TLS、端口、Secret 路径和 GPU 设备通过部署配置修改并重启。</p><div>{Object.keys(settings.deployment).map((key) => <span key={key}>{key} · 只读</span>)}</div></article>}
  </section>;
}
