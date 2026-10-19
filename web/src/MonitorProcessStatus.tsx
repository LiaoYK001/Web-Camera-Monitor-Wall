import { useCallback, useId, useRef, useState } from 'react';
import { fetchProcessDiagnostics } from './api';
import { withRequestTimeout } from './requestTimeout';
import { useVisiblePolling } from './useVisiblePolling';
import type { ProcessDiagnostics } from './types';

const names: Record<string, string> = { desktop: '桌面 / 浏览器', ffmpeg: 'FFmpeg', webobsd: '核心',
  go2rtc: 'go2rtc', mediamtx: 'MediaMTX', 'obs-browser': 'OBS 浏览器', python: 'Python 服务', runtime: '运行时', caddy: '网关' };

function ProcessReadout({ id }: { id: string }) {
  const [sample, setSample] = useState<{ data: ProcessDiagnostics; ready: boolean } | null>(null);
  const [error, setError] = useState('');
  const previous = useRef<number | null>(null);
  const refresh = useCallback(async (signal: AbortSignal) => {
    try {
      const data = await withRequestTimeout(8000, request => fetchProcessDiagnostics(request), signal);
      if (signal.aborted) return;
      const now = performance.now();
      setSample({ data, ready: previous.current !== null && now - previous.current < 15_000 });
      previous.current = now; setError('');
    } catch {
      if (!signal.aborted) { previous.current = null; setSample(null); setError('暂时无法读取进程占用，稍后自动重试。'); }
    }
  }, []);
  useVisiblePolling(refresh, 5000);
  const cores = sample?.data.cpuLogicalCores;
  const desktop = sample?.data.scope === 'desktop-process-tree' && Number.isInteger(cores) && (cores ?? 0) > 0;
  const divisor = desktop ? cores! : 1;
  const cpu = (value: number) => sample?.ready ? `${(Math.max(0, value) / divisor).toFixed(1)}%` : '采样中';
  return <section id={id} className="monitor-process-readout" aria-label="监看实时占用">
    <p role="status" aria-live="off">{error || (!sample ? '正在读取进程占用…' : desktop
      ? `本应用 CPU ${cpu(sample.data.processes.reduce((total, process) => total + process.cpuPercent, 0))} · 各项均按 ${cores} 个逻辑处理器折算`
      : '服务端进程占用 · 单个逻辑处理器 100%；不代表观看端整体 CPU')}
      <small>同类进程合计，播放中每 5 秒读取；首次需等待下一次采样。</small></p>
    {sample && <div className="monitor-process-roles">{sample.data.processes.map(process => <span key={process.name}>
      <strong>{names[process.name] ?? process.name}</strong> {cpu(process.cpuPercent)} <small>· {process.instances} 个进程</small>
    </span>)}</div>}
  </section>;
}

/** The readout owns its state so sampling never navigates away from the wall. */
export default function MonitorProcessStatus() {
  const [open, setOpen] = useState(false);
  const id = useId();
  return <div className="monitor-process-status">
    <button type="button" className="ghost-button" aria-expanded={open} aria-controls={id} onClick={() => setOpen(value => !value)}>实时占用</button>
    {open && <ProcessReadout id={id} />}
  </div>;
}
