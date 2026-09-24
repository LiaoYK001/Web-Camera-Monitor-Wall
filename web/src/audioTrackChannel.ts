import type { SourceAudioTrack } from './sourceAudio';

export type AudioChannelState = 'connecting' | 'connected' | 'reconnecting' | 'disabled';

export interface AudioTrackConnection {
  close: () => void;
  getState: () => AudioChannelState;
}

import { reconnectDelayMs } from './whep';

const HANDSHAKE_TIMEOUT_MS = 15_000;
const STALL_MS = 6_000;

/**
 * The control plane hands out relative endpoints (for example
 * `/api/v1/sources/<id>/audio-tracks/0/whep`), so the location must be resolved
 * against the page origin instead of the relative path itself.
 */
function sessionLocation(header: string | null, endpoint: string): string | null {
  if (!header) return null;
  try {
    const expected = new URL(endpoint, window.location.origin);
    const location = new URL(header, expected);
    if (location.origin !== expected.origin) return null;
    if (!location.pathname.startsWith(expected.pathname + '/')) return null;
    // Stay relative so the session DELETE keeps using the same origin/proxy.
    return location.pathname + location.search;
  } catch { return null; }
}

async function gatherIce(peer: RTCPeerConnection): Promise<void> {
  if (peer.iceGatheringState === 'complete') return;
  await new Promise<void>((resolve) => {
    const done = () => { if (peer.iceGatheringState === 'complete') { peer.removeEventListener('icegatheringstatechange', done); resolve(); } };
    peer.addEventListener('icegatheringstatechange', done);
    window.setTimeout(done, 3_000);
  });
}

/**
 * Audio-only WHEP channel for one source track.  There are no video frames to
 * wait for, so liveness is real RTP packet progress (never element brightness or
 * a bare connection state), and a stalled channel reconnects with bounded,
 * jittered backoff.  Authorization failures stop instead of looping.
 */
export function connectAudioTrack(
  track: SourceAudioTrack,
  onState: (state: AudioChannelState) => void,
  onStream?: (stream: MediaStream) => void,
): AudioTrackConnection {
  let closed = false;
  let attempt = 0;
  let peer: RTCPeerConnection | undefined;
  let location: string | null = null;
  let handshakeTimer: number | undefined;
  let stallTimer: number | undefined;
  let retryTimer: number | undefined;
  let lastPackets = -1;
  let lastProgressAt = Date.now();
  let state: AudioChannelState = 'connecting';

  const report = (next: AudioChannelState) => { state = next; onState(next); };

  const clearTimers = () => {
    if (handshakeTimer !== undefined) window.clearTimeout(handshakeTimer);
    if (stallTimer !== undefined) window.clearInterval(stallTimer);
    if (retryTimer !== undefined) window.clearTimeout(retryTimer);
    handshakeTimer = undefined; stallTimer = undefined; retryTimer = undefined;
  };

  const release = () => {
    clearTimers();
    if (peer) {
      peer.ontrack = null;
      peer.onconnectionstatechange = null;
      peer.close();
      peer = undefined;
    }
    if (location) {
      const target = location;
      location = null;
      void fetch(target, { method: 'DELETE', keepalive: true, cache: 'no-store' }).catch(() => undefined);
    }
  };

  const scheduleReconnect = (): void => {
    if (closed) return;
    release();
    // F6-10: never permanently give up on recoverable failures; only 401/403 disables.
    report('reconnecting');
    const delay = reconnectDelayMs(attempt);
    attempt += 1;
    retryTimer = window.setTimeout(() => void connect(), delay);
  };

  const connect = async (): Promise<void> => {
    if (closed) return;
    try {
      report(attempt === 0 ? 'connecting' : 'reconnecting');
      const next = new RTCPeerConnection();
      peer = next;
      const stream = new MediaStream();
      next.addTransceiver('audio', { direction: 'recvonly' });
      next.ontrack = (event) => {
        if (closed || peer !== next) return;
        if (!stream.getTracks().some((existing) => existing.id === event.track.id)) stream.addTrack(event.track);
        onStream?.(stream);
      };
      next.onconnectionstatechange = () => {
        if (closed || peer !== next) return;
        if (next.connectionState === 'failed') scheduleReconnect();
      };
      await next.setLocalDescription(await next.createOffer());
      await gatherIce(next);
      if (closed || peer !== next || !next.localDescription?.sdp) return;
      const response = await fetch(track.endpoint, {
        method: 'POST',
        headers: { Accept: 'application/sdp', 'Content-Type': 'application/sdp' },
        body: next.localDescription.sdp,
        cache: 'no-store',
        redirect: 'error',
      });
      if (response.status === 401 || response.status === 403) { release(); report('disabled'); return; }
      if (response.status !== 201) throw new Error('audio-only WHEP offer was rejected');
      const nextLocation = sessionLocation(response.headers.get('Location'), track.endpoint);
      if (!nextLocation) throw new Error('audio-only WHEP session location is invalid');
      location = nextLocation;
      await next.setRemoteDescription({ type: 'answer', sdp: await response.text() });
      handshakeTimer = window.setTimeout(() => { if (!closed) scheduleReconnect(); }, HANDSHAKE_TIMEOUT_MS);
      lastPackets = -1;
      lastProgressAt = Date.now();
      stallTimer = window.setInterval(() => {
        if (closed || !peer) return;
        if (peer.connectionState !== 'connected') return;
        if (handshakeTimer !== undefined) { window.clearTimeout(handshakeTimer); handshakeTimer = undefined; }
        if (state !== 'connected') {
          attempt = 0;
          report('connected');
        }
        void peer.getStats().then((stats) => {
          let packets = -1;
          stats.forEach((entry) => { if (entry.type === 'inbound-rtp' && entry.kind === 'audio') packets = Number(entry.packetsReceived ?? -1); });
          if (packets > lastPackets) { lastPackets = packets; lastProgressAt = Date.now(); return; }
          if (Date.now() - lastProgressAt > STALL_MS) scheduleReconnect();
        }).catch(() => undefined);
      }, 1_000);
    } catch (error) {
      if (closed || (error instanceof DOMException && error.name === 'AbortError')) return;
      scheduleReconnect();
    }
  };

  const close = () => {
    if (closed) return;
    closed = true;
    release();
    report('disabled');
  };

  void connect();
  return { close, getState: () => state };
}
