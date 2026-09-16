export type ProgramConnectionState = 'checking' | 'connecting' | 'live' | 'reconnecting' | 'offline' | 'disabled';

export type CompositeConfiguration = 'disabled' | 'incomplete' | 'ready' | 'unknown';
export type CompositeEngine = 'stopped' | 'starting' | 'ready' | 'failed' | 'unknown';
export type CompositePublish = 'idle' | 'publishing' | 'failed' | 'unknown';

export interface ProgramStatus {
  enabled: boolean;
  endpoint: string;
  /** Staged native Composite status; older servers omit these fields. */
  configuration?: CompositeConfiguration;
  engine?: CompositeEngine;
  publish?: CompositePublish;
  reason?: string;
  guidance?: string[];
  logs?: string;
  /** Free-form per-capability hardware detail when the server reports it. */
  detail?: string;
}

export interface ProgramConnection {
  close: () => void;
  /** Live browser measurements only. Callers must never persist or log the returned report. */
  getStats?: () => Promise<RTCStatsReport | null>;
  getReceivedBytes?: () => number | null;
  getCodec?: () => string;
  /** Staged playback progress; `live` only follows a real first frame. */
  getStage?: () => PlaybackStage;
  /** Retry play() after an autoplay block, from a user gesture. */
  resume?: () => Promise<boolean>;
}

type EndpointResolver = (signal: AbortSignal) => Promise<string | null>;
type EndpointValidator = (value: string) => URL | null;
type AuthorizationRejected = () => void | Promise<void>;

const gatherIce = (peer: RTCPeerConnection, timeoutMs = 10_000): Promise<void> => {
  if (peer.iceGatheringState === 'complete') return Promise.resolve();
  return new Promise((resolve, reject) => {
    const timeout = window.setTimeout(() => {
      peer.removeEventListener('icegatheringstatechange', changed);
      reject(new Error('ICE gathering timed out'));
    }, timeoutMs);
    const changed = () => {
      if (peer.iceGatheringState !== 'complete') return;
      window.clearTimeout(timeout);
      peer.removeEventListener('icegatheringstatechange', changed);
      resolve();
    };
    peer.addEventListener('icegatheringstatechange', changed);
  });
};

const validEndpoint = (value: string): URL | null => {
  const endpoint = new URL(value, window.location.href);
  if (endpoint.origin !== window.location.origin || endpoint.search || endpoint.hash) return null;
  if (endpoint.pathname === '/api/v1/program/whep') return endpoint;
  if (/^\/api\/v1\/sources\/[A-Za-z0-9._-]{1,64}\/whep$/.test(endpoint.pathname)) return endpoint;
  if (/^\/api\/v2\/media-plans\/[a-f0-9]{32}\/whep$/.test(endpoint.pathname)) return endpoint;
  return null;
};

export const validSessionLocation = (value: string | null, endpoint: URL): string | null => {
  if (!value) return null;
  const location = new URL(value, endpoint);
  if (location.origin !== endpoint.origin) return null;
  const prefix = `${endpoint.pathname.replace(/\/$/, '')}/`;
  if (!location.pathname.startsWith(prefix)) return null;
  const relative = location.pathname.slice(prefix.length);
  const sessionId = relative.startsWith('session/') ? relative.slice('session/'.length) : relative;
  if (!/^[A-Za-z0-9._~-]{1,128}$/.test(sessionId)) return null;
  if (location.search || location.hash) return null;
  return location.href;
};

const validSdpAnswer = (answer: string): boolean => {
  if (!answer || answer.length > 64 * 1024 || !answer.startsWith('v=0') ||
      [...answer].some((character) => {
        const code = character.charCodeAt(0);
        return code !== 9 && code !== 10 && code !== 13 && (code < 32 || code > 126);
      })) return false;
  const lines = answer.replace(/\r\n/g, '\n').split('\n').filter(Boolean);
  if (lines.length > 512 || lines.some((line) => line.length > 2048 || !/^[a-z]=/.test(line))) return false;
  const media = lines.filter((line) => line.startsWith('m='));
  if (media.length < 1 || media.length > 2 || media.filter((line) => line.startsWith('m=video ')).length !== 1 ||
      media.some((line) => !line.startsWith('m=video ') && !line.startsWith('m=audio '))) return false;
  return lines.filter((line) => line.startsWith('a=candidate:')).length <= 64 &&
    lines.some((line) => /^a=fingerprint:sha-256 [0-9A-F:]+$/i.test(line));
};

