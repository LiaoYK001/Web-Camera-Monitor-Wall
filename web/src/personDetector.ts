import * as ort from 'onnxruntime-web/webgpu';

export interface PersonModelManifest {
  schemaVersion: 1;
  id: string;
  version: string;
  file: string;
  sha256: string;
  license: string;
  source: string;
  sourceCommit: string;
  input: { width: number; height: number; layout: 'NHWC'; type: 'uint8' };
  class: 'person';
}

export interface PersonBox { x: number; y: number; width: number; height: number; confidence: number; }

const HEX = /^[0-9a-f]{64}$/i;
const clamp = (value: number, min: number, max: number) => Math.min(max, Math.max(min, value));
const MODEL_SIZE = 300;
const APPROVED_MODEL = Object.freeze({
  id: 'ssd-mobilenet-v1-12-person',
  version: 'onnx-model-zoo-4c46cd00',
  file: '/models/ssd_mobilenet_v1_12.onnx',
  sha256: 'b8fba5e404077d4048d27fcd1667e85e27e192eb9bf51e696c46a3acd7d21058',
  sourceCommit: '4c46cd00fbdb7cd30b6c1c17ab54f2e1f4f7b177',
  source: 'https://media.githubusercontent.com/media/onnx/models/4c46cd00fbdb7cd30b6c1c17ab54f2e1f4f7b177/validated/vision/object_detection_segmentation/ssd-mobilenetv1/model/ssd_mobilenet_v1_12.onnx',
});

interface LetterboxTransform { scale: number; offsetX: number; offsetY: number; width: number; height: number; }

function letterboxTransform(width: number, height: number): LetterboxTransform {
  if (!Number.isInteger(width) || !Number.isInteger(height) || width < 1 || height < 1)
    throw new Error('frame_dimensions_invalid');
  const scale = Math.min(MODEL_SIZE / width, MODEL_SIZE / height);
  const scaledWidth = Math.max(1, Math.round(width * scale));
  const scaledHeight = Math.max(1, Math.round(height * scale));
  return { scale, offsetX: (MODEL_SIZE - scaledWidth) / 2, offsetY: (MODEL_SIZE - scaledHeight) / 2,
    width: scaledWidth, height: scaledHeight };
}

export async function loadVerifiedPersonModel(manifestUrl = '/models/person-model.manifest.json'):
  Promise<{ manifest: PersonModelManifest; bytes: ArrayBuffer }> {
  const manifestResponse = await fetch(manifestUrl, { cache: 'no-store', credentials: 'same-origin' });
  if (!manifestResponse.ok) throw new Error('model_manifest_unavailable');
  const manifest = await manifestResponse.json() as PersonModelManifest;
  if (manifest.schemaVersion !== 1 || manifest.class !== 'person' || manifest.id !== APPROVED_MODEL.id ||
    manifest.version !== APPROVED_MODEL.version || manifest.file !== APPROVED_MODEL.file ||
    manifest.sourceCommit !== APPROVED_MODEL.sourceCommit || manifest.source !== APPROVED_MODEL.source ||
    typeof manifest.sha256 !== 'string' || manifest.sha256.toLowerCase() !== APPROVED_MODEL.sha256 || manifest.input?.width !== 300 ||
    manifest.input?.height !== 300 || manifest.input?.layout !== 'NHWC' || manifest.input?.type !== 'uint8' ||
    !HEX.test(manifest.sha256) || manifest.license !== 'MIT') throw new Error('model_manifest_invalid');
  const modelCache = typeof caches === 'undefined' ? undefined : await caches.open('webobs-model-v1');
  let response: Response;
  try {
    response = await fetch(manifest.file, { cache: 'no-store', credentials: 'same-origin' });
    if (!response.ok) throw new Error('model_unavailable');
  } catch (error) {
    const cached = await modelCache?.match(manifest.file);
    if (!cached) throw error;
    response = cached;
  }
  const bytes = await response.arrayBuffer();
  const digest = [...new Uint8Array(await crypto.subtle.digest('SHA-256', bytes))]
    .map((value) => value.toString(16).padStart(2, '0')).join('');
  if (digest.toLowerCase() !== manifest.sha256.toLowerCase()) {
    await modelCache?.delete(manifest.file);
    throw new Error('model_integrity_failed');
  }
  if (modelCache) await modelCache.put(manifest.file, new Response(bytes, { headers: { 'Content-Type': 'application/octet-stream' } }));
  return { manifest, bytes };
}

function inputTensor(rgba: Uint8ClampedArray, width: number, height: number): { tensor: ort.Tensor; transform: LetterboxTransform } {
  const transform = letterboxTransform(width, height);
  const data = new Uint8Array(MODEL_SIZE * MODEL_SIZE * 3);
  data.fill(114);
  for (let y = 0; y < transform.height; y += 1) for (let x = 0; x < transform.width; x += 1) {
    const targetX = Math.round(transform.offsetX) + x;
    const targetY = Math.round(transform.offsetY) + y;
    const sourceX = Math.min(width - 1, Math.floor(x * width / transform.width));
    const sourceY = Math.min(height - 1, Math.floor(y * height / transform.height));
    const source = (sourceY * width + sourceX) * 4;
    const target = (targetY * MODEL_SIZE + targetX) * 3;
    data[target] = rgba[source]; data[target + 1] = rgba[source + 1]; data[target + 2] = rgba[source + 2];
  }
  return { tensor: new ort.Tensor('uint8', data, [1, MODEL_SIZE, MODEL_SIZE, 3]), transform };
}

