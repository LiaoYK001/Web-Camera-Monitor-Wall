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

export interface CameraSceneSource extends SceneSourceBase {
  kind: 'camera'; cameraId: string; profileId: string; hardwareDecode: 'auto' | 'on' | 'off';
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

export type SceneSource = CameraSceneSource | RtspSceneSource | BrowserSceneSource | ImageSceneSource | MediaSceneSource |
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
  schemaVersion: 5;
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
  strategy: 'unknown' | 'passthrough' | 'hybrid' | 'composite';
  codec: string;
  audioCodec: string;
  deliveryMode?: 'direct' | 'hybrid' | 'composite';
  reason?: string;
  videoDelivery?: 'copy' | 'transcode' | 'composite';
  audioDelivery?: 'copy' | 'transcode' | 'composite';
  serverVideoDecode?: boolean;
  serverVideoEncode?: boolean;
  serverAudioTranscode?: boolean;
  decoder?: string;
  encoder?: string;
  serverCost?: 'low' | 'medium' | 'high';
  compositePublisherActive?: boolean;
}

export interface PlaybackCapabilities {
  defaultMode: 'direct' | 'composite';
  modes: {
    composite: { enabled: boolean; endpoint: string };
    direct: { enabled: boolean; fallback: 'composite' };
  };
  sources: SourcePlaybackCapability[];
}

export interface NvrSegment {
  id: string;
  cameraId: string;
  startUtcMs: number;
  endUtcMs: number;
  durationMs: number;
  kind: 'continuous' | 'event' | 'pre-event' | 'manual' | 'recovered' | 'orphan';
  videoCodec: string;
  audioCodec: string;
  sizeBytes: number;
  integrity: string;
  locked: boolean;
  mediaUrl: string;
}

export interface NvrTimelineCamera {
  cameraId: string;
  recordedStream: 'main' | 'sub';
  retentionBoundaryUtcMs: number | null;
  segments: NvrSegment[];
  gaps: Array<{ fromUtcMs: number; toUtcMs: number; reason: string }>;
}

export interface NvrTimeline {
  fromUtcMs: number;
  toUtcMs: number;
  storageTimeZone: 'UTC';
  queryDurationMs: number;
  cameras: NvrTimelineCamera[];
}

export interface NvrStatus {
  status: string;
  freeBytes: number;
  diskPressure: boolean;
  cameras: Array<{ id: string; policy: string; state: string; segments: number; eventActive: boolean }>;
}

export interface NvrExport {
  exportId: string;
  auditId: string;
  mode: 'fast' | 'exact';
  manifestSha256: string;
  manifestUrl: string;
  effectiveRange: { fromUtcMs: number; toUtcMs: number };
  files: Array<{ cameraId: string; name: string; sha256: string; downloadUrl: string }>;
}

