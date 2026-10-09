import { useEffect, useRef, useState } from 'react';
import { useDesktopWork } from './desktopRuntime';
import { withRequestTimeout } from './requestTimeout';
import { load as loadYaml } from 'js-yaml';

async function storedStreamNames(signal: AbortSignal): Promise<object> {
  const response = await fetch('/api/v1/go2rtc/api/config', { credentials: 'same-origin', cache: 'no-store', signal });
  if (!response.ok || !response.body) throw new Error('无法读取私密配置，请检查管理员权限和 go2rtc 状态。');
  const reader = response.body.getReader(), decoder = new TextDecoder();
  let size = 0, text = '';
  try {
    while (true) {
      const chunk = await reader.read();
      if (chunk.done) break;
      size += chunk.value.byteLength;
      if (size > 2 * 1024 * 1024) throw new Error('现有配置超过 2 MiB，请使用官方配置编辑器添加来源。');
      text += decoder.decode(chunk.value, { stream: true });
    }
    text += decoder.decode();
    let value: unknown;
    try { value = loadYaml(text); } catch { throw new Error('现有 YAML 配置无法解析，请先在官方配置编辑器修复。'); }
    if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('现有配置格式无效，请先在官方配置编辑器修复。');
    const streams = (value as { streams?: unknown }).streams;
    if (streams != null && (typeof streams !== 'object' || Array.isArray(streams))) throw new Error('现有 streams 配置格式无效，请先在官方配置编辑器修复。');
    return streams && typeof streams === 'object' ? streams : {};
  } finally { await reader.cancel().catch(() => undefined); reader.releaseLock(); }
}

type Engine = 'auto' | 'yt-dlp' | 'streamlink' | 'direct';
function sourceEngine(engine: Engine, url: URL): Exclude<Engine, 'auto'> {
  if (engine !== 'auto') return engine;
  return ['rtsp:', 'rtsps:', 'rtmp:', 'rtmps:'].includes(url.protocol) ||
    /\.(m3u8|mp4|mjpeg|mjpg|ts)$/i.test(url.pathname) ? 'direct' : 'yt-dlp';
}
export function onlineSourceUri(engine: Engine, address: string, height: string, video: string, cookies: string, windows: boolean): string {
  const bytes = new TextEncoder().encode(address);
  let url: URL;
  try { url = new URL(address); } catch { throw new Error('请输入完整地址，例如 rtsp://设备地址/流 或 https://视频网站/视频。'); }
  const resolved = sourceEngine(engine, url);
  const cameraCredentials = resolved === 'direct' && ['rtsp:', 'rtsps:'].includes(url.protocol);
  if (bytes.length > 2048 || /[\s\x00-\x1f\x7f]/.test(address) || !url.hostname ||
      (!cameraCredentials && (url.username || url.password)) ||
      !(resolved === 'direct' ? ['http:', 'https:', 'rtsp:', 'rtsps:', 'rtmp:', 'rtmps:'] : ['http:', 'https:']).includes(url.protocol))
    throw new Error('请输入单个有效视频网页或直播地址（最多 2048 字节），账号登录请使用私密 Cookie 配置。');
  if (resolved === 'direct') {
    if (['youtube.com', 'www.youtube.com', 'm.youtube.com', 'music.youtube.com', 'youtu.be'].includes(url.hostname.toLowerCase()))
      throw new Error('YouTube 链接是视频网页，请选择“自动识别”或“视频网页 · yt-dlp”，不能作为直接媒体地址。');
    if (url.hash) throw new Error('直接媒体地址不能带 # 参数，请在官方流管理中配置高级选项。');
    return ['rtmp:', 'rtmps:'].includes(url.protocol) ? `ffmpeg:${address}#video=copy#audio=copy` : address;
  }
  if (!['360', '480', '720', '1080', '1440', '2160'].includes(height) || !['auto', 'copy', 'h264'].includes(video) ||
      (cookies && !/^[A-Za-z0-9_-]{1,64}$/.test(cookies))) throw new Error('源设置无效；Cookie 配置仅接受名称。');
  const encoded = btoa(Array.from(bytes, byte => String.fromCharCode(byte)).join('')).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
  return `exec:webobs-online-source --engine ${resolved} --url64 ${encoded} --height ${height} --video ${video}${cookies ? ` --cookies-name ${cookies}` : ''} --output {output}#starttimeout=90${windows ? '' : '#killsignal=15#killtimeout=5'}`;
}

