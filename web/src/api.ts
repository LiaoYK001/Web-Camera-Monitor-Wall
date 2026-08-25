import type { ApiErrorEnvelope, CameraDetection, CameraRecord, ClientCameraGrant, ClientEnrollment, DeviceOperation, EnrolledClient, EventRule, MonitorEvent, MotionZone, NvrExport, NvrStatus, NvrTimeline, OnvifEvent, OnvifPreset, PlaybackCapabilities, ProcessDiagnostics, SceneDocument, SceneEvent, StudioCapabilities, StudioDocument, SystemCapabilities } from './types';

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

export interface AuthSession {
  authenticated: boolean;
  authenticationEnabled?: boolean;
  user?: string;
  via?: 'session' | 'basic';
  expiresAt?: number | null;
}

export async function fetchAuthSession(signal?: AbortSignal): Promise<AuthSession> {
  const response = await fetch('/api/v1/auth/session', { cache: 'no-store', credentials: 'same-origin', signal });
  if (response.status === 401) return { authenticated: false, authenticationEnabled: true };
  if (!response.ok) throw await parseError(response);
  return (await response.json()) as AuthSession;
}

export async function login(username: string, password: string): Promise<AuthSession> {
  const response = await fetch('/api/v1/auth/login', {
    method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  });
  if (!response.ok) throw await parseError(response);
  return (await response.json()) as AuthSession;
}

export async function logout(): Promise<void> {
  const response = await fetch('/api/v1/auth/logout', { method: 'POST', credentials: 'same-origin' });
  if (!response.ok && response.status !== 204) throw await parseError(response);
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

export async function fetchSystemCapabilities(signal?: AbortSignal): Promise<SystemCapabilities> {
  const response = await fetch('/api/v1/system/capabilities', { cache: 'no-store', signal });
  if (!response.ok) throw await parseError(response);
  return (await response.json()) as SystemCapabilities;
}

export async function fetchProcessDiagnostics(signal?: AbortSignal): Promise<ProcessDiagnostics> {
  const response = await fetch('/api/v1/system/processes', { cache: 'no-store', signal });
  if (!response.ok) throw await parseError(response);
  return (await response.json()) as ProcessDiagnostics;
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

export async function fetchStudio(signal?: AbortSignal): Promise<StudioDocument> {
  const response = await fetch('/api/v1/studio', { method: 'GET', cache: 'no-store', signal });
  if (!response.ok) throw await parseError(response);
  return (await response.json()) as StudioDocument;
}

export async function fetchStudioCapabilities(signal?: AbortSignal): Promise<StudioCapabilities> {
  const response = await fetch('/api/v1/studio/capabilities', { method: 'GET', cache: 'no-store', signal });
  if (!response.ok) throw await parseError(response);
  return (await response.json()) as StudioCapabilities;
}

export async function replaceStudio(studio: StudioDocument): Promise<StudioDocument> {
  const response = await fetch('/api/v1/studio', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json', 'If-Match': `"${studio.revision}"` },
    body: JSON.stringify(studio),
  });
  if (!response.ok) throw await parseError(response);
  return (await response.json()) as StudioDocument;
}

export async function studioAction(
  action: 'take' | 'undo' | 'redo',
  revision: number,
): Promise<StudioDocument> {
  const response = await fetch(`/api/v1/studio/${action}`, {
    method: 'POST',
    headers: { 'If-Match': `"${revision}"` },
  });
  if (!response.ok) throw await parseError(response);
  return (await response.json()) as StudioDocument;
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

async function nvrRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api/v1/nvr${path}`, { cache: 'no-store', ...init });
  if (!response.ok) throw await parseError(response);
  return (await response.json()) as T;
}

export const fetchNvrStatus = (signal?: AbortSignal) =>
  nvrRequest<NvrStatus>('/status', { signal });

export const fetchNvrTimeline = (fromUtcMs: number, toUtcMs: number, cameraIds: string[], signal?: AbortSignal) => {
  const query = new URLSearchParams({ from: String(fromUtcMs), to: String(toUtcMs) });
  cameraIds.forEach((cameraId) => query.append('cameraId', cameraId));
  return nvrRequest<NvrTimeline>(`/timeline?${query}`, { signal });
};

export const setNvrLock = (segmentId: string, locked: boolean) =>
  nvrRequest<{ id: string; locked: boolean }>(`/locks/${segmentId}`, {
    method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ locked }),
  });

export const deleteNvrSegment = (segmentId: string) =>
  nvrRequest<{ id: string; deleted: boolean }>(`/segments/${segmentId}`, { method: 'DELETE' });

export const createNvrSnapshot = (segmentId: string, offsetMs: number) =>
  nvrRequest<{ id: string; sha256: string; downloadUrl: string }>('/snapshots', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ segmentId, offsetMs }),
  });

export const createNvrExport = (
  cameraIds: string[], fromUtcMs: number, toUtcMs: number, mode: 'fast' | 'exact',
) => nvrRequest<NvrExport>('/exports', {
  method: 'POST', headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ cameraIds, fromUtcMs, toUtcMs, mode, lock: true }),
});

export const createPlaybackLease = (segmentId: string, ttlSeconds = 30) =>
  nvrRequest<{ id: string; segmentId: string; expiresUtcMs: number }>('/playback-leases', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ segmentId, ttlSeconds }),
  });

export const releasePlaybackLease = (leaseId: string) =>
  nvrRequest<{ id: string; released: boolean }>(`/playback-leases/${leaseId}`, { method: 'DELETE' });

async function cameraRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api/v1${path}`, { cache: 'no-store', ...init });
  if (!response.ok) throw await parseError(response);
  return (await response.json()) as T;
}

