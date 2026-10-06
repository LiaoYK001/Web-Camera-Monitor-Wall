import { createServer, type Server } from 'node:http';
import { readFile } from 'node:fs/promises';
import path from 'node:path';
import type { StudioDocument } from '../../src/types';

export const origin = 'http://127.0.0.1:4191';
export const studio: StudioDocument = { schemaVersion: 1, revision: 1,
  previewSceneId: 'scene-a', programSceneId: 'scene-b',
  scenes: ['a', 'b'].map(id => ({ schemaVersion: 1, id: 'scene-' + id, name: 'Saved ' + id,
    revision: 1, canvas: { width: 1280, height: 720, background: '#101010' }, sources: [], items: [] })) };
const legacyWorker =   "self.addEventListener('install',e=>e.waitUntil(self.skipWaiting()));" +
  "self.addEventListener('activate',e=>e.waitUntil(self.clients.claim()));";

export function pwaServer() {
  let current = false;
  const state = { authenticated: true, offline: false, mutations: [] as string[], syncPosts: 0,
    // exportPosts counts raw HTTP POSTs, including a browser-level resend of a request
    // whose socket died before any response; exportRequestIds and jobs model the
    // service's response-loss idempotency (one accepted job per request identity).
    jobs: [] as any[], exportPosts: 0, exportRequestIds: [] as string[], loseExportResponse: false,
    account: new Map<string, unknown>() };
  const directory = path.resolve('../tmp/pwa-continuity-dist');
  const server = createServer(async (req, res) => {
    const url = new URL(req.url!, origin), route = url.pathname;
    const json = (body: unknown, status = 200) => { res.writeHead(status, { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' }); res.end(JSON.stringify(body)); };
    const readBody = async () => { let text = ''; for await (const chunk of req) text += chunk; return JSON.parse(text || '{}'); };
    try {
      if (route === '/sw.js') {
        res.writeHead(200, { 'Content-Type': 'text/javascript', 'Cache-Control': 'no-store', 'Service-Worker-Allowed': '/' });
        res.end(current ? await readFile(path.join(directory, 'sw.js')) : legacyWorker); return;
      }
      if (route.startsWith('/api/')) {
        if (!['GET', 'HEAD'].includes(req.method!)) state.mutations.push(req.method + ' ' + route);
        if (route === '/api/v1/auth/session') return json({ authenticated: state.authenticated, user: 'pwa-fixture', registrationOpen: false, csrfToken: 'fixture-csrf' });
        if (state.offline) return json({ error: { code: 'offline', message: 'Fixture offline' } }, 503);
        if (route.startsWith('/api/v2/account/preferences/')) {
          if (req.method === 'PUT') state.account.set(route, (await readBody()).value);
          return json({ value: state.account.get(route) ?? null });
        }
        if (route === '/api/v1/studio') return json(studio);
        if (route === '/api/v1/scene') return json(studio.scenes[1]);
        if (route === '/api/v1/studio/capabilities') return json({ scenes: studio.scenes.map(s => ({ sceneId: s.id, directPlaySupported: true, supportsComposition: true, reasons: [] })) });
        if (route === '/api/v1/cameras') return json({ cameras: [] });
        if (route === '/api/v2/client/bootstrap') return json({ contractVersion: 2, revision: 1,
          syncPolicy: 'bidirectional-field-conflict-v1', sync: { resetRequired: false, documents: [], changes: [] } });
        if (route === '/api/v2/client/sync') {
          const body = await readBody(); state.syncPosts++;
          return json({ schemaVersion: 1, revision: 2, conflicts: [], accepted: body.mutations.map((m: any) => ({ kind: m.kind, id: m.id, revision: 2, unchanged: false })) });
        }
        if (route === '/api/v2/client/audit') return json({ accepted: true });
        if (route === '/api/v1/nvr/status') return json({ status: 'ok', freeBytes: 1e9, diskPressure: false,
          cameras: [{ id: 'cam', policy: 'continuous', state: 'idle', segments: 1, eventActive: false }] });
        if (route === '/api/v1/nvr/timeline') {
          const from = Number(url.searchParams.get('fromUtcMs')), to = Number(url.searchParams.get('toUtcMs'));
          return json({ fromUtcMs: from, toUtcMs: to, storageTimeZone: 'UTC', queryDurationMs: 2,
            cameras: [{ cameraId: 'cam', recordedStream: 'main', retentionBoundaryUtcMs: null, segments: [], gaps: [] }] });
        }
        if (route === '/api/v1/nvr/exports/jobs') {
          if (req.method === 'POST') {
            const { requestId, ...request } = await readBody(); state.exportPosts++;
            state.exportRequestIds.push(String(requestId));
            // Same identity returns the already accepted job instead of creating a
            // second export, which is what the real service guarantees.
            const accepted = state.jobs.find((job: any) => job.requestId === requestId);
            const job = accepted ?? { id: 'b'.repeat(32), requestId, state: 'running', createdUtcMs: Date.now(), updatedUtcMs: Date.now(), request, result: null, error: null };
            if (!accepted) state.jobs.push(job);
            if (state.loseExportResponse) { req.socket.destroy(); return; }
            return json(job, 202);
          }
          return json({ jobs: state.jobs });
        }
        return json({ error: { code: 'fixture_unimplemented', message: route } }, 404);
      }
      const relative = route === '/' ? 'index.html' : decodeURIComponent(route).slice(1);
      const file = path.resolve(directory, relative);
      if (!file.startsWith(directory + path.sep)) { res.writeHead(403); res.end(); return; }
      const body = await readFile(file).catch(() => readFile(path.join(directory, 'index.html')));
      const ext = path.extname(file);
      res.writeHead(200, { 'Content-Type': ({ '.js': 'text/javascript', '.html': 'text/html', '.css': 'text/css', '.json': 'application/json', '.svg': 'image/svg+xml', '.png': 'image/png', '.webmanifest': 'application/manifest+json' } as Record<string,string>)[ext] ?? 'application/octet-stream', 'Cache-Control': 'no-store' });
      res.end(body);
    } catch { json({ error: { code: 'fixture_internal', message: 'Fixture request failed' } }, 500); }
  });
  return { state, upgrade: () => { current = true; }, reset: () => { current = false; state.authenticated = true; state.offline = false; state.mutations = []; state.syncPosts = 0; state.jobs = []; state.exportPosts = 0; state.exportRequestIds = []; state.loseExportResponse = false; state.account.clear(); },
    start: async () => { await readFile(path.join(directory, 'sw.js')); await readFile(path.join(directory, 'tests/harness/pwa-seed.html')); await new Promise<void>((resolve, reject) => { server.once('error', reject); server.listen(4191, '127.0.0.1', resolve); }); },
    close: () => new Promise<void>(resolve => { server.closeAllConnections(); server.close(() => resolve()); }) };
}
