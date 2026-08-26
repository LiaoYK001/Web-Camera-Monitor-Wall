import Hls from 'hls.js';
import { browserDeviceHeaders, browserDeviceToken } from './browserEnrollment';
import { clearPrivateRuntimeState, loadBrowserIdentity, type BrowserGrantProfile } from './localRuntime';
import { connectApprovedWhep, type ProgramConnection, type ProgramConnectionState } from './whep';

export interface BrowserTopologyPlan {
  contractVersion: 2;
  planId: string;
  cameraId: string;
  profileId: string;
  topology: 'true-direct' | 'gateway-direct' | 'hybrid' | 'composite';
  runtimeKind: 'pwa' | 'chromium-iwa';
  executionOwner: 'browser' | 'docker';
  mediaTransport: 'whep' | 'hls' | 'mjpeg' | 'rtsp';
  credentialExposure: 'none' | 'ephemeral';
  decoder: string;
  renderer: string;
  encoder: string;
  liveServerMediaExpected: boolean;
  fallbackReason: string;
  offlineConfigExpiresAt: number;
}

export class BrowserPlanError extends Error {
  constructor(readonly kind: 'authorization' | 'rejected' | 'unavailable', message: string) {
    super(message);
    this.name = 'BrowserPlanError';
  }
}

export async function offlineSignedGrantPlan(
  cameraId: string, profileId: string, transport: 'whep' | 'hls' | 'mjpeg',
): Promise<BrowserTopologyPlan> {
  const identity = await loadBrowserIdentity();
  const profile = await approvedBrowserProfile(cameraId, profileId);
  if (!identity?.clientId || !profile || identity.expiresAt <= Date.now())
    throw new BrowserPlanError('authorization', '离线浏览器授权无效');
  return {
    contractVersion: 2, planId: '', cameraId, profileId, topology: 'true-direct', runtimeKind: 'pwa',
    executionOwner: 'browser', mediaTransport: transport, credentialExposure: 'none',
    decoder: 'browser-hardware-auto', renderer: 'browser', encoder: 'none',
    liveServerMediaExpected: false, fallbackReason: 'control_plane_offline_signed_grant',
    offlineConfigExpiresAt: Math.floor(identity.expiresAt / 1000),
  };
}

export async function browserGrantProfile(cameraId: string, profileId: string): Promise<BrowserGrantProfile | null> {
  const identity = await loadBrowserIdentity();
  const camera = identity?.grantPayload?.cameras.find((item) => item.cameraId === cameraId);
  return camera?.profiles.find((item) => item.id === profileId) ?? null;
}

export async function approvedBrowserProfile(cameraId: string, profileId: string): Promise<BrowserGrantProfile | null> {
  const profile = await browserGrantProfile(cameraId, profileId);
  if (!profile?.browserDirectEligible || !profile.endpoint || !['whep', 'hls', 'mjpeg'].includes(profile.adapter)) return null;
  const endpoint = new URL(profile.endpoint);
  if (endpoint.protocol !== 'https:' || endpoint.username || endpoint.password || endpoint.search || endpoint.hash)
    return null;
  return profile;
}

export async function requestBrowserPlan(
  cameraId: string, profileId: string, reachability: 'reachable' | 'unreachable', protocol: string,
): Promise<BrowserTopologyPlan> {
  if (!['whep', 'hls', 'mjpeg', 'rtsp'].includes(protocol)) throw new Error('浏览器媒体协议无效');
  let response: Response;
  try {
    response = await fetch('/api/v2/media-plans', {
      method: 'POST', cache: 'no-store', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', ...await browserDeviceHeaders() },
      body: JSON.stringify({
        cameraId, profileId, policy: 'auto', receiverKind: 'browser', networkClass: 'lan', reachability,
        protocols: ['whep', 'hls', 'mjpeg'], videoCodecs: ['h264', 'h265', 'mjpeg'],
        hardwareDecoders: ['webcodecs'], requiresComposite: false,
      }),
    });
  } catch {
    throw new BrowserPlanError('unavailable', '控制面当前不可达');
  }
  if (response.status === 401 || response.status === 403) {
    await clearPrivateRuntimeState();
    throw new BrowserPlanError('authorization', '浏览器授权已撤销或过期');
  }
  if (!response.ok) throw new BrowserPlanError('rejected', `媒体拓扑规划失败（HTTP ${response.status}）`);
  const plan = await response.json() as BrowserTopologyPlan;
  if (plan.contractVersion !== 2 || plan.cameraId !== cameraId || plan.profileId !== profileId ||
      plan.runtimeKind !== 'pwa' || !/^[0-9a-f]{32}$/.test(plan.planId) ||
      !['whep', 'hls', 'mjpeg', 'rtsp'].includes(plan.mediaTransport) ||
      plan.credentialExposure !== 'none' ||
      (plan.topology === 'true-direct' && (plan.executionOwner !== 'browser' ||
        plan.liveServerMediaExpected || plan.mediaTransport !== protocol)) ||
      (plan.topology !== 'true-direct' && (plan.executionOwner !== 'docker' || !plan.liveServerMediaExpected)))
    throw new BrowserPlanError('rejected', '媒体拓扑响应与浏览器请求不匹配');
  return plan;
}

