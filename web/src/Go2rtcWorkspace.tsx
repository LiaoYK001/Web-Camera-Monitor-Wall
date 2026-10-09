import { useEffect, useRef, useState } from 'react';
import { fetchRuntimeInfo, useDesktopWork } from './desktopRuntime';
import Go2rtcStreams from './Go2rtcStreams';
import Go2rtcOnlineSources from './Go2rtcOnlineSources';

const base = '/api/v1/go2rtc/';
const pages = [
  { id: '', label: '流管理', description: '查看、添加和测试协议转换后的流。' },
  { id: 'add.html', label: '设备与发现', description: '设备发现和临时连接测试。英文 Temporary stream 不会保存配置；永久 RTSP、网站和直播来源请使用上方添加表单。' },
  { id: 'config.html', label: '配置', description: '编辑完整 YAML 配置，保存后重新加载 go2rtc，现有桥接播放会短暂中断。' },
  { id: 'log.html', label: '日志', description: '查看 go2rtc 的运行日志与连接问题。' },
];

export default function Go2rtcWorkspace({ onDevices }: { onDevices: () => void }) {
  const [selected, setSelected] = useState('');
  const [state, setState] = useState<'loading' | 'ready' | 'error'>('loading');
  const [error, setError] = useState('');
  const [version, setVersion] = useState('');
  const [generation, setGeneration] = useState(0);
  const [rtspBase, setRtspBase] = useState('rtsp://127.0.0.1:18554/');
  const [configDirty, setConfigDirty] = useState(false);
  const [onlineRuntime, setOnlineRuntime] = useState({ enabled: false, platform: '' });
  const [streamsGeneration, setStreamsGeneration] = useState(0);
  const [configRevision, setConfigRevision] = useState(0);
  const frame = useRef<HTMLIFrameElement>(null);
  useDesktopWork('go2rtc-config', configDirty);
  useEffect(() => {
    const reloaded = (event: MessageEvent) => {
      if (event.origin === window.location.origin && event.source === frame.current?.contentWindow &&
          event.data?.type === 'webobs:go2rtc-reloaded') setConfigRevision(value => value + 1);
    };
    window.addEventListener('message', reloaded);
    return () => window.removeEventListener('message', reloaded);
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    void fetchRuntimeInfo(controller.signal).then(info => {
      if (!controller.signal.aborted) { setRtspBase(info.go2rtcRtspBase); setOnlineRuntime({ enabled: info.onlineSourcesEnabled === true, platform: info.platform }); }
    }).catch(() => undefined);
    return () => controller.abort();
  }, [generation]);
  useEffect(() => {
    if (!window.webobsDesktop || selected !== 'config.html') { setConfigDirty(false); return; }
    let cancelled = false;
    const inspect = async () => {
      type MonacoWindow = Window & { monaco?: { editor: { getModels(): { getValue(): string }[] } } };
      const model = (frame.current?.contentWindow as MonacoWindow | null)?.monaco?.editor.getModels()[0];
      if (!model) return;
      try { const response = await fetch(`${base}api/config`, { credentials: 'same-origin', cache: 'no-store' }); if (!response.ok) return;
        const saved = await response.text(); if (!cancelled) setConfigDirty(model.getValue() !== saved);
      } catch { if (!cancelled) setConfigDirty(true); }
    };
    const timer = window.setInterval(() => void inspect(), 1500);
    return () => { cancelled = true; window.clearInterval(timer); };
  }, [selected, state]);

  useEffect(() => {
    const controller = new AbortController();
    setState('loading'); setError('');
    void fetch(`${base}api`, { credentials: 'same-origin', cache: 'no-store', signal: controller.signal })
      .then(async (response) => {
        if (!response.ok) {
          if (response.status === 403) throw new Error('需要管理员的系统设置权限才能管理 go2rtc。');
          if (response.status === 401) throw new Error('登录已失效，请重新登录。');
          throw new Error('go2rtc 服务暂不可用。请确认后端已启用 go2rtc 并完成启动。');
        }
        const info = await response.json() as { version?: string };
        if (!controller.signal.aborted) { setVersion(info.version ?? ''); setState('ready'); }
      }).catch((reason: unknown) => {
        if (!controller.signal.aborted) { setError(reason instanceof Error ? reason.message : 'go2rtc 连接失败'); setState('error'); }
      });
    return () => controller.abort();
  }, [generation]);

  return <section className="page-panel go2rtc-workspace">
    <header className="page-heading"><div><span className="eyebrow">Protocol bridge</span><h1>go2rtc 管理</h1>
      <p>统一整理视频来源，再送入监控墙、媒体网关和 OBS。</p></div>
      <div className="go2rtc-actions"><span role="status">{state === 'ready' ? `已连接 ${version}` : state === 'loading' ? '正在连接…' : '暂不可用'}</span>
        <button type="button" onClick={() => setGeneration((value) => value + 1)}>重新连接</button>
        <button type="button" onClick={onDevices}>接入设备与来源</button>
        {state === 'ready' && <a href={`${base}${selected}`} target="_blank" rel="noopener noreferrer">独立打开 WebUI ↗</a>}
      </div>
    </header>
    <div className="go2rtc-guide"><strong>来源 → go2rtc → 监控墙 / OBS</strong>
      <p>先在 go2rtc 中配置来源，再在“设备与来源”添加 <code>{rtspBase}流名称</code>。这里的地址指后端所在环境；普通 RTSP 也可直接接入。</p>
      <p>配置与日志可能包含设备凭据，仅供管理员使用。修改流名称时，需要同步更新监控墙中的来源。</p>
    </div>
    {state === 'ready' && selected !== 'config.html' && <Go2rtcOnlineSources enabled={onlineRuntime.enabled} platform={onlineRuntime.platform} onCreated={() => setStreamsGeneration(value => value + 1)} />}
    <Go2rtcStreams refreshKey={streamsGeneration + configRevision} />
    <nav className="go2rtc-tabs" aria-label="go2rtc 页面">{pages.map((page) => <button type="button" key={page.id} aria-pressed={selected === page.id}
      className={selected === page.id ? 'active' : ''} onClick={() => setSelected(page.id)}>{page.label}</button>)}</nav>
    <p className="go2rtc-description">{pages.find((page) => page.id === selected)?.description}</p>
    {state === 'loading' && <p role="status">正在检查 go2rtc 服务…</p>}
    {state === 'error' && <div role="alert" className="inline-error">{error}</div>}
    {state === 'ready' && <iframe ref={frame} key={`${selected}:${generation}:${streamsGeneration}`} className="go2rtc-frame" title="go2rtc 官方 WebUI"
      src={`${base}${selected}`} allow="camera; microphone; fullscreen" />}
  </section>;
}