const boundedText = async (response: Response, limit: number): Promise<string> => {
  if (!response.body) return '';
  const reader = response.body.getReader();
  const chunks: Uint8Array[] = [];
  let size = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      size += value.byteLength;
      if (size > limit) throw new Error('WHEP response exceeds its size limit');
      chunks.push(value);
    }
  } catch (error) {
    await reader.cancel().catch(() => undefined);
    throw error;
  }
  const merged = new Uint8Array(size);
  let offset = 0;
  for (const chunk of chunks) { merged.set(chunk, offset); offset += chunk.byteLength; }
  return new TextDecoder('utf-8', { fatal: true }).decode(merged);
};

export interface PlaybackStage {
  /** WHEP offer answered and session created. */
  signaling: boolean;
  /** ICE reached the connected state. */
  iceConnected: boolean;
  /** At least one remote track arrived. */
  mediaReceived: boolean;
  /** A real video frame was presented. */
  firstFrame: boolean;
  /** Frames are still advancing. */
  playing: boolean;
  /** The browser blocked autoplay; media is fine, a gesture is required. */
  autoplayBlocked: boolean;
  reconnects: number;
  frames: number;
  lastError: string;
}

const HANDSHAKE_TIMEOUT_MS = 15_000;
const FIRST_FRAME_TIMEOUT_MS = 20_000;
const STALL_MS = 6_000;

