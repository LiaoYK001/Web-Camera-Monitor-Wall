/** Canvas bridge for the non-production Chromium IWA RTSP experiment. */

export interface VerifiedSyntheticRtspGrant {
  host: string;
  port: number;
  path: string;
  expiresAt: number;
  syntheticLabOnly: true;
}

export interface IwaLabSession {
  close(): void;
}

export function startIwaLabSession(
  workerUrl: URL,
  canvas: HTMLCanvasElement,
  grant: VerifiedSyntheticRtspGrant,
  onState: (state: 'connecting' | 'live' | 'error' | 'closed') => void,
): IwaLabSession {
  if (!window.isSecureContext || grant.syntheticLabOnly !== true || grant.expiresAt <= Date.now())
    throw new Error('a current verified synthetic-lab Grant is required');
  const worker = new Worker(workerUrl, { type: 'module', name: 'webobs-iwa-rtsp-lab' });
  const context = canvas.getContext('2d', { alpha: false });
  if (!context) { worker.terminate(); throw new Error('2D canvas is unavailable'); }
  let closed = false;
  onState('connecting');
  worker.onmessage = (event: MessageEvent<{ type: string; frame?: VideoFrame }>) => {
    if (closed) { event.data.frame?.close(); return; }
    if (event.data.type === 'error') { onState('error'); return; }
    const frame = event.data.frame;
    if (event.data.type !== 'frame' || !frame) return;
    canvas.width = frame.displayWidth;
    canvas.height = frame.displayHeight;
    context.drawImage(frame, 0, 0, canvas.width, canvas.height);
    frame.close();
    onState('live');
  };
  worker.postMessage({
    type: 'start', host: grant.host, port: grant.port, path: grant.path,
    grantHost: grant.host, grantPort: grant.port,
  });
  return {
    close() {
      if (closed) return;
      closed = true;
      worker.postMessage({ type: 'stop' });
      worker.terminate();
      context.clearRect(0, 0, canvas.width, canvas.height);
      onState('closed');
    },
  };
}
