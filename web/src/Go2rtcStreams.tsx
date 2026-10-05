import { useEffect, useId, useRef, useState } from 'react';
import { ControlApiError, createCamera, detectCamera, fetchCameras, probeSourceProfile } from './api';
import type { CameraRecord } from './types';
import { fetchRuntimeInfo, useDesktopWork } from './desktopRuntime';
import { useDraftGuard } from './useDraftGuard';
import { useOwnedRequest } from './useOwnedRequest';
import { withRequestTimeout } from './requestTimeout';

export const go2rtcStreamAddress = (name: string, base = 'rtsp://127.0.0.1:18554/') => `${base}${encodeURIComponent(name)}`;
// Only stream names leave this parser; producer URLs and diagnostics can contain secrets.
export function go2rtcStreamNames(value: unknown): string[] {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return [];
  return Object.keys(value).filter((name) => /^[\p{L}\p{N} _.-]{1,128}$/u.test(name)).sort().slice(0, 256);
}
export default function Go2rtcStreams({ onImported, refreshKey = 0, blocked = false, onBusyChange }: {
  onImported?: () => void; refreshKey?: number; blocked?: boolean; onBusyChange?: (busy: boolean) => void;
}) {
  const [names, setNames] = useState<string[]>([]);
  const [rtspBase, setRtspBase] = useState('rtsp://127.0.0.1:18554/');
  const [cameras, setCameras] = useState<CameraRecord[]>([]);
  const [status, setStatus] = useState('正在读取 go2rtc 流…');
  const [error, setError] = useState('');
  const [working, setWorking] = useState('');
  const [pending, setPending] = useState('');
  const [ready, setReady] = useState(false);
  const [search, setSearch] = useState('');
  const [generation, setGeneration] = useState(0);
  const imported = useRef(new Map<string, string>());
  const readingOwner = useRef<AbortController | null>(null);
  const submission = useRef<Partial<CameraRecord> | null>(null);
  const { run, busy, isMutating } = useOwnedRequest(setError, () => readingOwner.current?.abort());
  const workKey = useId();
  useDesktopWork(`go2rtc-import-${workKey}`, Boolean(pending), busy);
  useDraftGuard(Boolean(pending), busy, 'go2rtc 导入结果尚未确认，离开后需先核对设备目录。继续？', setStatus);
  useEffect(() => { onBusyChange?.(busy); return () => onBusyChange?.(false); }, [busy, onBusyChange]);
  useEffect(() => {
    const owner = new AbortController(); let reading = false;
    const refresh = async () => {
      if (reading || owner.signal.aborted || isMutating() || blocked) return;
      reading = true;
      const controller = new AbortController(); readingOwner.current = controller;
      const abort = () => controller.abort(); owner.signal.addEventListener('abort', abort, { once: true });
      const current = () => !owner.signal.aborted && !controller.signal.aborted && readingOwner.current === controller;
      try {
        const result = await withRequestTimeout(12000, async signal => {
        const response = await fetch('/api/v1/go2rtc/api/streams', { credentials: 'same-origin', cache: 'no-store', signal });
        if (!response.ok) {
          throw new ControlApiError(response.status, 'streams_unavailable', 'go2rtc 流暂不可用');
        }
        const names = go2rtcStreamNames(await response.json());
        const runtime = await fetchRuntimeInfo(signal), registry = await fetchCameras(signal);
        return { names, runtime, registry };
        }, controller.signal);
        if (current()) { setNames(result.names); setRtspBase(result.runtime.go2rtcRtspBase); setCameras(result.registry.cameras); setReady(true);
          setStatus(result.names.length ? `发现 ${result.names.length} 个命名流` : '暂无命名流，请先在 go2rtc 中添加并保存。'); }
      } catch (reason) { if (current()) { setReady(false); setStatus(reason instanceof ControlApiError && reason.status === 403
        ? '读取 go2rtc 流需要系统设置管理权限。' : reason instanceof ControlApiError && reason.status === 401
          ? '请登录后读取 go2rtc 流。' : 'go2rtc 流或内部地址读取失败，请检查服务后刷新；可继续手动添加设备。'); } }
      finally { owner.signal.removeEventListener('abort', abort); reading = false; }
    };
    void refresh();
    const timer = window.setInterval(() => { if (!document.hidden) void refresh(); }, 15000);
    const focus = () => void refresh(); window.addEventListener('focus', focus);
    return () => { owner.abort(); window.clearInterval(timer); window.removeEventListener('focus', focus); };
  }, [generation, refreshKey, blocked]);
  const existing = (name: string) => imported.current.get(name) ?? cameras.find((camera) =>
    camera.address === go2rtcStreamAddress(name, rtspBase) || camera.addressDisplay === go2rtcStreamAddress(name, rtspBase) ||
    camera.profiles.some((profile) => profile.endpoint === go2rtcStreamAddress(name, rtspBase)))?.id;
  const add = async (name: string) => {
    if (blocked || isMutating() || existing(name) || (pending && pending !== name)) return;
    setWorking(name);
    let created: CameraRecord | undefined;
    const confirmed = await run('导入 go2rtc 设备', async signal => {
      if (!submission.current) {
        const runtime = await fetchRuntimeInfo(signal);
        const address = go2rtcStreamAddress(name, runtime.go2rtcRtspBase);
        const detected = await detectCamera(address, undefined, signal);
        if (detected.adapter !== 'rtsp' || !detected.profiles.length) throw new Error('流尚未就绪，请先在 go2rtc 中测试播放');
        submission.current = { id: `camera-${crypto.randomUUID().replaceAll('-', '')}`, name, address, adapter: 'rtsp', hardwareDecode: 'auto', credentialsRef: '',
          profiles: detected.profiles.map(profile => ({ ...profile, transportMode: 'rtsp-tcp' })), capabilities: { bridge: 'go2rtc' } };
      }
      const submitted = submission.current;
      try {
        const record = await createCamera(submitted, signal);
        if (record.id !== submitted.id) throw new Error('服务未确认本次导入的设备标识');
        return record;
      } catch (reason) {
        if (!(reason instanceof ControlApiError) || reason.status !== 409) throw reason;
        const record = (await fetchCameras(signal)).cameras.find(camera => camera.id === submitted.id);
        if (!record) throw reason;
        return record;
      }
    }, camera => { created = camera; accept(camera, name); }, true, reason => {
      if (submission.current && (!(reason instanceof ControlApiError) || reason.status >= 500 || [408, 409].includes(reason.status))) setPending(name);
      else submission.current = null;
    });
    if (confirmed && created) {
      const camera: CameraRecord = created;
      await run('探测轨道', async signal => {
        for (const profile of camera.profiles) await probeSourceProfile(camera.id, profile.id, signal);
      }, () => setStatus(`“${name}”已建档并探测轨道。前往 Studio 的“选择场景来源”即可加入场景。`));
    }
  };
  const accept = (camera: CameraRecord, name: string) => {
    imported.current.set(name, camera.id); setCameras(values => [...values.filter(value => value.id !== camera.id), camera]);
    submission.current = null; setPending(''); onImported?.();
    setStatus(`“${name}”已加入设备目录；可在设备详情探测轨道，或前往 Studio 选择场景来源。`);
  };
  const reconcile = () => run('核对 go2rtc 导入', signal => fetchCameras(signal), result => {
    const record = result.cameras.find(camera => camera.id === submission.current?.id);
    if (record) accept(record, pending);
    else setStatus('目录中暂未找到这次导入。可继续提交同一设备；不自动生成第二个 ID。');
  }, false);
  return <section className="go2rtc-streams" aria-label="go2rtc 流接入">
    <header><h2>从 go2rtc 接入设备</h2><button type="button" disabled={busy || blocked} onClick={() => setGeneration((value) => value + 1)}>刷新 go2rtc 流</button>
      <a href="#go2rtc">管理 go2rtc</a></header>
    <p role="status">{status}</p>{error && <p role="alert">{error}</p>}
    {pending && <div className="notice" role="status"><p>“{pending}”导入结果尚未确认。请先核对；继续提交会保留同一设备 ID。</p>
      <button type="button" disabled={busy || blocked} onClick={() => void reconcile()}>核对导入结果</button>
      <button type="button" disabled={busy || blocked} onClick={() => void add(pending)}>继续提交同一设备</button></div>}
    <details><summary>从 go2rtc 到正式设备与场景：操作步骤</summary><ol>
      <li>打开“go2rtc 管理”，在流管理或设备与发现中添加来源，并在配置中保存命名流；先测试该流能播放。</li>
      <li>返回这里，刷新列表，点击对应流的“检测并添加设备”。系统使用后端内部 RTSP 地址检测并建档，摄像机密码继续保存在 go2rtc 配置中。</li>
      <li>在“设备与来源”查看刚添加的设备；轨道探测失败时，可在详情中重试，检查 go2rtc 源的编码与连接状态。</li>
      <li>前往 Studio，新建或右键场景 → 选择场景来源，勾选设备，调整画布位置并保存 Studio。可分别打开多个场景投影。</li>
    </ol><p>内部地址是后端环境的 <code>{rtspBase}流名称</code>。命名流无需再次做 ONVIF 发现；设备建档后使用稳定设备 ID。更改或删除 go2rtc 流名后，请同步调整设备地址。仅中转视频的流不具备原摄像机的 PTZ/ONVIF 功能。</p></details>
    {names.length > 0 && <><label>筛选 go2rtc 流<input value={search} onChange={(event) => setSearch(event.target.value)} maxLength={128} /></label>
      <div className="go2rtc-stream-list">{names.filter((name) => name.toLowerCase().includes(search.toLowerCase())).map((name) => <div key={name}>
        <strong>{name}</strong><code>{go2rtcStreamAddress(name, rtspBase)}</code><button type="button" disabled={busy || blocked || !ready || Boolean(pending) || Boolean(existing(name))}
          onClick={() => void add(name)}>{existing(name) ? '已在设备目录' : busy && working === name ? '检测并添加中…' : '检测并添加设备'}</button>
      </div>)}</div></>}
  </section>;
}
