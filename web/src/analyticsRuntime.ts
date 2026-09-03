import type { AnalyticsPolicy } from './types';
import type { DetectionSignal } from './monitorView';
import { requestAnalyticsSlot, type AnalyticsPriority } from './analyticsScheduler';

export type BrowserAnalyticsState = 'idle' | 'running' | 'unsupported' | 'error' | 'suspended';

export interface BrowserAnalyticsStatus {
  state: BrowserAnalyticsState;
  reason: string;
  sampleFps: number;
  lastSignalAt: number;
}

export interface BrowserAnalyticsOptions {
  video: HTMLVideoElement;
  cameraId: string;
  profileId: string;
  policy: AnalyticsPolicy;
  priority?: AnalyticsPriority;
  zones?: Array<{ mode: 'include' | 'exclude' | 'privacy'; polygon: number[][] }>;
  visible?: () => boolean;
  lowPower?: () => boolean;
  onSignal?: (signal: DetectionSignal) => void;
  onPersonBoxes?: (boxes: Array<{ x: number; y: number; width: number; height: number; confidence?: number }>, execution: 'browser-webgpu' | 'browser-wasm', model: { id: string; version: string; sha256: string }) => void;
  onStatus?: (status: BrowserAnalyticsStatus) => void;
}

type WorkerResult = { type: 'result'; key: string; signals: Array<Omit<DetectionSignal, 'schemaVersion'>> } |
  { type: 'error'; key: string; message: string };

const MAX_DIMENSION = 160;
const clamp = (value: number, min: number, max: number) => Math.min(max, Math.max(min, value));

/** Browser-only motion/scene-change runtime. Frames never leave this tab. */
export class BrowserAnalyticsRuntime {
  private readonly options: BrowserAnalyticsOptions;
  private worker: Worker | undefined;
  private personWorker: Worker | undefined;
  private personBusy = false;
  private canvas: HTMLCanvasElement | undefined;
  private timer = 0;
  private frameCallback = 0;
  private captureIntervalMs = 500;
  private videoFrameCallback = false;
  private stopped = true;
  private lastFrameAt = 0;
  private lastPersonFrameAt = 0;
  private lastSignalAt = 0;
  private status: BrowserAnalyticsStatus = { state: 'idle', reason: '', sampleFps: 0, lastSignalAt: 0 };

  constructor(options: BrowserAnalyticsOptions) { this.options = options; }

  start(): BrowserAnalyticsStatus {
    this.stop();
    const { policy } = this.options;
    if (!policy.motionEnabled && !policy.sceneChangeEnabled && !policy.personEnabled) return this.update('idle', 'disabled');
    if (typeof Worker === 'undefined' || typeof document === 'undefined') return this.update('unsupported', 'worker_unavailable');
    if (this.options.video.crossOrigin === 'use-credentials') return this.update('unsupported', 'credentialed_media_not_readable');
    if (policy.motionEnabled || policy.sceneChangeEnabled)
      this.worker = new Worker(new URL('./analytics.worker.ts', import.meta.url), { type: 'module', name: 'webobs-analytics' });
    this.worker?.addEventListener('message', (event: MessageEvent<WorkerResult>) => {
      if (event.data.type === 'error') { this.update('error', event.data.message); return; }
      for (const value of event.data.signals) {
        const signal: DetectionSignal = { schemaVersion: 2, ...value };
        if (!this.options.policy.motionEnabled && signal.kind === 'motion') continue;
        if (!this.options.policy.sceneChangeEnabled && signal.kind === 'scene-change') continue;
        this.lastSignalAt = signal.occurredAt;
        this.options.onSignal?.(signal);
      }
    });
    this.worker?.addEventListener('error', () => this.update('error', 'worker_failed'));
    if (policy.personEnabled) {
      this.personWorker = new Worker(new URL('./person.worker.ts', import.meta.url), { type: 'module', name: 'webobs-person-detector' });
      this.personWorker.addEventListener('message', (event: MessageEvent<{ type: 'result'; boxes: Array<{ x: number; y: number; width: number; height: number; confidence: number }>; execution: 'browser-webgpu' | 'browser-wasm'; model: { id: string; version: string; sha256: string } } | { type: 'error'; message: string }>) => {
        this.personBusy = false;
        if (event.data.type === 'error') this.update('error', event.data.message);
        else this.options.onPersonBoxes?.(event.data.boxes, event.data.execution, event.data.model);
      });
      this.personWorker.addEventListener('error', () => { this.personBusy = false; this.update('error', 'person_worker_failed'); });
    }
    this.canvas = document.createElement('canvas'); this.canvas.width = MAX_DIMENSION; this.canvas.height = 90;
    this.stopped = false;
    this.update('running', 'browser_worker');
    const interval = 1000 / clamp(this.options.policy.personEnabled && !this.options.policy.motionEnabled
      ? (this.options.policy.person?.sampleFps ?? 1) : (this.options.policy.motion?.sampleFps ?? 2), .5, 5);
    this.captureIntervalMs = interval;
    const video = this.options.video as HTMLVideoElement & {
      requestVideoFrameCallback?: (callback: (now: number, metadata: VideoFrameCallbackMetadata) => void) => number;
      cancelVideoFrameCallback?: (handle: number) => void;
    };
    if (typeof video.requestVideoFrameCallback === 'function') {
      this.videoFrameCallback = true;
      const queue = () => {
        if (this.stopped || !this.videoFrameCallback) return;
        this.frameCallback = video.requestVideoFrameCallback(() => {
          void this.capture().finally(queue);
        });
      };
      queue();
    } else {
      this.videoFrameCallback = false;
      this.timer = window.setInterval(() => void this.capture(), interval);
    }
    void this.capture();
    return this.status;
  }