export default function Go2rtcOnlineSources({ enabled, platform, onCreated }: { enabled: boolean; platform: string; onCreated: () => void }) {
  const [engine, setEngine] = useState<Engine>('auto');
  const [name, setName] = useState('');
  const [address, setAddress] = useState('');
  const [height, setHeight] = useState('720');
  const [video, setVideo] = useState('auto');
  const [cookies, setCookies] = useState('');
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');
  const pending = useRef<AbortController | null>(null);
  useEffect(() => setEngine(enabled ? 'auto' : 'direct'), [enabled]);
  useEffect(() => () => pending.current?.abort(), []);
  useDesktopWork('online-source', Boolean(address || name));
  const create = async (event: React.FormEvent) => {
    event.preventDefault();
    if (pending.current) return;
    const controller = new AbortController(); pending.current = controller;
    setBusy(true); setNotice(''); setError('');
    try {
      if (!/^[\p{L}\p{N} _.-]{1,128}$/u.test(name) || !name.trim()) throw new Error('请填写独立流名称（1–128 个字符），不能包含斜线。');
      if (!enabled && engine !== 'direct') throw new Error('此后端未安装网站解析运行时，请升级完整容器或 Windows x64 安装包。');
      const source = onlineSourceUri(engine, address.trim(), height, video, cookies.trim(), platform === 'windows');
      await withRequestTimeout(30000, async signal => {
        const existing = await fetch('/api/v1/go2rtc/api/streams', { credentials: 'same-origin', cache: 'no-store', signal });
        if (!existing.ok) throw new Error(existing.status === 403 ? '添加源需要系统设置管理权限。' : '无法读取现有流，请检查登录和 go2rtc 状态。');
        const streams = await existing.json() as Record<string, unknown>;
        if (Object.hasOwn(streams, name) || Object.hasOwn(await storedStreamNames(signal), name)) throw new Error('已有同名流，请使用新名称；修改已有源请打开官方流管理。');
        // Upstream intentionally rejects exec through /api/streams. Its administrator
        // config merge API accepts this fixed template and preserves other configuration.
        const response = await fetch('/api/v1/go2rtc/api/config', { method: 'PATCH', credentials: 'same-origin', cache: 'no-store', signal,
          headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ streams: { [name]: [source] } }) });
        if (!response.ok) throw new Error(response.status === 403 ? '添加源需要系统设置管理权限。' : '流未保存，请检查 go2rtc 配置是否可写后重试。');
        const restart = await fetch('/api/v1/go2rtc/api/restart', { method: 'POST', credentials: 'same-origin', cache: 'no-store', signal });
        if (!restart.ok) throw new Error('流已保存，但重载请求失败。请检查 go2rtc 状态后在官方配置中保存并重启。');
        while (!signal.aborted) {
          const active = await fetch('/api/v1/go2rtc/api/streams', { credentials: 'same-origin', cache: 'no-store', signal }).catch(() => null);
          if (active?.ok && Object.hasOwn(await active.json(), name)) return;
          await new Promise<void>(resolve => window.setTimeout(resolve, 500));
        }
      }, controller.signal);
      if (!controller.signal.aborted) {
        setNotice(`“${name}”已保存并加载。先在官方流管理中测试播放，再在下方“检测并添加设备”加入监控墙。`);
        setAddress(''); setName(''); onCreated();
      }
    } catch (reason) {
      if (!controller.signal.aborted) setError(reason instanceof DOMException && reason.name === 'TimeoutError'
        ? '保存或重载请求超时，结果尚未确认。请检查官方配置和下方流列表；已保存的源可通过“保存并重启”重新加载。'
        : reason instanceof Error ? reason.message : '添加源失败，请重试。');
    } finally { pending.current = null; if (!controller.signal.aborted) setBusy(false); }
  };
  return <section className="go2rtc-streams online-sources" aria-label="网站与直播源">
    <h2>添加网站与直播源</h2>
    <p>yt-dlp 解析视频网页，Streamlink 接入直播网站；HLS、HTTP、RTSP 和 RTMP 媒体地址可直接接入。连接时解析最新播放地址，按需启动转发。</p>
    <p>添加后会重启 go2rtc 应用新配置，现有桥接播放和录像输入会短暂中断；请安排合适时间操作。</p>
    {!enabled && <p role="status">当前后端未提供网站解析工具。请升级完整容器或 Windows x64 客户端；Android 使用所连接后端的工具。</p>}
    <form onSubmit={event => void create(event)}>
      <fieldset disabled={busy}><div className="online-source-fields">
        <label>接入方式<select value={engine} onChange={event => setEngine(event.target.value as Engine)}>
          <option value="auto" disabled={!enabled}>自动识别 · 网页 / RTSP / 媒体地址</option>
          <option value="yt-dlp" disabled={!enabled}>视频网页 · yt-dlp</option>
          <option value="streamlink" disabled={!enabled}>直播网站 · Streamlink</option>
          <option value="direct">直接媒体地址 · HLS / HTTP / RTSP / RTMP</option>
        </select></label>
        <label>流名称<input value={name} onChange={event => setName(event.target.value)} maxLength={128} placeholder="例如：网站直播" required autoComplete="off" /></label>
        <label className="online-source-address">视频网页或直播地址<input type="url" value={address} onChange={event => setAddress(event.target.value)} maxLength={2048} placeholder="rtsp://设备地址/流 或 https://视频网站/视频" required autoComplete="off" spellCheck={false} /></label>
        {engine !== 'direct' && <>
          <label>优先清晰度<select value={height} onChange={event => setHeight(event.target.value)}>{['360', '480', '720', '1080', '1440', '2160'].map(value => <option key={value} value={value}>{value}p</option>)}</select></label>
          <label>视频兼容策略<select value={video} onChange={event => setVideo(event.target.value)}>
            <option value="auto">自动 · H264 可直通，否则转换</option><option value="copy">直通 · 不转换编码</option><option value="h264">始终转换 H264</option>
          </select></label>
          <label>私密 Cookie 配置名（可选）<input value={cookies} onChange={event => setCookies(event.target.value)} maxLength={64} pattern="[A-Za-z0-9_-]+" placeholder="例如：my-account" autoComplete="off" /></label>
        </>}
      </div><button type="submit" disabled={!enabled && engine !== 'direct'}>{busy ? '正在保存并重载…' : '保存命名流并重启 go2rtc'}</button></fieldset>
    </form>
    {notice && <p role="status">{notice}</p>}{error && <p role="alert">{error}</p>}
    <details><summary>接入步骤、登录网站与常见问题</summary>
      <ol><li>选择 yt-dlp（单个视频或直播网页）、Streamlink（直播网页）或直接媒体地址，填写独立流名称并保存。新增命名流只会在播放时启动解析和转发。</li>
        <li>在官方“流管理”中找到该名称，打开播放测试；解析可能需要几十秒。私有、已结束、受地域限制或 DRM 视频可能无法播放。</li>
        <li>在下方刷新 go2rtc 流，点击“检测并添加设备”；然后在 Studio 选择设备加入场景。Android、Windows 和浏览器都使用同一后端设备目录。</li>
        <li>播放失败时检查网页在后端网络是否可访问、直播是否在线。尝试另一解析器或“H264 转换”；在配置/日志中查看固定错误提示。网站规则变化时升级 WebOBS 获取新的解析器。</li>
      </ol>
      <p>需要登录的网站：管理员在后端私密 go2rtc 配置目录的 <code>cookies/配置名.txt</code> 放置 Netscape 格式 Cookie 文件，再填写配置名。Windows 位于用户 WebOBS 数据目录的 <code>config/go2rtc/cookies</code>；容器位于 <code>/config/webobs/go2rtc/cookies</code>，目录 0700、文件 0600。Cookie 过期后需替换；页面不会上传 Cookie，也不会使用 WebOBS 登录会话访问视频网站。</p>
      <p>网站 Cookie 用于解析登录页面、获取签名播放地址。当前不支持必须向媒体服务器透传 Cookie 或 Authorization 的来源；这类来源会显示 <code>media_credentials_unsupported</code>，请使用可解析出签名媒体地址的来源。</p>
      <p>默认优先 720p；网站提供的清晰度以实际可用轨道为准。自动模式优先直通已识别的 H264，未知或不兼容的视频使用 FFmpeg 转换，可能增加 CPU 使用；可自行选择直通。点播从开头播放，观看权限需由用户自行具备。</p>
      <p><a href="https://github.com/yt-dlp/yt-dlp/blob/master/supportedsites.md" target="_blank" rel="noopener noreferrer">yt-dlp 支持的网站 ↗</a> · <a href="https://streamlink.github.io/plugins.html" target="_blank" rel="noopener noreferrer">Streamlink 直播插件 ↗</a></p>
    </details>
  </section>;
}
