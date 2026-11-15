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
  const sample = status?.draw_sample;
  const ready = (value: boolean) => value ? '是' : '否';
  return <section className="program-guidance" aria-label="Windows 原生监看">
    <h2>{error || failed ? '原生监看暂不可用' : status?.requested ? 'Program 原生监看已请求' : status ? '原生窗口已关闭' : '正在打开原生窗口…'}</h2>
    <p>H.264 / H.265 直接解码并显示，不为本机画面进行视频转码。双击原生画面或按 F11 全屏，Esc 返回。</p>
    <p>画面使用已 TAKE 的 Program 布局；声音使用 Studio 来源的监听设置。需要浏览器统计或检测叠层时，可切回“浏览器媒体”。</p>
    {error && <p role="alert">{error}</p>}
    {failed && <p role="alert">原生窗口创建失败或登录已失效，请检查本机服务后重试。</p>}
    {status?.state === 2 && <p>绘制回调次数：{status.frames}（不代表最终画面、媒体出帧或硬件解码）。请在原生窗口确认各路画面与时间进度。</p>}
    {sample?.available && status?.requested && <details>
      <summary>受控绘制诊断（不是画面验证）</summary>
      <p>最近采样回调：{sample.frame}；画布 {sample.base_width}×{sample.base_height}，显示 {sample.display_width}×{sample.display_height}。</p>
      <p>视频初始化：{ready(sample.video_ready)}；主纹理存在：{ready(sample.main_texture_ready)}；Program 绑定：{ready(sample.output_bound)}；来源 active：{ready(sample.output_active)}，showing：{ready(sample.output_showing)}。</p>
      <p>仅为先前一次受控绘制快照，可能滞后；不证明已 Present、五路出帧或硬解。重开时媒体需要恢复，持续黑屏仍须定位。</p>
    </details>}
    {(error || failed || (status && !status.requested)) && <button type="button" onClick={() => setAttempt(value => value + 1)}>重新打开原生窗口</button>}
  </section>;
}
