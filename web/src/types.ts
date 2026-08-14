export type ScaleMode = 'contain' | 'cover' | 'stretch';
export type Transport = 'tcp' | 'udp';

export interface SceneCanvas {
  width: number;
  height: number;
  backgroundColor: string;
}

interface SceneSourceBase {
  id: string;
  name: string;
  muted: boolean;
  volume: number;
}

export interface RtspSceneSource extends SceneSourceBase {
  kind: 'rtsp';
  rtspUrl: string;
  transport: Transport;
}

export interface BrowserSceneSource extends SceneSourceBase {
  kind: 'browser';
  url: string;
  width: number;
  height: number;
  fps: number;
  customCss: string;
  shutdownWhenHidden: boolean;
  restartWhenActive: boolean;
}

export type SceneSource = RtspSceneSource | BrowserSceneSource;

export interface SceneCrop {
  top: number;
  right: number;
  bottom: number;
  left: number;
}

export interface SceneItem {
  id: string;
  sourceId: string;
  x: number;
  y: number;
  width: number;
  height: number;
  scaleMode: ScaleMode;
  crop: SceneCrop;
  zIndex: number;
  visible: boolean;
}

export interface SceneDocument {
  schemaVersion: 2;
  revision: number;
  id: string;
  name: string;
  canvas: SceneCanvas;
  sources: SceneSource[];
  items: SceneItem[];
}

export interface SceneEvent {
  type: 'scene.snapshot' | 'scene.updated';
  scene: SceneDocument;
}

export interface ApiErrorEnvelope {
  error?: {
    code?: string;
    message?: string;
  };
  revision?: number;
}

export type PlaybackMode = 'composite' | 'direct';

export interface SourcePlaybackCapability {
  sourceId: string;
  endpoint?: string;
  preferred: 'direct' | 'composite';
  fallback: 'composite';
  strategy: 'unknown' | 'passthrough' | 'transcode' | 'composite';
  codec: string;
}

export interface PlaybackCapabilities {
  defaultMode: 'composite';
  modes: {
    composite: { enabled: boolean; endpoint: string };
    direct: { enabled: boolean; fallback: 'composite' };
  };
  sources: SourcePlaybackCapability[];
}
