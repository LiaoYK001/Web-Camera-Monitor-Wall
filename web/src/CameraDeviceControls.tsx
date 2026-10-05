import { useEffect, useRef, useState } from 'react';
import { ControlApiError, fetchOnvifPresets, fetchOnvifSnapshot, mutateOnvifPreset, pullOnvifEvents, sendOnvifPtz, sendOnvifTalk } from './api';
import { isPageVisible, subscribePageVisibility } from './pageVisibility';
import { withRequestTimeout } from './requestTimeout';
import { useShortTalk } from './useShortTalk';
import type { CameraRecord, OnvifPreset } from './types';

type Operation = { controller: AbortController; name: string; mutation: boolean };
export default function CameraDeviceControls({ camera, busy, fail }: { camera: CameraRecord; busy: boolean; fail: (message: string) => void }) {
  const capabilities = (camera.capabilities.onvif ?? {}) as Record<string, unknown>;
  const timeout = capabilities.ptzTimeout as { state?: string; minimumMs?: number; maximumMs?: number } | undefined;
  const minimum = timeout?.minimumMs, maximum = timeout?.maximumMs;
  const rangeAvailable = timeout?.state === 'available' && typeof minimum === 'number' && typeof maximum === 'number'
    && Number.isSafeInteger(minimum) && Number.isSafeInteger(maximum) && minimum >= 100 && maximum <= 2000 && minimum <= maximum;
  const low = rangeAvailable ? minimum! : 100, high = rangeAvailable ? maximum! : 2000;
  const incompatible = timeout?.state === 'unsupported';
  const [pulseMs, setPulseMs] = useState(350);
  const durationMs = Math.max(low, Math.min(high, pulseMs));
  useEffect(() => { setPulseMs(Math.max(low, Math.min(high, 350))); }, [camera.id, low, high]);
  const [presets, setPresets] = useState<OnvifPreset[]>([]);
  const [snapshot, setSnapshot] = useState('');
  const [status, setStatus] = useState('');
  const [pending, setPending] = useState('');
  const operation = useRef<Operation | null>(null), active = useRef(false);
  const talk = useShortTalk(camera.id, fail, capabilities.talk === true);
  useEffect(() => {
    active.current = true; setPresets([]); setSnapshot(''); setStatus(''); setPending('');
    const unsubscribe = subscribePageVisibility(() => {
      if (!isPageVisible() && operation.current) {
        const request = operation.current; operation.current = null; request.controller.abort();
        setPending(''); setStatus(request.mutation ? '已停止等待设备操作，结果尚未确认；返回后请核对设备状态。' : '已取消读取；返回后可重新读取。');
      }
    });
    return () => { active.current = false; operation.current?.controller.abort(); operation.current = null; unsubscribe(); };
  }, [camera.id, capabilities.ptz, capabilities.snapshot, capabilities.events]);
  const invoke = async <T,>(name: string, action: (signal: AbortSignal) => Promise<T>,
    success: string | ((result: T) => string), apply?: (result: T) => void, mutation = true, preempt = false) => {
    if (!active.current || !isPageVisible() || (operation.current && !preempt)) return;
    if (operation.current?.name === name && preempt) return;
    operation.current?.controller.abort();
    const request = { controller: new AbortController(), name, mutation }; operation.current = request;
    setPending(name); setStatus('正在处理设备操作…'); fail('');
    const current = () => active.current && operation.current === request && !request.controller.signal.aborted;
    try {
      const result = await withRequestTimeout(20000, action, request.controller.signal);
      if (current()) { apply?.(result); setStatus(typeof success === 'function' ? success(result) : success); }
    } catch (reason) {
      if (current()) {
        setStatus('');
        fail(reason instanceof DOMException && reason.name === 'TimeoutError'
          ? name === 'stop' ? '停止请求超时，尚未确认设备已停止。请检查设备状态并重试停止。'
          : mutation ? '设备操作超时，结果尚未确认。请核对设备状态，勿立即重复操作；仍可使用停止按钮。' : '设备读取超时，请检查网络后重试。'
          : reason instanceof ControlApiError && reason.status === 403 ? '当前账号没有此设备操作权限，请联系管理员。'
          : reason instanceof ControlApiError && reason.status === 401 ? '登录已失效，请重新登录后操作。'
          : `设备操作失败：${reason instanceof Error ? reason.message : '设备未响应'}。请检查设备连接或重新同步 ONVIF Profile。`);
      }
    } finally {
      if (operation.current === request) { operation.current = null; if (active.current) setPending(''); }
    }
  };
  const move = (x: number, y: number, zoom = 0) => invoke('move',
    signal => sendOnvifPtz(camera.id, { operation: 'continuous', x, y, zoom, durationMs }, signal), result => {
      if (typeof result.autoStopMs !== 'number' || !Number.isSafeInteger(result.autoStopMs) || result.autoStopMs < 100 || result.autoStopMs > 2000)
        return 'PTZ 命令已确认，停止时长尚未确认；请核对设备位置。';
      return result.deviceTimeoutMs === result.autoStopMs
        ? `PTZ 命令已确认，已提交设备侧超时 ${result.autoStopMs} 毫秒；后台也会请求停止。请核对设备位置。`
        : `PTZ 命令已确认，后台将在 ${result.autoStopMs} 毫秒后请求停止；设备侧超时尚未确认。请核对设备位置。`;
    });
  const disabled = busy || Boolean(pending);
  const moveDisabled = disabled || incompatible;
  if (!Object.values(capabilities).some(Boolean)) return null;
  return <div className="device-controls">
    {capabilities.ptz === true && <>
    <label>每次移动时长 <select aria-label="每次移动时长" value={durationMs} disabled={moveDisabled}
      onChange={event => setPulseMs(Number(event.target.value))}>
      {[...new Set([low, 350, 500, 1000, high].filter(value => value >= low && value <= high))].sort((a, b) => a - b)
        .map(value => <option key={value} value={value}>{value} 毫秒</option>)}
    </select></label>
    <small>{incompatible ? '设备超时范围不支持短时移动，可使用预置位或停止；请重新同步 ONVIF Profile 核对。'
      : rangeAvailable ? `设备侧超时范围 ${low}–${high} 毫秒；后台停止同时保留。`
      : '尚未确认设备自身的移动超时，当前依赖后台发送停止；请同步 ONVIF Profile。'}</small>
    <div className="ptz-pad" role="group" aria-label="PTZ 控制">
      <button type="button" aria-label="云台上移" disabled={moveDisabled} onClick={() => void move(0, 1)}>↑</button>
      <button type="button" aria-label="云台左移" disabled={moveDisabled} onClick={() => void move(-1, 0)}>←</button>
      <button type="button" aria-label="停止云台" disabled={pending === 'stop'} onClick={() => void invoke('stop',
        signal => sendOnvifPtz(camera.id, { operation: 'stop' }, signal), '停止云台命令已确认。', undefined, true, true)}>■</button>
      <button type="button" aria-label="云台右移" disabled={moveDisabled} onClick={() => void move(1, 0)}>→</button>
      <button type="button" aria-label="云台下移" disabled={moveDisabled} onClick={() => void move(0, -1)}>↓</button>
      <button type="button" aria-label="镜头放大" disabled={moveDisabled} onClick={() => void move(0, 0, .5)}>＋</button>
      <button type="button" aria-label="镜头缩小" disabled={moveDisabled} onClick={() => void move(0, 0, -.5)}>－</button>
    </div><div className="preset-controls">
      <button type="button" className="ghost-button" disabled={disabled} onClick={() => void invoke('presets',
        signal => fetchOnvifPresets(camera.id, signal), '预置位已读取。', value => setPresets(value.presets), false)}>预置位</button>
      {presets.map(preset => <button type="button" key={preset.token} disabled={disabled} onClick={() => void invoke('preset',
        signal => sendOnvifPtz(camera.id, { operation: 'gotoPreset', presetToken: preset.token }, signal), `预置位 ${preset.name} 命令已确认。`)}>{preset.name}</button>)}
      <button type="button" disabled={disabled} onClick={() => {
        const name = `Preset ${presets.length + 1}`;
        void invoke('save-preset', signal => mutateOnvifPreset(camera.id, { operation: 'set', name }, signal), '预置位已保存。',
          value => setPresets(current => [...current.filter(preset => preset.token !== value.presetToken), { token: value.presetToken, name }]));
      }}>保存当前位置</button>
    </div></>}
    <div className="device-actions">
      {capabilities.snapshot === true && <button type="button" disabled={disabled} onClick={() => void invoke('snapshot',
        signal => fetchOnvifSnapshot(camera.id, signal), '快照已读取。', value => setSnapshot(`data:${value.contentType};base64,${value.data}`), false)}>快照</button>}
      {capabilities.events === true && <button type="button" disabled={disabled} onClick={() => void invoke('events',
        signal => pullOnvifEvents(camera.id, signal), value => `收到 ${value.events.length} 个设备事件`, undefined, false)}>拉取事件</button>}
      {capabilities.talk === true && <>
        <button type="button" disabled={talk.phase !== 'recording' && (busy || talk.phase !== 'idle')}
          onClick={() => talk.phase === 'recording' ? talk.send() : void talk.record()}>{talk.phase === 'recording' ? '停止并发送' : '录制对讲'}</button>
        {['requesting', 'recording', 'encoding'].includes(talk.phase) && <button type="button" onClick={talk.discard}>丢弃录音</button>}
        <button type="button" disabled={pending === 'talk-stop'} onClick={() => { talk.discard(); void invoke('talk-stop',
          signal => sendOnvifTalk(camera.id, { operation: 'stop' }, signal), '停止设备对讲命令已确认。', undefined, true, true); }}>停止设备对讲</button>
      </>}
    </div>
    {snapshot && <img className="device-snapshot" src={snapshot} alt={`${camera.name} 快照`} />}
    {status && <small role="status">{status}</small>}{talk.status && <small role="status">{talk.status}</small>}
  </div>;
}
