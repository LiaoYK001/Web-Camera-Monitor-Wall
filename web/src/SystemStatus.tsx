import { useEffect, useState } from 'react';
import { fetchProcessDiagnostics, fetchSystemCapabilities } from './api';
import type { ProcessDiagnostics, SystemCapabilities, VideoBackendCapability } from './types';

const state = (value: boolean) => value ? '就绪' : '不可用';

function Backend({ name, value }: { name: string; value: VideoBackendCapability }) {
  return <article className={`hardware-card ${value.ready ? 'ready' : 'fallback'}`}>
    <header><h3>{name}</h3><strong>{state(value.ready)}</strong></header>
    <dl><div><dt>设备节点</dt><dd>{state(value.devicePresent)}</dd></div>
      <div><dt>驱动加载</dt><dd>{state(value.vaDriverLoaded)}</dd></div>
      <div><dt>编码能力</dt><dd>{state(value.encodeSupported && value.encoderAvailable)}</dd></div>
      <div><dt>解码能力</dt><dd>{state(value.decodeSupported)}</dd></div>
      <div><dt>运行探测</dt><dd>{state(value.runtimeProbePassed)}</dd></div></dl>
  </article>;
}

export default function SystemStatus({ onBack }: { onBack: () => void }) {
  const [capabilities, setCapabilities] = useState<SystemCapabilities | null>(null);
  const [processes, setProcesses] = useState<ProcessDiagnostics | null>(null);
  const [error, setError] = useState('');
  useEffect(() => {
    let active = true;
    const refresh = () => Promise.all([fetchSystemCapabilities(), fetchProcessDiagnostics()])
      .then(([nextCapabilities, nextProcesses]) => { if (active) { setCapabilities(nextCapabilities); setProcesses(nextProcesses); setError(''); } })
      .catch((reason: unknown) => { if (active) setError(reason instanceof Error ? reason.message : '读取系统状态失败'); });
    void refresh();
    const timer = window.setInterval(() => void refresh(), 5000);
    return () => { active = false; window.clearInterval(timer); };
  }, []);
  return <main className="system-page">
    <header className="registry-header"><div><span className="eyebrow">Runtime diagnostics</span><h1>系统状态 / 视频加速</h1></div><button className="ghost-button" type="button" onClick={onBack}>返回 Studio</button></header>
    {error && <div className="alert" role="alert">{error}</div>}
    {capabilities && <>
      <section className="system-summary"><article><span>编码器</span><strong>{capabilities.videoEncoder.selected.toUpperCase()}</strong><small>请求 {capabilities.videoEncoder.requested}{capabilities.videoEncoder.fallback ? ` · FALLBACK: ${capabilities.videoEncoder.fallbackReason}` : ''}</small></article>
        <article><span>场景渲染</span><strong>{capabilities.renderer.selected.toUpperCase()}</strong><small>请求 {capabilities.renderer.requested}{capabilities.renderer.fallback ? ` · FALLBACK: ${capabilities.renderer.fallbackReason}` : ''}</small></article>
        <article><span>来源硬解</span><strong>{capabilities.hardwareDecode.selected.toUpperCase()}</strong><small>请求 {capabilities.hardwareDecode.requested}{capabilities.hardwareDecode.fallback ? ` · FALLBACK: ${capabilities.hardwareDecode.fallbackReason}` : ''}</small></article></section>
      <section className="hardware-grid"><Backend name="AMD VA-API" value={capabilities.videoEncoder.backends.vaapi} /><Backend name="Intel QSV" value={capabilities.videoEncoder.backends.qsv} /><Backend name="NVIDIA NVENC" value={capabilities.videoEncoder.backends.nvenc} /></section>
    </>}
    {processes && <section className="process-panel"><div className="section-title"><h2>服务端执行链</h2><span>每 5 秒刷新</span></div>
      <div className="process-grid">{processes.processes.map((process) => <article key={process.name}><strong>{process.name}</strong><span>{process.cpuPercent.toFixed(1)}% CPU · {process.instances} 个进程</span><small>{(process.rssKiB / 1024).toFixed(1)} MiB RSS</small></article>)}</div>
      <dl className="runtime-facts"><div><dt>RTSP TCP sessions</dt><dd>{processes.rtspSessions}</dd></div><div><dt>AMD GFX busy</dt><dd>{processes.gpuBusyPercent >= 0 ? `${processes.gpuBusyPercent}%` : '不可读取'}</dd></div><div><dt>Control plane</dt><dd>{processes.controlPlaneActive ? 'ACTIVE' : 'IDLE'}</dd></div><div><dt>OBS engine</dt><dd>{processes.engineActive ? 'ACTIVE' : 'IDLE'}</dd></div><div><dt>Composite publisher</dt><dd>{processes.compositePublisherActive ? 'ACTIVE' : 'IDLE'}</dd></div></dl>
    </section>}
  </main>;
}
