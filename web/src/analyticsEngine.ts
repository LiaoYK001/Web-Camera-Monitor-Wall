import type { DetectionSignal } from './monitorView';

export interface AnalyticsFrame {
  width: number;
  height: number;
  pixels: Uint8Array;
  timestamp: number;
}

export interface MotionRuntimeOptions {
  sensitivity?: number;
  debounceMs?: number;
  cooldownMs?: number;
  sceneThreshold?: number;
  sceneConfirmFrames?: number;
  sceneCooldownMs?: number;
  /** Existing event-service zones, normalized to the sampled frame. */
  zones?: Array<{ mode: 'include' | 'exclude' | 'privacy'; polygon: number[][] }>;
}

export interface AnalyticsEngineResult {
  motion: number;
  sceneChange: number;
  signals: Array<Omit<DetectionSignal, 'schemaVersion'>>;
}

const clamp = (value: number, min: number, max: number) => Math.min(max, Math.max(min, value));

/**
 * Small, deterministic browser-side detector. It deliberately accepts only a
 * bounded grayscale frame so no camera frame can escape the worker boundary.
 */
export class MotionSceneEngine {
  private previous: Uint8Array | undefined;
  private background: Float32Array | undefined;
  private previousHistogram: Uint32Array | undefined;
  private previousActivePixels = 0;
  private zoneSignature = '';
  private previousAt = 0;
  private pendingMotionAt = 0;
  private motionCooldownUntil = 0;
  private sceneConfirmations = 0;
  private sceneCooldownUntil = 0;

  private histogram(pixels: Uint8Array, width: number, height: number,
    includeZones: MotionRuntimeOptions['zones'] = [], excludedZones: MotionRuntimeOptions['zones'] = []): { values: Uint32Array; activePixels: number } {
    const result = new Uint32Array(16);
    let activePixels = 0;
    for (let index = 0; index < pixels.length; index += 1) {
      const x = (index % width + .5) / width;
      const y = (Math.floor(index / width) + .5) / height;
      const inInclude = !includeZones.length || includeZones.some((zone) => pointInPolygon(x, y, zone.polygon));
      const inExcluded = excludedZones.some((zone) => pointInPolygon(x, y, zone.polygon));
      if (!inInclude || inExcluded) continue;
      result[Math.min(15, pixels[index] >> 4)] += 1;
      activePixels += 1;
    }
    return { values: result, activePixels };
  }

