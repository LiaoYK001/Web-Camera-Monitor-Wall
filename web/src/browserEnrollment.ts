import sodium from 'libsodium-wrappers';
import { clearPrivateRuntimeState, loadBrowserIdentity, saveBrowserIdentity, type BrowserGrantPayload, type StoredBrowserIdentity } from './localRuntime';

const textEncoder = new TextEncoder();

function head(major: number, value: number): Uint8Array {
  if (!Number.isSafeInteger(value) || value < 0) throw new Error('CBOR length is invalid');
  if (value < 24) return Uint8Array.of((major << 5) | value);
  if (value < 256) return Uint8Array.of((major << 5) | 24, value);
  if (value < 65536) return Uint8Array.of((major << 5) | 25, value >> 8, value & 255);
  const result = new Uint8Array(5);
  result[0] = (major << 5) | 26;
  new DataView(result.buffer).setUint32(1, value);
  return result;
}

function concat(parts: Uint8Array[]): Uint8Array {
  const result = new Uint8Array(parts.reduce((sum, part) => sum + part.length, 0));
  let offset = 0;
  for (const part of parts) { result.set(part, offset); offset += part.length; }
  return result;
}

function cbor(value: string | Uint8Array | Record<string, string | Uint8Array>): Uint8Array {
  if (typeof value === 'string') {
    const encoded = textEncoder.encode(value);
    return concat([head(3, encoded.length), encoded]);
  }
  if (value instanceof Uint8Array) return concat([head(2, value.length), value]);
  const entries = Object.entries(value).map(([key, item]) => [cbor(key), cbor(item)] as const)
    .sort(([left], [right]) => {
      if (left.length !== right.length) return left.length - right.length;
      for (let index = 0; index < left.length; index += 1)
        if (left[index] !== right[index]) return left[index] - right[index];
      return 0;
    });
  return concat([head(5, entries.length), ...entries.flatMap(([key, item]) => [key, item])]);
}

function b64(value: Uint8Array): string {
  return sodium.to_base64(value, sodium.base64_variants.URLSAFE_NO_PADDING);
}

function bytes(value: string): Uint8Array {
  return sodium.from_base64(value, sodium.base64_variants.URLSAFE_NO_PADDING);
}

function decodeCbor(input: Uint8Array): unknown {
  if (input.length > 1024 * 1024) throw new Error('Grant CBOR is too large');
  let offset = 0;
  const readLength = (additional: number): number => {
    if (additional < 24) return additional;
    const size = additional === 24 ? 1 : additional === 25 ? 2 : additional === 26 ? 4 : 0;
    if (!size || offset + size > input.length) throw new Error('Grant CBOR length is invalid');
    let value = 0;
    for (let index = 0; index < size; index += 1) value = value * 256 + input[offset++];
    return value;
  };
  const read = (): unknown => {
    if (offset >= input.length) throw new Error('Grant CBOR is truncated');
    const initial = input[offset++];
    const major = initial >> 5;
    const additional = initial & 31;
    if (major === 7) {
      if (additional === 20) return false;
      if (additional === 21) return true;
      if (additional === 22) return null;
      throw new Error('Grant CBOR simple value is unsupported');
    }
    const length = readLength(additional);
    if (length > 1024 * 1024 || ((major === 4 || major === 5) && length > 256))
      throw new Error('Grant CBOR collection is too large');
    if (major === 0) return length;
    if ((major === 2 || major === 3) && offset + length <= input.length) {
      const value = input.slice(offset, offset + length); offset += length;
      return major === 2 ? value : new TextDecoder('utf-8', { fatal: true }).decode(value);
    }
    if (major === 4) return Array.from({ length }, () => read());
    if (major === 5) {
      const value: Record<string, unknown> = {};
      for (let index = 0; index < length; index += 1) {
        const key = read();
        if (typeof key !== 'string' || Object.hasOwn(value, key)) throw new Error('Grant CBOR map is invalid');
        value[key] = read();
      }
      return value;
    }
    throw new Error('Grant CBOR type is unsupported');
  };
  const value = read();
  if (offset !== input.length) throw new Error('Grant CBOR has trailing data');
  return value;
}

