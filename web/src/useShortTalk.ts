import { useCallback, useEffect, useRef, useState } from 'react';
import { ControlApiError, sendOnvifTalk } from './api';
import { isPageVisible, subscribePageVisibility } from './pageVisibility';
import { withRequestTimeout } from './requestTimeout';

type Phase = 'idle' | 'requesting' | 'recording' | 'encoding' | 'sending';
type Capture = { controller: AbortController; stream?: MediaStream; recorder?: MediaRecorder;
  reader?: FileReader; timer?: number; chunks: Blob[]; size: number; contentType?: string };
const MAX_BYTES = 512 * 1024;
function stopTracks(capture: Capture) {
  capture.stream?.getTracks().forEach(track => { track.onended = null; track.stop(); });
  capture.stream = undefined;
}

/** A short, deliberate clip. Leaving/backgrounding discards it; returning never records. */
export function useShortTalk(cameraId: string, fail: (message: string) => void, enabled = true) {
  const [phase, setPhase] = useState<Phase>('idle');
  const [status, setStatus] = useState('');
  const capture = useRef<Capture | null>(null);
  const mounted = useRef(false), failure = useRef(fail); failure.current = fail;
  const release = useCallback((message = '') => {
    const value = capture.current; capture.current = null;
    if (value) {
      value.controller.abort(); window.clearTimeout(value.timer);
      if (value.recorder) {
        value.recorder.onstop = null; value.recorder.ondataavailable = null; value.recorder.onerror = null;
        if (value.recorder.state !== 'inactive') { try { value.recorder.stop(); } catch { /* Tracks still close below. */ } }
      }
      stopTracks(value);
      if (value.reader?.readyState === FileReader.LOADING) value.reader.abort();
      value.chunks = [];
    }
    if (mounted.current) { setPhase('idle'); setStatus(message); }
  }, []);
  const current = (value: Capture) => mounted.current && capture.current === value && !value.controller.signal.aborted && isPageVisible();
  useEffect(() => {
    mounted.current = true; setPhase('idle'); setStatus('');
    const unsubscribe = subscribePageVisibility(() => {
      if (!isPageVisible() && capture.current) {
        const sending = capture.current.reader != null;
        release(sending ? '已停止等待对讲结果；已提交的片段可能仍在设备播放，最多 10 秒。'
          : '已释放麦克风并丢弃未发送的录音；返回后需重新点击录音。');
      }
    });
    return () => { mounted.current = false; release(); unsubscribe(); };
  }, [cameraId, enabled, release]);

  const sendClip = async (value: Capture, blob: Blob) => {
    if (!current(value)) return;
    setPhase('encoding'); setStatus('正在准备对讲片段…');
    try {
      await withRequestTimeout(20000, async signal => {
        const encoded = await new Promise<string>((resolve, reject) => {
          const reader = new FileReader(); value.reader = reader;
          reader.onload = () => resolve(String(reader.result).split(',', 2)[1] ?? '');
          reader.onerror = () => reject(new Error('录音读取失败，请重新录音。'));
          reader.onabort = () => reject(new DOMException('录音已丢弃', 'AbortError'));
          reader.readAsDataURL(blob);
        });
        if (signal.aborted || !current(value)) throw new DOMException('录音已丢弃', 'AbortError');
        setPhase('sending'); setStatus('正在发送对讲片段…');
        return sendOnvifTalk(cameraId, { operation: 'start', contentType: value.contentType, data: encoded }, signal);
      }, value.controller.signal);
      if (current(value)) release('对讲片段已提交，设备播放最多 10 秒；可使用“停止设备对讲”结束播放。');
    } catch (reason) {
      if (!current(value)) return;
      release();
      failure.current(reason instanceof DOMException && reason.name === 'TimeoutError'
        ? '对讲请求超时，发送结果尚未确认。请检查设备状态，勿立即重复发送；可停止设备对讲。'
        : reason instanceof ControlApiError && reason.status === 403 ? '当前账号没有对讲权限，请联系管理员。'
        : reason instanceof ControlApiError && reason.status === 401 ? '登录已失效，请重新登录后操作。'
        : reason instanceof Error ? reason.message : '对讲发送失败，请检查设备后重试。');
    }
  };
  const send = () => {
    const value = capture.current;
    if (!value?.recorder || value.recorder.state !== 'recording' || !current(value)) return;
    window.clearTimeout(value.timer);
    try { value.recorder.stop(); stopTracks(value); }
    catch { release(); failure.current('录音无法结束，请重新录音。'); }
  };
  const record = async () => {
    if (!enabled || capture.current || !mounted.current || !isPageVisible()) return;
    const value: Capture = { controller: new AbortController(), chunks: [], size: 0 };
    capture.current = value; setPhase('requesting'); setStatus('正在请求麦克风…'); failure.current('');
    try {
      if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === 'undefined')
        throw new Error('当前浏览器不支持录音。局域网访问请使用 HTTPS 并确认麦克风权限。');
      const stream = await withRequestTimeout(20000, async signal => {
        const acquired = await navigator.mediaDevices.getUserMedia({ audio: true });
        if (signal.aborted || !current(value)) {
          acquired.getTracks().forEach(track => track.stop());
          throw new DOMException('录音已取消', 'AbortError');
        }
        value.stream = acquired; return acquired;
      }, value.controller.signal);
      if (!current(value)) return;
      const mimeType = ['audio/webm', 'audio/ogg', 'audio/mp4'].find(type => MediaRecorder.isTypeSupported(type));
      if (!mimeType) throw new Error('当前浏览器没有可用的对讲录音格式，请更换浏览器。');
      const recorder = new MediaRecorder(stream, { mimeType }); value.recorder = recorder;
      value.contentType = (recorder.mimeType || mimeType).split(';', 1)[0];
      recorder.ondataavailable = event => {
        if (!current(value) || !event.data.size) return;
        value.size += event.data.size;
        if (value.size > MAX_BYTES) { release(); failure.current('录音超过 512 KiB，已丢弃并释放麦克风。请缩短录音。'); }
        else value.chunks.push(event.data);
      };
      recorder.onerror = () => { if (current(value)) { release(); failure.current('录音中断，已释放麦克风。请重试。'); } };
      recorder.onstop = () => {
        if (!current(value)) return;
        window.clearTimeout(value.timer); stopTracks(value);
        const blob = new Blob(value.chunks, { type: value.contentType }); value.chunks = [];
        if (!blob.size) { release(); failure.current('没有取得有效录音，请检查麦克风后重试。'); return; }
        void sendClip(value, blob);
      };
      stream.getTracks().forEach(track => { track.onended = () => {
        if (current(value)) { release(); failure.current('麦克风已断开，录音未发送。请检查设备后重试。'); }
      }; });
      recorder.start(250); setPhase('recording'); setStatus('正在录音，再次点击即发送（最长 10 秒）；也可丢弃。');
      value.timer = window.setTimeout(send, 10000);
    } catch (reason) {
      if (!current(value)) return;
      release();
      failure.current(reason instanceof DOMException && reason.name === 'NotAllowedError' ? '麦克风权限未授予，请在浏览器或应用设置中允许后重试。'
        : reason instanceof DOMException && reason.name === 'TimeoutError' ? '等待麦克风超时，请确认浏览器权限后重试。'
        : reason instanceof Error ? reason.message : '麦克风或录音不可用，请检查权限和浏览器支持。');
    }
  };
  return { phase, status, record, send, discard: () => release(capture.current?.reader
    ? '已停止等待对讲结果；已提交的片段可能仍在播放，可停止设备对讲。' : '已丢弃未发送的录音并释放麦克风。') };
}