export async function activateGateway(planId: string): Promise<{ endpoint: string; deviceToken: string }> {
  if (!/^[0-9a-f]{32}$/.test(planId)) throw new Error('媒体计划 ID 无效');
  const headers = await browserDeviceHeaders();
  const deviceToken = await browserDeviceToken();
  let response: Response;
  try {
    response = await fetch(`/api/v2/media-plans/${planId}/activate`, {
      method: 'POST', cache: 'no-store', credentials: 'same-origin', headers,
    });
  } catch {
    throw new BrowserPlanError('unavailable', 'Gateway 控制面当前不可达');
  }
  if (response.status === 401 || response.status === 403) {
    await clearPrivateRuntimeState();
    throw new BrowserPlanError('authorization', '浏览器授权已撤销或过期');
  }
  if (!response.ok) throw new BrowserPlanError('rejected', `Gateway 启动失败（HTTP ${response.status}）`);
  const result = await response.json() as { mediaEndpoint: { endpoint: string } };
  const endpoint = new URL(result.mediaEndpoint.endpoint, window.location.href);
  if (endpoint.origin !== window.location.origin || endpoint.search || endpoint.hash ||
      endpoint.pathname !== `/api/v2/media-plans/${planId}/whep`)
    throw new BrowserPlanError('rejected', 'Gateway 返回了越界媒体端点');
  return { endpoint: endpoint.href, deviceToken };
}

export function validateHlsChildUrl(requestUrl: string, baseUrl: URL): void {
  const mediaUrl = new URL(requestUrl, baseUrl);
  if (mediaUrl.protocol !== 'https:' || mediaUrl.origin !== baseUrl.origin ||
      mediaUrl.username || mediaUrl.password || mediaUrl.hash)
    throw new Error('HLS child resource escaped the approved HTTPS origin');
}

export function hlsXhrSetup(xhr: XMLHttpRequest, requestUrl: string, baseUrl: URL): void {
  validateHlsChildUrl(requestUrl, baseUrl);
  xhr.withCredentials = false;
}

export function connectHls(
  video: HTMLVideoElement, endpoint: string, onState: (state: ProgramConnectionState) => void,
): ProgramConnection {
  const url = new URL(endpoint);
  if (url.protocol !== 'https:' || url.username || url.password || url.search || url.hash)
    throw new Error('HLS endpoint is not approved');
  let hls: Hls | undefined;
  let closed = false;
  const timeout = window.setTimeout(() => { if (!closed) onState('offline'); }, 20_000);
  onState('connecting');
  if (Hls.isSupported()) {
    hls = new Hls({
      enableWorker: true, lowLatencyMode: true, maxBufferLength: 12, maxMaxBufferLength: 20,
      xhrSetup(xhr, requestUrl) { hlsXhrSetup(xhr, requestUrl, url); },
    });
    hls.on(Hls.Events.MANIFEST_PARSED, () => void video.play().catch(() => undefined));
    hls.on(Hls.Events.ERROR, (_event, data) => { if (data.fatal && !closed) onState('offline'); });
    hls.loadSource(url.href); hls.attachMedia(video);
  } else if (video.canPlayType('application/vnd.apple.mpegurl')) {
    video.src = url.href; void video.play().catch(() => undefined);
  } else onState('offline');
  const live = () => { window.clearTimeout(timeout); onState('live'); };
  video.addEventListener('playing', live);
  return { close: () => { closed = true; window.clearTimeout(timeout); video.removeEventListener('playing', live); hls?.destroy(); video.removeAttribute('src'); video.load(); } };
}

export function connectMjpeg(
  image: HTMLImageElement, endpoint: string, onState: (state: ProgramConnectionState) => void,
): ProgramConnection {
  const url = new URL(endpoint);
  if (url.protocol !== 'https:' || url.username || url.password || url.search || url.hash)
    throw new Error('MJPEG endpoint is not approved');
  let closed = false;
  const timeout = window.setTimeout(() => { if (!closed) onState('offline'); }, 20_000);
  const live = () => { window.clearTimeout(timeout); onState('live'); };
  const failed = () => { window.clearTimeout(timeout); onState('offline'); };
  image.addEventListener('load', live); image.addEventListener('error', failed);
  onState('connecting'); image.src = url.href;
  return { close: () => { closed = true; window.clearTimeout(timeout); image.removeEventListener('load', live); image.removeEventListener('error', failed); image.removeAttribute('src'); } };
}

export { connectApprovedWhep };
