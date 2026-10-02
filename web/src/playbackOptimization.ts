import type { CameraProfile } from './types';

export interface PlaybackOptimization {
  enabled: boolean; slowStreamTolerance: boolean; adaptiveProfiles: boolean; catchUp: boolean;
}
export const defaultPlaybackOptimization = (): PlaybackOptimization => ({ enabled: true, slowStreamTolerance: true, adaptiveProfiles: true, catchUp: true });
export function normalizePlaybackOptimization(value?: Partial<PlaybackOptimization>): PlaybackOptimization {
  return { enabled: value?.enabled !== false, slowStreamTolerance: value?.slowStreamTolerance !== false,
    adaptiveProfiles: value?.adaptiveProfiles !== false, catchUp: value?.catchUp !== false };
}

/** Frame arrival cadence, not nominal FPS. Legitimate low-rate video must not reconnect every six seconds. */
export class FrameCadence {
  private last = 0;
  private gaps: number[] = [];
  observe(now: number) {
    if (this.last > 0 && now > this.last) { this.gaps.push(now - this.last); if (this.gaps.length > 16) this.gaps.shift(); }
    this.last = now;
  }
  stallAfterMs(enabled: boolean): number {
    if (!enabled || !this.gaps.length) return enabled ? 45000 : 6000;
    const sorted = [...this.gaps].sort((a, b) => a - b);
    const cadence = sorted[Math.floor((sorted.length - 1) * .9)];
    return Math.min(90000, Math.max(6000, cadence * 5 + 3000));
  }
  reset() { this.last = 0; this.gaps = []; }
}
export interface NetworkSample { received: number; lost: number; jitter: number; freezes: number; timestamp: number }
export function congested(previous: NetworkSample, current: NetworkSample): boolean {
  const received = current.received - previous.received, lost = Math.max(0, current.lost - previous.lost);
  if (current.timestamp <= previous.timestamp || received < 0) return false;
  return (received + lost >= 20 && lost / (received + lost) > .05) || current.jitter > .18 ||
    (current.jitter > .06 && current.freezes > previous.freezes);
}
const cost = (profile: CameraProfile) => Math.max(1, profile.width) * Math.max(1, profile.height) * Math.max(.1, profile.fps || 25);
export function lowerBandwidthProfile(current: CameraProfile, candidates: CameraProfile[]): CameraProfile | undefined {
  return candidates.filter((profile) => profile.id !== current.id && profile.enabled !== false && profile.role !== 'snapshot' &&
    (!current.audioCodec || Boolean(profile.audioCodec)) &&
    profile.width > 0 && profile.height > 0 && profile.fps > 0 && cost(profile) < cost(current) * .8)
    .sort((a, b) => cost(b) - cost(a))[0];
}
