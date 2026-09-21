/// <reference lib="webworker" />

import { createPersonSession, inferPersonsWithSession, loadVerifiedPersonModel } from './personDetector';

const scope = self as DedicatedWorkerGlobalScope;
let model: ArrayBuffer | undefined;
let manifest: Awaited<ReturnType<typeof loadVerifiedPersonModel>>['manifest'] | undefined;
let loading: Promise<ArrayBuffer> | undefined;
let session: Awaited<ReturnType<typeof createPersonSession>> | undefined;

async function getModel(): Promise<ArrayBuffer> {
  if (model) return model;
  loading ??= loadVerifiedPersonModel().then((value) => { model = value.bytes; manifest = value.manifest; return value.bytes; });
  return loading;
}

scope.addEventListener('message', (event: MessageEvent<{ type: 'frame'; rgba: ArrayBuffer; width: number; height: number; threshold: number; maxBoxes: number } | { type: 'reset' }>) => {
  const message = event.data;
  if (message.type === 'reset') { model = undefined; manifest = undefined; loading = undefined; session = undefined; return; }
  void getModel().then(async (bytes) => {
    session ??= await createPersonSession(bytes);
    return { boxes: await inferPersonsWithSession(session.session, new Uint8ClampedArray(message.rgba), message.width, message.height, message.threshold, message.maxBoxes), execution: session.execution,
      model: { id: manifest?.id ?? '', version: manifest?.version ?? '', sha256: manifest?.sha256 ?? '' } };
  }).then((result) => scope.postMessage({ type: 'result', ...result }))
    .catch((error: unknown) => scope.postMessage({ type: 'error', message: error instanceof Error ? error.message : 'person_detector_failed' }));
});

export {};
