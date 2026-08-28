export type ProgramConnectionState = 'checking' | 'connecting' | 'live' | 'reconnecting' | 'offline' | 'disabled';

interface ProgramStatus {
  enabled: boolean;
  endpoint: string;
}

export interface ProgramConnection {
  close: () => void;
  /** Live browser measurements only. Callers must never persist or log the returned report. */
  getStats?: () => Promise<RTCStatsReport | null>;
  getReceivedBytes?: () => number | null;
  getCodec?: () => string;
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

function connectWhep(
  video: HTMLVideoElement,
  resolveEndpoint: EndpointResolver,
  onState: (state: ProgramConnectionState) => void,
  receiveAudio = false,
  onRemoteStream?: (stream: MediaStream) => void,
  validateEndpoint: EndpointValidator = validEndpoint,
  requestHeaders: Record<string, string> = {},
  onAuthorizationRejected?: AuthorizationRejected,
): ProgramConnection {
  let closed = false;
  let attempt = 0;
  let generation = 0;
  let peer: RTCPeerConnection | undefined;
  let sessionLocation: string | null = null;
  let retryTimer: number | undefined;
  let disconnectedTimer: number | undefined;
  let handshakeTimer: number | undefined;
  let request: AbortController | undefined;

  const clearTimers = () => {
    if (retryTimer !== undefined) window.clearTimeout(retryTimer);
    if (disconnectedTimer !== undefined) window.clearTimeout(disconnectedTimer);
    if (handshakeTimer !== undefined) window.clearTimeout(handshakeTimer);
    retryTimer = undefined;
    disconnectedTimer = undefined;
    handshakeTimer = undefined;
  };

  const releaseSession = () => {
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

  const scheduleReconnect = () => {
    if (closed || retryTimer !== undefined) return;
    clearTimers();
    releaseSession();
    onState(attempt === 0 ? 'offline' : 'reconnecting');
    const delay = Math.min(1000 * (2 ** attempt), 8000);
    attempt = Math.min(attempt + 1, 3);
    retryTimer = window.setTimeout(() => {
      retryTimer = undefined;
      void connect();
    }, delay);
  };

  const connect = async () => {
    if (closed) return;
    const currentGeneration = ++generation;
    onState(attempt === 0 ? 'checking' : 'reconnecting');
    request = new AbortController();
    try {
      const resolved = await resolveEndpoint(request.signal);
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
      nextPeer.ontrack = (event) => {
        if (currentGeneration !== generation || closed) return;
        if (!remoteStream.getTracks().some((track) => track.id === event.track.id))
          remoteStream.addTrack(event.track);
        onRemoteStream?.(remoteStream);
        void video.play().catch(() => undefined);
      };
      nextPeer.onconnectionstatechange = () => {
        if (currentGeneration !== generation || closed) return;
        if (nextPeer.connectionState === 'connected') {
          if (handshakeTimer !== undefined) window.clearTimeout(handshakeTimer);
          handshakeTimer = undefined;
          attempt = 0;
          onState('live');
        } else if (nextPeer.connectionState === 'failed') {
          scheduleReconnect();
        } else if (nextPeer.connectionState === 'disconnected' && disconnectedTimer === undefined) {
          disconnectedTimer = window.setTimeout(scheduleReconnect, 3000);
        } else if (nextPeer.connectionState === 'connecting' && disconnectedTimer !== undefined) {
          window.clearTimeout(disconnectedTimer);
          disconnectedTimer = undefined;
        }
      };

      await nextPeer.setLocalDescription(await nextPeer.createOffer());
      await gatherIce(nextPeer);
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
      if (!validSdpAnswer(answer)) throw new Error('WHEP answer is invalid');
      await nextPeer.setRemoteDescription({ type: 'answer', sdp: answer });
      handshakeTimer = window.setTimeout(scheduleReconnect, 15_000);
    } catch (error) {
      if (!closed && currentGeneration === generation && !(error instanceof DOMException && error.name === 'AbortError'))
        scheduleReconnect();
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

  window.addEventListener('pagehide', close);
  void connect();
  return { close, getStats: () => peer?.getStats() ?? Promise.resolve(null) };
}

export function connectProgram(
  video: HTMLVideoElement,
  onState: (state: ProgramConnectionState) => void,
): ProgramConnection {
  return connectWhep(video, async (signal) => {
    const statusResponse = await fetch('/api/v1/program/status', { cache: 'no-store', signal });
    if (!statusResponse.ok) throw new Error('Program status is unavailable');
    const status = (await statusResponse.json()) as ProgramStatus;
    return status.enabled ? status.endpoint : null;
  }, onState, true);
}

export function connectSource(
  video: HTMLVideoElement,
  endpoint: string,
  onState: (state: ProgramConnectionState) => void,
  onRemoteStream?: (stream: MediaStream) => void,
): ProgramConnection {
  return connectWhep(video, async () => endpoint, onState, true, onRemoteStream);
}

export function connectApprovedWhep(
  video: HTMLVideoElement,
  endpoint: string,
  onState: (state: ProgramConnectionState) => void,
  options: {
    deviceToken?: string;
    onRemoteStream?: (stream: MediaStream) => void;
    onAuthorizationRejected?: AuthorizationRejected;
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
    options.deviceToken ? { 'Authorization': `Bearer ${options.deviceToken}` } : {}, options.onAuthorizationRejected);
}
