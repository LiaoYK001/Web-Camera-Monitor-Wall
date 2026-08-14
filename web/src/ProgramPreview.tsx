import { useEffect, useRef, useState } from 'react';
import { connectProgram, type ProgramConnectionState } from './whep';

const labels: Record<ProgramConnectionState, string> = {
  checking: '正在检查节目流',
  connecting: '正在连接节目流',
  live: '实时节目',
  reconnecting: '节目流重连中',
  offline: '节目流暂时离线',
  disabled: 'WebRTC 播放未启用',
};

export default function ProgramPreview({ aspectRatio }: { aspectRatio: string }) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [state, setState] = useState<ProgramConnectionState>('checking');
  const [audioEnabled, setAudioEnabled] = useState(false);
  const [audioBlocked, setAudioBlocked] = useState(false);

  useEffect(() => {
    if (!videoRef.current) return undefined;
    const connection = connectProgram(videoRef.current, setState);
    return connection.close;
  }, []);

  const toggleAudio = async () => {
    const video = videoRef.current;
    if (!video) return;
    if (audioEnabled) {
      video.muted = true;
      setAudioEnabled(false);
      setAudioBlocked(false);
      return;
    }
    video.muted = false;
    try {
      await video.play();
      setAudioEnabled(true);
      setAudioBlocked(false);
    } catch {
      video.muted = true;
      setAudioEnabled(false);
      setAudioBlocked(true);
    }
  };

  return (
    <div className="program-preview-shell">
      <div
        className="direct-audio-control program-audio-control"
        data-audio-enabled={audioEnabled ? 'true' : 'false'}
        data-audio-state={audioBlocked ? 'blocked' : audioEnabled ? 'running' : 'disabled'}
      >
        <button type="button" aria-pressed={audioEnabled} onClick={() => void toggleAudio()}>
          {audioEnabled ? '关闭节目声音' : '启用节目声音'}
        </button>
        <span>{audioBlocked ? '浏览器阻止了播放，请再次点击。' : 'Composite Opus 默认静音，点击后启用。'}</span>
      </div>
      <div className={`program-preview ${state}`} style={{ aspectRatio }}>
        <video ref={videoRef} autoPlay muted={!audioEnabled} playsInline aria-label="实时合成节目画面" />
        <div className="program-preview-status" role="status">
          <i aria-hidden="true" />
          <span>{labels[state]}</span>
        </div>
        {state !== 'live' && <div className="program-preview-placeholder" aria-hidden="true">W</div>}
      </div>
    </div>
  );
}
