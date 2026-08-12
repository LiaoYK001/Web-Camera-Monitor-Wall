import { type CSSProperties, useEffect, useMemo, useRef, useState } from 'react';
import { fetchPlaybackCapabilities } from './api';
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

function DirectTile({ item, source, capability }: {
  item: SceneItem;
  source: SceneSource;
  capability?: SourcePlaybackCapability;
}) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [state, setState] = useState<ProgramConnectionState>(capability ? 'checking' : 'offline');
  const [dimensions, setDimensions] = useState({ width: 0, height: 0 });

  useEffect(() => {
    if (!videoRef.current || !capability) return undefined;
    const connection = connectSource(videoRef.current, capability.endpoint, setState);
    return connection.close;
  }, [capability]);

  const geometry = useMemo(
    () => videoGeometry(item, dimensions.width, dimensions.height),
    [item, dimensions],
  );

  return (
    <div className={`direct-tile ${state}`} data-source-id={source.id}>
      <video
        ref={videoRef}
        autoPlay
        muted
        playsInline
        style={geometry}
        aria-label={`${source.name} 直达画面`}
        onLoadedMetadata={(event) => setDimensions({
          width: event.currentTarget.videoWidth,
          height: event.currentTarget.videoHeight,
        })}
      />
      <span className="direct-tile-state"><i aria-hidden="true" />{labels[state]}</span>
      {state !== 'live' && <span className="direct-tile-name">{source.name}</span>}
    </div>
  );
}

export default function DirectPreview({ scene }: { scene: SceneDocument }) {
  const [capabilities, setCapabilities] = useState<SourcePlaybackCapability[]>([]);
  const [available, setAvailable] = useState(true);

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

  return (
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
              <DirectTile item={item} source={source} capability={bySource.get(source.id)} />
            </div>
          );
        })}
      {!available && <div className="direct-preview-unavailable">Direct WebRTC 当前不可用，请切换到服务端合成。</div>}
    </div>
  );
}
