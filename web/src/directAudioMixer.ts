import type { SceneSource } from './types';

export type DirectAudioState = 'disabled' | 'running' | 'suspended' | 'blocked';

/** One selected input track of a source, keyed by "source + input track". */
export interface DirectAudioTrackMeter {
  sourceId: string;
  trackIndex: number;
  rmsDbfs: number | null;
  peakDbfs: number | null;
  gain: number;
  muted: boolean;
  live: boolean;
}

export interface DirectAudioSourceSnapshot {
  sourceId: string;
  rmsDbfs: number | null;
  peakDbfs: number | null;
  audioTracks?: number;
  streamBound?: boolean;
  /** Measured level of every selected track of this source summed together. */
  merged: { rmsDbfs: number | null; peakDbfs: number | null } | null;
  /** Per-track meters; empty until a track stream is bound. */
  independent: DirectAudioTrackMeter[];
}

export interface DirectAudioSnapshot {
  state: DirectAudioState;
  inputCount: number;
  level: number;
  sources: DirectAudioSourceSnapshot[];
}

/** Per-track gain/mute as configured by the audio workspace. */
export interface DirectAudioTrackSelection {
  index: number;
  gain: number;
  muted: boolean;
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

interface TrackEntry {
  sourceId: string;
  trackIndex: number;
  stream?: MediaStream;
  sourceNode?: MediaStreamAudioSourceNode;
  gainNode?: GainNode;
  analyserNode?: AnalyserNode;
  gain: number;
  muted: boolean;
  rmsDbfs?: number;
  peakDbfs?: number;
}

interface MergeEntry {
  gainNode: GainNode;
  analyserNode: AnalyserNode;
  rmsDbfs?: number;
  peakDbfs?: number;
}

const clamp = (value: number, minimum: number, maximum: number) =>
  Math.min(Math.max(value, minimum), maximum);

const trackKey = (sourceId: string, trackIndex: number) => `${sourceId}#${trackIndex}`;

export class DirectAudioMixer {
  private readonly entries = new Map<string, MixerEntry>();
  /** Per-track audio-only channels, keyed by "sourceId#trackIndex". */
  private readonly trackEntries = new Map<string, TrackEntry>();
  private readonly mergeEntries = new Map<string, MergeEntry>();
  private readonly configuration = new Map<string, SceneSource>();
  private readonly trackConfiguration = new Map<string, Map<number, DirectAudioTrackSelection>>();
  private context?: AudioContext;
  private master?: GainNode;
  private analyser?: AnalyserNode;
  private meterTimer?: number;
  private enabled = false;
  private blocked = false;
  private level = 0;
  private masterVolume = 1;
  private outputEnabled = true;
  private latest: DirectAudioSnapshot = { state: 'disabled', inputCount: 0, level: 0, sources: [] };

  constructor(private readonly onSnapshot: (snapshot: DirectAudioSnapshot) => void) {
    this.emit();
  }

