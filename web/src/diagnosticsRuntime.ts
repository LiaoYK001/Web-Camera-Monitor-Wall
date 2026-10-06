import { isPageVisible, subscribePageVisibility } from './pageVisibility';

// This store accepts rich inputs but ONLY retains explicitly selected primitives.
// No source/account/job IDs, messages, URLs, paths, tracks, levels or raw payloads.
export const DIAGNOSTIC_LIMITS = { controls: 16, media: 24, issues: 24, events: 64, sample: 256, bytes: 48 * 1024 } as const;
const unavailable = 'unavailable' as const;
const object = (value: unknown): Record<string, unknown> => value !== null && typeof value === 'object' ? value as Record<string, unknown> : {};
const array = (value: unknown): unknown[] => Array.isArray(value) ? value : [];
export const count = (value: unknown, max = 1_000_000_000): number => typeof value === 'number' && Number.isFinite(value) ? Math.min(max, Math.max(0, Math.floor(value))) : 0;
export const timestamp = (value: unknown): number | null => typeof value === 'number' && Number.isSafeInteger(value) && value > 0 && value <= 8_640_000_000_000_000 ? value : null;
const flag = (value: unknown): boolean | null => typeof value === 'boolean' ? value : null;
export const choice = <T extends string>(value: unknown, values: readonly T[]): T | 'unavailable' => typeof value === 'string' && values.includes(value as T) ? value as T : unavailable;
export function injectedVersion(value: unknown): string {
  // Do not turn arbitrary build labels into an exfiltration channel. Known release
  // and engineering numeric versions only; do not invent a release/revision.
  return typeof value === 'string' && value.length <= 64 && /^v?[0-9]{1,6}[.][0-9]{1,6}[.][0-9]{1,6}(?:-(?:dev|alpha|beta|rc)(?:[.]android)?(?:[.][0-9]{1,10}){0,3})?$/.test(value) ? value : unavailable;
}
const controlPhases = ['connecting', 'online', 'retrying', 'offline', 'paused'] as const;
const controlReasons = ['', 'network_offline', 'connection_timeout', 'snapshot_timeout', 'transport_error', 'transport_closed', 'constructor_failed', 'resume', 'manual'] as const;
const mediaReasons = ['', 'first_frame_timeout', 'ice_failed', 'ice_disconnected', 'ice_timeout', 'frame_stall', 'track_ended', 'connect_failed', 'authorization_rejected'] as const;
const jobStates = ['queued', 'running', 'cancelling', 'completed', 'failed', 'cancelled', 'interrupted'] as const;
const exportReasons = ['export_range_incomplete', 'export_disk_full', 'export_interrupted', 'export_timeout', 'export_conversion_failed', 'export_duration_mismatch', 'export_source_changed', 'export_range_too_large', 'export_scope_rejected', 'export_queue_full', 'permission_rejected'] as const;
const issueCodes = ['MEDIA_DIRECT_FALLBACK', 'MEDIA_FIRST_FRAME_TIMEOUT', 'MEDIA_CODEC_INCOMPATIBLE', 'MEDIA_GATEWAY_ACTIVATION_FAILED', 'MEDIA_AUTHORIZATION_REJECTED', 'LOW_POWER_TARGET_UNMET', 'AUDIO_TRACK_MISSING', 'AUDIO_RUNTIME_UNAVAILABLE', 'ANALYTICS_RUNTIME_UNAVAILABLE', 'LEGACY_SOURCE_IMPORT_REQUIRED', 'NVR_DISK_PRESSURE', 'NVR_RECORDING_FAILED'] as const;
const components = ['browser-media', 'browser-analytics', 'direct-audio', 'low-power', 'nvr', 'camera', 'go2rtc', 'core', 'mediamtx', 'obs'] as const;
const transportModes = ['auto', 'rtsp-tcp', 'rtsp-udp', 'rtsp-udp-multicast', 'http', 'https'] as const;
const adapters = ['onvif', 'rtsp', 'mjpeg', 'snapshot', 'hls', 'http-flv', 'whep', 'srt', 'rtp', 'v4l2'] as const;

