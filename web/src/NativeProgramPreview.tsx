import { useEffect, useState } from 'react';
import type { NativePreviewStatus } from './desktopRuntime';

export default function NativeProgramPreview() {
  const [status, setStatus] = useState<NativePreviewStatus | null>(null);
  const [error, setError] = useState('');
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const bridge = window.webobsDesktop?.nativePreview;
    if (!bridge) { setError('此桌面版本不支持原生监看。'); return; }
    let stopped = false;
    let timer: number | undefined;
    setError(''); setStatus(null);
    const poll = async () => {
      try {
        const value = await bridge('status');
        if (stopped) return;
        setStatus(value);
        timer = window.setTimeout(() => void poll(), 1000);
      } catch (cause) { if (!stopped) setError(cause instanceof Error ? cause.message : '原生监看不可用。'); }
    };
    void bridge('open').then(value => {
      if (stopped) return;
      setStatus(value); timer = window.setTimeout(() => void poll(), 1000);
    }).catch(cause => { if (!stopped) setError(cause instanceof Error ? cause.message : '原生监看无法启动。'); });
    return () => { stopped = true; window.clearTimeout(timer); void bridge('close').catch(() => {}); };
  }, [attempt]);
  const failed = status?.state === 3;
  return <section className="program-guidance" aria-label="Windows 原生监看">
    <h2>{error || failed ? '原生监看暂不可用' : status?.requested ? 'Program 已交给原生窗口显示' : status ? '原生窗口已关闭' : '正在打开原生窗口…'}</h2>
    <p>H.264 / H.265 直接解码并显示，不为本机画面进行视频转码。双击原生画面或按 F11 全屏，Esc 返回。</p>
    <p>画面使用已 TAKE 的 Program 布局；声音使用 Studio 来源的监听设置。需要浏览器统计或检测叠层时，可切回“浏览器媒体”。</p>
    {error && <p role="alert">{error}</p>}
    {failed && <p role="alert">原生窗口创建失败或登录已失效，请检查本机服务后重试。</p>}
    {status?.state === 2 && <p>窗口绘制次数：{status.frames}（用于确认窗口刷新）</p>}
    {(error || failed || (status && !status.requested)) && <button type="button" onClick={() => setAttempt(value => value + 1)}>重新打开原生窗口</button>}
  </section>;
}
