import { useCallback, useState } from 'react';
import { useVisiblePolling } from './useVisiblePolling';
import { fetchProcessDiagnostics, fetchSystemCapabilities } from './api';
import type { ProcessDiagnostics, SystemCapabilities, VideoBackendCapability } from './types';

const state = (value: boolean) => value ? '就绪' : '不可用';

function Backend({ name, kind, value }: { name: string; kind: 'vaapi' | 'qsv' | 'nvenc'; value: VideoBackendCapability }) {
  // NVENC uses CUDA/NVENC libraries; a VA-API driver is not part of that path.
  const driverLoaded = kind === 'nvenc' ? value.libraryLoaded : value.vaDriverLoaded;
  return <article className={`hardware-card ${value.ready ? 'ready' : 'fallback'}`}>
    <header><h3>{name}</h3><strong>{state(value.ready)}</strong></header>
    <dl><div><dt>设备节点</dt><dd>{state(value.devicePresent)}</dd></div>
      <div><dt title={kind === 'nvenc' ? 'CUDA/NVENC 运行库' : 'VA-API 驱动'}>驱动加载</dt><dd>{state(driverLoaded)}</dd></div>
      <div><dt>编码能力</dt><dd>{state(value.encodeSupported && value.encoderAvailable)}</dd></div>
      <div><dt>解码能力</dt><dd>{state(value.decodeSupported)}</dd></div>
      <div><dt>运行探测</dt><dd>{state(value.runtimeProbePassed)}</dd></div></dl>
  </article>;
}

export default function SystemStatus({ onBack }: { onBack: () => void }) {
  const [capabilities, setCapabilities] = useState<SystemCapabilities | null>(null);
  const [processes, setProcesses] = useState<ProcessDiagnostics | null>(null);
  const [error, setError] = useState('');
  const refresh = useCallback(async (signal: AbortSignal) => {
    try {
      const [nextCapabilities, nextProcesses] = await Promise.all([fetchSystemCapabilities(signal), fetchProcessDiagnostics(signal)]);
      if (!signal.aborted) { setCapabilities(nextCapabilities); setProcesses(nextProcesses); setError(''); }
    } catch (reason) { if (!signal.aborted) setError(reason instanceof Error ? reason.message : '读取系统状态失败'); }
  }, []);
  useVisiblePolling(refresh, 5000);
  return <main className="system-page">
    <header className="registry-header"><div><span className="eyebrow">Runtime diagnostics</span><h1>系统状态 / 视频加速</h1></div><button className="ghost-button" type="button" onClick={onBack}>返回 Studio</button></header>
    {error && <div className="alert" role="alert">{error}</div>}
    {capabilities && <>
      <p className="runtime-explanation" role="status">{processes?.compositePublisherActive
        ? 'Composite 正在合成画面；下面的编码器与渲染器状态反映服务端 GPU 路径。'
        : 'OBS 合成器未运行。可直通的 Direct 来源只由网关转发，服务端编码器空闲属正常；Hybrid 来源才可能使用硬件转码，浏览器解码则由观看设备决定。'}</p>
      <section className="system-summary"><article><span>编码器</span><strong>{capabilities.videoEncoder.selected.toUpperCase()}</strong><small>请求 {capabilities.videoEncoder.requested}{capabilities.videoEncoder.fallback ? ` · FALLBACK: ${capabilities.videoEncoder.fallbackReason}` : ''}</small></article>
        <article><span>场景渲染</span><strong>{capabilities.renderer.selected.toUpperCase()}</strong><small>请求 {capabilities.renderer.requested}{capabilities.renderer.fallback ? ` · FALLBACK: ${capabilities.renderer.fallbackReason}` : ''}</small></article>
        <article><span>来源硬解</span><strong>{capabilities.hardwareDecode.selected.toUpperCase()}</strong><small>请求 {capabilities.hardwareDecode.requested}{capabilities.hardwareDecode.fallback ? ` · FALLBACK: ${capabilities.hardwareDecode.fallbackReason}` : ''}</small></article></section>
      <section className="hardware-grid"><Backend name="AMD VA-API" kind="vaapi" value={capabilities.videoEncoder.backends.vaapi} /><Backend name="Intel QSV" kind="qsv" value={capabilities.videoEncoder.backends.qsv} /><Backend name="NVIDIA NVENC" kind="nvenc" value={capabilities.videoEncoder.backends.nvenc} /></section>
    </>}
    {processes && <section className="process-panel"><div className="section-title"><h2>服务端执行链</h2><span>每 5 秒刷新</span></div>
      {processes.scope === 'desktop-process-tree' && <p role="status">WebOBS 整体 CPU：{(processes.processes.reduce((sum, process) => sum + process.cpuPercent, 0) / Math.max(1, processes.cpuLogicalCores || 1)).toFixed(1)}%（按 {processes.cpuLogicalCores} 个逻辑处理器折算，首次采样需等待下一次刷新）。只统计本次应用及其子进程。</p>}
      <p>下方按单个逻辑处理器 100% 计量；多线程进程可超过 100%。Direct 的 H.264 优先直通；不兼容的编码可能使用 Hybrid 转换。</p>
      <div className="process-grid">{processes.processes.map((process) => <article key={process.name}><strong>{process.name}</strong><span>{process.cpuPercent.toFixed(1)}% CPU · {process.instances} 个进程</span><small>{(process.rssKiB / 1024).toFixed(1)} MiB RSS</small></article>)}</div>
      <dl className="runtime-facts"><div><dt>RTSP TCP sessions</dt><dd>{processes.rtspSessionProbeAvailable === false ? '不可读取' : processes.rtspSessions}</dd></div><div><dt>AMD GFX busy</dt><dd>{processes.gpuBusyPercent >= 0 ? `${processes.gpuBusyPercent}%` : '不可读取'}</dd></div><div><dt>Control plane</dt><dd>{processes.controlPlaneActive ? 'ACTIVE' : 'IDLE'}</dd></div><div><dt>OBS engine</dt><dd>{processes.engineActive ? 'ACTIVE' : 'IDLE'}</dd></div><div><dt>Composite publisher</dt><dd>{processes.compositePublisherActive ? 'ACTIVE' : 'IDLE'}</dd></div></dl>
    </section>}
  </main>;
}