export function safeControl(value: unknown) {
  const v = object(value);
  return { localOrdinal: count(v.id), phase: choice(v.phase, controlPhases), reason: choice(v.reason, controlReasons),
    attempts: count(v.attempts), failures: count(v.failures), rejectedMessages: count(v.rejectedMessages), messages: count(v.messages),
    connectedAt: timestamp(v.connectedAt), lastSnapshotAt: timestamp(v.lastSnapshotAt), nextRetryAt: timestamp(v.nextRetryAt) };
}
export function safeIssue(value: unknown) {
  const v = object(value), detail = object(v.technicalDetails);
  return { code: choice(v.code, issueCodes), component: choice(v.component, components),
    severity: choice(v.severity, ['info', 'warning', 'error']), state: choice(v.state, ['open', 'acknowledged', 'resolved']),
    firstSeenAt: timestamp(v.firstSeenAt), lastSeenAt: timestamp(v.lastSeenAt), occurrences: count(v.occurrences),
    transportMode: choice(detail.transportMode, transportModes), adapter: choice(detail.adapter, adapters),
    topology: choice(detail.topology, ['direct', 'gateway', 'composite']), reason: choice(detail.reason, mediaReasons),
    retryCount: typeof detail.retryCount === 'number' ? count(detail.retryCount) : null,
    lastFrameAgeMs: typeof detail.lastFrameAgeMs === 'number' ? count(detail.lastFrameAgeMs) : null };
}
export function safeNative(value: unknown) {
  const v = object(value), app = object(v.app), runtime = object(v.runtime), update = object(v.update);
  return { observedAt: Date.now(), version: injectedVersion(app.version),
    platform: choice(app.platform, ['win32', 'linux', 'darwin']), architecture: choice(app.architecture, ['x64', 'arm64', 'ia32', 'arm']), packaged: flag(app.packaged),
    runtimePhase: choice(runtime.phase, ['starting', 'ready', 'failed', 'stopping', 'stopped']),
    updatePhase: choice(update.phase, ['idle', 'disabled', 'checking', 'current', 'available', 'downloading', 'downloaded', 'preparing', 'error']),
    restartCount: unavailable, restartReason: unavailable };
}

let startedAt = Date.now(), sequence = 0, droppedEvents = 0, droppedMedia = 0, droppedControls = 0;
type Event = { at: number; component: string; state: string; localOrdinal: number | null };
const events: Event[] = [];
function event(component: string, state: string, localOrdinal: number | null = null) {
  events.push({ at: Date.now(), component, state, localOrdinal });
  if (events.length > DIAGNOSTIC_LIMITS.events) { events.shift(); droppedEvents = count(droppedEvents + 1); }
}
const controls = new Map<number, ReturnType<typeof safeControl> & { active: boolean; observedAt: number }>();
export function observeControl(value: unknown, active = true) {
  const next = safeControl(value), old = controls.get(next.localOrdinal);
  if (!old || old.phase !== next.phase || old.reason !== next.reason || old.active !== active) event('control', active ? next.phase : 'closed', next.localOrdinal);
  if (!old && controls.size >= DIAGNOSTIC_LIMITS.controls) { controls.delete(controls.keys().next().value!); droppedControls = count(droppedControls + 1); }
  controls.set(next.localOrdinal, { ...next, active, observedAt: Date.now() });
}
function mediaStage(value: unknown) {
  const v = object(value);
  return { signaling: flag(v.signaling), iceConnected: flag(v.iceConnected), mediaReceived: flag(v.mediaReceived), firstFrame: flag(v.firstFrame),
    playing: flag(v.playing), autoplayBlocked: flag(v.autoplayBlocked), reconnects: count(v.reconnects), frames: count(v.frames), reason: choice(v.lastError, mediaReasons) };
}
const media = new Map<number, ReturnType<typeof mediaStage> & { localOrdinal: number; topology: string; transport: 'whep'; active: boolean;
  createdAt: number; observedAt: number; firstFrameAt: number | null; lastFrameAt: number | null; nextRetryAt: number | null; attempts: number }>();
