import type { SceneSource } from './types';

export type DirectAudioState = 'disabled' | 'running' | 'suspended' | 'blocked';

export interface DirectAudioSnapshot {
  state: DirectAudioState;
  inputCount: number;
  level: number;
  sources: Array<{ sourceId: string; rmsDbfs: number | null; peakDbfs: number | null }>;
}

interface MixerEntry {
  element: HTMLVideoElement;
  stream?: MediaStream;
  sourceNode?: MediaStreamAudioSourceNode;
  delayNode?: DelayNode;
  gainNode?: GainNode;
  analyserNode?: AnalyserNode;
  rmsDbfs?: number;
  peakDbfs?: number;
}

const clamp = (value: number, minimum: number, maximum: number) =>
  Math.min(Math.max(value, minimum), maximum);

export class DirectAudioMixer {
  private readonly entries = new Map<string, MixerEntry>();
  private readonly configuration = new Map<string, SceneSource>();
  private context?: AudioContext;
  private master?: GainNode;
  private analyser?: AnalyserNode;
  private meterTimer?: number;
  private enabled = false;
  private blocked = false;
  private level = 0;
  private masterVolume = 1;

  constructor(private readonly onSnapshot: (snapshot: DirectAudioSnapshot) => void) {
    this.emit();
  }

  attach(sourceId: string, element: HTMLVideoElement): () => void {
    this.detach(sourceId);
    this.entries.set(sourceId, { element });
    element.muted = true;
    if (this.context) this.materialize(sourceId);
    this.applyConfiguration();
    this.emit();
    return () => {
      const entry = this.entries.get(sourceId);
      if (!entry || entry.element !== element) return;
      this.detach(sourceId);
      this.emit();
    };
  }

  configure(sources: SceneSource[]): void {
    this.configuration.clear();
    for (const source of sources) this.configuration.set(source.id, source);
    this.applyConfiguration();
  }

  setMasterVolume(value: number): void {
    this.masterVolume = clamp(value, 0, 1);
    if (this.master && this.context)
      this.master.gain.setTargetAtTime(this.masterVolume, this.context.currentTime, .01);
  }

  bindStream(sourceId: string, stream: MediaStream): void {
    const entry = this.entries.get(sourceId);
    if (!entry) return;
    if (entry.stream === stream) {
      if (this.context && !entry.gainNode) {
        this.materialize(sourceId);
        this.applyConfiguration();
      } else {
        this.emit();
      }
      return;
    }
    this.disconnectEntry(entry);
    entry.stream = stream;
    if (this.context) this.materialize(sourceId);
    this.applyConfiguration();
  }

  async enable(): Promise<boolean> {
    this.enabled = true;
    this.blocked = false;
    if (!this.context) {
      this.context = new AudioContext({ latencyHint: 'interactive', sampleRate: 48_000 });
      this.master = this.context.createGain();
      this.master.gain.value = this.masterVolume;
      this.analyser = this.context.createAnalyser();
      this.analyser.fftSize = 2048;
      this.master.connect(this.analyser).connect(this.context.destination);
    }
    for (const sourceId of this.entries.keys()) this.materialize(sourceId);
    this.applyConfiguration();

    const playback = [...this.entries.values()].map(({ element }) => element.play());
    try {
      await Promise.all([this.context.resume(), ...playback]);
      if (this.context.state !== 'running') throw new Error('audio context did not start');
      this.startMeter();
      this.emit();
      return true;
    } catch {
      this.blocked = true;
      this.enabled = false;
      await this.context.suspend().catch(() => undefined);
      this.stopMeter();
      this.emit();
      return false;
    }
  }

  async disable(): Promise<void> {
    this.enabled = false;
    this.blocked = false;
    if (this.context) await this.context.suspend().catch(() => undefined);
    this.stopMeter();
    this.emit();
  }

  destroy(): void {
    this.enabled = false;
    this.stopMeter();
    for (const sourceId of [...this.entries.keys()]) this.detach(sourceId);
    this.master?.disconnect();
    this.analyser?.disconnect();
    void this.context?.close();
    this.context = undefined;
    this.master = undefined;
    this.analyser = undefined;
  }

