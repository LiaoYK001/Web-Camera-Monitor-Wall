interface Sample {
  started: number;
  pending?: Promise<RTCStatsReport | null>;
  report?: RTCStatsReport;
}

const samples = new WeakMap<RTCPeerConnection, Sample>();
const REUSE_MS = 200;

/** Share native statistics between telemetry and liveness checks for one peer. */
export function readPeerStats(peer: RTCPeerConnection): Promise<RTCStatsReport | null> {
  if (peer.connectionState === 'closed' || typeof peer.getStats !== 'function') return Promise.resolve(null);
  const previous = samples.get(peer);
  if (previous?.pending) return previous.pending;
  if (previous?.report && performance.now() - previous.started < REUSE_MS) return Promise.resolve(previous.report);
  const sample: Sample = { started: performance.now() };
  samples.set(peer, sample);
  sample.pending = Promise.resolve().then(() => peer.getStats()).then((report) => {
    if (samples.get(peer) !== sample || peer.connectionState === 'closed') return null;
    sample.report = report;
    return report;
  }).catch((error: unknown) => {
    if (samples.get(peer) === sample) samples.delete(peer);
    throw error;
  }).finally(() => { sample.pending = undefined; });
  return sample.pending;
}

export function forgetPeerStats(peer: RTCPeerConnection): void {
  samples.delete(peer);
}
