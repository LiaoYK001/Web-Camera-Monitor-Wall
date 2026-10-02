// Development-only UI fixture: all API requests stay in memory; no live devices are touched.
import { useState } from 'react';
import { createRoot } from 'react-dom/client';
import WorkspaceShell, { type ProductArea } from '../../src/WorkspaceShell';
import SourceCatalog from '../../src/SourceCatalog';
import AccountWorkspace from '../../src/AccountWorkspace';
import SettingsWorkspace from '../../src/SettingsWorkspace';
import DirectPreview from '../../src/DirectPreview';
import App from '../../src/App';
import { clearPrivateRuntimeState } from '../../src/localRuntime';
import { defaultMonitorView, defaultSourceDecoration } from '../../src/monitorView';
import type { OperationalIssue, RuntimeSettings, SceneDocument, SourceCatalogItem, StudioDocument } from '../../src/types';
import '../../src/styles.css';

const cameras: SourceCatalogItem[] = Array.from({ length: 53 }, (_, index) => ({
  schemaVersion: 2, id: `fixture-${index}`, name: `${index === 0 ? '大门入口' : index === 1 ? '仓库通道' : '办公区域'} ${String(index + 1).padStart(2, '0')}`,
  kind: 'camera', adapter: 'rtsp', enabled: true, groupId: index < 24 ? '一楼' : '二楼', tags: ['日常监看'],
  addressDisplay: `rtsp://camera-${index}.example.invalid/live`, health: index % 5 === 0 ? 'offline' : 'online',
  hardwareDecode: 'auto', profileCount: 1, trackCount: 1, deviceCapabilities: { ptz: false, snapshot: false, talk: false },
  profiles: [{ id: 'main', name: '主码流', role: 'main', videoCodec: 'h264', audioCodec: '', width: 3840, height: 2160, fps: 25,
    endpointDisplay: 'rtsp://camera.example.invalid/live', enabled: true, transportMode: 'auto', liveBitrateCapKbps: null,
    audioExpectation: 'auto', probeState: 'ready', lastProbeAt: 0, tracks: [], allowInsecureHttp: false }],
  revision: 1, createdAt: 0, updatedAt: 0,
}));
const preferences = new Map<string, unknown>();
const fixtureOptions = new URLSearchParams(location.search);
const scene: SceneDocument = {
  schemaVersion: 5, revision: 1, id: 'fixture-scene', name: '测试监控', canvas: { width: 1920, height: 1080, backgroundColor: '#000000' },
  sources: [{ id: 'color-one', kind: 'color', name: '测试色块', color: '#214f75', muted: true, volume: 0, syncOffsetMs: 0, monitoring: 'off', audioTrack: 1, filters: [] }],
  items: [{ id: 'item-one', sourceId: 'color-one', x: 0, y: 0, width: 1920, height: 1080, scaleMode: 'contain', crop: { top: 0, right: 0, bottom: 0, left: 0 }, zIndex: 0, visible: true, locked: false, groupId: '', rotation: 0, opacity: 1, blendMode: 'normal' }],
};
const studio: StudioDocument = { schemaVersion: 1, revision: 1, previewSceneId: scene.id, programSceneId: scene.id, scenes: [scene], transition: { kind: 'cut', durationMs: 0 } };
if (fixtureOptions.has('mixer') || fixtureOptions.has('layout')) {
  scene.sources = [0, 1].map((index) => ({ id: `audio-source-${index}`, kind: 'camera', name: index ? '有声音的摄像机' : '无音轨摄像机',
    cameraId: `fixture-${index}`, profileId: 'main', hardwareDecode: 'auto', muted: true, volume: 1, syncOffsetMs: 0,
    monitoring: 'off', audioTrack: 1, filters: [] }));
  scene.items = scene.sources.map((source, index) => ({ ...scene.items[0], id: `audio-item-${index}`, sourceId: source.id, x: index * 960, width: 960 }));
  cameras[1].profiles[0].audioCodec = 'pcm_alaw';
  cameras[1].profiles[0].tracks = [{ index: 1, kind: 'audio', codec: 'pcm_alaw', bitrateKbps: null, width: 0, height: 0, fps: 0, channels: 1, sampleRate: 8000, source: 'probe' }];
}
const monitorView = { ...defaultMonitorView(), sourceDecorations: { 'other-scene-source': { ...defaultSourceDecoration(), audioMeter: { ...defaultSourceDecoration().audioMeter, enabled: true, opacity: .6 } } } };
if (fixtureOptions.has('layout')) {
  const canvas = document.createElement('canvas'); canvas.width = 640; canvas.height = 360;
  const context = canvas.getContext('2d')!;
  let frame = 0;
  window.setInterval(() => {
    context.fillStyle = '#14384a'; context.fillRect(0, 0, 640, 360);
    context.fillStyle = '#baff50'; context.fillRect((frame++ * 3) % 540, 80, 100, 100);
    context.font = '28px sans-serif'; context.fillText('LIVE LAYOUT FIXTURE', 50, 290);
  }, 80);
  const stream = canvas.captureStream(12);
  class FixturePeer {
    iceGatheringState = 'complete'; connectionState = 'new'; localDescription: RTCSessionDescriptionInit | null = null;
    ontrack?: (event: { track: MediaStreamTrack }) => void; onconnectionstatechange?: () => void;
    track?: MediaStreamTrack;
    addTransceiver() {}
    async createOffer() { return { type: 'offer', sdp: 'v=0\r\n' }; }
    async setLocalDescription(value: RTCSessionDescriptionInit) { this.localDescription = value; }
    async setRemoteDescription() {
      this.track = stream.getVideoTracks()[0].clone(); this.ontrack?.({ track: this.track });
      this.connectionState = 'connected'; this.onconnectionstatechange?.();
    }
    async getStats() { return new Map(); }
    close() { this.track?.stop(); this.connectionState = 'closed'; }
  }
  window.RTCPeerConnection = FixturePeer as unknown as typeof RTCPeerConnection;
}
preferences.set('/api/v2/account/preferences/monitor-view', monitorView);
if (fixtureOptions.has('profile')) {
  preferences.set('/api/v2/account/preferences/config-profiles', { profiles: [{ schemaVersion: 1, id: 'fixture-profile', name: '值班布局', createdAt: 1, updatedAt: 1, studio }] });
  preferences.set('/api/v2/account/preferences/active-profile', { id: 'fixture-profile' });
}
let settings: RuntimeSettings = { schemaVersion: 1, revision: 1, values: { defaultTransportMode: 'auto', probeTimeoutSeconds: 8, sourceRecoveryEnabled: true, issueRetentionLimit: 256 }, deployment: { tls: 'read-only', ports: 'read-only', secrets: 'read-only', gpuDevice: 'read-only' } };
const issue: OperationalIssue = { id: 'fixture-issue', code: 'FIXTURE_OFFLINE', severity: 'warning', state: 'open', scopeKind: 'device', scopeId: 'camera-fixture', component: 'playback', firstSeenAt: 1720000000, lastSeenAt: 1720000000, occurrences: 2, summary: '测试摄像机连接中断', explanation: '模拟网络断开，供界面验证。', recommendedActions: ['检查设备网络后重试。'], technicalDetails: { retryCount: 2 } };
const metrics = { queries: [] as string[], saves: [] as unknown[], monitorSaves: [] as unknown[], preferenceWrites: [] as Array<{ path: string; value: unknown }>, settingsPatches: [] as unknown[], acknowledgments: 0, imports: 0, activeSaves: 0, maxConcurrentSaves: 0 };
const updateMetrics = () => document.documentElement.setAttribute('data-fixture-metrics', JSON.stringify(metrics));
updateMetrics();
const originalFetch = window.fetch.bind(window);
let fixtureOffers = 0;
window.fetch = async (input, init) => {
  const url = new URL(typeof input === 'string' ? input : input instanceof URL ? input.href : input.url, location.href);
  if (!url.pathname.startsWith('/api/')) return originalFetch(input, init);
  if (fixtureOptions.has('account-server') && url.pathname === '/api/v2/account/preferences/monitor-view') return originalFetch(input, init);
  const reply = (data: unknown, status = 200) => new Response(JSON.stringify(data), { status, headers: { 'Content-Type': 'application/json' } });
  if (url.pathname === '/api/v1/studio') return reply(studio);
  if (fixtureOptions.has('layout') && url.pathname.includes('/account-cameras/')) {
    if (init?.method === 'DELETE') return new Response(null, { status: 204 });
    fixtureOffers++; document.documentElement.dataset.fixtureOffers = String(fixtureOffers);
    return new Response('v=0\r\no=- 0 0 IN IP4 127.0.0.1\r\ns=-\r\nt=0 0\r\nm=video 9 UDP/TLS/RTP/SAVPF 96\r\na=mid:0\r\na=fingerprint:sha-256 AA:BB\r\n',
      { status: 201, headers: { 'Content-Type': 'application/sdp', Location: url.pathname + '/session/fixture-session' } });
  }
  const wait = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));
  if (url.pathname === '/api/v2/account/me') return reply({ username: 'demo', displayName: '值班管理员', avatar: 'camera', roles: ['admin'], permissions: ['user.manage'], scopes: [], acl: [{ permission: 'live.view', allowed: true }] });
  if (url.pathname.startsWith('/api/v2/account/preferences/')) {
    if (fixtureOptions.has('monitor-timeout') && url.pathname.endsWith('/monitor-view') && init?.method !== 'PUT') {
      return new Promise<Response>((_resolve, reject) => {
        if (init?.signal?.aborted) reject(new DOMException('Aborted', 'AbortError'));
        else init?.signal?.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')), { once: true });
      });
    }
    if (init?.method === 'PUT') {
      metrics.activeSaves++; metrics.maxConcurrentSaves = Math.max(metrics.maxConcurrentSaves, metrics.activeSaves);
      updateMetrics(); await wait(650);
      if (init.signal?.aborted) { metrics.activeSaves--; updateMetrics(); throw new DOMException('Aborted', 'AbortError'); }
      const value = JSON.parse(String(init.body)).value;
      preferences.set(url.pathname, value);
      if (url.pathname.endsWith('/workspace-layout')) metrics.saves.push(value);
      if (url.pathname.endsWith('/monitor-view')) metrics.monitorSaves.push(value);
      metrics.preferenceWrites.push({ path: url.pathname, value });
      metrics.activeSaves--; updateMetrics();
    }
    return reply({ value: preferences.get(url.pathname) ?? null });
  }
  if (url.pathname === '/api/v2/source-catalog') {
    const query = url.searchParams.get('q') ?? '';
    metrics.queries.push(query); updateMetrics();
    // Deliberately ignore abort signals to exercise the UI's stale-result guard.
    await wait(query === 'slow' ? 900 : 30);
    const matching = cameras.filter((camera) => (!query || camera.name.includes(query))
      && (!url.searchParams.get('adapter') || url.searchParams.get('adapter') === camera.adapter));
    const page = Number(url.searchParams.get('page') ?? 1); const limit = Number(url.searchParams.get('limit') ?? 24);
    return reply({ schemaVersion: 2, page, limit, total: matching.length, items: matching.slice((page - 1) * limit, page * limit) });
  }
  if (url.pathname === '/api/v1/cameras' && init?.method === 'POST') { metrics.imports++; updateMetrics(); await wait(500); return reply({ id: `import-${metrics.imports}` }); }
  if (url.pathname === '/api/v2/source-catalog/batch') {
    const items = JSON.parse(String(init?.body)).items;
    for (const item of items) { const camera = cameras.find((entry) => entry.id === item.cameraId); if (camera) Object.assign(camera, item, { revision: camera.revision + 1 }); }
    return reply({ items: cameras.filter((camera) => items.some((item: { cameraId: string }) => item.cameraId === camera.id)) });
  }
  if (url.pathname === '/api/v2/settings') {
    if (init?.method === 'PATCH') {
      const change = JSON.parse(String(init.body)); metrics.settingsPatches.push(change); updateMetrics(); await wait(500);
      if (fixtureOptions.has('settings-fail') && metrics.settingsPatches.length === 1) return reply({ error: { code: 'REVISION_CONFLICT', message: '设置版本冲突' } }, 409);
      settings = { ...settings, revision: settings.revision + 1, values: { ...settings.values, ...change } };
    }
    return reply(settings);
  }
  const catalogItem = url.pathname.match(/^\/api\/v2\/source-catalog\/(fixture-\d+)(\/profiles\/main\/probe)?$/);
  if (catalogItem) {
    const camera = cameras.find((value) => value.id === catalogItem[1])!;
    if (catalogItem[2]) {
      await wait(250);
      const profile = camera.profiles[0];
      if (fixtureOptions.has('probe-fail') && !profile.probeAttempts) {
        profile.probeState = 'failed'; profile.probeAttempts = 10; camera.health = 'offline';
        return reply({ error: { code: 'MEDIA_PROBE_FAILED', message: '探测连接超时' } }, 502);
      }
      profile.probeState = 'ready'; profile.probeAttempts = 0; camera.health = 'online';
      return reply({ cameraId: camera.id, profile });
    }
    if (init?.method === 'PATCH') {
      const update = JSON.parse(String(init.body));
      if (update.profiles?.[0]) Object.assign(camera.profiles[0], update.profiles[0]);
      camera.revision += 1;
    }
    return reply(camera);
  }
  if (url.pathname === '/api/v2/operations/issues') return reply({ issues: fixtureOptions.has('issues') ? [issue, { ...issue, id: 'fixture-resolved', state: 'resolved', summary: '已恢复的测试摄像机' }] : [] });
  if (url.pathname.endsWith('/fixture-issue/acknowledge')) {
    metrics.acknowledgments++; updateMetrics(); await wait(500);
    if (fixtureOptions.has('issues-fail') && metrics.acknowledgments === 1) return reply({ error: { code: 'TEMPORARY_FAILURE', message: '确认暂时失败，请重试' } }, 503);
    issue.state = 'acknowledged'; return reply(issue);
  }
  if (url.pathname === '/api/v1/cameras') return reply({ cameras: fixtureOptions.has('mixer') || fixtureOptions.has('layout') ? cameras.slice(0, 2) : [] });
  if (url.pathname === '/api/v1/playback/capabilities') return reply({ modes: { direct: { enabled: true } }, sources: [] });
  if (url.pathname.includes('analytics')) return reply({ policies: [] });
  if (url.pathname.includes('motion-zones')) return reply({ zones: [] });
  return reply({}, 404);
};

function Fixture() {
  const [area, setArea] = useState<ProductArea>((fixtureOptions.get('area') ?? 'devices') as ProductArea);
  if (fixtureOptions.has('layout')) return <App />;
  return <WorkspaceShell area={area} onNavigate={setArea} connection="online">
    {area === 'devices' ? <SourceCatalog /> : area === 'account' ? <AccountWorkspace onAdmin={() => setArea('admin')} />
      : area === 'settings' ? <SettingsWorkspace studio={studio} /> : area === 'monitor' ? <><button onClick={() => void clearPrivateRuntimeState().then(() => setArea('devices'))}>模拟退出清理</button>
        <section className="monitor-surface"><button onClick={(event) => void event.currentTarget.parentElement!.requestFullscreen()}>测试真全屏</button><DirectPreview scene={scene} /></section></>
      : <section className="page-panel"><h1>{area}</h1><button onClick={() => setArea('devices')}>返回设备列表</button></section>}
  </WorkspaceShell>;
}
createRoot(document.getElementById('root')!).render(<Fixture />);
