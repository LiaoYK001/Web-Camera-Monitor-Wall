import { withRequestTimeout } from './requestTimeout';

/** Conservative in-memory policy, NOT a reference-device/WebView qualification. */
export const ARCHIVE_PLAYBACK_MAX_BYTES = 32 * 1024 * 1024;
/** One deadline for ticket acquisition, response headers/body and complete SHA-256. */
export const ARCHIVE_PLAYBACK_TIMEOUT_MS = 60_000;

export interface ArchivePlaybackTicket {
  segmentId: string;
  cameraId: string;
  url: string;
  sha256: string;
  sizeBytes: number;
  contentType: string;
  expiresAt: number;
  credentialExposure: 'ephemeral';
}

function checkActive(signal: AbortSignal, deadline: number) {
  if (signal.aborted) throw signal.reason ?? new DOMException('归档下载已取消', 'AbortError');
  if (performance.now() >= deadline) throw new DOMException('归档下载超时', 'TimeoutError');
}

function validateTicket(ticket: ArchivePlaybackTicket, segmentId: string, cameraId: string): URL {
  let endpoint: URL;
  try { endpoint = new URL(ticket.url); }
  catch { throw new Error('归档回放票据无效或已过期'); }
  if (endpoint.protocol !== 'https:' || endpoint.username || endpoint.password || endpoint.hash
      || ticket.segmentId !== segmentId || ticket.cameraId !== cameraId
      || ticket.credentialExposure !== 'ephemeral' || !Number.isFinite(ticket.expiresAt)
      || ticket.expiresAt * 1000 <= Date.now() || !/^[0-9a-f]{64}$/.test(ticket.sha256)
      || !Number.isSafeInteger(ticket.sizeBytes) || ticket.sizeBytes < 1) {
    throw new Error('归档回放票据无效或已过期');
  }
  if (ticket.sizeBytes > ARCHIVE_PLAYBACK_MAX_BYTES) {
    throw new Error('归档片段超过浏览器回放的保守上限（32 MiB），请使用其他受控回放方式');
  }
  return endpoint;
}

/** Never await cancellation: a broken stream's cancel() can itself hang. */
function cancelBody(body: ReadableStream<Uint8Array> | null) {
  if (body && !body.locked) void body.cancel().catch(() => undefined);
}

async function readBoundedBody(response: Response, size: number, signal: AbortSignal, deadline: number): Promise<Uint8Array<ArrayBuffer>> {
  if (!response.body) throw new Error('归档下载不支持流式读取');
  const reader = response.body.getReader();
  let bytes: Uint8Array<ArrayBuffer> | null = null;
  let completed = false, cancelled = false, received = 0;
  const cancel = () => {
    // Drop our buffer immediately even if an adversarial reader ignores cancellation.
    bytes = null;
    if (!cancelled) { cancelled = true; void reader.cancel().catch(() => undefined); }
  };
  signal.addEventListener('abort', cancel, { once: true });
  try {
    checkActive(signal, deadline);
    bytes = new Uint8Array(size);
    while (true) {
      checkActive(signal, deadline);
      const { done, value } = await reader.read();
      checkActive(signal, deadline);
      if (done) break;
      // Compare BEFORE copying; do not retain a list of arbitrarily sized chunks.
      if (value.byteLength > size - received || value.byteLength > ARCHIVE_PLAYBACK_MAX_BYTES - received) {
        throw new Error('归档录像超过票据大小或浏览器回放上限');
      }
      bytes!.set(value, received);
      received += value.byteLength;
    }
    if (received !== size) throw new Error('归档录像大小校验失败');
    completed = true;
    return bytes!;
  } finally {
    signal.removeEventListener('abort', cancel);
    if (!completed) cancel();
    reader.releaseLock();
  }
}

/** Ticket is obtained only from the product gate; no product credentials reach its URL. */
export function downloadVerifiedArchivedRecording(
  segmentId: string,
  cameraId: string,
  requestTicket: (signal: AbortSignal) => Promise<ArchivePlaybackTicket>,
  parent?: AbortSignal,
): Promise<Blob> {
  const deadline = performance.now() + ARCHIVE_PLAYBACK_TIMEOUT_MS;
  return withRequestTimeout(ARCHIVE_PLAYBACK_TIMEOUT_MS, async signal => {
    const ticket = await requestTicket(signal);
    checkActive(signal, deadline);
    const endpoint = validateTicket(ticket, segmentId, cameraId);
    const response = await fetch(endpoint, {
      method: 'GET', cache: 'no-store', credentials: 'omit', redirect: 'error',
      referrer: '', referrerPolicy: 'no-referrer', signal,
    });
    try {
      checkActive(signal, deadline);
      if (!response.ok) throw new Error('无法读取归档录像');
      // A header is only an early rejection optimization, never the byte-count authority.
      const length = response.headers.get('Content-Length');
      if (length !== null && (!/^\d+$/.test(length) || Number(length) !== ticket.sizeBytes)) {
        throw new Error('归档录像大小校验失败');
      }
      const bytes = await readBoundedBody(response, ticket.sizeBytes, signal, deadline);
      checkActive(signal, deadline);
      const digest = await crypto.subtle.digest('SHA-256', bytes);
      checkActive(signal, deadline);
      const computed = [...new Uint8Array(digest)].map(value => value.toString(16).padStart(2, '0')).join('');
      if (computed !== ticket.sha256) throw new Error('归档录像 SHA-256 校验失败');
      return new Blob([bytes], { type: ticket.contentType === 'video/mp4' ? 'video/mp4' : 'application/octet-stream' });
    } finally {
      // Also closes late fetch responses arriving after their owner/deadline has gone.
      cancelBody(response.body);
    }
  }, parent);
}