export type CameraAdapter = 'onvif' | 'rtsp' | 'mjpeg' | 'snapshot' | 'hls' | 'http-flv' | 'whep' | 'srt' | 'rtp' | 'v4l2';
export type CameraKind = 'camera' | 'network-stream';
export type TransportMode = 'auto' | 'rtsp-tcp' | 'rtsp-udp' | 'rtsp-udp-multicast' | 'http' | 'https';
export type AudioExpectation = 'auto' | 'required' | 'disabled';
export interface TrackDescriptor {
  index: number; kind: 'video' | 'audio' | 'data'; codec: string; bitrateKbps: number | null;
  width: number; height: number; fps: number; sampleRate: number; channels: number; source: 'legacy' | 'probe';
}
export interface CameraProfile {
  id: string; name: string; role: 'main' | 'sub' | 'snapshot' | 'auxiliary'; endpoint: string;
  videoCodec: string; audioCodec: string; width: number; height: number; fps: number;
  enabled?: boolean; transportMode?: TransportMode; liveBitrateCapKbps?: number | null;
  audioExpectation?: AudioExpectation; probeState?: string; lastProbeAt?: number; tracks?: TrackDescriptor[];
}
export interface CameraRecord {
  id: string; name: string; address: string; adapter: CameraAdapter; credentialsRef: string;
  hardwareDecode: 'auto' | 'on' | 'off'; capabilities: Record<string, unknown>; health: string;
  profiles: CameraProfile[]; createdAt: number; updatedAt: number; kind?: CameraKind; enabled?: boolean;
  groupId?: string; tags?: string[]; revision?: number;
}
export interface SourceCatalogProfile extends Omit<CameraProfile, 'endpoint'> {
  endpointDisplay: string; enabled: boolean; transportMode: TransportMode; liveBitrateCapKbps: number | null;
  audioExpectation: AudioExpectation; probeState: string; lastProbeAt: number; tracks: TrackDescriptor[];
  allowInsecureHttp: boolean;
}
export interface SourceCatalogItem {
  schemaVersion: 2; id: string; name: string; kind: CameraKind; adapter: CameraAdapter; enabled: boolean;
  groupId: string; tags: string[]; addressDisplay: string; health: string;
  hardwareDecode: 'auto' | 'on' | 'off'; profileCount: number; trackCount: number;
  deviceCapabilities: { ptz: boolean; snapshot: boolean; talk: boolean };
  profiles: SourceCatalogProfile[]; revision: number; createdAt: number; updatedAt: number;
}
export interface SourceCatalogPage { schemaVersion: 2; page: number; limit: number; total: number; items: SourceCatalogItem[]; }
export interface OperationalIssue {
  id: string; code: string; severity: 'info' | 'warning' | 'error'; state: 'open' | 'acknowledged' | 'resolved';
  scopeKind: 'device' | 'profile' | 'source' | 'media-plan' | 'nvr' | 'system'; scopeId: string;
  component: string; firstSeenAt: number; lastSeenAt: number; occurrences: number;
  summary: string; explanation: string; recommendedActions: string[]; technicalDetails: Record<string, string | number | boolean>;
}
export interface RuntimeSettings {
  schemaVersion: 1; revision: number;
  values: { defaultTransportMode: 'auto' | 'rtsp-tcp' | 'rtsp-udp'; probeTimeoutSeconds: number;
    sourceRecoveryEnabled: boolean; issueRetentionLimit: number };
  deployment: Record<'tls' | 'ports' | 'secrets' | 'gpuDevice', 'read-only'>;
}
export interface AudioMeterSnapshot {
  topology: 'direct' | 'composite'; executionOwner: 'browser' | 'docker';
  sources: Array<{ sourceId: string; rmsDbfs: number | null; peakDbfs: number | null }>;
}
export interface AnalyticsPolicy {
  cameraId: string; profileId: string;
  motionEnabled: boolean; sceneChangeEnabled: boolean; personEnabled: boolean;
  allowEventPromotion: boolean; promotionThreshold: number;
  promotionHoldSeconds: number; promotionCooldownSeconds: number;
  forceAnalyticsAlwaysOn: boolean; updatedAt: number;
}
export interface CameraDetection {
  address: string;
  adapter: CameraAdapter;
  probe: string;
  contentType?: string;
  profileVersion?: 'T' | 'S';
  capabilities?: Record<string, unknown>;
  profiles: CameraProfile[];
}
export interface OnvifPreset { token: string; name: string; }
export interface OnvifEvent { topic: string; properties: Record<string, string>; }
export interface DeviceOperation { id: number; operation: string; result: string; createdAt: number; }
export type ClientPermission = 'view' | 'ptz' | 'talk' | 'snapshot' | 'record-local';
export interface ClientEnrollment { id: string; name: string; platform: 'windows' | 'linux' | 'android' | 'web' | 'chromium-iwa'; state: 'pending' | 'approved'; createdAt: number; expiresAt: number; }
export interface EnrolledClient { id: string; name: string; platform: string; status: 'active' | 'revoked'; createdAt: number; lastSeen: number; grantExpiresAt: number; revision: number; revokedAt: number | null; cameraCount: number; weakRevocation: boolean; }
export interface ClientCameraGrant { cameraId: string; profileIds: string[]; permissions: ClientPermission[]; credentialMode: 'none' | 'existing' | 'dedicated'; credentialsRef?: string; }
export interface MonitorEvent { id: string; cameraId: string; type: string; source: string; topic: string; occurredAt: number; severity: string; confidence: number | null; zoneId: string; label: string; acknowledged: boolean; note: string; properties: Record<string, unknown>; segmentIds: string[]; }
export interface MotionZone { id: string; cameraId: string; name: string; mode: 'include' | 'exclude' | 'privacy'; polygon: number[][]; sensitivity: number; debounceMs: number; cooldownMs: number; enabled: boolean; }
export interface EventRule { id: string; name: string; enabled: number; conditions: Record<string, unknown>; actions: Array<Record<string, unknown>>; cooldown_ms: number; }

