// Development-only UI fixture: all API requests stay in memory; no live devices are touched.
import { useState } from 'react';
import { createRoot } from 'react-dom/client';
import WorkspaceShell, { type ProductArea } from '../../src/WorkspaceShell';
import SourceCatalog from '../../src/SourceCatalog';
import AccountWorkspace from '../../src/AccountWorkspace';
import type { SourceCatalogItem } from '../../src/types';
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
const metrics = { queries: [] as string[], saves: [] as unknown[], imports: 0, activeSaves: 0, maxConcurrentSaves: 0 };
const updateMetrics = () => document.documentElement.setAttribute('data-fixture-metrics', JSON.stringify(metrics));
const originalFetch = window.fetch.bind(window);
window.fetch = async (input, init) => {
  const url = new URL(typeof input === 'string' ? input : input instanceof URL ? input.href : input.url, location.href);
  if (!url.pathname.startsWith('/api/')) return originalFetch(input, init);
  const reply = (data: unknown, status = 200) => new Response(JSON.stringify(data), { status, headers: { 'Content-Type': 'application/json' } });
  const wait = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));
  if (url.pathname === '/api/v2/account/me') return reply({ username: 'demo', displayName: '值班管理员', avatar: 'camera', roles: ['admin'], permissions: ['user.manage'], scopes: [], acl: [{ permission: 'live.view', allowed: true }] });
  if (url.pathname.startsWith('/api/v2/account/preferences/')) {
    if (init?.method === 'PUT') {
      metrics.activeSaves++; metrics.maxConcurrentSaves = Math.max(metrics.maxConcurrentSaves, metrics.activeSaves);
      updateMetrics(); await wait(650);
      const value = JSON.parse(String(init.body)).value;
      preferences.set(url.pathname, value);
      if (url.pathname.endsWith('/workspace-layout')) metrics.saves.push(value);
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
  if (url.pathname === '/api/v2/operations/issues') return reply({ issues: [] });
  if (url.pathname === '/api/v1/cameras') return reply({ cameras: [] });
  if (url.pathname === '/api/v1/playback/capabilities') return reply({ sources: [] });
  if (url.pathname.includes('analytics')) return reply({ policies: [] });
  if (url.pathname.includes('motion-zones')) return reply({ zones: [] });
  return reply({}, 404);
};

function Fixture() {
  const [area, setArea] = useState<ProductArea>('devices');
  return <WorkspaceShell area={area} onNavigate={setArea} connection="online">
    {area === 'devices' ? <SourceCatalog /> : area === 'account' ? <AccountWorkspace onAdmin={() => setArea('admin')} />
      : <section className="page-panel"><h1>{area}</h1><button onClick={() => setArea('devices')}>返回设备列表</button></section>}
  </WorkspaceShell>;
}
createRoot(document.getElementById('root')!).render(<Fixture />);
