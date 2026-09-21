/**
 * Direct/Hybrid first-frame decomposition probe.
 *
 * The wall renders one tile per source and every tile asks the control plane
 * for a media plan, activates it, then opens a WHEP session.  Measuring only
 * the first presented frame hides where the time goes, so this probe records
 * per tile when it enters connecting / live and how long each plan and WHEP
 * HTTP call took, which is how the serialized ~11s-per-source server step was
 * located (see docs/feedback-5-acceptance.md section 4.3).
 *
 * Usage: node tests/direct-latency-probe.mjs   (needs a running dev backend,
 *        Vite on 5173 and a paired or pairable browser; PROBE_SECONDS
 *        overrides the 120 second window)
 */
import { chromium } from '@playwright/test';
import { readFileSync, existsSync } from 'node:fs';
import path from 'node:path';

const root = path.resolve(import.meta.dirname, '../..');
const secret = (name) => existsSync(path.join(root, 'secrets', name))
  ? readFileSync(path.join(root, 'secrets', name), 'utf8').trim() : '';
const seconds = Number(process.env.PROBE_SECONDS ?? '120');

const browser = await chromium.launch({ channel: 'chrome' });
const page = await browser.newPage();
page.on('console', (message) => { if (message.type() === 'error') console.log('[console-error]', message.text().slice(0, 160)); });
await page.addInitScript(() => {
  window.__frames = {};
  window.__api = [];
  const originalFetch = window.fetch;
  window.fetch = async function (...args) {
    const url = String(args[0]);
    if (!url.includes('/api/')) return originalFetch.apply(this, args);
    const record = { url: url.replace('http://127.0.0.1:5173', ''), method: (args[1]?.method ?? 'GET'), start: Date.now(), end: null, status: null };
    window.__api.push(record);
    try {
      const response = await originalFetch.apply(this, args);
      record.end = Date.now();
      record.status = response.status;
      return response;
    } catch (error) {
      record.end = Date.now();
      record.status = 'error';
      throw error;
    }
  };
  const Original = window.RTCPeerConnection;
  window.__pcs = [];
  class Tracked extends Original { constructor(...args) { super(...args); window.__pcs.push(this); } }
  window.RTCPeerConnection = Tracked;
});

await page.goto('http://127.0.0.1:5173');
await page.waitForTimeout(2500);
if (await page.getByRole('heading', { name: '登录监控工作台' }).isVisible().catch(() => false)) {
  await page.getByLabel('用户名', { exact: true }).fill(secret('webobs-dev-username.txt'));
  await page.getByLabel('密码', { exact: true }).fill(secret('webobs-dev-password.txt'));
  await page.getByRole('button', { name: '登录', exact: true }).click();
}
await page.waitForTimeout(3000);

const pairing = await page.evaluate(async () => {
  const enrollment = await import('/src/browserEnrollment.ts');
  const current = await enrollment.currentBrowserPairing().catch(() => null);
  if (current?.state === 'approved') return { skipped: true };
  const began = await enrollment.beginBrowserEnrollment('direct-probe');
  const registry = await (await fetch('/api/v1/cameras', { credentials: 'same-origin' })).json();
  const cameraGrants = (registry.cameras ?? []).map((camera) => ({
    cameraId: camera.id, profileIds: (camera.profiles ?? []).map((p) => p.id),
    permissions: ['view'], credentialMode: 'none',
  }));
  const response = await fetch(`/api/v2/enrollments/${began.enrollmentId}/approve`, {
    method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ pairingCode: began.pairingCode, cameraGrants }),
  });
  if (!response.ok) return { error: response.status };
  const completed = await enrollment.completeBrowserEnrollment();
  return { state: completed?.state };
});
console.log('pairing:', JSON.stringify(pairing));
await page.reload();
await page.waitForTimeout(6000);

const modeButton = page.getByRole('button', { name: '浏览器媒体' });
if (await modeButton.count()) await modeButton.first().click().catch(() => undefined);
await page.waitForTimeout(1000);

// Install frame counting and record when each tile starts/first presents.
const started = Date.now();
await page.evaluate(() => {
  window.__probe = { startedAt: Date.now(), tiles: {} };
  const attach = (id, video) => {
    const entry = window.__probe.tiles[id] ??= { id, firstFrameMs: null, frames: 0 };
    if (entry.attached) return;
    entry.attached = true;
    const tick = () => {
      if (typeof video.requestVideoFrameCallback !== 'function') return;
      video.requestVideoFrameCallback(() => {
        entry.frames += 1;
        if (entry.firstFrameMs === null) entry.firstFrameMs = Date.now() - window.__probe.startedAt;
        tick();
      });
    };
    tick();
  };
  const scan = () => {
    document.querySelectorAll('.direct-tile[data-source-id]').forEach((tile) => {
      const video = tile.querySelector('video');
      const id = tile.getAttribute('data-source-id');
      if (video && id) attach(id, video);
    });
  };
  scan();
  window.setInterval(scan, 500);
});

const timeline = [];
const deadline = Date.now() + seconds * 1000;
while (Date.now() < deadline) {
  await page.waitForTimeout(500);
  const snapshot = await page.evaluate(() => ({
    at: Date.now() - window.__probe.startedAt,
    tiles: [...document.querySelectorAll('.direct-tile[data-source-id]')].map((tile) => {
      const id = tile.getAttribute('data-source-id');
      const entry = window.__probe.tiles[id];
      return {
        id,
        cls: tile.className.replace('direct-tile ', ''),
        firstFrameMs: entry?.firstFrameMs ?? null,
      };
    }),
  }));
  timeline.push(snapshot);
}

const firstSeen = (id, predicate) => {
  const hit = timeline.find((sample) => {
    const tile = sample.tiles.find((t) => t.id === id);
    return tile && predicate(tile);
  });
  return hit ? hit.at : null;
};
const ids = [...new Set(timeline.flatMap((s) => s.tiles.map((t) => t.id)))];
console.log('id'.padEnd(20), 'connecting@ms', 'live@ms', 'firstFrame@ms');
for (const id of ids) {
  console.log(
    id.padEnd(20),
    String(firstSeen(id, (t) => t.cls.includes('connecting'))).padStart(12),
    String(firstSeen(id, (t) => t.cls.includes('live'))).padStart(9),
    String(firstSeen(id, (t) => t.firstFrameMs !== null)).padStart(14),
  );
}
console.log('elapsed wall ms:', Date.now() - started);

const api = await page.evaluate(() => window.__api ?? []);
const origin = await page.evaluate(() => window.__probe?.startedAt ?? Date.now());
const slow = api
  .filter((entry) => entry.url.includes('/whep') || entry.url.includes('media-plans') || entry.url.includes('/whep/session'))
  .map((entry) => ({
    url: entry.url.slice(0, 70),
    method: entry.method,
    status: entry.status,
    startOffsetMs: entry.start - origin,
    durationMs: (entry.end ?? entry.start) - entry.start,
  }))
  .sort((a, b) => a.startOffsetMs - b.startOffsetMs);
console.log('== plan/whep calls ==');
for (const entry of slow) console.log(JSON.stringify(entry));
await browser.close();
