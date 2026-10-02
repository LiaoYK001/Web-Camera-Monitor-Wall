import { useCallback, useEffect, useRef, useState } from 'react';
import { getDirectAudioMixer, subscribeDirectAudio, type DirectAudioSnapshot, type DirectAudioSourceSnapshot } from './directAudioMixer';
import { isPageVisible, subscribePageVisibility } from './pageVisibility';

const empty: DirectAudioSnapshot = { state: 'disabled', inputCount: 0, level: 0, sources: [] };
const identity = (snapshot: DirectAudioSnapshot) => snapshot;
const identical = <T,>(left: T, right: T) => left === right;

function useSelectedAudio<T>(select: (snapshot: DirectAudioSnapshot) => T, equal: (left: T, right: T) => boolean, enabled: boolean) {
  const [value, setValue] = useState(() => select(enabled ? getDirectAudioMixer().getSnapshot() : empty));
  const latest = useRef(value);
  useEffect(() => {
    const receive = (snapshot: DirectAudioSnapshot) => {
      const next = select(snapshot);
      // Compare before scheduling React work, rather than bailing out inside a state updater.
      if (equal(latest.current, next)) return;
      latest.current = next;
      setValue(next);
    };
    if (!enabled) { receive(empty); return; }
    return subscribeDirectAudio(receive);
  }, [select, equal, enabled]);
  return value;
}

function sameTopology(left: DirectAudioSnapshot, right: DirectAudioSnapshot) {
  return left.state === right.state && left.inputCount === right.inputCount && left.sources.length === right.sources.length &&
    left.sources.every((source, index) => {
      const other = right.sources[index];
      return source.sourceId === other.sourceId && source.audioTracks === other.audioTracks && source.streamBound === other.streamBound &&
        source.independent.length === other.independent.length && source.independent.every((track, trackIndex) => {
          const otherTrack = other.independent[trackIndex];
          return track.trackIndex === otherTrack.trackIndex && track.gain === otherTrack.gain && track.muted === otherTrack.muted && track.live === otherTrack.live;
        });
    });
}

/** Runtime/track changes belong to the wall; 10 Hz level samples belong to its meters. */
export function useDirectAudioTopology(enabled = true) {
  return useSelectedAudio(identity, sameTopology, enabled);
}

function useVisibleMeters(enabled: boolean) {
  const [visible, setVisible] = useState(isPageVisible);
  useEffect(() => subscribePageVisibility(() => setVisible(isPageVisible())), []);
  return enabled && visible;
}

export function useDirectAudioMeters(enabled = true) {
  return useSelectedAudio(identity, identical, useVisibleMeters(enabled));
}

function sameSourceLevel(left: DirectAudioSourceSnapshot | undefined, right: DirectAudioSourceSnapshot | undefined) {
  return left === right || (left !== undefined && right !== undefined && left.sourceId === right.sourceId && left.rmsDbfs === right.rmsDbfs &&
    left.peakDbfs === right.peakDbfs && left.audioTracks === right.audioTracks);
}

export function useDirectAudioSourceLevel(sourceId: string, enabled: boolean) {
  const select = useCallback((snapshot: DirectAudioSnapshot) => snapshot.sources.find((source) => source.sourceId === sourceId), [sourceId]);
  return useSelectedAudio(select, sameSourceLevel, useVisibleMeters(enabled));
}

/** Threshold checks need fresh samples without re-rendering the video tile. */
export function useDirectAudioPeak(sourceId: string, enabled: boolean) {
  const peak = useRef<number | null>(null);
  useEffect(() => {
    peak.current = null;
    if (!enabled) return;
    return subscribeDirectAudio((snapshot) => { peak.current = snapshot.sources.find((source) => source.sourceId === sourceId)?.peakDbfs ?? null; });
  }, [sourceId, enabled]);
  return peak;
}
