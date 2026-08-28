import type { ProgramConnection } from './whep';

export type DecoderKind = 'HW' | 'SW' | 'Unknown';
export interface MediaTelemetry { fps: number | null; bytesPerSecond: number | null; codec: string; decoder: DecoderKind; implementation?: string }
export const unavailableTelemetry = (): MediaTelemetry => ({ fps: null, bytesPerSecond: null, codec: 'Unknown', decoder: 'Unknown' });

interface PreviousSample { at: number; frames: number; bytes: number }

function boundedImplementation(value: unknown): string | undefined {
  if (typeof value !== 'string') return undefined;
  return value.replace(/[^\w .()+/-]/g, '').trim().slice(0, 48) || undefined;
}

function decoderKind(implementation: string | undefined): DecoderKind {
  if (!implementation) return 'Unknown';
  if (/software|libvpx|libdav1d|ffmpeg|openh264|sw decoder/i.test(implementation)) return 'SW';
  if (/hardware|d3d|vaapi|video ?toolbox|mediacodec|nvdec|qsv/i.test(implementation)) return 'HW';
  return 'Unknown';
}

export async function sampleConnectionTelemetry(connection: ProgramConnection, previous?: PreviousSample): Promise<{
  telemetry: MediaTelemetry; previous?: PreviousSample;
}> {
  const reports = await connection.getStats?.();
  if (!reports) return { telemetry: unavailableTelemetry() };
  let inbound: RTCInboundRtpStreamStats | undefined;
  reports.forEach((report) => {
    if (report.type === 'inbound-rtp' && report.kind === 'video' && !report.isRemote) inbound = report as RTCInboundRtpStreamStats;
  });
  if (!inbound) return { telemetry: unavailableTelemetry() };
  const codecReport = inbound.codecId ? reports.get(inbound.codecId) as { mimeType?: string } | undefined : undefined;
  const implementation = boundedImplementation((inbound as RTCInboundRtpStreamStats & { decoderImplementation?: string }).decoderImplementation);
  const at = performance.now();
  const frames = inbound.framesRendered ?? inbound.framesDecoded ?? 0;
  const bytes = inbound.bytesReceived ?? 0;
  const seconds = previous ? Math.max((at - previous.at) / 1000, .001) : 0;
  return {
    telemetry: {
      fps: previous ? Math.max(0, (frames - previous.frames) / seconds) : null,
      bytesPerSecond: previous ? Math.max(0, (bytes - previous.bytes) / seconds) : null,
      codec: codecReport?.mimeType?.split('/', 2)[1]?.toUpperCase() ?? 'Unknown',
      decoder: decoderKind(implementation), implementation,
    },
    previous: { at, frames, bytes },
  };
}

export function sampleElementTelemetry(
  video: HTMLVideoElement, connection: ProgramConnection, previous?: PreviousSample,
): { telemetry: MediaTelemetry; previous: PreviousSample } {
  const quality = video.getVideoPlaybackQuality?.();
  const frames = quality?.totalVideoFrames ?? 0;
  const bytes = connection.getReceivedBytes?.() ?? 0;
  const at = performance.now();
  const seconds = previous ? Math.max((at - previous.at) / 1000, .001) : 0;
  return {
    telemetry: {
      fps: previous ? Math.max(0, (frames - previous.frames) / seconds) : null,
      bytesPerSecond: connection.getReceivedBytes?.() === null || !previous ? null : Math.max(0, (bytes - previous.bytes) / seconds),
      codec: connection.getCodec?.() ?? 'Unknown', decoder: 'Unknown',
    },
    previous: { at, frames, bytes },
  };
}

export function formatTelemetry(telemetry: MediaTelemetry, fields: Array<'fps' | 'bitrate' | 'codec' | 'decoder'>): string {
  const values: Record<string, string> = {
    fps: telemetry.fps === null ? 'FPS —' : `${telemetry.fps.toFixed(telemetry.fps < 10 ? 1 : 0)} fps`,
    bitrate: telemetry.bytesPerSecond === null ? 'Speed —' : `${(telemetry.bytesPerSecond / 1024).toFixed(telemetry.bytesPerSecond < 10240 ? 1 : 0)} KB/s`,
    codec: telemetry.codec || 'Unknown',
    decoder: telemetry.implementation ? `${telemetry.decoder} ${telemetry.implementation}` : telemetry.decoder,
  };
  return fields.map((field) => values[field]).join(' · ');
}

export function countRenderedFrames(video: HTMLVideoElement, onFrame: () => void): () => void {
  let stopped = false;
  let callbackId = 0;
  const next = () => {
    if (stopped || !video.requestVideoFrameCallback) return;
    callbackId = video.requestVideoFrameCallback(() => { onFrame(); next(); });
  };
  next();
  return () => { stopped = true; if (callbackId && video.cancelVideoFrameCallback) video.cancelVideoFrameCallback(callbackId); };
}