function connectWhep(
  video: HTMLVideoElement,
  resolveEndpoint: EndpointResolver,
  onState: (state: ProgramConnectionState) => void,
  receiveAudio = false,
  onRemoteStream?: (stream: MediaStream) => void,
  validateEndpoint: EndpointValidator = validEndpoint,
  requestHeaders: Record<string, string> = {},
  onAuthorizationRejected?: AuthorizationRejected,
  onStage?: (stage: PlaybackStage) => void,
): ProgramConnection {
  let closed = false;
  let attempt = 0;
  let generation = 0;
  let peer: RTCPeerConnection | undefined;
  let sessionLocation: string | null = null;
  let retryTimer: number | undefined;
  let disconnectedTimer: number | undefined;
  let handshakeTimer: number | undefined;
  let firstFrameTimer: number | undefined;
  let watchdogTimer: number | undefined;
  let fallbackPollTimer: number | undefined;
  let frameCallbackId: number | undefined;
  let request: AbortController | undefined;
  let lastFrameAt = 0;
  let lastFrameCount = 0;
  let stage: PlaybackStage = {
    signaling: false, iceConnected: false, mediaReceived: false, firstFrame: false,
    playing: false, autoplayBlocked: false, reconnects: 0, frames: 0, lastError: '',
  };

  const report = (patch: Partial<PlaybackStage>) => {
    stage = { ...stage, ...patch };
    onStage?.({ ...stage });
  };

  const clearTimers = () => {
    if (retryTimer !== undefined) window.clearTimeout(retryTimer);
    if (disconnectedTimer !== undefined) window.clearTimeout(disconnectedTimer);
    if (handshakeTimer !== undefined) window.clearTimeout(handshakeTimer);
    if (firstFrameTimer !== undefined) window.clearTimeout(firstFrameTimer);
    retryTimer = undefined;
    disconnectedTimer = undefined;
    handshakeTimer = undefined;
    firstFrameTimer = undefined;
  };

  const stopFrameTracking = () => {
    if (watchdogTimer !== undefined) window.clearInterval(watchdogTimer);
    if (fallbackPollTimer !== undefined) window.clearInterval(fallbackPollTimer);
    watchdogTimer = undefined;
    fallbackPollTimer = undefined;
    if (frameCallbackId !== undefined) {
      const cancel = (video as HTMLVideoElement & { cancelVideoFrameCallback?: (id: number) => void }).cancelVideoFrameCallback;
      try { cancel?.call(video, frameCallbackId); } catch { /* the element may have been replaced */ }
    }
    frameCallbackId = undefined;
  };

  const releaseSession = () => {
    stopFrameTracking();
    request?.abort();
    request = undefined;
    if (peer) {
      peer.ontrack = null;
      peer.onconnectionstatechange = null;
      peer.close();
      peer = undefined;
    }
    video.srcObject = null;
    if (sessionLocation) {
      void fetch(sessionLocation, {
        method: 'DELETE', keepalive: true, cache: 'no-store', redirect: 'error', headers: requestHeaders,
      }).catch(() => undefined);
      sessionLocation = null;
    }
  };

  const scheduleReconnect = (reason = '') => {
    if (closed || retryTimer !== undefined) return;
    clearTimers();
    releaseSession();
    report({ signaling: false, iceConnected: false, mediaReceived: false, firstFrame: false, playing: false,
      reconnects: stage.reconnects + 1, lastError: reason });
    onState(attempt === 0 ? 'offline' : 'reconnecting');
    // Bounded exponential backoff with jitter: five tiles must not reconnect in lockstep.
    const delay = Math.round(Math.min(1000 * (2 ** attempt), 15_000) * (0.7 + Math.random() * 0.6));
    attempt = Math.min(attempt + 1, 4);
    retryTimer = window.setTimeout(() => {
      retryTimer = undefined;
      void connect();
    }, delay);
  };

  const markFrame = (currentGeneration: number) => {
    if (closed || currentGeneration !== generation) return;
    stage.frames += 1;
    lastFrameAt = performance.now();
    if (!stage.firstFrame) {
      if (firstFrameTimer !== undefined) { window.clearTimeout(firstFrameTimer); firstFrameTimer = undefined; }
      report({ firstFrame: true, playing: true, iceConnected: true, mediaReceived: true, autoplayBlocked: false });
      attempt = 0;
      onState('live');
      startWatchdog(currentGeneration);
    }
  };

  const startFrameTracking = (currentGeneration: number) => {
    const rvfc = (video as HTMLVideoElement & { requestVideoFrameCallback?: (callback: () => void) => number }).requestVideoFrameCallback;
    if (rvfc) {
      const onFrame = () => {
        if (closed || currentGeneration !== generation) return;
        markFrame(currentGeneration);
        frameCallbackId = rvfc.call(video, onFrame);
      };
      frameCallbackId = rvfc.call(video, onFrame);
      return;
    }
    // Compatibility fallback: decoded frame counts, never picture brightness.
    fallbackPollTimer = window.setInterval(() => {
      if (closed || currentGeneration !== generation) return;
      const quality = (video as HTMLVideoElement & { getVideoPlaybackQuality?: () => { totalVideoFrames: number } }).getVideoPlaybackQuality?.();
      const frames = quality?.totalVideoFrames ?? 0;
      if (frames > lastFrameCount || (!video.paused && video.currentTime > 0)) {
        lastFrameCount = Math.max(lastFrameCount, frames);
        markFrame(currentGeneration);
      }
    }, 500);
  };

  const startWatchdog = (currentGeneration: number) => {
    if (watchdogTimer !== undefined) return;
    watchdogTimer = window.setInterval(() => {
      if (closed || currentGeneration !== generation) return;
      if (document.hidden) return; // a background tab pause is not a stall
      if (video.paused) {
        void video.play().catch((error: unknown) => {
          if (error instanceof DOMException && error.name === 'NotAllowedError') report({ autoplayBlocked: true, playing: false });
        });
        return;
      }
      if (lastFrameAt && performance.now() - lastFrameAt > STALL_MS) scheduleReconnect('frame_stall');
    }, 1000);
  };

  const connect = async () => {
    if (closed) return;
    const currentGeneration = ++generation;
    onState(attempt === 0 ? 'checking' : 'reconnecting');
    request = new AbortController();
    try {
      const resolved = await resolveEndpoint(request.signal);
      if (currentGeneration !== generation || closed) return;
      if (resolved === null) {
        onState('disabled');
        return;
      }
      const endpoint = validateEndpoint(resolved);
      if (!endpoint) throw new Error('WHEP endpoint is invalid');
      onState(attempt === 0 ? 'connecting' : 'reconnecting');

      const nextPeer = new RTCPeerConnection();
      peer = nextPeer;
      const remoteStream = new MediaStream();
      video.srcObject = remoteStream;
      nextPeer.addTransceiver('video', { direction: 'recvonly' });
      if (receiveAudio) nextPeer.addTransceiver('audio', { direction: 'recvonly' });
      startFrameTracking(currentGeneration);
      nextPeer.ontrack = (event) => {
        if (currentGeneration !== generation || closed) return;
        if (!remoteStream.getTracks().some((track) => track.id === event.track.id))
          remoteStream.addTrack(event.track);
        report({ mediaReceived: true });
        onRemoteStream?.(remoteStream);
        void video.play().catch((error: unknown) => {
          if (error instanceof DOMException && error.name === 'NotAllowedError') report({ autoplayBlocked: true });
        });
      };
      nextPeer.onconnectionstatechange = () => {
        if (currentGeneration !== generation || closed) return;
        if (nextPeer.connectionState === 'connected') {
          if (handshakeTimer !== undefined) { window.clearTimeout(handshakeTimer); handshakeTimer = undefined; }
          report({ iceConnected: true });
          if (!stage.firstFrame && firstFrameTimer === undefined)
            firstFrameTimer = window.setTimeout(() => {
              if (!stage.firstFrame) scheduleReconnect('first_frame_timeout');
            }, FIRST_FRAME_TIMEOUT_MS);
        } else if (nextPeer.connectionState === 'failed') {
          scheduleReconnect('ice_failed');
        } else if (nextPeer.connectionState === 'disconnected' && disconnectedTimer === undefined) {
          disconnectedTimer = window.setTimeout(() => scheduleReconnect('ice_disconnected'), 3000);
        } else if (nextPeer.connectionState === 'connecting' && disconnectedTimer !== undefined) {
          window.clearTimeout(disconnectedTimer);
          disconnectedTimer = undefined;
        }
      };

      await nextPeer.setLocalDescription(await nextPeer.createOffer());
      await gatherIce(nextPeer);
      if (currentGeneration !== generation || closed) return;
      if (!nextPeer.localDescription?.sdp) throw new Error('Browser did not produce an SDP offer');
      const offerResponse = await fetch(endpoint.href, {
        method: 'POST',
        headers: { Accept: 'application/sdp', 'Content-Type': 'application/sdp', ...requestHeaders },
        body: nextPeer.localDescription.sdp,
        signal: request.signal,
        redirect: 'error',
      });
      if (offerResponse.status === 401 || offerResponse.status === 403)
        await onAuthorizationRejected?.();
      if (offerResponse.status !== 201) throw new Error('WHEP offer was rejected');
      if (offerResponse.headers.get('Content-Type')?.split(';', 1)[0].trim().toLowerCase() !== 'application/sdp')
        throw new Error('WHEP answer content type is invalid');
      const location = validSessionLocation(offerResponse.headers.get('Location'), endpoint);
      if (!location) throw new Error('WHEP session location is invalid');
      sessionLocation = location;
      const answer = await boundedText(offerResponse, 64 * 1024);
      if (validSdpAnswer(answer) === false) throw new Error('WHEP answer is invalid');
      await nextPeer.setRemoteDescription({ type: 'answer', sdp: answer });
      report({ signaling: true });
      handshakeTimer = window.setTimeout(() => {
        if (!stage.iceConnected) scheduleReconnect('ice_timeout');
      }, HANDSHAKE_TIMEOUT_MS);
    } catch (error) {
      if (!closed && currentGeneration === generation && !(error instanceof DOMException && error.name === 'AbortError'))
        scheduleReconnect(error instanceof Error ? error.message : 'connect_failed');
    }
  };

  const close = () => {
    if (closed) return;
    closed = true;
    generation += 1;
    window.removeEventListener('pagehide', close);
    clearTimers();
    releaseSession();
  };

  const resume = async (): Promise<boolean> => {
    try {
      await video.play();
      report({ autoplayBlocked: false, playing: true });
      return true;
    } catch {
      report({ autoplayBlocked: true, playing: false });
      return false;
    }
  };

  window.addEventListener('pagehide', close);
  void connect();
  return { close, getStats: () => peer?.getStats() ?? Promise.resolve(null), getStage: () => ({ ...stage }), resume };
}

