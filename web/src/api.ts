import type { ApiErrorEnvelope, PlaybackCapabilities, SceneDocument, SceneEvent } from './types';

export class ControlApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly revision?: number;

  constructor(status: number, code: string, message: string, revision?: number) {
    super(message);
    this.name = 'ControlApiError';
    this.status = status;
    this.code = code;
    this.revision = revision;
  }
}

async function parseError(response: Response): Promise<ControlApiError> {
  let envelope: ApiErrorEnvelope = {};
  try {
    envelope = (await response.json()) as ApiErrorEnvelope;
  } catch {
    // The UI keeps server parse details private when the response is not JSON.
  }
  return new ControlApiError(
    response.status,
    envelope.error?.code ?? 'request_failed',
    envelope.error?.message ?? `请求失败（HTTP ${response.status}）`,
    envelope.revision,
  );
}

export async function fetchScene(signal?: AbortSignal): Promise<SceneDocument> {
  const response = await fetch('/api/v1/scene', {
    method: 'GET',
    cache: 'no-store',
    signal,
  });
  if (!response.ok) throw await parseError(response);
  return (await response.json()) as SceneDocument;
}

export async function fetchPlaybackCapabilities(signal?: AbortSignal): Promise<PlaybackCapabilities> {
  const response = await fetch('/api/v1/playback/capabilities', {
    method: 'GET',
    cache: 'no-store',
    signal,
  });
  if (!response.ok) throw await parseError(response);
  return (await response.json()) as PlaybackCapabilities;
}

export async function replaceScene(scene: SceneDocument): Promise<SceneDocument> {
  const response = await fetch('/api/v1/scene', {
    method: 'PUT',
    headers: {
      'Content-Type': 'application/json',
      'If-Match': `"${scene.revision}"`,
    },
    body: JSON.stringify(scene),
  });
  if (!response.ok) throw await parseError(response);
  return (await response.json()) as SceneDocument;
}

export function connectSceneEvents(
  onEvent: (event: SceneEvent) => void,
  onState: (connected: boolean) => void,
): () => void {
  let closed = false;
  let socket: WebSocket | undefined;
  let retryTimer: number | undefined;
  let retryDelay = 500;

  const connect = () => {
    if (closed) return;
    const scheme = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    socket = new WebSocket(`${scheme}//${window.location.host}/api/v1/ws`);
    socket.addEventListener('open', () => {
      retryDelay = 500;
      onState(true);
    });
    socket.addEventListener('message', (message) => {
      try {
        const event = JSON.parse(String(message.data)) as SceneEvent;
        if (event.type === 'scene.snapshot' || event.type === 'scene.updated') onEvent(event);
      } catch {
        // Ignore malformed unsolicited events and keep the last valid scene.
      }
    });
    socket.addEventListener('close', () => {
      onState(false);
      if (closed) return;
      retryTimer = window.setTimeout(connect, retryDelay);
      retryDelay = Math.min(retryDelay * 2, 8000);
    });
    socket.addEventListener('error', () => socket?.close());
  };

  connect();
  return () => {
    closed = true;
    if (retryTimer !== undefined) window.clearTimeout(retryTimer);
    socket?.close();
  };
}