  attach(sourceId: string, element: HTMLVideoElement): () => void {
    this.detach(sourceId);
    this.entries.set(sourceId, { element });
    // The element never plays its own audio: the mixer feeds the speaker so a
    // multi-track source cannot double-play track 0 through the video element.
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

  /**
   * Declare which input tracks of a source are selected.  Entries are created
   * for tracks that already have a bound stream; a track that is deselected
   * releases its Web Audio nodes immediately.
   */
  configureTracks(sourceId: string, selections: DirectAudioTrackSelection[]): void {
    const wanted = new Map<number, DirectAudioTrackSelection>();
    for (const selection of selections) {
      wanted.set(selection.index, { index: selection.index, gain: clamp(selection.gain, 0, 1), muted: selection.muted });
    }
    this.trackConfiguration.set(sourceId, wanted);
    for (const [key, entry] of [...this.trackEntries]) {
      if (entry.sourceId !== sourceId || wanted.has(entry.trackIndex)) continue;
      this.releaseTrack(key);
    }
    this.applyTrackGains();
    this.emit();
  }

  /** Bind the audio-only stream of one source+track (from its own WHEP channel). */
  bindTrack(sourceId: string, trackIndex: number, stream: MediaStream): void {
    const key = trackKey(sourceId, trackIndex);
    const existing = this.trackEntries.get(key);
    if (existing?.stream === stream) {
      if (this.context && !existing.gainNode) this.materializeTrack(key);
      this.applyTrackGains();
      this.emit();
      return;
    }
    if (existing) this.releaseTrack(key);
    const selection = this.trackConfiguration.get(sourceId)?.get(trackIndex);
    const entry: TrackEntry = {
      sourceId, trackIndex, gain: selection?.gain ?? 1, muted: selection?.muted ?? false, stream,
    };
    this.trackEntries.set(key, entry);
    if (this.context) this.materializeTrack(key);
    this.applyTrackGains();
    this.emit();
  }

  unbindTrack(sourceId: string, trackIndex: number): void {
    this.releaseTrack(trackKey(sourceId, trackIndex));
    this.emit();
  }

  unbindSourceTracks(sourceId: string): void {
    for (const [key, entry] of [...this.trackEntries]) {
      if (entry.sourceId === sourceId) this.releaseTrack(key);
    }
    this.emit();
  }

  /** Bound audio-only track channels of one source. */
  trackChannelCount(sourceId?: string): number {
    if (sourceId !== undefined) {
      let count = 0;
      for (const entry of this.trackEntries.values()) if (entry.sourceId === sourceId) count += 1;
      return count;
    }
    return this.trackEntries.size;
  }

  setMasterVolume(value: number): void {
    this.masterVolume = clamp(value, 0, 1);
    this.applyMasterGain();
  }

  /**
   * Meter-only mode keeps every analyser alive for the level meter and
   * threshold detection while muting the speaker output, matching the OBS
   * "monitor only" quick action.
   */
  setOutputEnabled(enabled: boolean): void {
    this.outputEnabled = enabled;
    this.applyMasterGain();
  }

  getSnapshot(): DirectAudioSnapshot {
    return this.latest;
  }

  private applyMasterGain(): void {
    if (!this.master || !this.context) return;
    const target = this.outputEnabled ? this.masterVolume : 0;
    this.master.gain.setTargetAtTime(target, this.context.currentTime, .01);
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
      this.master.gain.value = this.outputEnabled ? this.masterVolume : 0;
      this.analyser = this.context.createAnalyser();
      this.analyser.fftSize = 2048;
      this.master.connect(this.analyser).connect(this.context.destination);
    }
    for (const sourceId of this.entries.keys()) this.materialize(sourceId);
    for (const key of this.trackEntries.keys()) this.materializeTrack(key);
    this.applyConfiguration();
    this.applyTrackGains();

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
    for (const key of [...this.trackEntries.keys()]) this.releaseTrack(key);
    for (const merge of this.mergeEntries.values()) {
      merge.gainNode.disconnect();
      merge.analyserNode.disconnect();
    }
    this.mergeEntries.clear();
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

  private mergeFor(sourceId: string): MergeEntry | undefined {
    if (!this.context || !this.master) return undefined;
    const existing = this.mergeEntries.get(sourceId);
    if (existing) return existing;
    const gainNode = this.context.createGain();
    const analyserNode = this.context.createAnalyser();
    analyserNode.fftSize = 1024;
    gainNode.connect(analyserNode).connect(this.master);
    const entry: MergeEntry = { gainNode, analyserNode };
    this.mergeEntries.set(sourceId, entry);
    return entry;
  }

  private materializeTrack(key: string): void {
    const entry = this.trackEntries.get(key);
    if (!entry || !this.context || !entry.stream || entry.gainNode) return;
    if (entry.stream.getAudioTracks().length === 0) return;
    const merge = this.mergeFor(entry.sourceId);
    if (!merge) return;
    const sourceNode = this.context.createMediaStreamSource(entry.stream);
    const gainNode = this.context.createGain();
    const analyserNode = this.context.createAnalyser();
    analyserNode.fftSize = 1024;
    // Track gain feeds both the merged meter and the speaker output.
    sourceNode.connect(analyserNode).connect(gainNode).connect(merge.gainNode);
    entry.sourceNode = sourceNode;
    entry.gainNode = gainNode;
    entry.analyserNode = analyserNode;
  }

  private releaseTrack(key: string): void {
    const entry = this.trackEntries.get(key);
    if (!entry) return;
    entry.sourceNode?.disconnect();
    entry.gainNode?.disconnect();
    entry.analyserNode?.disconnect();
    entry.sourceNode = undefined;
    entry.gainNode = undefined;
    entry.analyserNode = undefined;
    this.trackEntries.delete(key);
    const stillUsed = [...this.trackEntries.values()].some((candidate) => candidate.sourceId === entry.sourceId);
    if (!stillUsed) {
      const merge = this.mergeEntries.get(entry.sourceId);
      if (merge) {
        merge.gainNode.disconnect();
        merge.analyserNode.disconnect();
        this.mergeEntries.delete(entry.sourceId);
      }
    }
  }

  private detach(sourceId: string): void {
    const entry = this.entries.get(sourceId);
    if (entry) {
      this.disconnectEntry(entry);
      entry.element.muted = true;
      this.entries.delete(sourceId);
    }
    for (const [key, track] of [...this.trackEntries]) {
      if (track.sourceId === sourceId) this.releaseTrack(key);
    }
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

  private applyTrackGains(): void {
    const now = this.context?.currentTime ?? 0;
    for (const [key, entry] of this.trackEntries) {
      const selection = this.trackConfiguration.get(entry.sourceId)?.get(entry.trackIndex);
      if (selection) {
        entry.gain = selection.gain;
        entry.muted = selection.muted;
      }
      entry.gainNode?.gain.setTargetAtTime(entry.muted ? 0 : entry.gain, now, 0.01);
    }
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
      for (const entry of this.trackEntries.values()) {
        if (!entry.analyserNode) { entry.rmsDbfs = undefined; entry.peakDbfs = undefined; continue; }
        const trackSamples = new Float32Array(entry.analyserNode.fftSize);
        entry.analyserNode.getFloatTimeDomainData(trackSamples);
        let trackSum = 0; let peak = 0;
        for (const sample of trackSamples) { trackSum += sample * sample; peak = Math.max(peak, Math.abs(sample)); }
        entry.rmsDbfs = amplitudeToDbfs(Math.sqrt(trackSum / trackSamples.length));
        entry.peakDbfs = amplitudeToDbfs(peak);
      }
      for (const merge of this.mergeEntries.values()) {
        const merged = new Float32Array(merge.analyserNode.fftSize);
        merge.analyserNode.getFloatTimeDomainData(merged);
        let mergedSum = 0; let peak = 0;
        for (const sample of merged) { mergedSum += sample * sample; peak = Math.max(peak, Math.abs(sample)); }
        merge.rmsDbfs = amplitudeToDbfs(Math.sqrt(mergedSum / merged.length));
        merge.peakDbfs = amplitudeToDbfs(peak);
      }
      this.emit();
    }, 100);
  }

