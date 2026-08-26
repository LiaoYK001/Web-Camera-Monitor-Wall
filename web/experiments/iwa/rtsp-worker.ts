/// <reference lib="webworker" />

declare class TCPSocket {
  constructor(host: string, port: number);
  opened: Promise<{ readable: ReadableStream<Uint8Array>; writable: WritableStream<Uint8Array> }>;
  close(): Promise<void>;
}

type Start = { type: 'start'; host: string; port: number; path: string; grantHost: string; grantPort: number };
const scope = self as DedicatedWorkerGlobalScope;
const MAX_NETWORK_BUFFER = 2 * 1024 * 1024;
const MAX_RESPONSE = 64 * 1024;
const MAX_ACCESS_UNIT = 4 * 1024 * 1024;
const encoder = new TextEncoder();
let stopped = false;
let activeSocket: TCPSocket | null = null;
let generation = 0;

function concat(parts: Uint8Array[]): Uint8Array {
  const output = new Uint8Array(parts.reduce((sum, part) => sum + part.length, 0));
  let offset = 0;
  for (const part of parts) { output.set(part, offset); offset += part.length; }
  return output;
}

function startCode(nal: Uint8Array): Uint8Array { return concat([Uint8Array.of(0, 0, 0, 1), nal]); }

class BufferedReader {
  private buffer: Uint8Array<ArrayBufferLike> = new Uint8Array(0);
  constructor(private readonly reader: ReadableStreamDefaultReader<Uint8Array>) {}
  private async fill(minimum: number): Promise<void> {
    while (this.buffer.length < minimum) {
      const { value, done } = await this.reader.read();
      if (done || !value) throw new Error('RTSP connection ended');
      if (this.buffer.length + value.length > MAX_NETWORK_BUFFER) throw new Error('RTSP network buffer exceeded');
      this.buffer = concat([this.buffer, value]);
    }
  }
  async response(): Promise<{ status: number; headers: Map<string, string>; body: string }> {
    while (true) {
      const marker = new TextDecoder().decode(this.buffer).indexOf('\r\n\r\n');
      if (marker >= 0) {
        if (marker > MAX_RESPONSE) throw new Error('RTSP response header exceeded');
        const headerLength = marker + 4;
        const head = new TextDecoder('utf-8', { fatal: true }).decode(this.buffer.slice(0, headerLength));
        const lines = head.slice(0, -4).split('\r\n');
        const match = /^RTSP\/1\.0 (\d{3}) /.exec(lines.shift() ?? '');
        if (!match) throw new Error('RTSP status line is invalid');
        const headers = new Map<string, string>();
        for (const line of lines) {
          const split = line.indexOf(':');
          if (split <= 0) throw new Error('RTSP header is invalid');
          const name = line.slice(0, split).trim().toLowerCase();
          if (headers.has(name)) throw new Error('duplicate RTSP header');
          headers.set(name, line.slice(split + 1).trim());
        }
        const contentLength = Number(headers.get('content-length') ?? 0);
        if (!Number.isSafeInteger(contentLength) || contentLength < 0 || contentLength > MAX_RESPONSE)
          throw new Error('RTSP body length is invalid');
        await this.fill(headerLength + contentLength);
        const body = new TextDecoder('utf-8', { fatal: true }).decode(this.buffer.slice(headerLength, headerLength + contentLength));
        this.buffer = this.buffer.slice(headerLength + contentLength);
        return { status: Number(match[1]), headers, body };
      }
      await this.fill(this.buffer.length + 1);
    }
  }
  async packet(): Promise<Uint8Array> {
    await this.fill(4);
    if (this.buffer[0] !== 0x24 || this.buffer[1] !== 0) throw new Error('unexpected RTSP interleaved channel');
    const length = (this.buffer[2] << 8) | this.buffer[3];
    if (length < 12 || length > 65535) throw new Error('RTP packet length is invalid');
    await this.fill(4 + length);
    const packet = this.buffer.slice(4, 4 + length);
    this.buffer = this.buffer.slice(4 + length);
    return packet;
  }
}

