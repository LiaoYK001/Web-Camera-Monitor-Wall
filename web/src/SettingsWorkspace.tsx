import { useEffect, useState } from 'react';
import { fetchRuntimeSettings, patchRuntimeSettings } from './api';
import ConfigProfiles from './ConfigProfiles';
import type { RuntimeSettings } from './types';
import type { LocalConfigProfile } from './localRuntime';
import type { StudioDocument } from './types';

const groups = ['界面与行为', '视频与播放', '音频', '录像与存储', '检测策略', '统计与组件', 'Watchdog 与恢复', '安全与 PWA'];

export default function SettingsWorkspace({ studio, onProfileSelected }: {
  studio?: StudioDocument | null;
  onProfileSelected?: (profile: LocalConfigProfile) => void;
}) {
  const [settings, setSettings] = useState<RuntimeSettings | null>(null);
  const [error, setError] = useState('');
  useEffect(() => { void fetchRuntimeSettings().then(setSettings).catch((reason: unknown) => setError(reason instanceof Error ? reason.message : '设置不可用')); }, []);
  const patch = async (change: Record<string, unknown>) => {
    if (!settings) return;
    try { setSettings(await patchRuntimeSettings(settings.revision, change)); setError(''); }
    catch (reason) { setError(reason instanceof Error ? reason.message : '设置更新失败'); }
  };
  return <section className="settings-workspace page-panel">
    <header className="page-heading"><div><span className="eyebrow">Runtime policy</span><h1>系统设置</h1><p>浏览器偏好、本机热更新策略与部署只读项分区展示。</p></div></header>
    {error && <div className="alert conflict-alert">{error}</div>}
    <ConfigProfiles studio={studio ?? null} onProfileSelected={onProfileSelected} />
    <div className="settings-grid">{groups.map((group, index) => <article key={group}><h2>{group}</h2>{index === 1 && settings ? <>
      <label>默认传输方式<select value={settings.values.defaultTransportMode} onChange={(event) => void patch({ defaultTransportMode: event.target.value })}><option value="auto">自动</option><option value="rtsp-tcp">RTSP TCP</option><option value="rtsp-udp">RTSP UDP</option></select></label>
      <label>探测超时（秒）<input key={`probe-${settings.revision}`} type="number" min="2" max="30" defaultValue={settings.values.probeTimeoutSeconds} onBlur={(event) => void patch({ probeTimeoutSeconds: Number(event.currentTarget.value) })} /></label></> : index === 5 && settings ? <label>问题保留上限<input key={`issues-${settings.revision}`} type="number" min="128" max="4096" defaultValue={settings.values.issueRetentionLimit} onBlur={(event) => void patch({ issueRetentionLimit: Number(event.currentTarget.value) })} /></label> : index === 6 && settings ? <label><input type="checkbox" checked={settings.values.sourceRecoveryEnabled} onChange={(event) => void patch({ sourceRecoveryEnabled: event.target.checked })} />来源自动恢复</label> : <p>该组当前使用加密本地偏好或已有服务策略。</p>}</article>)}</div>
    <article className="deployment-readonly"><h2>部署配置（只读）</h2><p>TLS、端口、Secret 路径和 GPU 设备必须通过 Compose/Secret 修改并重启；Web UI 不回显具体路径或 Secret。</p><div>{settings && Object.keys(settings.deployment).map((key) => <span key={key}>{key} · read-only</span>)}</div></article>
  </section>;
}
