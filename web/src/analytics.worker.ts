/// <reference lib="webworker" />

import { MotionSceneEngine } from './analyticsEngine';

interface WorkerFrameMessage {
  type: 'frame';
  cameraId: string;
  profileId: string;
  width: number;
  height: number;
  pixels: ArrayBuffer;
  timestamp: number;
  options?: {
    sensitivity?: number;
    debounceMs?: number;
    cooldownMs?: number;
    sceneThreshold?: number;
    sceneConfirmFrames?: number;
    sceneCooldownMs?: number;
    zones?: Array<{ mode: 'include' | 'exclude' | 'privacy'; polygon: number[][] }>;
  };
}

const engines = new Map<string, MotionSceneEngine>();
const scope = self as DedicatedWorkerGlobalScope;

scope.addEventListener('message', (event: MessageEvent<WorkerFrameMessage | { type: 'reset'; key?: string }>) => {
  const message = event.data;
  if (message.type === 'reset') {
    if (message.key) engines.delete(message.key); else engines.clear();
    return;
  }
  if (message.type !== 'frame') return;
  const key = `${message.cameraId}\u0000${message.profileId}`;
  try {
    const engine = engines.get(key) ?? new MotionSceneEngine();
    engines.set(key, engine);
    const result = engine.evaluate({ width: message.width, height: message.height, pixels: new Uint8Array(message.pixels), timestamp: message.timestamp },
      { cameraId: message.cameraId, profileId: message.profileId }, message.options);
    scope.postMessage({ type: 'result', key, ...result });
  } catch (error) {
    scope.postMessage({ type: 'error', key, message: error instanceof Error ? error.message : 'analytics worker failed' });
  }
});

export {};
