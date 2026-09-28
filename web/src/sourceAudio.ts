/**
 * Real audio tracks of a source, as reported by the control plane
 * (`GET /api/v1/sources/<id>/audio-tracks`).  MediaMTX 1.18.2 maps a single
 * audio output per WHEP session, so every track has its own audio-only channel.
 */
export interface SourceAudioTrack {
  index: number;
  streamIndex: number;
  codec: string;
  channels: number;
  channelLayout: string;
  sampleRate: number;
  language: string;
  title: string;
  sourceCodecBrowserCompatible: boolean;
  endpoint: string;
}

export type SourceAudioTracks =
  | { status: 'loading' }
  /** The source really has these tracks. */
  | { status: 'available'; tracks: SourceAudioTrack[] }
  /** Probe succeeded and the source has no audio at all. */
  | { status: 'none' }
  /** Probe failed (offline, timeout, gateway error): unknown, never "no audio". */
  | { status: 'unavailable'; reason: string };

const CACHE_TTL_MS = 15_000;
const cache = new Map<string, { at: number; value: SourceAudioTracks }>();
const inflight = new Map<string, Promise<SourceAudioTracks>>();

export function invalidateSourceAudioTracks(sourceId?: string): void {
  if (sourceId === undefined) cache.clear();
  else for (const key of cache.keys()) if (key === sourceId || key.startsWith(`${sourceId}|`)) cache.delete(key);
}

export function cachedSourceAudioTracks(sourceId: string, now = Date.now()): SourceAudioTracks | undefined {
  const entry = cache.get(sourceId);
  if (!entry) return undefined;
  if (now - entry.at > CACHE_TTL_MS) {
    cache.delete(sourceId);
    return undefined;
  }
  return entry.value;
}

function isTrack(value: unknown): value is SourceAudioTrack {
  if (!value || typeof value !== 'object') return false;
  const track = value as Partial<SourceAudioTrack>;
  return Number.isInteger(track.index) && (track.index ?? -1) >= 0 &&
    typeof track.codec === 'string' &&
    typeof track.endpoint === 'string' && /^\/api\/v1\/(?:sources\/[A-Za-z0-9._-]+|account-cameras\/[A-Za-z0-9._-]+\/[A-Za-z0-9._-]+)\/audio-tracks\/[0-9]+\/whep$/.test(track.endpoint) &&
    track.endpoint.endsWith('/whep');
}

/** Probe one source, deduplicating concurrent callers and reusing the TTL cache. */
export function fetchSourceAudioTracks(sourceId: string, signal?: AbortSignal, camera?: { cameraId: string; profileId: string }): Promise<SourceAudioTracks> {
  const cacheKey = camera ? `${sourceId}|${camera.cameraId}/${camera.profileId}` : sourceId;
  const cached = cachedSourceAudioTracks(cacheKey);
  if (cached && cached.status !== 'loading') return Promise.resolve(cached);
  const pending = inflight.get(cacheKey);
  if (pending) return pending;
  const request = (async (): Promise<SourceAudioTracks> => {
    try {
      const base = camera ? `/api/v1/account-cameras/${encodeURIComponent(camera.cameraId)}/${encodeURIComponent(camera.profileId)}` : `/api/v1/sources/${encodeURIComponent(sourceId)}`;
      const response = await fetch(`${base}/audio-tracks`,
        { cache: 'no-store', signal });
      if (!response.ok) {
        const value: SourceAudioTracks = { status: 'unavailable', reason: response.status === 502 ? 'probe_failed' : `http_${response.status}` };
        cache.set(cacheKey, { at: Date.now(), value });
        return value;
      }
      const payload = await response.json() as { tracks?: unknown };
      if (!Array.isArray(payload.tracks) || !payload.tracks.every(isTrack))
        return { status: 'unavailable', reason: 'invalid_response' };
      const tracks = payload.tracks.filter(isTrack);
      const value: SourceAudioTracks = tracks.length > 0 ? { status: 'available', tracks } : { status: 'none' };
      cache.set(cacheKey, { at: Date.now(), value });
      return value;
    } catch (error) {
      const aborted = error instanceof DOMException && error.name === 'AbortError';
      const value: SourceAudioTracks = { status: 'unavailable', reason: aborted ? 'aborted' : 'network' };
      if (!aborted) cache.set(cacheKey, { at: Date.now(), value });
      return value;
    } finally {
      inflight.delete(cacheKey);
    }
  })();
  inflight.set(cacheKey, request);
  return request;
}

/** Default selection: the first real track, per the F5-05 brief. */
export function defaultSelectedTracks(tracks: SourceAudioTrack[]): number[] {
  return tracks.length > 0 ? [tracks[0].index] : [];
}
