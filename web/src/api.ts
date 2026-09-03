import type { AnalyticsJob, AnalyticsPolicy, AnalyticsRuntimePlan, AnalyticsStatus, ApiErrorEnvelope, ArchiveTarget, AudioMeterSnapshot, BackupJob, CameraDetection, CameraRecord, ClientCameraGrant, ClientEnrollment, ClusterNode, ClusterRecordingTimeline, ClusterRole, ClusterUser, DeviceOperation, EnrolledClient, EventRule, ExternalProvider, MonitorEvent, MotionZone, NvrExport, NvrStatus, NvrTimeline, OnvifEvent, OnvifPreset, OperationalIssue, PlaybackCapabilities, ProcessDiagnostics, RecordingPlacement, ResourceCapacity, RuntimeSettings, SceneDocument, SceneEvent, SourceCatalogItem, SourceCatalogPage, StorageVolume, StudioCapabilities, StudioDocument, SystemCapabilities } from './types';

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
export const fetchAnalyticsPolicies = (signal?: AbortSignal) => cameraRequest<{ policies: AnalyticsPolicy[] }>('/cameras/analytics-policies', { signal });
export const updateAnalyticsPolicies = (policies: Array<Omit<AnalyticsPolicy, 'updatedAt'>>) =>
  cameraRequest<{ policies: AnalyticsPolicy[] }>('/cameras/analytics-policies', {
    method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ policies }),
  });
const analyticsRequest = async <T>(path: string, init?: RequestInit): Promise<T> => {
  const response = await fetch(`/api/v3${path}`, { cache: 'no-store', credentials: 'same-origin', ...init });
  if (!response.ok) throw await parseError(response);
  return (await response.json()) as T;
};
export const fetchV3AnalyticsPolicies = (signal?: AbortSignal) => analyticsRequest<{ schemaVersion: 2; revision: number; policies: AnalyticsPolicy[] }>('/analytics/policies', { signal });
export const patchV3AnalyticsPolicies = (baseRevision: number, policies: Array<Omit<AnalyticsPolicy, 'updatedAt'>>) => analyticsRequest<{ schemaVersion: 2; revision: number; policies: AnalyticsPolicy[] }>('/analytics/policies', {
  method: 'PATCH', headers: { 'Content-Type': 'application/json', 'If-Match': `"${baseRevision}"` }, body: JSON.stringify({ baseRevision, policies }),
});
export const requestAnalyticsRuntimePlan = (cameraId: string, profileId: string, kinds: Array<'motion' | 'scene-change' | 'person'>, capabilities: Record<string, unknown>) => analyticsRequest<{ sessionId: string; expiresAt: number; plans: AnalyticsRuntimePlan[] }>('/analytics/runtime-plans', {
  method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ cameraId, profileId, kinds, capabilities }),
});
export const fetchAnalyticsStatus = (signal?: AbortSignal) => analyticsRequest<{ statuses: AnalyticsStatus[] }>('/analytics/status', { signal });
export const submitAnalyticsSignals = (sessionId: string, signals: Array<Record<string, unknown>>) => analyticsRequest<{ accepted: number; events: MonitorEvent[] }>('/analytics/signals/batch', {
  method: 'POST', headers: { 'Content-Type': 'application/json', 'X-WebObs-Analytics-Session': sessionId }, body: JSON.stringify({ signals }),
});
export const closeAnalyticsRuntimeSession = (sessionId: string, cameraId?: string, profileId?: string) => analyticsRequest<{ closed: boolean }>(`/analytics/runtime-sessions/${encodeURIComponent(sessionId)}`, {
  method: 'DELETE',
  ...(cameraId && profileId ? { headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ cameraId, profileId }) } : {}),
});
export const fetchAnalyticsJobs = () => clientAdminRequest<{ jobs: AnalyticsJob[]; revision: number }>('/analytics-jobs');
export const createAnalyticsJob = (value: { cameraId: string; profileId: string; modelId: string; modelSha256: string; nodeId?: string }) => clientAdminRequest<AnalyticsJob>('/analytics-jobs', {
  method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ kind: 'person', ...value }),
});
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
export const qualifyBrowserDirect = (cameraId: string, profileId: string) => cameraRequest<{
  cameraId: string; profileId: string; eligible: boolean; reason: string; checkedAt: number;
}>(`/cameras/${encodeURIComponent(cameraId)}/profiles/${encodeURIComponent(profileId)}/browser-direct/probe`, {
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
export interface SourceCatalogQuery {
  page?: number; limit?: number; q?: string; group?: string; adapter?: string; health?: string;
  enabled?: boolean; tag?: string; sort?: 'name' | 'status' | 'updated' | 'group'; direction?: 'asc' | 'desc';
}
export const fetchSourceCatalog = (query: SourceCatalogQuery = {}, signal?: AbortSignal) => {
  const parameters = new URLSearchParams();
  Object.entries(query).forEach(([key, value]) => { if (value !== undefined && value !== '') parameters.set(key, String(value)); });
  return clientAdminRequest<SourceCatalogPage>(`/source-catalog${parameters.size ? `?${parameters}` : ''}`, { signal });
};
export const fetchSourceCatalogItem = (cameraId: string, signal?: AbortSignal) =>
  clientAdminRequest<SourceCatalogItem>(`/source-catalog/${encodeURIComponent(cameraId)}`, { signal });
export const patchSourceCatalogItem = (cameraId: string, revision: number, patch: Record<string, unknown>) =>
  clientAdminRequest<SourceCatalogItem>(`/source-catalog/${encodeURIComponent(cameraId)}`, {
    method: 'PATCH', headers: { 'Content-Type': 'application/json', 'If-Match': `"${revision}"` }, body: JSON.stringify(patch),
  });
export const batchSourceCatalog = (items: Array<Record<string, unknown>>) =>
  clientAdminRequest<{ items: SourceCatalogItem[] }>('/source-catalog/batch', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ items }),
  });