  private materialize(sourceId: string): void {
    const entry = this.entries.get(sourceId);
    if (!entry || !this.context || !this.master || entry.gainNode || !entry.stream ||
        entry.stream.getAudioTracks().length === 0) return;
    const sourceNode = this.context.createMediaStreamSource(entry.stream);
    const delayNode = this.context.createDelay(20.1);
    const gainNode = this.context.createGain();
    const analyserNode = this.context.createAnalyser();
    analyserNode.fftSize = 1024;
    sourceNode.connect(analyserNode).connect(delayNode).connect(gainNode).connect(this.master);
    entry.sourceNode = sourceNode;
    entry.delayNode = delayNode;
    entry.gainNode = gainNode;
    entry.analyserNode = analyserNode;
  }

  private detach(sourceId: string): void {
    const entry = this.entries.get(sourceId);
    if (!entry) return;
    this.disconnectEntry(entry);
    entry.element.muted = true;
    this.entries.delete(sourceId);
  }

  private disconnectEntry(entry: MixerEntry): void {
    entry.sourceNode?.disconnect();
    entry.delayNode?.disconnect();
    entry.gainNode?.disconnect();
    entry.analyserNode?.disconnect();
    entry.sourceNode = undefined;
    entry.delayNode = undefined;
    entry.gainNode = undefined;
    entry.analyserNode = undefined;
    entry.rmsDbfs = undefined;
    entry.peakDbfs = undefined;
  }

  private applyConfiguration(): void {
    const offsets = [...this.entries.entries()]
      .filter(([, entry]) => (entry.stream?.getAudioTracks().length ?? 0) > 0)
      .map(([sourceId]) => this.configuration.get(sourceId)?.syncOffsetMs ?? 0);
    const baseline = Math.min(0, ...offsets);
    const now = this.context?.currentTime ?? 0;
    for (const [sourceId, entry] of this.entries) {
      const source = this.configuration.get(sourceId);
      const gain = source && !source.muted ? clamp(source.volume, 0, 1) : 0;
      const delay = clamp(((source?.syncOffsetMs ?? 0) - baseline) / 1000, 0, 20);
      entry.gainNode?.gain.setTargetAtTime(gain, now, 0.01);
      entry.delayNode?.delayTime.setTargetAtTime(delay, now, 0.01);
      entry.element.muted = true;
      entry.element.volume = 1;
    }
    this.emit();
  }

  private startMeter(): void {
    this.stopMeter();
    this.meterTimer = window.setInterval(() => {
      if (!this.analyser || !this.enabled) return;
      const samples = new Float32Array(this.analyser.fftSize);
      this.analyser.getFloatTimeDomainData(samples);
      let sum = 0;
      for (const sample of samples) sum += sample * sample;
      this.level = Math.sqrt(sum / samples.length);
      for (const entry of this.entries.values()) {
        if (!entry.analyserNode) { entry.rmsDbfs = undefined; entry.peakDbfs = undefined; continue; }
        const sourceSamples = new Float32Array(entry.analyserNode.fftSize);
        entry.analyserNode.getFloatTimeDomainData(sourceSamples);
        let sourceSum = 0; let peak = 0;
        for (const sample of sourceSamples) { sourceSum += sample * sample; peak = Math.max(peak, Math.abs(sample)); }
        entry.rmsDbfs = amplitudeToDbfs(Math.sqrt(sourceSum / sourceSamples.length));
        entry.peakDbfs = amplitudeToDbfs(peak);
      }
      this.emit();
    }, 100);
  }

  private stopMeter(): void {
    if (this.meterTimer !== undefined) window.clearInterval(this.meterTimer);
    this.meterTimer = undefined;
    this.level = 0;
    for (const entry of this.entries.values()) { entry.rmsDbfs = undefined; entry.peakDbfs = undefined; }
  }

  private emit(): void {
    const state: DirectAudioState = this.blocked ? 'blocked'
      : !this.enabled ? 'disabled'
        : this.context?.state === 'running' ? 'running' : 'suspended';
    const inputCount = [...this.entries.values()]
      .filter((entry) => (entry.stream?.getAudioTracks().length ?? 0) > 0).length;
    const snapshot: DirectAudioSnapshot = { state, inputCount, level: this.level,
      sources: [...this.entries.entries()].map(([sourceId, entry]) => ({ sourceId,
        rmsDbfs: entry.rmsDbfs ?? null, peakDbfs: entry.peakDbfs ?? null })) };
    this.onSnapshot(snapshot);
    window.dispatchEvent(new CustomEvent('webobs:direct-audio-meters', { detail: snapshot }));
  }
}

export function amplitudeToDbfs(value: number): number {
  if (!Number.isFinite(value) || value <= 0.000001) return -120;
  return Math.max(-120, Math.min(0, 20 * Math.log10(value)));
}
