export type ProgramConnectionState = 'checking' | 'connecting' | 'live' | 'reconnecting' | 'offline' | 'disabled';

interface ProgramStatus {
  enabled: boolean;
  endpoint: string;
}

export interface ProgramConnection {
  close: () => void;
}

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

const validSessionLocation = (value: string | null): string | null => {
  if (!value) return null;
  const location = new URL(value, window.location.href);
  if (location.origin !== window.location.origin) return null;
  if (!/^\/api\/v1\/program\/whep\/session\/[a-f0-9]{32}$/.test(location.pathname)) return null;
  if (location.search || location.hash) return null;
  return location.pathname;
};

export function connectProgram(
  video: HTMLVideoElement,
  onState: (state: ProgramConnectionState) => void,
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
      void fetch(sessionLocation, { method: 'DELETE', keepalive: true }).catch(() => undefined);
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
      const statusResponse = await fetch('/api/v1/program/status', {
        cache: 'no-store',
        signal: request.signal,
      });
      if (!statusResponse.ok) throw new Error('Program status is unavailable');
      const status = (await statusResponse.json()) as ProgramStatus;
      if (!status.enabled) {
        onState('disabled');
        return;
      }
      if (status.endpoint !== '/api/v1/program/whep') throw new Error('Program endpoint is invalid');
      onState(attempt === 0 ? 'connecting' : 'reconnecting');

      const nextPeer = new RTCPeerConnection();
      peer = nextPeer;
      nextPeer.addTransceiver('video', { direction: 'recvonly' });
      nextPeer.ontrack = (event) => {
        if (currentGeneration !== generation || closed) return;
        video.srcObject = event.streams[0] ?? new MediaStream([event.track]);
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
      const offerResponse = await fetch(status.endpoint, {
        method: 'POST',
        headers: { 'Accept': 'application/sdp', 'Content-Type': 'application/sdp' },
        body: nextPeer.localDescription.sdp,
        signal: request.signal,
      });
      if (offerResponse.status !== 201) throw new Error('Program offer was rejected');
      const location = validSessionLocation(offerResponse.headers.get('Location'));
      if (!location) throw new Error('Program session location is invalid');
      sessionLocation = location;
      const answer = await offerResponse.text();
      if (!answer || answer.length > 64 * 1024) throw new Error('Program answer is invalid');
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
  return {
    close,
  };
}