function browserGrant(value: unknown): BrowserGrantPayload {
  const candidate = value as BrowserGrantPayload;
  const exactKeys = (item: object, allowed: string[]) =>
    Object.keys(item).every((key) => allowed.includes(key)) && allowed.every((key) => key in item || key === 'endpoint');
  const forbidden = (item: unknown): boolean => {
    if (!item || typeof item !== 'object') return false;
    if (Array.isArray(item)) return item.some(forbidden);
    return Object.entries(item).some(([key, nested]) =>
      /^(?:credentials?|credentialsRef|password|secret|token|username|rtspUrl)$/i.test(key) || forbidden(nested));
  };
  const now = Math.floor(Date.now() / 1000);
  if (!candidate || candidate.format !== 'webobs-browser-grant-v1' || candidate.contractVersion !== 2 ||
      !exactKeys(candidate, ['format', 'contractVersion', 'clientId', 'issuedAt', 'expiresAt', 'revision', 'cameras']) ||
      !/^[0-9a-f]{32}$/.test(candidate.clientId) || !Number.isInteger(candidate.issuedAt) ||
      !Number.isInteger(candidate.expiresAt) || candidate.expiresAt <= candidate.issuedAt ||
      candidate.issuedAt > now + 300 || candidate.expiresAt <= now ||
      candidate.expiresAt - candidate.issuedAt > 7 * 24 * 60 * 60 + 300 ||
      !Number.isInteger(candidate.revision) || candidate.revision < 0 ||
      !Array.isArray(candidate.cameras) || candidate.cameras.length > 64 || forbidden(candidate))
    throw new Error('浏览器授权包契约无效');
  const cameraIds = new Set<string>();
  for (const camera of candidate.cameras) {
    if (!camera || !exactKeys(camera, ['cameraId', 'name', 'adapter', 'profiles', 'permissions', 'credentialMode', 'weakRevocation']) ||
        !/^[A-Za-z0-9._-]{1,64}$/.test(camera.cameraId) || typeof camera.name !== 'string' ||
        camera.name.length > 128 || !Array.isArray(camera.profiles) || camera.profiles.length > 32 ||
        !Array.isArray(camera.permissions) || camera.permissions.length < 1 || camera.permissions.length > 5 ||
        !camera.permissions.includes('view') || new Set(camera.permissions).size !== camera.permissions.length ||
        camera.permissions.some((item) => !['view', 'snapshot', 'ptz', 'talk', 'record-local'].includes(item)))
      throw new Error('浏览器摄像机授权范围无效');
    if (cameraIds.has(camera.cameraId)) throw new Error('浏览器摄像机授权重复');
    cameraIds.add(camera.cameraId);
    const profileIds = new Set<string>();
    for (const profile of camera.profiles) {
      if (!profile || !exactKeys(profile, ['id', 'name', 'role', 'adapter', 'videoCodec', 'audioCodec', 'width',
          'height', 'fpsMilli', 'browserDirectEligible', 'browserDirectReason', 'endpoint']) ||
          !/^[A-Za-z0-9._-]{1,64}$/.test(profile.id) || typeof profile.name !== 'string' ||
          profile.name.length > 128 || typeof profile.adapter !== 'string' ||
          typeof profile.browserDirectEligible !== 'boolean' || typeof profile.browserDirectReason !== 'string' ||
          profile.browserDirectReason.length > 128)
        throw new Error('浏览器媒体 Profile 无效');
      if (profileIds.has(profile.id)) throw new Error('浏览器媒体 Profile 重复');
      profileIds.add(profile.id);
      if (profile.browserDirectEligible) {
        if (!profile.endpoint) throw new Error('浏览器直连 Profile 缺少端点');
        const endpoint = new URL(profile.endpoint);
        if (!['whep', 'hls', 'mjpeg'].includes(profile.adapter) || endpoint.protocol !== 'https:' ||
            endpoint.username || endpoint.password || endpoint.search || endpoint.hash)
          throw new Error('浏览器直连 Profile 端点无效');
      } else if (profile.endpoint) throw new Error('不合格的浏览器 Profile 不得暴露端点');
    }
  }
  return candidate;
}

