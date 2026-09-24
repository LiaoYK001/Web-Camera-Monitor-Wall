import { useEffect, useMemo, useState } from 'react';
import type { DirectAudioSnapshot } from './directAudioMixer';

export interface AudioMixerChannel {
  sourceId: string;
  name: string;
  hasAudio: boolean;
  gain: number;
  muted: boolean;
  monitor: boolean;
  merged: boolean;
  tracks: Array<{ index: number; label: string; selected: boolean; gain: number; muted: boolean; rmsDbfs: number | null; peakDbfs: number | null }>;
}

export interface AudioMixerBarProps {
  channels: AudioMixerChannel[];
  snapshot: DirectAudioSnapshot;
  audioEnabled: boolean;
  masterVolume: number;
  output: 'speaker' | 'meter-only';
  compact?: boolean;
  onToggleAudio: () => void;
  onMasterVolume: (value: number) => void;
  onOutput: (value: 'speaker' | 'meter-only') => void;
  onSourceGain: (sourceId: string, gain: number) => void;
  onSourceMute: (sourceId: string, muted: boolean) => void;
  onSourceMonitor: (sourceId: string, monitor: boolean) => void;
  onToggleTrack: (sourceId: string, trackIndex: number) => void;
  onToggleMerge: (sourceId: string) => void;
}

function meterPercent(dbfs: number | null | undefined): number {
  if (dbfs === null || dbfs === undefined) return 0;
  return Math.max(0, Math.min(100, (dbfs + 60) / 0.6));
}

/**
 * F6-06 OBS-style horizontal Audio Mixer.  Only sources that really carry
 * audio tracks get a channel (F6-02); video-only tiles never pollute the strip.
 */
export default function AudioMixerBar({
  channels, snapshot, audioEnabled, masterVolume, output, compact,
  onToggleAudio, onMasterVolume, onOutput, onSourceGain, onSourceMute, onSourceMonitor,
  onToggleTrack, onToggleMerge,
}: AudioMixerBarProps) {
  const [collapsed, setCollapsed] = useState(false);
  const levels = useMemo(() => {
    const map = new Map<string, { rms: number | null; peak: number | null }>();
    for (const source of snapshot.sources) {
      map.set(source.sourceId, {
        rms: source.merged?.rmsDbfs ?? source.rmsDbfs,
        peak: source.merged?.peakDbfs ?? source.peakDbfs,
      });
    }
    return map;
  }, [snapshot]);
  const audible = channels.filter((channel) => channel.hasAudio);
  if (!audible.length) return null;
  return (
    <section className={`audio-mixer-bar${collapsed ? ' collapsed' : ''}`} aria-label="Audio Mixer">
      <header className="audio-mixer-bar-head">
        <strong>Audio Mixer</strong>
        <button type="button" className="primary-button" aria-pressed={audioEnabled} onClick={onToggleAudio}>
          {audioEnabled ? '监听中' : '启用声音'}
        </button>
        <label className="audio-mixer-master">
          总音量
          <input type="range" min="0" max="1" step="0.01" value={masterVolume} onChange={(event) => onMasterVolume(Number(event.target.value))} />
        </label>
        <select aria-label="声音输出模式" value={output} onChange={(event) => onOutput(event.target.value as 'speaker' | 'meter-only')}>
          <option value="speaker">扬声器 + 电平表</option>
          <option value="meter-only">仅电平表 / 阈值</option>
        </select>
        <button type="button" className="ghost-button" onClick={() => setCollapsed((value) => !value)}>{collapsed ? '展开' : '收起'}</button>
      </header>
      {!collapsed && <div className="audio-mixer-columns">
        {audible.map((channel) => {
          const level = levels.get(channel.sourceId) ?? { rms: null, peak: null };
          return <article key={channel.sourceId} className="audio-mixer-channel" data-source-id={channel.sourceId}>
            <header>
              <span title={channel.name}>{channel.name}</span>
              <button type="button" className="ghost-button" aria-pressed={channel.merged} title="合并输出 / 独立电平"
                onClick={() => onToggleMerge(channel.sourceId)}>{channel.merged ? '合并' : '独立'}</button>
            </header>
            <div className="audio-mixer-meter" aria-label={`${channel.name} 电平`}>
              <div className="audio-mixer-meter-fill" style={{ height: `${meterPercent(level.rms)}%` }} />
              <div className="audio-mixer-meter-peak" style={{ bottom: `${meterPercent(level.peak)}%` }} />
            </div>
            <output className="audio-mixer-db">{level.peak === null ? '—' : `${level.peak.toFixed(1)} dB`}</output>
            <input className="audio-mixer-fader" type="range" min="0" max="1.5" step="0.01" aria-label={`${channel.name} 音量`}
              value={channel.gain} onChange={(event) => onSourceGain(channel.sourceId, Number(event.target.value))} />
            <div className="audio-mixer-actions">
              <button type="button" className={channel.muted ? 'active' : ''} aria-pressed={channel.muted}
                onClick={() => onSourceMute(channel.sourceId, !channel.muted)}>M</button>
              <button type="button" className={channel.monitor ? 'active' : ''} aria-pressed={channel.monitor}
                title="监听输出" onClick={() => onSourceMonitor(channel.sourceId, !channel.monitor)}>🎧</button>
            </div>
            {!compact && channel.tracks.length > 1 && <div className="audio-mixer-tracks">
              {channel.tracks.map((track) => <label key={track.index}>
                <input type="checkbox" checked={track.selected} onChange={() => onToggleTrack(channel.sourceId, track.index)} />
                {track.label}
              </label>)}
            </div>}
          </article>;
        })}
      </div>}
    </section>
  );
}