  stop(): void {
    this.stopped = true;
    if (this.timer) window.clearInterval(this.timer);
    this.timer = 0;
    const video = this.options.video as HTMLVideoElement & { cancelVideoFrameCallback?: (handle: number) => void };
    if (this.frameCallback && typeof video.cancelVideoFrameCallback === 'function') video.cancelVideoFrameCallback(this.frameCallback);
    this.frameCallback = 0;
    this.videoFrameCallback = false;
    this.lastPersonFrameAt = 0;
    this.worker?.postMessage({ type: 'reset', key: `${this.options.cameraId}\u0000${this.options.profileId}` });
    this.worker?.terminate(); this.worker = undefined; this.canvas = undefined;
    this.personWorker?.postMessage({ type: 'reset' }); this.personWorker?.terminate(); this.personWorker = undefined; this.personBusy = false;
    if (this.status.state === 'running') this.update('idle', 'stopped');
  }

  private update(state: BrowserAnalyticsState, reason: string): BrowserAnalyticsStatus {
    const configured = this.options.policy.motionEnabled
      ? (this.options.policy.motion?.sampleFps ?? 2)
      : (this.options.policy.person?.sampleFps ?? 1);
    this.status = { state, reason, sampleFps: clamp(configured, .1, 5), lastSignalAt: this.lastSignalAt };
    this.options.onStatus?.(this.status); return this.status;
  }

  private async capture(): Promise<void> {
    if (this.stopped || !this.canvas || this.options.video.readyState < HTMLMediaElement.HAVE_CURRENT_DATA ||
      this.options.visible?.() === false) return;
    const lowPowerSuppressed = this.options.lowPower?.() === true && !this.options.policy.forceAnalyticsAlwaysOn;
    if (lowPowerSuppressed) {
      if (this.status.state !== 'suspended') this.update('suspended', 'low_power');
      return;
    }
    if (this.status.state === 'suspended') this.update('running', 'browser_worker');
    const now = performance.now();
    if (now - this.lastFrameAt < Math.max(50, this.captureIntervalMs - 4)) return;
    if (!requestAnalyticsSlot('frame', this.options.priority)) return;
    this.lastFrameAt = now;
    const context = this.canvas.getContext('2d', { willReadFrequently: true });
    if (!context) { this.update('unsupported', 'canvas_unavailable'); return; }
    try {
      const aspect = this.options.video.videoWidth > 0 && this.options.video.videoHeight > 0
        ? this.options.video.videoWidth / this.options.video.videoHeight : 16 / 9;
      const width = MAX_DIMENSION;
      const height = Math.max(2, Math.min(MAX_DIMENSION, Math.round(width / aspect)));
      if (this.canvas.height !== height) this.canvas.height = height;
      context.drawImage(this.options.video, 0, 0, width, height);
      const rgba = context.getImageData(0, 0, width, height).data;
      const pixels = new Uint8Array(width * height);
      for (let source = 0, target = 0; target < pixels.length; target += 1, source += 4)
        pixels[target] = Math.round(rgba[source] * .299 + rgba[source + 1] * .587 + rgba[source + 2] * .114);
      if (this.worker) this.worker.postMessage({ type: 'frame', cameraId: this.options.cameraId, profileId: this.options.profileId,
        width, height, pixels: pixels.buffer, timestamp: Date.now(), options: {
          sensitivity: this.options.policy.motion?.sensitivity ?? .15,
          debounceMs: this.options.policy.motion?.debounceMs ?? 500,
          cooldownMs: this.options.policy.motion?.cooldownMs ?? 5000,
          sceneThreshold: this.options.policy.sceneChange?.threshold ?? .55,
          sceneConfirmFrames: this.options.policy.sceneChange?.confirmFrames ?? 2,
          sceneCooldownMs: this.options.policy.sceneChange?.cooldownMs ?? 30000,
          zones: this.options.zones,
        } }, [pixels.buffer]);
      const personInterval = 1000 / clamp(this.options.policy.person?.sampleFps ?? 1, .1, 5);
      if (this.personWorker && !this.personBusy && now - this.lastPersonFrameAt >= personInterval - 4) {
        if (!requestAnalyticsSlot('person', this.options.priority)) return;
        this.personBusy = true;
        this.lastPersonFrameAt = now;
        const personPixels = new Uint8ClampedArray(rgba);
        this.personWorker.postMessage({ type: 'frame', width, height, rgba: personPixels.buffer,
          threshold: this.options.policy.person?.confidenceThreshold ?? .6, maxBoxes: this.options.policy.person?.maxBoxes ?? 16 }, [personPixels.buffer]);
      }
    } catch (error) {
      this.update('unsupported', error instanceof DOMException && error.name === 'SecurityError' ? 'pixel_access_denied' : 'frame_capture_failed');
    }
  }
}