export function connectProgram(
  video: HTMLVideoElement,
  onState: (state: ProgramConnectionState) => void,
  onStage?: (stage: PlaybackStage) => void,
): ProgramConnection {
  return connectWhep(video, async (signal) => {
    const statusResponse = await fetch('/api/v1/program/status', { cache: 'no-store', signal });
    if (!statusResponse.ok) throw new Error('Program status is unavailable');
    const status = (await statusResponse.json()) as ProgramStatus;
    return status.enabled ? status.endpoint : null;
  }, onState, true, undefined, undefined, {}, undefined, onStage);
}

export function connectSource(
  video: HTMLVideoElement,
  endpoint: string,
  onState: (state: ProgramConnectionState) => void,
  onRemoteStream?: (stream: MediaStream) => void,
  onStage?: (stage: PlaybackStage) => void,
): ProgramConnection {
  return connectWhep(video, async () => endpoint, onState, true, onRemoteStream, undefined, {}, undefined, onStage);
}

export function connectApprovedWhep(
  video: HTMLVideoElement,
  endpoint: string,
  onState: (state: ProgramConnectionState) => void,
  options: {
    deviceToken?: string;
    onRemoteStream?: (stream: MediaStream) => void;
    onAuthorizationRejected?: AuthorizationRejected;
    onStage?: (stage: PlaybackStage) => void;
  } = {},
): ProgramConnection {
  const approved = new URL(endpoint);
  const validate: EndpointValidator = (value) => {
    const candidate = new URL(value);
    const secureTransport = candidate.protocol === 'https:' ||
      (candidate.protocol === 'http:' && ['127.0.0.1', 'localhost', '::1'].includes(candidate.hostname));
    if (candidate.href !== approved.href || !secureTransport || candidate.username ||
        candidate.password || candidate.search || candidate.hash || candidate.pathname.length > 1024) return null;
    return candidate;
  };
  return connectWhep(video, async () => endpoint, onState, true, options.onRemoteStream, validate,
    options.deviceToken ? { 'Authorization': `Bearer ${options.deviceToken}` } : {}, options.onAuthorizationRejected, options.onStage);
}