export const fetchCameras = (signal?: AbortSignal) => cameraRequest<{ cameras: CameraRecord[] }>('/cameras', { signal });
export const detectCamera = (address: string) => cameraRequest<CameraDetection>('/camera-detect', {
  method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ address }),
});
export const discoverOnvif = () => cameraRequest<{ devices: Array<{ address: string; host: string; adapter: 'onvif' }> }>('/onvif/discover', {
  method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}',
});
export const probeOnvif = (address: string, credentialsRef: string) => cameraRequest<CameraDetection>('/onvif/probe', {
  method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ address, credentialsRef }),
});
export const createCamera = (camera: Partial<CameraRecord>) => cameraRequest<CameraRecord>('/cameras', {
  method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(camera),
});
export const syncOnvifCamera = (cameraId: string) => cameraRequest<CameraRecord>(`/cameras/${encodeURIComponent(cameraId)}/onvif/sync`, {
  method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}',
});
export const deleteCamera = (cameraId: string) => cameraRequest<{ id: string; deleted: boolean }>(`/cameras/${encodeURIComponent(cameraId)}`, { method: 'DELETE' });
const onvifOperation = <T>(cameraId: string, operation: string, body: Record<string, unknown>) =>
  cameraRequest<T>(`/cameras/${encodeURIComponent(cameraId)}/onvif/${operation}`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  });
export const fetchOnvifPresets = (cameraId: string) => cameraRequest<{ presets: OnvifPreset[] }>(`/cameras/${encodeURIComponent(cameraId)}/onvif/presets`);
export const sendOnvifPtz = (cameraId: string, body: Record<string, unknown>) => onvifOperation<{ state: string }>(cameraId, 'ptz', body);
export const mutateOnvifPreset = (cameraId: string, body: Record<string, unknown>) => onvifOperation<{ presetToken: string }>(cameraId, 'presets', body);
export const fetchOnvifSnapshot = (cameraId: string) => onvifOperation<{ contentType: string; data: string; sha256: string }>(cameraId, 'snapshot', {});
export const pullOnvifEvents = (cameraId: string) => onvifOperation<{ events: OnvifEvent[] }>(cameraId, 'events/pull', {});
export const sendOnvifTalk = (cameraId: string, body: Record<string, unknown>) => onvifOperation<{ state: string }>(cameraId, 'talk', body);
export const fetchDeviceOperations = (cameraId: string) => cameraRequest<{ operations: DeviceOperation[] }>(`/cameras/${encodeURIComponent(cameraId)}/operations`);
async function clientAdminRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api/v2${path}`, { cache: 'no-store', credentials: 'same-origin', ...init });
  if (!response.ok) throw await parseError(response);
  return (await response.json()) as T;
}
export const fetchClientEnrollments = (signal?: AbortSignal) =>
  clientAdminRequest<{ enrollments: ClientEnrollment[] }>('/enrollments', { signal });
export const fetchEnrolledClients = (signal?: AbortSignal) =>
  clientAdminRequest<{ clients: EnrolledClient[] }>('/clients', { signal });
export const approveClientEnrollment = (enrollmentId: string, pairingCode: string, cameraGrants: ClientCameraGrant[]) =>
  clientAdminRequest<{ clientId: string; state: 'approved'; grantExpiresAt: number; revision: number }>(
    `/enrollments/${encodeURIComponent(enrollmentId)}/approve`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ pairingCode, cameraGrants }),
    });
export const revokeEnrolledClient = (clientId: string) =>
  clientAdminRequest<{ clientId: string; status: 'revoked'; revokedAt: number;
    offlineEffectiveNoLaterThan: number; weakRevocation: boolean;
    cameraCredentialCleanup: 'complete' | 'partial' | 'not-applicable' }>(
    `/clients/${encodeURIComponent(clientId)}`, { method: 'DELETE' });
export const fetchEvents = (query = '') => cameraRequest<{ events: MonitorEvent[] }>(`/events${query ? `?${query}` : ''}`);
export const createEvent = (event: Record<string, unknown>) => cameraRequest<MonitorEvent>('/events', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(event) });
export const acknowledgeEvent = (eventId: string, acknowledged: boolean, note: string) => cameraRequest<{ id: string; acknowledged: boolean }>(`/events/${encodeURIComponent(eventId)}/acknowledgement`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ acknowledged, note }) });
export const fetchMotionZones = () => cameraRequest<{ zones: MotionZone[] }>('/motion-zones');
export const createMotionZone = (zone: Record<string, unknown>) => cameraRequest<MotionZone>('/motion-zones', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(zone) });
export const fetchEventRules = () => cameraRequest<{ rules: EventRule[] }>('/event-rules');
export const createEventRule = (rule: Record<string, unknown>) => cameraRequest<{ id: string }>('/event-rules', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(rule) });