export interface VideoBackendCapability {
  devicePresent: boolean; vaDriverLoaded: boolean; encoderAvailable: boolean;
  encodeSupported: boolean; decodeSupported: boolean; runtimeProbePassed: boolean; ready: boolean;
}
export interface SystemCapabilities {
  videoEncoder: { requested: string; selected: string; fallback: boolean; fallbackReason: string;
    backends: { x264: VideoBackendCapability; vaapi: VideoBackendCapability; qsv: VideoBackendCapability; nvenc: VideoBackendCapability } };
  renderer: { requested: string; selected: string; hardwareProbePassed: boolean; fallback: boolean; fallbackReason: string };
  hardwareDecode: { requested: string; selected: string; fallback: boolean; fallbackReason: string };
}
export interface ProcessDiagnostics {
  processes: Array<{ name: string; instances: number; rssKiB: number; cpuPercent: number }>;
  rtspSessions: number; gpuBusyPercent: number; controlPlaneActive: boolean; engineActive: boolean; compositePublisherActive: boolean;
}

export type ClusterRole = 'admin' | 'operator' | 'viewer' | 'auditor' | 'exporter';
export interface ClusterUser {
  id: string; username: string; enabled: boolean; roles: ClusterRole[];
  scopes: Array<{ kind: 'camera' | 'group'; id: string }>; revision: number;
}
export interface ClusterAuditRecord {
  id: number; event: string; actorId: string; subjectId: string; result: string; createdAt: number;
}
export interface ClusterNode {
  id: string; name: string; role: 'recorder' | 'worker'; status: string; version: string;
  lastSeenAt: number; clockOffsetMs: number; certificateExpiresAt: number;
  capabilities: Record<string, unknown>; revision: number;
}
export interface StorageVolume {
  id: string; nodeId: string; label: string; tier: 'hot' | 'warm' | 'archive';
  state: 'online' | 'degraded' | 'read-only' | 'evacuating' | 'offline';
  capacityBytes: number; freeBytes: number; reserveBytes: number;
  highWatermark: number; lowWatermark: number; readOnly: boolean; lastScrubAt: number; revision: number;
}
export interface ResourceCapacity {
  nodes: Array<{ nodeId: string; cpuCores: number; memoryBytes: number; rated: boolean;
    capabilities: Record<string, unknown>; reservations: Array<Record<string, unknown>>; updatedAt: number }>;
  taskPriorities: Record<string, number>;
  referenceTiers: Record<string, { streams: number; profile: string; taskType: string }>;
  revision: number;
}
export interface RecordingPlacement {
  cameraId: string; profileId: string; nodeId: string; generation: number; state: string;
  leaseExpiresAt: number; isolationDeadline: number;
}
export interface ClusterRecording {
  id: string; cameraId: string; profileId: string; startUtcMs: number; endUtcMs: number;
  durationMs: number; kind: string; videoCodec: string; audioCodec: string; sizeBytes: number;
  integrity: string; locked: boolean; nodeId: string; volumeId: string; archiveState: string;
  playbackState: 'recorder' | 'archived';
}
export interface ClusterRecordingTimeline {
  fromUtcMs: number; toUtcMs: number; storageTimeZone: 'UTC'; queryDurationMs: number; revision: number;
  cameras: Array<{ cameraId: string; recordedStream: 'profile'; retentionBoundaryUtcMs: number | null;
    segments: ClusterRecording[]; gaps: Array<{ fromUtcMs: number; toUtcMs: number; reason: string }> }>;
}
export interface ArchiveTarget {
  id: string; name: string; endpointAuthority: string; bucket: string;
  credentialsRef: string; region: string; enabled: boolean; revision: number;
}
export interface BackupJob {
  id: string; state: string; targetId: string; sha256: string;
  createdAt: number; completedAt: number; errorCode: string;
}
export interface ExternalProvider {
  id: string; name: string; endpointAuthority: string;
  taskTypes: Array<'external-nvr' | 'export' | 'detector'>;
  maxConcurrent: number; enabled: boolean; revision: number;
  taskCounts: Partial<Record<'offered' | 'media-opened' | 'expired', number>>;
}