async function persistVerifiedGrant(
  identity: StoredBrowserIdentity,
  client: { id: string; grantExpiresAt: number },
  grantBundle: Record<string, unknown> & { ciphertext: string; serverSigningPublicKey: string },
): Promise<number> {
  if (grantBundle.format !== 'webobs-client-grant+cbor-sealed-v1' || grantBundle.contractVersion !== 2 ||
      typeof grantBundle.ciphertext !== 'string' || grantBundle.ciphertext.length > 2 * 1024 * 1024 ||
      typeof grantBundle.serverSigningPublicKey !== 'string' ||
      bytes(grantBundle.serverSigningPublicKey).length !== sodium.crypto_sign_PUBLICKEYBYTES)
    throw new Error('浏览器授权包封装无效');
  const opened = sodium.crypto_box_seal_open(
    bytes(grantBundle.ciphertext), bytes(identity.encryptionPublicKey), bytes(identity.encryptionPrivateKey),
  );
  if (!opened || opened.length <= sodium.crypto_sign_BYTES) throw new Error('浏览器授权包无法解密');
  const signature = opened.slice(0, sodium.crypto_sign_BYTES);
  const payload = opened.slice(sodium.crypto_sign_BYTES);
  const pinnedSigningKey = identity.grantBundle?.serverSigningPublicKey;
  if (typeof pinnedSigningKey === 'string' && pinnedSigningKey !== grantBundle.serverSigningPublicKey)
    throw new Error('服务端授权签名密钥发生意外变化');
  if (!sodium.crypto_sign_verify_detached(signature, payload, bytes(grantBundle.serverSigningPublicKey)))
    throw new Error('浏览器授权包签名无效');
  const grantPayload = browserGrant(decodeCbor(payload));
  if (grantPayload.clientId !== client.id || grantPayload.expiresAt !== client.grantExpiresAt)
    throw new Error('浏览器授权包客户端或期限不匹配');
  if (identity.grantPayload && (grantPayload.revision < identity.grantPayload.revision ||
      grantPayload.issuedAt < identity.grantPayload.issuedAt))
    throw new Error('浏览器授权包重放已拒绝');
  const expiresAt = client.grantExpiresAt * 1000;
  await saveBrowserIdentity({
    ...identity, pairingCode: undefined, clientId: client.id, grantBundle, grantPayload, expiresAt,
  });
  return expiresAt;
}

export interface BrowserPairingState {
  enrollmentId: string;
  pairingCode: string;
  expiresAt: number;
  state: 'pending' | 'approved';
}

export async function beginBrowserEnrollment(name: string): Promise<BrowserPairingState> {
  await sodium.ready;
  const normalizedName = name.trim().slice(0, 64);
  if (!normalizedName) throw new Error('浏览器名称不能为空');
  const signing = sodium.crypto_sign_keypair();
  const encryption = sodium.crypto_box_keypair();
  const nonce = crypto.getRandomValues(new Uint8Array(32));
  const proof = cbor({
    purpose: 'webobs-client-enrollment-v1', name: normalizedName, platform: 'web',
    signingPublicKey: signing.publicKey, encryptionPublicKey: encryption.publicKey, nonce,
  });
  const response = await fetch('/api/v2/enrollments', {
    method: 'POST', cache: 'no-store', credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      name: normalizedName, platform: 'web', signingPublicKey: b64(signing.publicKey),
      encryptionPublicKey: b64(encryption.publicKey), enrollmentNonce: b64(nonce),
      signature: b64(sodium.crypto_sign_detached(proof, signing.privateKey)),
    }),
  });
  if (!response.ok) throw new Error(`浏览器配对创建失败（HTTP ${response.status}）`);
  const created = await response.json() as { enrollmentId: string; pairingCode: string; deviceToken: string; expiresAt: number };
  const now = Math.floor(Date.now() / 1000);
  if (!/^[0-9a-f]{32}$/.test(created.enrollmentId) || !/^\d{8}$/.test(created.pairingCode) ||
      !/^[A-Za-z0-9_-]{64}$/.test(created.deviceToken) || !Number.isInteger(created.expiresAt) ||
      created.expiresAt <= now || created.expiresAt > now + 10 * 60 + 30)
    throw new Error('浏览器配对响应无效');
  await clearPrivateRuntimeState();
  await saveBrowserIdentity({
    enrollmentId: created.enrollmentId, pairingCode: created.pairingCode, deviceToken: created.deviceToken,
    signingPublicKey: b64(signing.publicKey), signingPrivateKey: b64(signing.privateKey),
    encryptionPublicKey: b64(encryption.publicKey), encryptionPrivateKey: b64(encryption.privateKey),
    expiresAt: created.expiresAt * 1000,
  });
  return { enrollmentId: created.enrollmentId, pairingCode: created.pairingCode, expiresAt: created.expiresAt * 1000, state: 'pending' };
}