export const probeSourceProfile = (cameraId: string, profileId: string) =>
  clientAdminRequest<{ cameraId: string; profile: SourceCatalogItem['profiles'][number] }>(
    `/source-catalog/${encodeURIComponent(cameraId)}/profiles/${encodeURIComponent(profileId)}/probe`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}',
    });
export const fetchOperationalIssues = (query = '', signal?: AbortSignal) =>
  clientAdminRequest<{ issues: OperationalIssue[] }>(`/operations/issues${query ? `?${query}` : ''}`, { signal });
export const acknowledgeOperationalIssue = (issueId: string) =>
  clientAdminRequest<OperationalIssue>(`/operations/issues/${encodeURIComponent(issueId)}/acknowledge`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}',
  });
export const fetchRuntimeSettings = (signal?: AbortSignal) =>
  clientAdminRequest<RuntimeSettings>('/settings', { signal });
export const patchRuntimeSettings = (revision: number, patch: Record<string, unknown>) =>
  clientAdminRequest<RuntimeSettings>('/settings', {
    method: 'PATCH', headers: { 'Content-Type': 'application/json', 'If-Match': `"${revision}"` }, body: JSON.stringify(patch),
  });
export const fetchAudioMeters = (sceneId: string, topology: 'direct' | 'composite', signal?: AbortSignal) => {
  const query = new URLSearchParams({ sceneId, topology });
  return clientAdminRequest<AudioMeterSnapshot>(`/audio/mixer?${query}`, { signal });
};
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

export const fetchClusterUsers = (signal?: AbortSignal) =>
  clientAdminRequest<{ users: ClusterUser[]; revision: number }>('/users', { signal });
export const createClusterUser = (value: { username: string; password: string; roles: ClusterRole[];
  scopes: Array<{ kind: 'camera' | 'group'; id: string }> }) =>
  clientAdminRequest<ClusterUser>('/users', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(value) });
export const patchClusterUser = (userId: string, revision: number, patch: Record<string, unknown>) =>
  clientAdminRequest<ClusterUser>(`/users/${encodeURIComponent(userId)}`, {
    method: 'PATCH', headers: { 'Content-Type': 'application/json', 'If-Match': `"${revision}"` }, body: JSON.stringify(patch),
  });
export const fetchClusterRoles = (signal?: AbortSignal) =>
  clientAdminRequest<{ roles: Array<{ id: ClusterRole; permissions: string[] }> }>('/roles', { signal });
export const fetchClusterAudit = (limit = 100, before?: number, signal?: AbortSignal) => {
  const query = new URLSearchParams({ limit: String(limit) });
  if (before !== undefined) query.set('before', String(before));
  return clientAdminRequest<{ records: import('./types').ClusterAuditRecord[]; nextBefore: number | null }>(
    `/audit?${query}`, { signal });
};
export const fetchClusterNodes = (signal?: AbortSignal) =>
  clientAdminRequest<{ nodes: ClusterNode[]; revision: number }>('/nodes', { signal });
export const createNodeEnrollment = (value: { name: string; role: 'recorder' | 'worker' }) =>
  clientAdminRequest<{ id: string; token: string; expiresAt: number; state: string }>('/node-enrollments', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(value),
  });
export const approveNodeEnrollment = (enrollmentId: string) =>
  clientAdminRequest<{ id: string; nodeId: string; state: string }>(`/node-enrollments/${encodeURIComponent(enrollmentId)}/approve`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}',
  });
export const revokeClusterNode = (nodeId: string, revision: number) =>
  clientAdminRequest<{ id: string; state: string }>(`/nodes/${encodeURIComponent(nodeId)}`, {
    method: 'DELETE', headers: { 'If-Match': `"${revision}"` },
  });
