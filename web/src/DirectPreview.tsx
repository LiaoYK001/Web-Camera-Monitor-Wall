import { type CSSProperties, useEffect, useMemo, useRef, useState } from 'react';
import { fetchPlaybackCapabilities } from './api';
import { DirectAudioMixer, type DirectAudioSnapshot } from './directAudioMixer';
import type { SceneDocument, SceneItem, SceneSource, SourcePlaybackCapability } from './types';
import { connectSource, type ProgramConnectionState } from './whep';

const labels: Record<ProgramConnectionState, string> = {
  checking: '检查中',
  connecting: '连接中',
  live: '直达',
  reconnecting: '重连中',
  offline: '离线',
  disabled: '未启用',
};

function videoGeometry(item: SceneItem, width: number, height: number): CSSProperties {
  if (width <= 0 || height <= 0) return { width: '100%', height: '100%', objectFit: item.scaleMode === 'stretch' ? 'fill' : item.scaleMode };
  const croppedWidth = Math.max(1, width - item.crop.left - item.crop.right);
  const croppedHeight = Math.max(1, height - item.crop.top - item.crop.bottom);
  const scaleX = item.width / croppedWidth;
  const scaleY = item.height / croppedHeight;
  const scale = item.scaleMode === 'contain' ? Math.min(scaleX, scaleY)
    : item.scaleMode === 'cover' ? Math.max(scaleX, scaleY) : 1;
  const renderedWidth = item.scaleMode === 'stretch' ? width * scaleX : width * scale;
  const renderedHeight = item.scaleMode === 'stretch' ? height * scaleY : height * scale;
  const contentWidth = item.scaleMode === 'stretch' ? item.width : croppedWidth * scale;
  const contentHeight = item.scaleMode === 'stretch' ? item.height : croppedHeight * scale;
  const left = (item.width - contentWidth) / 2 - item.crop.left * (item.scaleMode === 'stretch' ? scaleX : scale);
  const top = (item.height - contentHeight) / 2 - item.crop.top * (item.scaleMode === 'stretch' ? scaleY : scale);
  return {
    width: `${(renderedWidth / item.width) * 100}%`,
    height: `${(renderedHeight / item.height) * 100}%`,
    left: `${(left / item.width) * 100}%`,
    top: `${(top / item.height) * 100}%`,
  };
}

function DirectTile({ item, source, capability, mixer }: {
  item: SceneItem;
  source: SceneSource;
  capability?: SourcePlaybackCapability;
  mixer: DirectAudioMixer | null;
}) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [state, setState] = useState<ProgramConnectionState>(capability ? 'checking' : 'offline');
  const [dimensions, setDimensions] = useState({ width: 0, height: 0 });

  useEffect(() => {
    if (!videoRef.current || !mixer || !capability?.endpoint || capability.preferred !== 'direct') return undefined;
    const connection = connectSource(videoRef.current, capability.endpoint, setState,
      (stream) => mixer.bindStream(source.id, stream));
    return connection.close;
  }, [capability, mixer, source.id]);

  useEffect(() => {
    if (!mixer || !videoRef.current || !capability?.endpoint || capability.preferred !== 'direct') return undefined;
    return mixer.attach(source.id, videoRef.current);
  }, [capability, mixer, source.id]);

  const geometry = useMemo(
    () => videoGeometry(item, dimensions.width, dimensions.height),
    [item, dimensions],
  );

  return (
    <div
      className={`direct-tile ${state}`}
      data-source-id={source.id}
      data-audio-gain={source.muted ? '0' : source.volume.toFixed(3)}
      data-audio-sync-ms={source.syncOffsetMs}
    >
      <video
        ref={videoRef}
        autoPlay
        muted
        playsInline
        style={geometry}
        aria-label={`${source.name} 网关直通画面`}
        onLoadedMetadata={(event) => setDimensions({
          width: event.currentTarget.videoWidth,
          height: event.currentTarget.videoHeight,
        })}
      />
      <span className="direct-tile-state"><i aria-hidden="true" />{labels[state]}</span>
      {capability && capability.strategy !== 'unknown' && (
        <div className={`delivery-diagnostic cost-${capability.serverCost ?? 'low'}`}>
          <strong>{capability.deliveryMode === 'hybrid' ? 'HYBRID' : 'DIRECT RELAY'}</strong>
          <span>Video: {capability.videoDelivery ?? 'copy'} · Audio: {capability.audioDelivery ?? 'copy'}</span>
          <span>Server decode: {capability.serverVideoDecode ? 'ON' : 'OFF'} · encode: {capability.encoder ?? 'none'}</span>
          {capability.reason && <span>Reason: {capability.reason}</span>}
        </div>
      )}
      {source.kind === 'browser'
        ? <span className="direct-tile-name">{source.name} · 仅服务端合成</span>
        : state !== 'live' && <span className="direct-tile-name">{source.name}</span>}
    </div>
  );
}