export async function completeBrowserEnrollment(): Promise<BrowserPairingState | null> {
  await sodium.ready;
  const identity = await loadBrowserIdentity();
  if (!identity) return null;
  const response = await fetch(`/api/v2/enrollments/${identity.enrollmentId}/complete`, {
    method: 'POST', cache: 'no-store', credentials: 'same-origin',
    headers: { 'X-WebObs-Device-Token': identity.deviceToken },
  });
  if (response.status === 202) return {
    enrollmentId: identity.enrollmentId, pairingCode: identity.pairingCode ?? '', expiresAt: identity.expiresAt, state: 'pending',
  };
  if (response.status === 401 || response.status === 403) {
    await clearPrivateRuntimeState();
    throw new Error('浏览器配对身份已失效');
  }
  if (!response.ok) throw new Error(`浏览器配对完成失败（HTTP ${response.status}）`);
  const completed = await response.json() as {
    client: { id: string; grantExpiresAt: number };
    grantBundle: Record<string, unknown> & { ciphertext: string; serverSigningPublicKey: string };
  };
  const expiresAt = await persistVerifiedGrant(identity, completed.client, completed.grantBundle);
  return { enrollmentId: identity.enrollmentId, pairingCode: '', expiresAt, state: 'approved' };
}

export async function browserDeviceHeaders(): Promise<Record<string, string>> {
  const identity = await loadBrowserIdentity();
  if (!identity?.clientId) throw new Error('此浏览器尚未完成配对');
  return { 'X-WebObs-Device-Token': identity.deviceToken };
}

export async function currentBrowserPairing(): Promise<BrowserPairingState | null> {
  const identity = await loadBrowserIdentity();
  if (!identity) return null;
  return {
    enrollmentId: identity.enrollmentId, pairingCode: identity.pairingCode ?? '',
    expiresAt: identity.expiresAt, state: identity.clientId ? 'approved' : 'pending',
  };
}

export async function refreshBrowserAuthorization(): Promise<number | null> {
  await sodium.ready;
  const identity = await loadBrowserIdentity();
  if (!identity?.clientId) return null;
  const revision = identity.grantPayload?.revision ?? 0;
  const response = await fetch(`/api/v2/client/bootstrap?sinceRevision=${revision}`, {
    cache: 'no-store', credentials: 'same-origin',
    headers: { 'X-WebObs-Device-Token': identity.deviceToken },
  });
  if (response.status === 401 || response.status === 403) {
    await clearPrivateRuntimeState();
    throw new Error('浏览器授权已撤销或过期');
  }
  if (!response.ok) throw new Error(`浏览器授权续期失败（HTTP ${response.status}）`);
  const bootstrap = await response.json() as {
    contractVersion: number; client: { id: string; grantExpiresAt: number };
    grantBundle: Record<string, unknown> & { ciphertext: string; serverSigningPublicKey: string };
  };
  if (bootstrap.contractVersion !== 2) throw new Error('浏览器启动契约版本不匹配');
  return persistVerifiedGrant(identity, bootstrap.client, bootstrap.grantBundle);
}
