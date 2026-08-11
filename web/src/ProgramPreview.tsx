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

  useEffect(() => {
    if (!videoRef.current) return undefined;
    const connection = connectProgram(videoRef.current, setState);
    return connection.close;
  }, []);

  return (
    <div className={`program-preview ${state}`} style={{ aspectRatio }}>
      <video ref={videoRef} autoPlay muted playsInline aria-label="实时合成节目画面" />
      <div className="program-preview-status" role="status">
        <i aria-hidden="true" />
        <span>{labels[state]}</span>
      </div>
      {state !== 'live' && <div className="program-preview-placeholder" aria-hidden="true">W</div>}
    </div>
  );
}
