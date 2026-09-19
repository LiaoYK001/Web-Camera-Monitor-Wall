import { expect, test } from '@playwright/test';
import { appendFileSync, existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

/**
 * Feedback-5 playback soak against the real product page.
 *
 * It is skipped unless WEBOBS_SOAK=1 so the normal focused suite stays fast.
 * The run drives the real login/plan/player path, counts presented frames per
 * tile through requestVideoFrameCallback, and writes machine-readable evidence
 * next to the server-side samples produced by tests/soak-evidence.mjs.
 *
 *   WEBOBS_SOAK=1 WEBOBS_SOAK_MODE=composite WEBOBS_SOAK_MINUTES=30 \
 *     WEBOBS_SOAK_BASE_URL=http://127.0.0.1:5173 \
 *     node node_modules/@playwright/test/cli.js test -c <config> -g "feedback-5 soak"
 */

const enabled = process.env.WEBOBS_SOAK === '1';
const minutes = Number(process.env.WEBOBS_SOAK_MINUTES ?? '30');
const mode = process.env.WEBOBS_SOAK_MODE === 'composite' ? 'composite' : 'direct';
const targetFps = Number(process.env.WEBOBS_SOAK_TARGET_FPS ?? '30');
const baseUrl = process.env.WEBOBS_SOAK_BASE_URL ?? 'http://127.0.0.1:5173';
const repositoryRoot = fileURLToPath(new URL('../../..', import.meta.url));
const evidenceRoot = process.env.WEBOBS_SOAK_EVIDENCE
  ?? path.join(repositoryRoot, 'tests/artifacts/browser-soak');
const targetFpsMap = process.env.WEBOBS_SOAK_TARGET_FPS_MAP
  ? JSON.parse(process.env.WEBOBS_SOAK_TARGET_FPS_MAP) as Record<string, number>
  : {};

/** The first frame is a documented threshold; long stalls are the other one. */
const FIRST_FRAME_BUDGET_MS = 20_000;
const STALL_BUDGET_MS = 3_000;
const FPS_RATIO = 0.9;

function secret(name: string): string {
  const file = path.join(repositoryRoot, 'secrets', name);
  return existsSync(file) ? readFileSync(file, 'utf8').trim() : '';
}

interface SourceSample {
  id: string;
  frames: number;
  firstFrameMs: number | null;
  lastMediaTime: number;
  maxGapMs: number;
  gaps: number[];
  decodedFrames?: number | null;
  droppedFrames?: number | null;
}

type InstrumentedWindow = Window & { __webobsSoak?: { startedAt: number } };

test.describe('feedback-5 soak', () => {
  test.skip(!enabled, 'set WEBOBS_SOAK=1 to run the long playback soak');
  test(`keeps the ${mode} wall playing for the configured duration`, async ({ page }) => {
    test.setTimeout((minutes + 6) * 60_000);
    const runId = `${new Date().toISOString().replace(/[:.]/g, '-')}-${mode}`;
    const directory = path.join(evidenceRoot, runId);
    mkdirSync(directory, { recursive: true });

    // Track every RTCPeerConnection the player creates so the WebRTC receive
    // path can be attributed (received vs decoded vs dropped, NACKs, loss)
    // instead of guessing whether the gap is transport or presentation.
    await page.addInitScript(() => {
      const Original = window.RTCPeerConnection;
      const tracked: RTCPeerConnection[] = [];
      (window as unknown as { __webobsPeerConnections: RTCPeerConnection[] }).__webobsPeerConnections = tracked;
      class TrackedPeerConnection extends Original {
        constructor(...args: ConstructorParameters<typeof Original>) {
          super(...args);
          tracked.push(this);
        }
      }
      window.RTCPeerConnection = TrackedPeerConnection as unknown as typeof RTCPeerConnection;
    });

    await page.goto(baseUrl);
    // The session probe resolves asynchronously, so wait for the gate *or* the
    // workspace before deciding whether a login is needed.
    let gateVisible = false;
    for (let attempt = 0; attempt < 30; attempt++) {
      if (await page.getByRole('button', { name: '退出登录' }).isVisible().catch(() => false)) break;
      if (await page.getByRole('heading', { name: '登录监控工作台' }).isVisible().catch(() => false)) {
        gateVisible = true;
        break;
      }
      await page.waitForTimeout(1000);
    }
    if (gateVisible) {
      const user = process.env.WEBOBS_DEV_USERNAME || secret('webobs-dev-username.txt');
      const password = process.env.WEBOBS_DEV_PASSWORD || secret('webobs-dev-password.txt');
      expect(user, 'a development username must be available for the real login path').not.toBe('');
      await page.getByLabel('用户名', { exact: true }).fill(user);
      await page.getByLabel('密码', { exact: true }).fill(password);
      await page.getByRole('button', { name: '登录', exact: true }).click();
    }
    await expect(page.getByRole('button', { name: '退出登录' })).toBeVisible({ timeout: 30_000 });

    // The Direct/Hybrid path needs a paired browser: a real RTSP source only
    // plays through a granted device token, not through an anonymous session.
    // WEBOBS_SOAK_PAIR=1 walks the product's own enrollment flow (create, approve
    // from the admin session, complete) instead of stubbing authorization.
    if (process.env.WEBOBS_SOAK_PAIR === '1') {
      // The app's own local runtime also touches the same IndexedDB and can clear
      // private state between the create and complete steps, so the sequence is
      // retried as a whole instead of being treated as a one-shot.
      let pairing: { state?: string; skipped?: boolean; grants?: number; error?: string } = { error: 'not attempted' };
      for (let attempt = 1; attempt <= 3; attempt++) {
        pairing = await page.evaluate(async () => {
          try {
            const enrollment = await import('/src/browserEnrollment.ts');
            const current = await enrollment.currentBrowserPairing().catch(() => null);
            if (current?.state === 'approved') return { skipped: true, state: current.state };
            const began = await enrollment.beginBrowserEnrollment('soak-browser');
            const registry = await (await fetch('/api/v1/cameras', { credentials: 'same-origin' })).json();
            const cameraGrants = (registry.cameras ?? []).map((camera: { id: string; profiles?: Array<{ id: string }> }) => ({
              cameraId: camera.id,
              profileIds: (camera.profiles ?? []).map((profile) => profile.id),
              permissions: ['view'],
              credentialMode: 'none',
            }));
            const response = await fetch(`/api/v2/enrollments/${began.enrollmentId}/approve`, {
              method: 'POST', credentials: 'same-origin',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ pairingCode: began.pairingCode, cameraGrants }),
            });
            if (!response.ok) return { error: `approve failed HTTP ${response.status}` };
            const completed = await enrollment.completeBrowserEnrollment();
            return { state: completed?.state ?? 'unknown', grants: cameraGrants.length };
          } catch (error) {
            return { error: String((error as Error)?.message ?? error) };
          }
        });
        console.log(`[browser-soak] pairing attempt ${attempt}: ${JSON.stringify(pairing)}`);
        if (!pairing.error) break;
        await page.waitForTimeout(2000);
      }
      expect(pairing.error, 'the browser must be paired for the direct/hybrid path').toBeUndefined();
      await page.reload();
      await expect(page.getByRole('button', { name: '退出登录' })).toBeVisible({ timeout: 30_000 });
    }

    // Switch to the playback mode under test through the real UI controls.  The
    // monitor workspace and the studio workspace label the same choice
    // differently and the workspace controls mount after the session loads, so
    // poll until one of the spellings is on screen before clicking.
    const modeLabels = mode === 'composite' ? ['服务端合成', '服务端 Program'] : ['网关直通', '浏览器媒体'];
    let switched = false;
    for (let attempt = 0; attempt < 30 && !switched; attempt++) {
      for (const label of modeLabels) {
        const button = page.getByRole('button', { name: label });
        if (await button.count()) {
          await button.first().click().catch(() => undefined);
          switched = true;
          break;
        }
      }
      if (!switched) await page.waitForTimeout(1000);
    }
    console.log(`[browser-soak] mode switch to ${mode}: ${switched ? 'clicked' : 'not found'}`);
    if (mode === 'composite') {
      await page.waitForSelector('video[aria-label="实时合成节目画面"]', { timeout: 30_000 }).catch(() => undefined);
    }

    await page.evaluate(() => {
      const state = { startedAt: Date.now(), entries: {} as Record<string, unknown> };
      (window as InstrumentedWindow).__webobsSoak = state;
      const attach = (id: string, video: HTMLVideoElement) => {
        const entries = state.entries as Record<string, {
          id: string; frames: number; firstFrameMs: number | null; lastFrameAt: number;
          lastMediaTime: number; maxGapMs: number; gaps: number[]; attached?: boolean;
        }>;
        const entry = entries[id] ?? {
          id, frames: 0, firstFrameMs: null, lastFrameAt: 0, lastMediaTime: 0, maxGapMs: 0, gaps: [],
        };
        entries[id] = entry;
        if (entry.attached) return;
        entry.attached = true;
        const tick = () => {
          const callback = (video as HTMLVideoElement & {
            requestVideoFrameCallback?: (callback: () => void) => number;
          }).requestVideoFrameCallback;
          if (typeof callback !== 'function') return;
          callback.call(video, () => {
            const now = Date.now();
            entry.frames += 1;
            if (entry.firstFrameMs === null) entry.firstFrameMs = now - state.startedAt;
            if (entry.lastFrameAt > 0) {
              const gap = now - entry.lastFrameAt;
              if (gap > 1000) { entry.gaps.push(gap); entry.maxGapMs = Math.max(entry.maxGapMs, gap); }
            }
            entry.lastFrameAt = now;
            entry.lastMediaTime = video.currentTime;
            tick();
          });
        };
        tick();
      };
      const scan = () => {
        // Composite measures the single program player; direct/hybrid measures
        // every tile the wall renders.
        const program = document.querySelector('video[aria-label="实时合成节目画面"]');
        if (program) attach('program', program as HTMLVideoElement);
        document.querySelectorAll('.direct-tile[data-source-id]').forEach((tile) => {
          const video = tile.querySelector('video');
          const id = tile.getAttribute('data-source-id');
          if (video && id) attach(id, video as HTMLVideoElement);
        });
      };
      scan();
      window.setInterval(scan, 2000);
    });

    const startedAt = Date.now();
    const deadline = startedAt + minutes * 60_000;
    const timeline: Array<{ at: number; entries: SourceSample[]; rtc?: Array<Record<string, number | string>> }> = [];
    while (Date.now() < deadline) {
      await page.waitForTimeout(15_000);
      const snapshot = await page.evaluate(() => {
        const state = (window as InstrumentedWindow).__webobsSoak as unknown as {
          entries: Record<string, SourceSample>;
        };
        // Decoded frames come from the element's own playback-quality counters;
        // comparing them with the presented-frame count separates "the pipeline
        // did not deliver" from "this headless surface did not present".
        const videos: Record<string, HTMLVideoElement> = {};
        const program = document.querySelector('video[aria-label="实时合成节目画面"]');
        if (program) videos.program = program as HTMLVideoElement;
        document.querySelectorAll('.direct-tile[data-source-id]').forEach((tile) => {
          const video = tile.querySelector('video');
          const id = tile.getAttribute('data-source-id');
          if (video && id) videos[id] = video as HTMLVideoElement;
        });
        return Object.values(state?.entries ?? {}).map((entry) => {
          const video = videos[entry.id];
          const quality = video && typeof video.getVideoPlaybackQuality === 'function'
            ? video.getVideoPlaybackQuality() : null;
          return {
            id: entry.id, frames: entry.frames, firstFrameMs: entry.firstFrameMs,
            lastMediaTime: entry.lastMediaTime, maxGapMs: entry.maxGapMs, gaps: entry.gaps.slice(-20),
            decodedFrames: quality ? quality.totalVideoFrames : null,
            droppedFrames: quality ? quality.droppedVideoFrames : null,
          };
        });
      });
      const rtc = await page.evaluate(async () => {
        const connections = (window as unknown as { __webobsPeerConnections?: RTCPeerConnection[] })
          .__webobsPeerConnections ?? [];
        const inbound: Array<Record<string, number | string>> = [];
        for (const connection of connections) {
          try {
            const report = await connection.getStats();
            report.forEach((entry: Record<string, unknown>) => {
              if (entry.type !== 'inbound-rtp' || entry.kind !== 'video') return;
              inbound.push({
                id: String(entry.id ?? ''),
                framesReceived: Number(entry.framesReceived ?? 0),
                framesDecoded: Number(entry.framesDecoded ?? 0),
                framesDropped: Number(entry.framesDropped ?? 0),
                keyFramesDecoded: Number(entry.keyFramesDecoded ?? 0),
                packetsLost: Number(entry.packetsLost ?? 0),
                nackCount: Number(entry.nackCount ?? 0),
                pliCount: Number(entry.pliCount ?? 0),
                freezeCount: Number(entry.freezeCount ?? 0),
                totalFreezesDuration: Number(entry.totalFreezesDuration ?? 0),
                jitterBufferDelay: Number(entry.jitterBufferDelay ?? 0),
                jitterBufferEmittedCount: Number(entry.jitterBufferEmittedCount ?? 0),
              });
            });
          } catch { /* stats unavailable for this connection */ }
        }
        return inbound;
      });
      timeline.push({ at: Date.now() - startedAt, entries: snapshot, rtc });
      // Append as we go: a long soak can be interrupted, and the samples taken so
      // far are still evidence.
      appendFileSync(path.join(directory, 'browser-soak-timeline.jsonl'),
        JSON.stringify(timeline.at(-1)) + '\n');
      console.log(`[browser-soak] ${Math.round((Date.now() - startedAt) / 1000)}s ` +
        snapshot.map((entry) => `${entry.id}=${entry.frames}f(presented)/${entry.decodedFrames ?? '?'}f(decoded)/${entry.lastMediaTime.toFixed(1)}s`).join(' '));
    }

    const durationSeconds = (Date.now() - startedAt) / 1000;
    const final = timeline.at(-1)?.entries ?? [];
    const measured = final.map((entry) => {
      const target = targetFpsMap[entry.id] ?? targetFps;
      const fps = entry.frames / durationSeconds;
      const decodedFps = entry.decodedFrames === null || entry.decodedFrames === undefined
        ? null : Number((entry.decodedFrames / durationSeconds).toFixed(2));
      return {
        id: entry.id,
        frames: entry.frames,
        measuredFps: Number(fps.toFixed(2)),
        decodedFps,
        decodedFrames: entry.decodedFrames ?? null,
        droppedFrames: entry.droppedFrames ?? null,
        targetFps: target,
        fpsRatio: Number((fps / target).toFixed(3)),
        firstFrameMs: entry.firstFrameMs,
        lastMediaTime: Number(entry.lastMediaTime.toFixed(2)),
        maxGapMs: entry.maxGapMs,
        stalls: entry.gaps.filter((gap) => gap > STALL_BUDGET_MS).length,
      };
    });
    const checks = [
      {
        name: 'every sampled source advanced its media time',
        passed: measured.length > 0 && measured.every((entry) => entry.lastMediaTime > 1),
        detail: measured.map((entry) => `${entry.id}: ${entry.lastMediaTime}s`).join(', ') || 'no source was sampled',
      },
      {
        name: 'no unexpected frame stall beyond 3s',
        passed: measured.every((entry) => entry.maxGapMs <= STALL_BUDGET_MS),
        detail: measured.map((entry) => `${entry.id}: max gap ${entry.maxGapMs}ms`).join(', '),
      },
      {
        name: 'first frame within 20s',
        passed: measured.every((entry) => entry.firstFrameMs !== null && entry.firstFrameMs <= FIRST_FRAME_BUDGET_MS),
        detail: measured.map((entry) => `${entry.id}: ${entry.firstFrameMs ?? 'none'}ms`).join(', '),
      },
      {
        name: `decoded frame rate is at least ${FPS_RATIO * 100}% of the configured target`,
        passed: measured.length > 0 && measured.every((entry) => entry.fpsRatio >= FPS_RATIO),
        detail: measured.map((entry) => `${entry.id}: ${entry.measuredFps}/${entry.targetFps} fps (${entry.fpsRatio})`).join(', '),
      },
    ];
    const report = {
      runId,
      mode,
      targetFps,
      baseUrl,
      browserVersion: page.context().browser()?.version() ?? '',
      durationSeconds: Number(durationSeconds.toFixed(1)),
      firstFrameBudgetMs: FIRST_FRAME_BUDGET_MS,
      stallBudgetMs: STALL_BUDGET_MS,
      fpsRatioRequired: FPS_RATIO,
      measured,
      checks,
      passed: checks.every((check) => check.passed) && measured.length > 0,
    };
    writeFileSync(path.join(directory, 'browser-soak.json'), JSON.stringify(report, null, 2));
    writeFileSync(path.join(directory, 'browser-soak-timeline.json'), JSON.stringify(timeline, null, 2));
    writeFileSync(path.join(directory, 'browser-soak.md'), [
      `# Browser soak — ${runId}`,
      '',
      `- mode: ${mode}, target fps: ${targetFps}, duration: ${durationSeconds.toFixed(0)}s`,
      `- browser: ${report.browserVersion}`,
      '',
      '| source | frames | fps | target | ratio | first frame | last media time | max gap |',
      '|---|---|---|---|---|---|---|---|',
      ...measured.map((entry) => `| ${entry.id} | ${entry.frames} | ${entry.measuredFps} | ${entry.targetFps} | ${entry.fpsRatio} | ${entry.firstFrameMs ?? 'n/a'} | ${entry.lastMediaTime} | ${entry.maxGapMs} |`),
      '',
      ...checks.map((check) => `- ${check.passed ? 'PASS' : 'FAIL'} — ${check.name}: ${check.detail}`),
      '',
      report.passed ? 'Verdict: PASS' : 'Verdict: FAIL',
      '',
    ].join('\n'));
    console.log(`[browser-soak] evidence ${directory}`);
    expect(measured.length, 'the soak must observe at least one playing source').toBeGreaterThan(0);
  });
});
