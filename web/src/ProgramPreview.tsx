import { useEffect, useRef, useState } from 'react';
import { useMonitorPreferences } from './useMonitorPreferences';
import { openProjectorWindow } from './projector';
import { connectProgram, type PlaybackStage, type ProgramConnection, type ProgramConnectionState, type ProgramStatus } from './whep';

const labels: Record<ProgramConnectionState, string> = {
  checking: '正在检查节目流',
  connecting: '正在连接节目流',
  live: '实时节目',
  reconnecting: '节目流重连中',
  offline: '节目流暂时离线',
  disabled: 'Composite 未启用',
};

const configurationLabels: Record<string, string> = {
  ready: '已就绪', incomplete: '依赖不完整', disabled: '未启用', unknown: '未知',
};
const engineLabels: Record<string, string> = {
  ready: '已就绪', starting: '启动中', stopped: '未启动', failed: '启动失败', unknown: '未知',
};
const publishLabels: Record<string, string> = {
  publishing: '已发布', idle: '未发布', failed: '发布失败', unknown: '未知',
};

export default function ProgramPreview({ aspectRatio, silent = false }: { aspectRatio: string; silent?: boolean }) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const connectionRef = useRef<ProgramConnection | null>(null);
  const [state, setState] = useState<ProgramConnectionState>('checking');
  const [stage, setStage] = useState<PlaybackStage | null>(null);
  const [status, setStatus] = useState<ProgramStatus | null>(null);
  const [audioEnabled, setAudioEnabled] = useState(false);
  const [audioBlocked, setAudioBlocked] = useState(false);
  const { view, setView, loaded, error: preferenceError } = useMonitorPreferences(silent);

  useEffect(() => {
    if (!videoRef.current) return undefined;
    const connection = connectProgram(videoRef.current, setState, setStage);
    connectionRef.current = connection;
    return () => { connection.close(); connectionRef.current = null; };
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    const load = () => void fetch('/api/v1/program/status', { cache: 'no-store', signal: controller.signal })
      .then((response) => response.ok ? response.json() as Promise<ProgramStatus> : null)
      .then((value) => { if (value) setStatus(value); })
      .catch(() => undefined);
    load();
    const timer = window.setInterval(load, 5000);
    return () => { controller.abort(); window.clearInterval(timer); };
  }, []);

  useEffect(() => {
    const video = videoRef.current;
    if (!video || !loaded) return;
    video.volume = view.localMonitorVolume;
    if (silent || !view.audioMonitorEnabled || view.audioOutput !== 'speaker') {
      video.muted = true; setAudioEnabled(false); setAudioBlocked(false); return;
    }
    if (state !== 'live') return;
    let active = true;
    video.muted = false;
    void (connectionRef.current?.resume?.() ?? video.play()).then(() => {
      if (active) { setAudioEnabled(true); setAudioBlocked(false); }
    }).catch(() => {
      if (active) { video.muted = true; setAudioEnabled(false); setAudioBlocked(true); }
    });
    return () => { active = false; };
  }, [loaded, view.audioMonitorEnabled, view.audioOutput, view.localMonitorVolume, state, silent]);

  const toggleAudio = async () => {
    const video = videoRef.current;
    if (!video) return;
    if (audioEnabled) {
      if (!silent) setView((current) => ({ ...current, audioMonitorEnabled: false }));
      video.muted = true;
      setAudioEnabled(false);
      setAudioBlocked(false);
      return;
    }
    if (!silent) setView((current) => ({ ...current, audioMonitorEnabled: true, audioOutput: 'speaker' }));
    video.muted = false;
    try {
      await (connectionRef.current?.resume?.() ?? video.play());
      setAudioEnabled(true);
      setAudioBlocked(false);
    } catch {
      video.muted = true;
      setAudioEnabled(false);
      setAudioBlocked(true);
    }
  };

  const compositeDisabled = status ? !status.enabled : state === 'disabled';
  return (
    <div className="program-preview-shell">
      <div
        className="direct-audio-control program-audio-control"
        data-audio-enabled={audioEnabled ? 'true' : 'false'}
        data-audio-state={audioBlocked ? 'blocked' : audioEnabled ? 'running' : 'disabled'}
      >
        {preferenceError && <span role="alert">{preferenceError}</span>}
        <button type="button" aria-pressed={audioEnabled} onClick={() => void toggleAudio()}>
          {audioEnabled ? '关闭节目声音' : '启用节目声音'}
        </button>
        <button type="button" onClick={() => { openProjectorWindow('composite'); }}>独立小窗</button>
        <span>{audioBlocked ? '监听设置已保留；浏览器需要点击一次恢复声音。' : view.audioMonitorEnabled && !silent ? 'Composite 声音按账号设置恢复。' : 'Composite 声音监听已关闭。'}</span>
      </div>
      <div className={`program-preview ${state}`} style={{ aspectRatio }}>
        <video ref={videoRef} autoPlay muted={!audioEnabled} playsInline aria-label="实时合成节目画面" />
        <div className="program-preview-status" role="status">
          <i aria-hidden="true" />
          <span>{labels[state]}</span>
        </div>
        {state !== 'live' && <div className="program-preview-placeholder" aria-hidden="true">W</div>}
      </div>
      {state !== 'live' && (
        <div className="program-diagnostics" role="status">
          <strong>{labels[state]}</strong>
          <ul>
            <li>Composite 配置：{configurationLabels[status?.configuration ?? 'unknown']}</li>
            <li>合成引擎：{engineLabels[status?.engine ?? 'unknown']}</li>
            <li>Program 发布：{publishLabels[status?.publish ?? 'unknown']}</li>
            {status?.reason && <li>原因：{status.reason}</li>}
            {stage && <li>播放阶段：{stage.firstFrame ? '已出首帧' : stage.iceConnected ? 'ICE 已连接，等待首帧' : stage.signaling ? '信令完成，等待 ICE' : '正在建立信令'}</li>}
          </ul>
          {compositeDisabled && (
            <div className="program-guidance">
              <p>本地服务端合成需要显式开启，并按需构建 OBS 图形/媒体输入/编码与 WHIP 输出模块：</p>
              <code>.\scripts\dev.ps1 -Setup -Composite</code>
              <code>.\scripts\dev.ps1 -Composite</code>
              <p>修改启动参数后需要重启本次原生服务；日志目录：{status?.logs ?? '%USERPROFILE%\.cache\webobs-dev（项目哈希）\logs'}</p>
            </div>
          )}
          {stage?.autoplayBlocked && <button type="button" onClick={() => void toggleAudio()}>启用播放与声音</button>}
        </div>
      )}
    </div>
  );
}