export function createMediaDiagnostic(topology: 'direct' | 'composite' | 'approved') {
  const localOrdinal = ++sequence;
  if (media.size >= DIAGNOSTIC_LIMITS.media) { media.delete(media.keys().next().value!); droppedMedia = count(droppedMedia + 1); }
  media.set(localOrdinal, { ...mediaStage({}), localOrdinal, topology: choice(topology, ['direct', 'composite', 'approved']), transport: 'whep', active: true,
    createdAt: Date.now(), observedAt: Date.now(), firstFrameAt: null, lastFrameAt: null, nextRetryAt: null, attempts: 0 });
  return {
    attempt: () => { const v = media.get(localOrdinal); if (v) { v.attempts = count(v.attempts + 1); v.nextRetryAt = null; v.observedAt = Date.now(); event('media', 'connecting', localOrdinal); } },
    stage: (value: unknown) => { const v = media.get(localOrdinal); if (!v) return; const next = mediaStage(value);
      if (v.playing !== next.playing || v.reason !== next.reason || v.reconnects !== next.reconnects || v.autoplayBlocked !== next.autoplayBlocked)
        event('media', next.autoplayBlocked ? 'autoplay_blocked' : next.playing ? 'playing' : next.reason || 'waiting', localOrdinal);
      Object.assign(v, next, { observedAt: Date.now() }); },
    frame: () => { const v = media.get(localOrdinal); if (v) { const now = Date.now(); v.firstFrameAt ??= now; v.lastFrameAt = now; v.observedAt = now; v.frames = count(v.frames + 1); } },
    retry: (delay: number) => { const v = media.get(localOrdinal); if (v) v.nextRetryAt = Date.now() + count(delay, 120_000); },
    close: () => { const v = media.get(localOrdinal); if (v) { v.active = false; v.playing = false; v.nextRetryAt = null; v.observedAt = Date.now(); event('media', 'closed', localOrdinal); } },
  };
}
type Issues = { observedAt: number; total: number; omitted: number; items: ReturnType<typeof safeIssue>[] };
let localIssues: Issues | null = null, serverIssues: Issues | null = null;
export function observeIssues(value: unknown, origin: 'local' | 'server') {
  const values = array(value), next = { observedAt: Date.now(), total: count(values.length), omitted: count(values.length - DIAGNOSTIC_LIMITS.issues), items: values.slice(0, DIAGNOSTIC_LIMITS.issues).map(safeIssue) };
  if (origin === 'local') localIssues = next; else serverIssues = next;
}
let native: ReturnType<typeof safeNative> | null = null;
let nativeRevision = 0;
export const nativeObservationRevision = () => nativeRevision;
export function observeNative(value: unknown) {
  nativeRevision++;
  const next = safeNative(value);
  if (!native || native.runtimePhase !== next.runtimePhase) event('native-runtime', next.runtimePhase);
  native = next;
}
let audio: { observedAt: number; state: string; inputCount: number; sourcesSampled: number; sourcesOmitted: number; streamsBound: number; audioTracks: number } | null = null;
export function observeAudio(value: unknown) {
  const v = object(value), sources = array(v.sources), sample = sources.slice(0, DIAGNOSTIC_LIMITS.sample);
  const state = choice(v.state, ['disabled', 'running', 'suspended', 'blocked']);
  if (!audio || audio.state !== state) event('audio', state);
  audio = { observedAt: Date.now(), state, inputCount: count(v.inputCount), sourcesSampled: sample.length, sourcesOmitted: count(sources.length - sample.length),
    streamsBound: sample.filter(source => object(source).streamBound === true).length,
    audioTracks: count(sample.reduce<number>((sum, source) => sum + count(object(source).audioTracks, 256), 0)) };
}
function summarize(values: unknown[], states: readonly string[], property: string) {
  const sample = values.slice(0, DIAGNOSTIC_LIMITS.sample), counts: Record<string, number> = Object.fromEntries([...states, unavailable].map(state => [state, 0]));
  for (const value of sample) counts[choice(object(value)[property], states)]++;
  return { total: count(values.length), sampled: sample.length, omitted: count(values.length - sample.length), counts };
}
let recorder: ReturnType<typeof recorderSummary> | null = null;
function recorderSummary(value: unknown) {
  const v = object(value);
  return { observedAt: Date.now(), status: choice(v.status, ['ok', 'ready', 'running', 'degraded', 'stopped', 'error']), diskPressure: flag(v.diskPressure),
    cameras: summarize(array(v.cameras), ['recording', 'idle', 'disabled', 'stopped', 'starting', 'error', 'failed', 'backoff', 'degraded'], 'state') };
}
export function observeRecorder(value: unknown) { recorder = recorderSummary(value); }
let jobs: ReturnType<typeof jobSummary> | null = null;
function jobSummary(value: unknown) {
  const values = array(value), sample = values.slice(0, DIAGNOSTIC_LIMITS.sample);
  return { observedAt: Date.now(), ...summarize(values, jobStates, 'state'),
    recent: sample.slice(0, 12).map(value => { const v = object(value); return { state: choice(v.state, jobStates), createdAt: timestamp(v.createdUtcMs), updatedAt: timestamp(v.updatedUtcMs),
      mode: choice(object(v.request).mode, ['fast', 'exact']), reason: choice(object(v.error).code, exportReasons) }; }) };
}
export function observeExportJobs(value: unknown) { jobs = jobSummary(value); }
let session: { observedAt: number; authenticated: boolean | null; authenticationEnabled: boolean | null; offline: boolean; unavailable: boolean } | null = null;
export function observeSession(value: unknown) {
  const v = object(value);
  session = { observedAt: Date.now(), authenticated: flag(v.authenticated), authenticationEnabled: flag(v.authenticationEnabled), offline: timestamp(v.offlineExpiresAt) !== null, unavailable: v.unavailable === true };
}
const freshness = <T extends { observedAt: number }>(value: T | null, now: number) => value ? { availability: now - value.observedAt > 30_000 ? 'stale' : 'observed', ...value } : { availability: unavailable };
export function diagnosticSnapshot() {
  const now = Date.now();
  // JSON detach prevents callers from mutating retained state. Everything above is allowlisted.
  return JSON.parse(JSON.stringify({ startedAt, capturedAt: now, networkOnline: navigator.onLine, foreground: isPageVisible(), androidForeground: flag(window.webobsAndroidForeground),
    controls: [...controls.values()], media: [...media.values()], events,
    session: freshness(session, now), native: freshness(native, now), audio: freshness(audio, now), recorder: freshness(recorder, now), exportJobs: freshness(jobs, now),
    issues: { local: freshness(localIssues, now), server: freshness(serverIssues, now) }, dropped: { events: droppedEvents, media: droppedMedia, controls: droppedControls } })) as DiagnosticSnapshot;
}
/** Discard previous-account observations without ever storing an account key here. */
export function resetDiagnostics() {
  startedAt = Date.now(); controls.clear(); media.clear(); events.length = 0;
  droppedEvents = 0; droppedMedia = 0; droppedControls = 0;
  nativeRevision++;
  localIssues = null; serverIssues = null; native = null; audio = null; recorder = null; jobs = null; session = null;
}
export type DiagnosticSnapshot = { capturedAt: number; startedAt: number; [key: string]: unknown };
// Memory-only observations last for this page, including before opening diagnostics.
const visibility = () => event('lifecycle', isPageVisible() ? 'foreground' : 'background');
const online = () => event('network', navigator.onLine ? 'online' : 'offline');
const unsubscribeVisibility = subscribePageVisibility(visibility);
window.addEventListener('online', online); window.addEventListener('offline', online);
visibility();
if (import.meta.hot) import.meta.hot.dispose(() => { unsubscribeVisibility(); window.removeEventListener('online', online); window.removeEventListener('offline', online); });