function h264Track(sdp: string): { control: string; parameterSets: Uint8Array[] } {
  if (sdp.length > MAX_RESPONSE || /\r(?!\n)|(?<!\r)\n/.test(sdp)) throw new Error('SDP line endings are invalid');
  const sections = sdp.split(/(?=m=)/);
  const video = sections.find((section) => /^m=video\s/m.test(section) && /a=rtpmap:\d+ H264\/90000/i.test(section));
  if (!video) throw new Error('SDP has no H.264 video track');
  const control = /^a=control:([^\r\n]{1,1024})$/m.exec(video)?.[1];
  if (!control || /[\s?#]/.test(control)) throw new Error('SDP control URI is invalid');
  const encoded = /sprop-parameter-sets=([^;\r\n]+)/i.exec(video)?.[1]?.split(',') ?? [];
  const parameterSets = encoded.map((value) => Uint8Array.from(atob(value), (character) => character.charCodeAt(0)));
  if (parameterSets.some((value) => value.length < 4 || value.length > 4096)) throw new Error('SDP parameter set is invalid');
  return { control, parameterSets };
}

class H264Depacketizer {
  private accessUnit: Uint8Array[] = [];
  private fragment: Uint8Array[] | null = null;
  private timestamp = 0;
  push(packet: Uint8Array): { data: Uint8Array; key: boolean; timestamp: number } | null {
    const csrc = packet[0] & 15;
    const extension = (packet[0] & 16) !== 0;
    let offset = 12 + csrc * 4;
    if (extension) {
      if (offset + 4 > packet.length) throw new Error('RTP extension is truncated');
      offset += 4 + (((packet[offset + 2] << 8) | packet[offset + 3]) * 4);
    }
    if (offset >= packet.length) throw new Error('RTP payload is empty');
    const marker = (packet[1] & 128) !== 0;
    this.timestamp = (packet[4] * 0x1000000 + (packet[5] << 16) + (packet[6] << 8) + packet[7]) >>> 0;
    const payload = packet.slice(offset);
    const type = payload[0] & 31;
    if (type >= 1 && type <= 23) this.accessUnit.push(startCode(payload));
    else if (type === 24) {
      let cursor = 1;
      while (cursor + 2 <= payload.length) {
        const size = (payload[cursor] << 8) | payload[cursor + 1]; cursor += 2;
        if (!size || cursor + size > payload.length) throw new Error('STAP-A is invalid');
        this.accessUnit.push(startCode(payload.slice(cursor, cursor + size))); cursor += size;
      }
      if (cursor !== payload.length) throw new Error('STAP-A has trailing data');
    } else if (type === 28) {
      if (payload.length < 3) throw new Error('FU-A is truncated');
      const start = (payload[1] & 128) !== 0; const end = (payload[1] & 64) !== 0;
      if (start) this.fragment = [Uint8Array.of((payload[0] & 0xe0) | (payload[1] & 31)), payload.slice(2)];
      else if (this.fragment) this.fragment.push(payload.slice(2));
      else return null;
      if (end && this.fragment) { this.accessUnit.push(startCode(concat(this.fragment))); this.fragment = null; }
    } else return null;
    const size = this.accessUnit.reduce((sum, value) => sum + value.length, 0);
    if (size > MAX_ACCESS_UNIT) throw new Error('H.264 access unit exceeded');
    if (!marker) return null;
    const data = concat(this.accessUnit); this.accessUnit = [];
    const key = data.some((_byte, index) => index + 4 < data.length && data[index] === 0 && data[index + 1] === 0 &&
      data[index + 2] === 0 && data[index + 3] === 1 && (data[index + 4] & 31) === 5);
    return { data, key, timestamp: Math.round(this.timestamp * 1_000_000 / 90_000) };
  }
}

async function run(message: Start, runGeneration: number): Promise<void> {
  if (message.host !== message.grantHost || message.port !== message.grantPort ||
      !/^[A-Za-z0-9.-]{1,253}$/.test(message.host) || !Number.isInteger(message.port) ||
      message.port < 1 || message.port > 65535 || !/^\/[A-Za-z0-9._~!$&'()*+,;=:@%/-]{1,1023}$/.test(message.path))
    throw new Error('destination is outside the verified Grant');
  const socket = new TCPSocket(message.host, message.port);
  activeSocket = socket;
  let writer: WritableStreamDefaultWriter<Uint8Array> | undefined;
  let decoder: VideoDecoder | undefined;
  let session = '';
  try {
  const opened = await socket.opened;
  writer = opened.writable.getWriter();
  const reader = new BufferedReader(opened.readable.getReader());
  let cseq = 0;
  const request = async (method: string, url: string, headers = '') => {
    await writer!.write(encoder.encode(`${method} ${url} RTSP/1.0\r\nCSeq: ${++cseq}\r\nUser-Agent: WebOBS-IWA-Lab/1\r\n${headers}\r\n`));
    const response = await reader.response();
    if (response.status !== 200) throw new Error(`RTSP ${method} rejected`);
    return response;
  };
  const base = `rtsp://${message.host}:${message.port}${message.path}`;
  await request('OPTIONS', base);
  const description = await request('DESCRIBE', base, 'Accept: application/sdp\r\n');
  const track = h264Track(description.body);
  const trackUrl = new URL(track.control, `${base.endsWith('/') ? base : `${base}/`}`).href;
  if (!trackUrl.startsWith(`rtsp://${message.host}:${message.port}/`)) throw new Error('SDP redirected outside Grant');
  const setup = await request('SETUP', trackUrl, 'Transport: RTP/AVP/TCP;unicast;interleaved=0-1\r\n');
  session = setup.headers.get('session')?.split(';', 1)[0] ?? '';
  if (!session || !/^[A-Za-z0-9._~-]{1,128}$/.test(session)) throw new Error('RTSP session is invalid');
  await request('PLAY', base, `Session: ${session}\r\n`);
  decoder = new VideoDecoder({
    output: (frame) => scope.postMessage({ type: 'frame', frame }, [frame]),
    error: () => { scope.postMessage({ type: 'error', reason: 'decoder_failed' }); stopped = true; },
  });
  decoder.configure({ codec: 'avc1.64001f', optimizeForLatency: true });
  const depacketizer = new H264Depacketizer();
  let keyframeSeen = false;
  while (!stopped && runGeneration === generation) {
    const unit = depacketizer.push(await reader.packet());
    if (!unit || (!keyframeSeen && !unit.key)) continue;
    const data = unit.key && track.parameterSets.length ? concat([...track.parameterSets.map(startCode), unit.data]) : unit.data;
    keyframeSeen ||= unit.key;
    if (decoder.decodeQueueSize > 8) { if (!unit.key) continue; keyframeSeen = false; }
    decoder.decode(new EncodedVideoChunk({ type: unit.key ? 'key' : 'delta', timestamp: unit.timestamp, data }));
  }
  } finally {
    // Interleaved RTP may precede a TEARDOWN response; closing the socket is the
    // authoritative bounded release operation for this single-stream lab.
    if (decoder && decoder.state !== 'closed') decoder.close();
    try { writer?.releaseLock(); } catch { /* already released */ }
    try { await socket.close(); } catch { /* already closed */ }
    if (activeSocket === socket) activeSocket = null;
  }
}

scope.onmessage = (event: MessageEvent<Start | { type: 'stop' }>) => {
  if (event.data.type === 'stop') {
    stopped = true; generation += 1;
    void activeSocket?.close(); activeSocket = null;
    return;
  }
  if (event.data.type !== 'start' || !self.isSecureContext) return;
  stopped = true; generation += 1; void activeSocket?.close();
  stopped = false;
  const runGeneration = generation;
  void run(event.data, runGeneration).catch(() => {
    if (!stopped && runGeneration === generation)
      scope.postMessage({ type: 'error', reason: 'rtsp_session_failed' });
  });
};
