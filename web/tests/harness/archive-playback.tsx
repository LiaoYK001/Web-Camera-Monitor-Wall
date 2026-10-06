import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { downloadVerifiedArchivedRecording, ARCHIVE_PLAYBACK_TIMEOUT_MS, ARCHIVE_PLAYBACK_MAX_BYTES, type ArchivePlaybackTicket } from '../../src/archiveDownload';
import { useArchivedRecording } from '../../src/useArchivedRecording';

const sha256 = 'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad'; // abc
const ticket = (): ArchivePlaybackTicket => ({ segmentId: 'segment', cameraId: 'camera',
  url: 'https://archive.invalid/presigned?synthetic=1', sha256, sizeBytes: 3,
  contentType: 'video/mp4', expiresAt: Math.floor(Date.now() / 1000) + 3600, credentialExposure: 'ephemeral' });
const fixture = (window as any).archiveFixture = {
  timeout: ARCHIVE_PLAYBACK_TIMEOUT_MS, maxBytes: ARCHIVE_PLAYBACK_MAX_BYTES,
  unhandled: 0, state: {} as any, controller: null as AbortController | null,
  releaseTicket: () => {}, releaseHeaders: () => {}, releaseDigest: () => {},
  start(options: { scenario?: string; patch?: Partial<ArchivePlaybackTicket>; preAbort?: boolean } = {}) {
    const scenario = options.scenario || 'good';
    const state = fixture.state = { tickets: 0, fetches: 0, reads: 0, cancels: 0, aborted: false, settled: '', error: '', blobSize: 0, blobText: '', init: null as any };
    const controller = fixture.controller = new AbortController();
    if (options.preAbort) controller.abort();
    const value = { ...ticket(), ...options.patch };
    let response: Response | undefined;
    const makeResponse = () => {
      let part = 0;
      const chunks = scenario === 'overflow' ? ['abc', 'x', 'unread']
        : scenario === 'underflow' ? ['ab'] : scenario === 'hash' ? ['abd'] : ['a', 'bc'];
      const stream = new ReadableStream<Uint8Array>({
        pull(target) {
          state.reads++;
          if (scenario === 'hangBody') return new Promise(() => undefined);
          if (part < chunks.length) target.enqueue(new TextEncoder().encode(chunks[part++]));
          else target.close();
        },
        cancel() { state.cancels++; if (scenario === 'hangBody') return new Promise(() => undefined); },
      }, { highWaterMark: 0 });
      response = new Response(scenario === 'missingStream' ? null : stream, {
        status: scenario === 'httpError' ? 403 : 200,
        headers: scenario === 'headerOverflow' ? { 'Content-Length': '4000' } : {},
      });
      // A regression to arrayBuffer() must fail, even with small fixtures.
      response.arrayBuffer = () => { throw new Error('Unbounded body API used'); };
      return response;
    };
    fixture.isLocked = () => response?.body?.locked ?? false;
    window.fetch = async (_input, init) => {
      state.fetches++;
      state.init = { ...init, signal: Boolean(init?.signal) };
      init?.signal?.addEventListener('abort', () => { state.aborted = true; });
      if (scenario === 'hangHeaders') return await new Promise<Response>(resolve => { fixture.releaseHeaders = () => resolve(makeResponse()); });
      return makeResponse();
    };
    if (scenario === 'hangHash') crypto.subtle.digest = (() => new Promise<ArrayBuffer>(resolve => {
      fixture.releaseDigest = () => resolve(Uint8Array.from(sha256.match(/../g)!, hex => parseInt(hex, 16)).buffer);
    })) as typeof crypto.subtle.digest;
    void downloadVerifiedArchivedRecording('segment', 'camera', async signal => {
      state.tickets++;
      signal.addEventListener('abort', () => { state.aborted = true; });
      if (scenario === 'hangTicket') await new Promise<void>(resolve => { fixture.releaseTicket = resolve; });
      return value;
    }, controller.signal).then(async blob => {
      state.blobSize = blob.size; state.blobText = await blob.text(); state.settled = 'success';
    }, error => { state.settled = error?.name || 'error'; state.error = error?.message || ''; });
  },
};
addEventListener('unhandledrejection', () => fixture.unhandled++);

const requests: Array<{ segmentId: string; cameraId: string; signal: AbortSignal; resolve: (blob: Blob) => void; reject: (reason: Error) => void }> = [];
const created: string[] = [], revoked: string[] = [];
const originalCreate = URL.createObjectURL.bind(URL), originalRevoke = URL.revokeObjectURL.bind(URL);
URL.createObjectURL = blob => { const url = originalCreate(blob); created.push(url); return url; };
URL.revokeObjectURL = url => { revoked.push(url); originalRevoke(url); };
const deferredDownload = (segmentId: string, cameraId: string, signal: AbortSignal) => new Promise<Blob>((resolve, reject) => requests.push({ segmentId, cameraId, signal, resolve, reject }));
const hookFixture = (window as any).archiveHook = { requests, created, revoked, current: null as any,
  resolve(index: number) { requests[index].resolve(new Blob(['abc'], { type: 'video/mp4' })); },
  reject(index: number) { requests[index].reject(new Error('obsolete failure')); },
  unmount: () => {},
};
function HookFixture() {
  const archive = useArchivedRecording(deferredDownload);
  hookFixture.current = archive;
  return <section><output data-testid="loading">{archive.loading?.segmentId || ''}</output>
    <output data-testid="preview">{archive.preview?.segmentId || ''}</output><output data-testid="error">{archive.error}</output></section>;
}
const root = createRoot(document.getElementById('root')!);
hookFixture.unmount = () => root.unmount();
root.render(<StrictMode><HookFixture /></StrictMode>);
