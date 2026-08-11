export type ScaleMode = 'contain' | 'cover' | 'stretch';
export type Transport = 'tcp' | 'udp';

export interface SceneCanvas {
  width: number;
  height: number;
  backgroundColor: string;
}

export interface SceneSource {
  id: string;
  kind: 'rtsp';
  name: string;
  rtspUrl: string;
  transport: Transport;
  muted: boolean;
  volume: number;
}

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
  schemaVersion: 1;
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