export const fetchStorageVolumes = (signal?: AbortSignal) =>
  clientAdminRequest<{ volumes: StorageVolume[]; revision: number }>('/storage-volumes', { signal });
export const patchStorageVolume = (volume: StorageVolume, patch: Record<string, unknown>) =>
  clientAdminRequest<StorageVolume>(`/storage-volumes/${encodeURIComponent(volume.nodeId)}/${encodeURIComponent(volume.id)}`, {
    method: 'PATCH', headers: { 'Content-Type': 'application/json', 'If-Match': `"${volume.revision}"` }, body: JSON.stringify(patch),
  });
export const fetchResourceCapacity = (signal?: AbortSignal) =>
  clientAdminRequest<ResourceCapacity>('/resource-capacity', { signal });
export const fetchRecordingPlacements = (signal?: AbortSignal) =>
  clientAdminRequest<{ placements: RecordingPlacement[]; revision: number }>('/recording-placements', { signal });
export const fetchClusterRecordingTimeline = (fromUtcMs: number, toUtcMs: number, signal?: AbortSignal) => {
  const query = new URLSearchParams({ from: String(fromUtcMs), to: String(toUtcMs) });
  return clientAdminRequest<ClusterRecordingTimeline>(`/recordings/timeline?${query}`, { signal });
};
export const fetchVerifiedArchivedRecording = async (segmentId: string, cameraId: string): Promise<Blob> => {
  const query = new URLSearchParams({ cameraId });
  const ticket = await clientAdminRequest<{ segmentId: string; cameraId: string; url: string; sha256: string;
    sizeBytes: number; contentType: string; expiresAt: number; credentialExposure: 'ephemeral' }>(
    `/recordings/${encodeURIComponent(segmentId)}/playback-ticket?${query}`, { method: 'POST', body: '' },
  );
  const endpoint = new URL(ticket.url);
  if (endpoint.protocol !== 'https:' || ticket.segmentId !== segmentId || ticket.cameraId !== cameraId
      || ticket.credentialExposure !== 'ephemeral' || ticket.expiresAt * 1000 <= Date.now()
      || !/^[0-9a-f]{64}$/.test(ticket.sha256) || ticket.sizeBytes < 1 || ticket.sizeBytes > 512 * 1024 * 1024) {
    throw new Error('归档回放票据无效或已过期');
  }
  const response = await fetch(endpoint, {
    method: 'GET', cache: 'no-store', credentials: 'omit', redirect: 'error', referrerPolicy: 'no-referrer',
  });
  if (!response.ok) throw new Error('无法读取归档录像');
  const bytes = await response.arrayBuffer();
  if (bytes.byteLength !== ticket.sizeBytes) throw new Error('归档录像大小校验失败');
  const computed = [...new Uint8Array(await crypto.subtle.digest('SHA-256', bytes))]
    .map((value) => value.toString(16).padStart(2, '0')).join('');
  if (computed !== ticket.sha256) throw new Error('归档录像 SHA-256 校验失败');
  return new Blob([bytes], { type: ticket.contentType === 'video/mp4' ? 'video/mp4' : 'application/octet-stream' });
};
export const fetchArchiveTargets = (signal?: AbortSignal) =>
  clientAdminRequest<{ targets: ArchiveTarget[]; revision: number }>('/archive-targets', { signal });
export const fetchBackupJobs = (signal?: AbortSignal) =>
  clientAdminRequest<{ jobs: BackupJob[]; revision: number }>('/backup-jobs', { signal });
export const createBackupJob = (targetId = 'local') =>
  clientAdminRequest<BackupJob>('/backup-jobs', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ targetId }) });
export const fetchExternalProviders = (signal?: AbortSignal) =>
  clientAdminRequest<{ providers: ExternalProvider[]; revision: number }>('/providers', { signal });
export const fetchEvents = (query = '') => cameraRequest<{ events: MonitorEvent[] }>(`/events${query ? `?${query}` : ''}`);
export const createEvent = (event: Record<string, unknown>) => cameraRequest<MonitorEvent>('/events', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(event) });
export const acknowledgeEvent = (eventId: string, acknowledged: boolean, note: string) => cameraRequest<{ id: string; acknowledged: boolean }>(`/events/${encodeURIComponent(eventId)}/acknowledgement`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ acknowledged, note }) });
export const fetchMotionZones = (signal?: AbortSignal) => cameraRequest<{ zones: MotionZone[] }>('/motion-zones', { signal });
export const createMotionZone = (zone: Record<string, unknown>) => cameraRequest<MotionZone>('/motion-zones', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(zone) });
export const fetchEventRules = () => cameraRequest<{ rules: EventRule[] }>('/event-rules');
export const createEventRule = (rule: Record<string, unknown>) => cameraRequest<{ id: string }>('/event-rules', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(rule) });