function values(value: ort.Tensor | undefined): ArrayLike<number> {
  return value?.data as ArrayLike<number> ?? [];
}

function outputName(names: readonly string[], ...parts: string[]): string | undefined {
  return names.find((name) => {
    const normalized = name.toLowerCase().replaceAll('-', '_');
    return parts.some((part) => normalized.includes(part));
  });
}

export function decodePersonOutputs(outputs: Record<string, ort.Tensor>, names: readonly string[], width: number, height: number, threshold = .6, maxBoxes = 16): PersonBox[] {
  const countName = outputName(names, 'num_detections', 'detection_count', 'count');
  const boxesName = outputName(names, 'detection_boxes', 'boxes');
  const scoresName = outputName(names, 'detection_scores', 'scores');
  const classesName = outputName(names, 'detection_classes', 'classes');
  if (!countName || !boxesName || !scoresName || !classesName) return [];
  const transform = letterboxTransform(width, height);
  const arrays = [countName, boxesName, scoresName, classesName].map((name) => values(outputs[name]));
  const count = Math.min(Number(arrays[0][0] ?? 0), 100);
  const limit = Number.isInteger(maxBoxes) ? Math.min(16, Math.max(1, maxBoxes)) : 16;
  const boxes: PersonBox[] = [];
  for (let index = 0; index < count; index += 1) {
    const score = Number(arrays[2][index] ?? 0); const label = Number(arrays[3][index] ?? 0);
    if (label !== 1 || score < threshold) continue;
    const top = clamp(Number(arrays[1][index * 4] ?? 0), 0, 1) * MODEL_SIZE;
    const left = clamp(Number(arrays[1][index * 4 + 1] ?? 0), 0, 1) * MODEL_SIZE;
    const bottom = clamp(Number(arrays[1][index * 4 + 2] ?? 0), 0, 1) * MODEL_SIZE;
    const right = clamp(Number(arrays[1][index * 4 + 3] ?? 0), 0, 1) * MODEL_SIZE;
    const sourceLeft = clamp((left - transform.offsetX) / transform.width, 0, 1);
    const sourceTop = clamp((top - transform.offsetY) / transform.height, 0, 1);
    const sourceRight = clamp((right - transform.offsetX) / transform.width, sourceLeft, 1);
    const sourceBottom = clamp((bottom - transform.offsetY) / transform.height, sourceTop, 1);
    boxes.push({ x: sourceLeft, y: sourceTop, width: sourceRight - sourceLeft, height: sourceBottom - sourceTop, confidence: clamp(score, 0, 1) });
    if (boxes.length >= limit) break;
  }
  return boxes;
}

export async function createPersonSession(bytes: ArrayBuffer): Promise<{ session: ort.InferenceSession; execution: 'browser-webgpu' | 'browser-wasm' }> {
  const hasGpu = typeof navigator !== 'undefined' && Boolean((navigator as Navigator & { gpu?: unknown }).gpu);
  if (hasGpu) {
    try {
      return { session: await ort.InferenceSession.create(bytes, { executionProviders: ['webgpu'] }), execution: 'browser-webgpu' };
    } catch {
      // A present WebGPU object does not guarantee that the model or adapter
      // can initialize. Continue with the bounded single-thread WASM path.
    }
  }
  ort.env.wasm.numThreads = 1;
  ort.env.wasm.proxy = false;
  return { session: await ort.InferenceSession.create(bytes, { executionProviders: ['wasm'] }), execution: 'browser-wasm' };
}

export async function inferPersonsWithSession(session: ort.InferenceSession, rgba: Uint8ClampedArray, width: number, height: number,
  threshold = .6, maxBoxes = 16): Promise<PersonBox[]> {
  if (!Number.isFinite(threshold) || threshold < .05 || threshold > 1 ||
    !Number.isInteger(maxBoxes) || maxBoxes < 1 || maxBoxes > 16) throw new Error('person_policy_invalid');
  const inputName = session.inputNames[0];
  if (!inputName) throw new Error('model_input_missing');
  const result = await session.run({ [inputName]: inputTensor(rgba, width, height).tensor });
  return decodePersonOutputs(result, session.outputNames, width, height, threshold, maxBoxes);
}

export async function inferPersons(bytes: ArrayBuffer, rgba: Uint8ClampedArray, width: number, height: number,
  threshold = .6, maxBoxes = 16): Promise<{ boxes: PersonBox[]; execution: 'browser-webgpu' | 'browser-wasm' }> {
  const created = await createPersonSession(bytes);
  return { boxes: await inferPersonsWithSession(created.session, rgba, width, height, threshold, maxBoxes), execution: created.execution };
}