  private stopMeter(): void {
    if (this.meterTimer !== undefined) window.clearInterval(this.meterTimer);
    this.meterTimer = undefined;
    this.level = 0;
    for (const entry of this.entries.values()) { entry.rmsDbfs = undefined; entry.peakDbfs = undefined; }
    for (const entry of this.trackEntries.values()) { entry.rmsDbfs = undefined; entry.peakDbfs = undefined; }
    for (const merge of this.mergeEntries.values()) { merge.rmsDbfs = undefined; merge.peakDbfs = undefined; }
  }

  private emit(): void {
    const state: DirectAudioState = this.blocked ? 'blocked'
      : !this.enabled ? 'disabled'
        : this.context?.state === 'running' ? 'running' : 'suspended';
    const sourceIds = new Set<string>([...this.entries.keys(), ...this.trackEntries.values()].map((value) =>
      typeof value === 'string' ? value : (value as TrackEntry).sourceId));
    const sources: DirectAudioSourceSnapshot[] = [];
    let inputCount = 0;
    for (const sourceId of sourceIds) {
      const entry = this.entries.get(sourceId);
      const videoTracks = entry?.stream?.getAudioTracks().length ?? 0;
      const independent: DirectAudioTrackMeter[] = [...this.trackEntries.values()]
        .filter((track) => track.sourceId === sourceId)
        .sort((left, right) => left.trackIndex - right.trackIndex)
        .map((track) => ({ sourceId, trackIndex: track.trackIndex, rmsDbfs: track.rmsDbfs ?? null,
          peakDbfs: track.peakDbfs ?? null, gain: track.gain, muted: track.muted,
          live: (track.stream?.getAudioTracks().length ?? 0) > 0 }));
      if (videoTracks > 0 || independent.length > 0) inputCount += 1;
      const merge = this.mergeEntries.get(sourceId);
      sources.push({ sourceId,
        rmsDbfs: entry?.rmsDbfs ?? null, peakDbfs: entry?.peakDbfs ?? null,
        audioTracks: videoTracks + independent.length,
        // An attached element without any stream is "unknown", not "no audio".
        streamBound: Boolean(entry?.stream) || independent.some((track) => track.live),
        merged: independent.length > 0 && merge
          ? { rmsDbfs: merge.rmsDbfs ?? null, peakDbfs: merge.peakDbfs ?? null }
          : null,
        independent });
    }
    const snapshot: DirectAudioSnapshot = { state, inputCount, level: this.level, sources };
    this.latest = snapshot;
    this.onSnapshot(snapshot);
  }
}

export function amplitudeToDbfs(value: number): number {
  if (!Number.isFinite(value) || value <= 0.000001) return -120;
  return Math.max(-120, Math.min(0, 20 * Math.log10(value)));
}

const listeners = new Set<(snapshot: DirectAudioSnapshot) => void>();
let sharedMixer: DirectAudioMixer | undefined;

/**
 * One mixer per page: the audio workspace binds per-track channels into the
 * same graph the preview renders, so meters and speaker output stay coherent.
 */
export function getDirectAudioMixer(): DirectAudioMixer {
  if (!sharedMixer) {
    sharedMixer = new DirectAudioMixer((snapshot) => {
      for (const listener of [...listeners]) listener(snapshot);
      window.dispatchEvent(new CustomEvent('webobs:direct-audio-meters', { detail: snapshot }));
    });
  }
  return sharedMixer;
}

export function subscribeDirectAudio(listener: (snapshot: DirectAudioSnapshot) => void): () => void {
  listeners.add(listener);
  const mixer = getDirectAudioMixer();
  listener(mixer.getSnapshot());
  return () => { listeners.delete(listener); };
}
