export type ScaleMode = 'contain' | 'cover' | 'stretch';
export type Transport = 'tcp' | 'udp';
export type AudioMonitoring = 'off' | 'monitor-only' | 'monitor-and-output';
export type BlendMode = 'normal' | 'add' | 'multiply' | 'screen';
export type FilterKind = 'crop-pad' | 'opacity' | 'color-correction' | 'mask-blend' | 'lut' | 'scaling' | 'delay';

export interface SceneFilter {
  id: string;
  kind: FilterKind;
  enabled: boolean;
  amount: number;
  value: string;
}

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
  syncOffsetMs: number;
  monitoring: AudioMonitoring;
  audioTrack: number;
  filters: SceneFilter[];
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

export interface ImageSceneSource extends SceneSourceBase { kind: 'image'; filePath: string }
export interface MediaSceneSource extends SceneSourceBase { kind: 'media'; filePath: string; loop: boolean }
export interface TextSceneSource extends SceneSourceBase { kind: 'text'; text: string; color: string }
export interface ColorSceneSource extends SceneSourceBase { kind: 'color'; color: string }
export interface NestedSceneSource extends SceneSourceBase { kind: 'nested'; sceneId: string }

export type SceneSource = RtspSceneSource | BrowserSceneSource | ImageSceneSource | MediaSceneSource |
  TextSceneSource | ColorSceneSource | NestedSceneSource;

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
  locked: boolean;
  groupId: string;
  rotation: number;
  opacity: number;
  blendMode: BlendMode;
}

export interface SceneDocument {
  schemaVersion: 4;
  revision: number;
  id: string;
  name: string;
  canvas: SceneCanvas;
  sources: SceneSource[];
  items: SceneItem[];
}

export interface StudioDocument {
  schemaVersion: 1;
  revision: number;
  programSceneId: string;
  previewSceneId: string;
  transition: {
    kind: 'cut' | 'fade';
    durationMs: number;
  };
  scenes: SceneDocument[];
}

export interface StudioModeCapability {
  selected: 'direct' | 'hybrid' | 'composite';
  exact: boolean;
  reasons: string[];
}

export interface StudioCapabilities {
  revision: number;
  scenes: Array<{
    sceneId: string;
    direct: StudioModeCapability;
    hybrid: StudioModeCapability;
  }>;
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
  audioCodec: string;
}

export interface PlaybackCapabilities {
  defaultMode: 'composite';
  modes: {
    composite: { enabled: boolean; endpoint: string };
    direct: { enabled: boolean; fallback: 'composite' };
  };
  sources: SourcePlaybackCapability[];
}