export default function DirectPreview({ scene }: { scene: SceneDocument }) {
  const [capabilities, setCapabilities] = useState<SourcePlaybackCapability[]>([]);
  const [available, setAvailable] = useState(true);
  const [mixer, setMixer] = useState<DirectAudioMixer | null>(null);
  const [audio, setAudio] = useState<DirectAudioSnapshot>({ state: 'disabled', inputCount: 0, level: 0 });

  useEffect(() => {
    const nextMixer = new DirectAudioMixer(setAudio);
    setMixer(nextMixer);
    return () => nextMixer.destroy();
  }, []);

  useEffect(() => mixer?.configure(scene.sources), [mixer, scene.sources]);

  useEffect(() => {
    const controller = new AbortController();
    fetchPlaybackCapabilities(controller.signal)
      .then((result) => {
        setAvailable(result.modes.direct.enabled);
        setCapabilities(result.sources);
      })
      .catch(() => setAvailable(false));
    return () => controller.abort();
  }, [scene.revision]);

  const bySource = useMemo(
    () => new Map(capabilities.map((capability) => [capability.sourceId, capability])),
    [capabilities],
  );
  const audioEnabled = audio.state === 'running';

  return (
    <div className="direct-preview-shell">
      <div
        className="direct-audio-control"
        data-audio-enabled={audioEnabled ? 'true' : 'false'}
        data-audio-state={audio.state}
        data-audio-inputs={audio.inputCount}
        data-audio-level={audio.level.toFixed(4)}
      >
        <button
          type="button"
          aria-pressed={audioEnabled}
          onClick={() => { if (audioEnabled) void mixer?.disable(); else void mixer?.enable(); }}
        >{audioEnabled ? '关闭声音' : '启用声音'}</button>
        <span>{audio.state === 'blocked'
          ? '浏览器阻止了播放，请再次点击。'
          : `Web Audio 混音 · ${audio.inputCount} 路 · 默认静音，点击后启用`}</span>
      </div>
      <div
        className="direct-preview"
        data-direct-available={available ? 'true' : 'false'}
        style={{ aspectRatio: `${scene.canvas.width} / ${scene.canvas.height}`, backgroundColor: scene.canvas.backgroundColor }}
      >
        {[...scene.items]
          .filter((item) => item.visible)
          .sort((left, right) => left.zIndex - right.zIndex)
          .map((item) => {
            const source = scene.sources.find((candidate) => candidate.id === item.sourceId);
            if (!source) return null;
            const style = {
              left: `${(item.x / scene.canvas.width) * 100}%`,
              top: `${(item.y / scene.canvas.height) * 100}%`,
              width: `${(item.width / scene.canvas.width) * 100}%`,
              height: `${(item.height / scene.canvas.height) * 100}%`,
              zIndex: item.zIndex + 1,
            } as CSSProperties;
            return (
              <div className="direct-tile-position" style={style} key={item.id}>
                <DirectTile
                  item={item}
                  source={source}
                  capability={bySource.get(source.id)}
                  mixer={mixer}
                />
              </div>
            );
          })}
        {!available && <div className="direct-preview-unavailable">Direct WebRTC 当前不可用；请检查网关状态或显式启用 Composite。</div>}
      </div>
    </div>
  );
}