  private signalId(): string {
    const random = typeof crypto !== 'undefined' && 'randomUUID' in crypto ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(36).slice(2)}`;
    return `browser-${random}`;
  }

  reset(): void {
    this.previous = undefined;
    this.background = undefined;
    this.previousHistogram = undefined;
    this.previousActivePixels = 0;
    this.zoneSignature = '';
    this.previousAt = 0;
    this.pendingMotionAt = 0;
    this.motionCooldownUntil = 0;
    this.sceneConfirmations = 0;
    this.sceneCooldownUntil = 0;
  }

  evaluate(frame: AnalyticsFrame, ids: { cameraId: string; profileId: string }, options: MotionRuntimeOptions = {}): AnalyticsEngineResult {
    const size = frame.width * frame.height;
    if (!Number.isInteger(frame.width) || !Number.isInteger(frame.height) || frame.width < 2 || frame.height < 2 ||
      size > 262_144 || frame.pixels.length !== size) throw new Error('analytics frame is invalid');
    const sensitivity = clamp(options.sensitivity ?? .15, .01, 1);
    const debounceMs = clamp(Math.trunc(options.debounceMs ?? 500), 0, 60_000);
    const cooldownMs = clamp(Math.trunc(options.cooldownMs ?? 5_000), 0, 3_600_000);
    const sceneThreshold = clamp(options.sceneThreshold ?? .55, .05, 1);
    const sceneConfirmFrames = clamp(Math.trunc(options.sceneConfirmFrames ?? 2), 1, 5);
    const sceneCooldownMs = clamp(Math.trunc(options.sceneCooldownMs ?? 30_000), 0, 3_600_000);
    const now = Number.isFinite(frame.timestamp) ? frame.timestamp : Date.now();
    const includeZones = (options.zones ?? []).filter((zone) => zone.mode === 'include' && zone.polygon.length >= 3);
    const excludedZones = (options.zones ?? []).filter((zone) => (zone.mode === 'exclude' || zone.mode === 'privacy') && zone.polygon.length >= 3);
    // Zone edits change the population used for histogram normalization.  A
    // short re-baseline avoids comparing a whole-frame histogram with a
    // masked-frame histogram and producing a false scene-change event.
    const nextZoneSignature = JSON.stringify({ include: includeZones, exclude: excludedZones });
    if (nextZoneSignature !== this.zoneSignature) {
      this.zoneSignature = nextZoneSignature;
      this.previous = undefined;
      this.background = undefined;
      this.previousHistogram = undefined;
      this.previousActivePixels = 0;
    }
    if (!this.background || this.background.length !== size || !this.previous || this.previous.length !== size) {
      this.background = Float32Array.from(frame.pixels);
      this.previous = frame.pixels.slice();
      const baseline = this.histogram(frame.pixels, frame.width, frame.height, includeZones, excludedZones);
      this.previousHistogram = baseline.values;
      this.previousActivePixels = baseline.activePixels;
      this.previousAt = now;
      return { motion: 0, sceneChange: 0, signals: [] };
    }
    let changedCount = 0;
    let sceneDelta = 0;
    let activePixels = 0;
    const histogram = new Uint32Array(16);
    for (let index = 0; index < size; index += 1) {
      const x = (index % frame.width + .5) / frame.width;
      const y = (Math.floor(index / frame.width) + .5) / frame.height;
      const inInclude = !includeZones.length || includeZones.some((zone) => pointInPolygon(x, y, zone.polygon));
      const inExcluded = excludedZones.some((zone) => pointInPolygon(x, y, zone.polygon));
      if (!inInclude || inExcluded) continue;
      activePixels += 1;
      const value = frame.pixels[index];
      const delta = Math.abs(value - this.background[index]);
      if (delta >= 24) changedCount += 1;
      // Scene changes are evaluated against the EMA background, so a cut
      // remains observable for the configured confirmation frames instead of
      // disappearing after the first identical post-cut frame.
      sceneDelta += delta / 255;
      histogram[Math.min(15, value >> 4)] += 1;
      // EMA background makes slow illumination changes non-events.
      this.background[index] = this.background[index] * .92 + value * .08;
    }
    const motion = activePixels ? changedCount / activePixels : 0;
    const histogramDistance = activePixels && this.previousHistogram && this.previousActivePixels
      ? histogram.reduce((sum, value, index) => sum + Math.abs(value / activePixels - this.previousHistogram![index] / this.previousActivePixels), 0) / 2 : 0;
    const sceneChange = activePixels ? Math.max(sceneDelta / activePixels, histogramDistance) : 0;
    this.previous.set(frame.pixels);
    this.previousHistogram = histogram;
    this.previousActivePixels = activePixels;
    const signals: Array<Omit<DetectionSignal, 'schemaVersion'>> = [];
    if (motion >= sensitivity) {
      if (!this.pendingMotionAt) this.pendingMotionAt = now;
      if (now - this.pendingMotionAt >= debounceMs && now >= this.motionCooldownUntil) {
        signals.push({ ...ids, signalId: this.signalId(), kind: 'motion', occurredAt: now, confidence: clamp(motion, 0, 1), source: 'browser' });
        this.motionCooldownUntil = now + cooldownMs;
        this.pendingMotionAt = 0;
      }
    } else this.pendingMotionAt = 0;
    if (sceneChange >= sceneThreshold) this.sceneConfirmations += 1;
    else this.sceneConfirmations = 0;
    if (this.sceneConfirmations >= sceneConfirmFrames && now >= this.sceneCooldownUntil) {
      signals.push({ ...ids, signalId: this.signalId(), kind: 'scene-change', occurredAt: now, confidence: clamp(sceneChange, 0, 1), source: 'browser' });
      this.sceneCooldownUntil = now + sceneCooldownMs;
      this.sceneConfirmations = 0;
      // Re-baseline after a genuine scene cut so it does not repeat forever.
      this.background.set(frame.pixels);
    }
    this.previousAt = now;
    return { motion, sceneChange, signals };
  }
}

function pointInPolygon(x: number, y: number, polygon: number[][]): boolean {
  let inside = false;
  for (let index = 0, previous = polygon.length - 1; index < polygon.length; previous = index++) {
    const current = polygon[index]; const prior = polygon[previous];
    const currentX = Number(current?.[0]); const currentY = Number(current?.[1]);
    const priorX = Number(prior?.[0]); const priorY = Number(prior?.[1]);
    if (![currentX, currentY, priorX, priorY].every(Number.isFinite)) continue;
    const intersects = ((currentY > y) !== (priorY > y)) &&
      (x < (priorX - currentX) * (y - currentY) / ((priorY - currentY) || Number.EPSILON) + currentX);
    if (intersects) inside = !inside;
  }
  return inside;
}

export function grayscaleFromRgba(rgba: Uint8ClampedArray, width: number, height: number): AnalyticsFrame {
  if (rgba.length !== width * height * 4) throw new Error('RGBA frame is invalid');
  const pixels = new Uint8Array(width * height);
  for (let source = 0, target = 0; target < pixels.length; target += 1, source += 4)
    pixels[target] = Math.round(rgba[source] * .299 + rgba[source + 1] * .587 + rgba[source + 2] * .114);
  return { width, height, pixels, timestamp: Date.now() };
}
