import { expect, test } from '@playwright/test';
import { appendFileSync, existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import {
  FPS_RATIO, FIRST_FRAME_BUDGET_MS, MIN_FORMAL_SECONDS, REOPEN_BUDGET_MS, STALL_BUDGET_MS, STATUS,
  buildVerdict, statusIsPass,
} from '../../../tests/soak-verdict.mjs';

/**
 * Feedback-5 playback soak against the real product page.
 *
 * Skipped unless WEBOBS_SOAK=1 so the focused suite stays fast.  The run drives
 * the real login/plan/player path and hands everything it observed to the shared
 * verdict module (tests/soak-verdict.mjs), which is also what the recompute tool
 * uses.  The observation rules the previous version of this file got wrong:
 *
 *  - the observer is installed *before* the mode switch, so the first-frame
 *    measurement covers plan, queue, activation, ICE and play;
 *  - observers are re-attached when the player replaces a <video> element, and
 *    `getVideoPlaybackQuality()` deltas are accumulated per generation instead of
 *    being read once from whichever element happens to be mounted at the end;
 *  - an in-progress gap (time since the last frame) is reported alongside the
 *    largest completed gap, so a stream that stops for good still fails;
 *  - the expected source set and every per-source target are explicit inputs, and
 *    a missing source or a missing target can never pass;
 *  - the final snapshot is taken and the evidence is written before the run ends,
 *    and a short run can only ever produce a smoke result.
 *
 *   WEBOBS_SOAK=1 WEBOBS_SOAK_MODE=composite WEBOBS_SOAK_MINUTES=30 \
 *     WEBOBS_SOAK_BASE_URL=http://127.0.0.1:5173 \
 *     node node_modules/@playwright/test/cli.js test -c <config> -g "feedback-5 soak"
 */

const enabled = process.env.WEBOBS_SOAK === '1';
const minutes = Number(process.env.WEBOBS_SOAK_MINUTES ?? '30');
const observationSeconds = Number(process.env.WEBOBS_SOAK_SECONDS ?? String(minutes * 60));
// A run shorter than the formal window is a smoke run; it must never be able to
// report a formal PASS.
const smoke = process.env.WEBOBS_SOAK_SMOKE === '1' || observationSeconds < MIN_FORMAL_SECONDS;
const stopAfterSeconds = process.env.WEBOBS_SOAK_STOP_AFTER_SECONDS
  ? Number(process.env.WEBOBS_SOAK_STOP_AFTER_SECONDS) : null;
const mode = process.env.WEBOBS_SOAK_MODE === 'composite' ? 'composite' : 'direct';
const sourceType = process.env.WEBOBS_SOAK_SOURCE_TYPE ?? 'unknown';
const explicitTargetFps = process.env.WEBOBS_SOAK_TARGET_FPS
  ? Number(process.env.WEBOBS_SOAK_TARGET_FPS) : null;
const baseUrl = process.env.WEBOBS_SOAK_BASE_URL ?? 'http://127.0.0.1:5173';
const repositoryRoot = fileURLToPath(new URL('../../..', import.meta.url));
const evidenceRoot = process.env.WEBOBS_SOAK_EVIDENCE
  ?? path.join(repositoryRoot, 'tests/artifacts/browser-soak');
const targetFpsMap = process.env.WEBOBS_SOAK_TARGET_FPS_MAP
  ? JSON.parse(process.env.WEBOBS_SOAK_TARGET_FPS_MAP) as Record<string, number>
  : {};
const expectedOverride = process.env.WEBOBS_SOAK_EXPECTED_SOURCES
  ? JSON.parse(process.env.WEBOBS_SOAK_EXPECTED_SOURCES) : null;
const excusedStallWindows = process.env.WEBOBS_SOAK_EXCUSED_WINDOWS
  ? JSON.parse(process.env.WEBOBS_SOAK_EXCUSED_WINDOWS) : [];
const readyTimeoutMs = Number(process.env.WEBOBS_SOAK_READY_TIMEOUT_MS ?? '180000');

function secret(name: string): string {
  const file = path.join(repositoryRoot, 'secrets', name);
  return existsSync(file) ? readFileSync(file, 'utf8').trim() : '';
}

interface ObservedEntry {
  id: string;
  presentedFrames: number;
  decodedFrames: number;
  droppedFrames: number;
  firstFrameMs: number | null;
  endedMaxGapMs: number;
  inProgressGapMsAtEnd: number | null;
  longStalls: Array<{ fromMs: number; toMs: number; gapMs: number }>;
  mediaTimeSeconds: number;
  generations: number;
  counterResets: number;
  teardownCount: number;
  attached: boolean;
  receivedFrames: number | null;
  rtc: Record<string, number> | null;
}

interface ObservedSnapshot {
  atMs: number;
  instrumentedAtMs: number;
  observationStartedAtMs: number | null;
  actionAtMs: number | null;
  entries: ObservedEntry[];
  events: Array<Record<string, unknown>>;
}

type InstrumentedWindow = Window & {
  __webobsSoak?: {
    actionAt: number | null;
    snapshot: () => Promise<ObservedSnapshot>;
    scan: () => void;
    beginObservation: () => void;
  };
};

/**
 * Runs inside the page.  It must not close over anything but its argument:
 * Playwright serialises the function source.
 */
function installSoakInstrumentation(options: { stallBudgetMs: number }) {
  const scope = window as unknown as {
    __webobsSoak?: Record<string, unknown>;
    __webobsPeerConnections?: RTCPeerConnection[];
  };
  const previous = scope.__webobsSoak as { stop?: () => void } | undefined;
  if (previous?.stop) previous.stop();

  interface Entry {
    id: string;
    presentedFrames: number;
    decodedFrames: number;
    droppedFrames: number;
    firstFrameMs: number | null;
    firstFrameAtMs: number | null;
    lastFrameAtMs: number | null;
    lastMediaTime: number;
    endedMaxGapMs: number;
    longStalls: Array<{ fromMs: number; toMs: number; gapMs: number }>;
    generations: number;
    counterResets: number;
    teardownCount: number;
    video: HTMLVideoElement | null;
    token: number;
    lastDecodedSample: number;
    lastDroppedSample: number;
  }

  const state: Record<string, unknown> = {
    instrumentedAt: performance.now(),
    instrumentedAtMs: Math.round(performance.now()),
    timeOrigin: performance.timeOrigin,
    actionAt: null,
    observationStartedAtMs: null as number | null,
    entries: {} as Record<string, Entry>,
    events: [] as Array<Record<string, unknown>>,
    interval: 0,
  };
  scope.__webobsSoak = state;

  const record = (type: string, id: string, extra: Record<string, unknown> = {}) => {
    (state.events as Array<Record<string, unknown>>).push({
      type, id, atMs: Math.round(performance.now()), ...extra,
    });
  };
  const entries = state.entries as Record<string, Entry>;
  const entryFor = (id: string): Entry => {
    let entry = entries[id];
    if (!entry) {
      entry = entries[id] = {
        id, presentedFrames: 0, decodedFrames: 0, droppedFrames: 0,
        firstFrameMs: null, firstFrameAtMs: null, lastFrameAtMs: null, lastMediaTime: 0,
        endedMaxGapMs: 0, longStalls: [], generations: 0, counterResets: 0, teardownCount: 0,
        video: null, token: 0, lastDecodedSample: 0, lastDroppedSample: 0,
      };
    }
    return entry;
  };

  // Playback-quality counters belong to one element and restart at zero when the
  // player mounts a new one, so every generation contributes a delta.
  const sampleQuality = (entry: Entry) => {
    const video = entry.video;
    if (!video || typeof video.getVideoPlaybackQuality !== 'function') return;
    let quality: VideoPlaybackQuality | null = null;
    try { quality = video.getVideoPlaybackQuality(); } catch { return; }
    if (!quality) return;
    const decoded = Number(quality.totalVideoFrames ?? 0);
    const dropped = Number(quality.droppedVideoFrames ?? 0);
    if (decoded < entry.lastDecodedSample || dropped < entry.lastDroppedSample) {
      entry.counterResets += 1;
      record('counter-reset', entry.id, { decoded, previous: entry.lastDecodedSample });
      entry.lastDecodedSample = decoded;
      entry.lastDroppedSample = dropped;
      return;
    }
    entry.decodedFrames += decoded - entry.lastDecodedSample;
    entry.droppedFrames += dropped - entry.lastDroppedSample;
    entry.lastDecodedSample = decoded;
    entry.lastDroppedSample = dropped;
  };

  const detach = (entry: Entry, reason: string) => {
    if (!entry.video) return;
    sampleQuality(entry);
    record('teardown', entry.id, { reason, generation: entry.generations });
    entry.teardownCount += 1;
    entry.video = null;
    entry.token += 1;
  };

  const attach = (id: string, video: HTMLVideoElement) => {
    const entry = entryFor(id);
    if (entry.video === video) return;
    if (entry.video) detach(entry, 'element-replaced');
    entry.generations += 1;
    entry.video = video;
    entry.token += 1;
    const token = entry.token;
    let quality: VideoPlaybackQuality | null = null;
    try {
      quality = typeof video.getVideoPlaybackQuality === 'function' ? video.getVideoPlaybackQuality() : null;
    } catch { quality = null; }
    entry.lastDecodedSample = Number(quality?.totalVideoFrames ?? 0);
    entry.lastDroppedSample = Number(quality?.droppedVideoFrames ?? 0);
    record('attach', id, { generation: entry.generations, baselineDecoded: entry.lastDecodedSample });
    const tick = () => {
      const element = video as HTMLVideoElement & { requestVideoFrameCallback?: (callback: () => void) => number };
      if (typeof element.requestVideoFrameCallback !== 'function') return;
      element.requestVideoFrameCallback(() => {
        if (entry.token !== token || entry.video !== video) return;
        const now = performance.now();
        entry.presentedFrames += 1;
        if (entry.firstFrameAtMs === null) {
          entry.firstFrameAtMs = now;
          entry.firstFrameMs = Math.round(now - (state.instrumentedAt as number));
        }
        if (entry.lastFrameAtMs !== null) {
          const gap = now - entry.lastFrameAtMs;
          if (gap > entry.endedMaxGapMs) entry.endedMaxGapMs = Math.round(gap);
          if (gap > options.stallBudgetMs) {
            entry.longStalls.push({
              fromMs: Math.round(entry.lastFrameAtMs), toMs: Math.round(now), gapMs: Math.round(gap),
            });
          }
        }
        entry.lastFrameAtMs = now;
        entry.lastMediaTime = video.currentTime;
        tick();
      });
    };
    tick();
  };

  const videosById = (): Record<string, HTMLVideoElement> => {
    const found: Record<string, HTMLVideoElement> = {};
    const program = document.querySelector('video[aria-label="实时合成节目画面"]');
    if (program) found.program = program as HTMLVideoElement;
    document.querySelectorAll('.direct-tile[data-source-id]').forEach((tile) => {
      const id = tile.getAttribute('data-source-id');
      const video = tile.querySelector('video');
      if (id && video) found[id] = video as HTMLVideoElement;
    });
    return found;
  };

  // The observation window starts once every expected source is ready, so the
  // counters and the duration describe exactly the same interval.  The first
  // frame keeps its earlier timestamp: it measures plan, queue, activation, ICE
  // and play, which happen before the window starts.
  const beginObservation = () => {
    state.observationStartedAtMs = Math.round(performance.now());
    for (const entry of Object.values(entries)) {
      sampleQuality(entry);
      entry.presentedFrames = 0;
      entry.decodedFrames = 0;
      entry.droppedFrames = 0;
      entry.endedMaxGapMs = 0;
      entry.longStalls = [];
    }
    record('observation-start', '', { atMs: state.observationStartedAtMs });
  };

  const scan = () => {
    const found = videosById();
    for (const [id, video] of Object.entries(found)) attach(id, video);
    for (const entry of Object.values(entries)) {
      if (entry.video && found[entry.id] !== entry.video) detach(entry, 'element-gone');
      sampleQuality(entry);
    }
  };

  const snapshot = async () => {
    scan();
    const connections = scope.__webobsPeerConnections ?? [];
    const inbound: Record<string, Record<string, number>> = {};
    for (const entry of Object.values(entries)) {
      const video = entry.video;
      const stream = video?.srcObject as MediaStream | null | undefined;
      if (!video || !stream) continue;
      const tracks = new Set<MediaStreamTrack>(stream.getVideoTracks ? stream.getVideoTracks() : []);
      const connection = connections.find((candidate) => {
        try {
          return candidate.getReceivers().some((receiver) => receiver.track && tracks.has(receiver.track));
        } catch { return false; }
      });
      if (!connection) continue;
      try {
        const report = await connection.getStats();
        report.forEach((item) => {
          const stats = item as unknown as Record<string, unknown>;
          if (stats.type !== 'inbound-rtp' || stats.kind !== 'video') return;
          inbound[entry.id] = {
            framesReceived: Number(stats.framesReceived ?? 0),
            framesDecoded: Number(stats.framesDecoded ?? 0),
            framesDropped: Number(stats.framesDropped ?? 0),
            packetsLost: Number(stats.packetsLost ?? 0),
            nackCount: Number(stats.nackCount ?? 0),
            keyFramesDecoded: Number(stats.keyFramesDecoded ?? 0),
            freezeCount: Number(stats.freezeCount ?? 0),
          };
        });
      } catch { /* stats unavailable for this connection */ }
    }
    const now = performance.now();
    return {
      atMs: Math.round(now),
      instrumentedAtMs: Math.round(state.instrumentedAt as number),
      observationStartedAtMs: state.observationStartedAtMs === null ? null : Math.round(state.observationStartedAtMs as number),
      actionAtMs: state.actionAt === null ? null : Math.round(state.actionAt as number),
      entries: Object.values(entries).map((entry) => ({
        id: entry.id,
        presentedFrames: entry.presentedFrames,
        decodedFrames: entry.decodedFrames,
        droppedFrames: entry.droppedFrames,
        firstFrameMs: entry.firstFrameMs,
        endedMaxGapMs: entry.endedMaxGapMs,
        inProgressGapMsAtEnd: entry.lastFrameAtMs === null ? null : Math.round(now - entry.lastFrameAtMs),
        longStalls: entry.longStalls,
        mediaTimeSeconds: Number(entry.lastMediaTime ?? 0),
        generations: entry.generations,
        counterResets: entry.counterResets,
        teardownCount: entry.teardownCount,
        attached: entry.video !== null,
        receivedFrames: inbound[entry.id]?.framesReceived ?? null,
        rtc: inbound[entry.id] ?? null,
      })),
      events: state.events as Array<Record<string, unknown>>,
    };
  };

  state.snapshot = snapshot;
  state.scan = scan;
  state.beginObservation = beginObservation;
  state.stop = () => {
    if (state.interval) window.clearInterval(state.interval as number);
    state.interval = 0;
  };
  state.interval = window.setInterval(scan, 1000);
  scan();
}

test.describe('feedback-5 soak', () => {
  test.skip(!enabled, 'set WEBOBS_SOAK=1 to run the long playback soak');
  test(`keeps the ${mode} wall playing for the configured duration`, async ({ page }) => {
    test.setTimeout((Math.ceil(observationSeconds / 60) + 12) * 60_000);
    const runId = `${new Date().toISOString().replace(/[:.]/g, '-')}-${mode}`;
    const directory = path.join(evidenceRoot, runId);
    mkdirSync(directory, { recursive: true });

    // Track every RTCPeerConnection the player creates so the WebRTC receive
    // path can be attributed instead of guessed.
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

    if (process.env.WEBOBS_SOAK_PAIR === '1') {
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
            // An exception whose message is empty stringified to "", which made a
            // pairing failure undiagnosable; keep the name and where it happened.
            const detail = error instanceof Error
              ? `${error.name}: ${error.message || '(no message)'} @ ${(error.stack ?? '').split('\\n')[1]?.trim() ?? ''}`
              : String(error);
            return { error: detail };
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

    // The expected source set comes from the product's own scene document unless
    // it is supplied explicitly; a set derived from what happens to be on screen
    // could never detect a missing tile.
    const expectedIds: string[] = await (async () => {
      if (expectedOverride) {
        return Array.isArray(expectedOverride)
          ? expectedOverride.map((entry) => (typeof entry === 'string' ? entry : entry.id))
          : Object.keys(expectedOverride);
      }
      if (mode === 'composite') return ['program'];
      const scene = await page.evaluate(async () => {
        try {
          const response = await fetch('/api/v1/scene', { credentials: 'same-origin', cache: 'no-store' });
          if (!response.ok) return null;
          return await response.json();
        } catch { return null; }
      });
      const sources = (scene?.sources ?? []) as Array<{ id: string; kind?: string }>;
      return sources.filter((source) => !source.kind || source.kind === 'camera').map((source) => source.id);
    })();
    const expected = expectedIds.map((id) => ({
      id,
      targetFps: targetFpsMap[id] ?? explicitTargetFps ?? undefined,
    }));
    console.log(`[browser-soak] expected sources: ${JSON.stringify(expected)}`);

    // Sampling is installed before the start action so the first-frame timing
    // covers plan, queue, activation, ICE and play.
    await page.evaluate(installSoakInstrumentation, { stallBudgetMs: STALL_BUDGET_MS });

    const modeLabels = mode === 'composite' ? ['服务端合成', '服务端 Program'] : ['网关直通', '浏览器媒体'];
    await page.evaluate(() => {
      const state = (window as InstrumentedWindow).__webobsSoak;
      if (state) state.actionAt = performance.now();
    });
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

    const snap = () => page.evaluate(async () => {
      const state = (window as InstrumentedWindow).__webobsSoak;
      if (!state) throw new Error('the soak instrumentation is not installed');
      return await state.snapshot();
    });
    const engineSources = async () => (mode !== 'composite' ? null : page.evaluate(async () => {
      try {
        const response = await fetch('/api/v1/sources/status', { credentials: 'same-origin', cache: 'no-store' });
        if (!response.ok) return null;
        return await response.json();
      } catch { return null; }
    }));

    // Observation starts once every expected source has produced a frame.
    const readyDeadline = Date.now() + readyTimeoutMs;
    let readySnapshot = await snap();
    let allExpectedReady = expected.every((entry) => readySnapshot.entries.some(
      (observed) => observed.id === entry.id && observed.firstFrameMs !== null));
    while (!allExpectedReady && Date.now() < readyDeadline) {
      await page.waitForTimeout(2000);
      readySnapshot = await snap();
      allExpectedReady = expected.every((entry) => readySnapshot.entries.some(
        (observed) => observed.id === entry.id && observed.firstFrameMs !== null));
    }
    console.log(`[browser-soak] all expected sources ready: ${allExpectedReady}`);

    // The observation window opens now: the counters, the gap accounting and the
    // duration then describe exactly the same interval, while the first-frame
    // measurement keeps its earlier timestamp (it covers plan, queue, activation,
    // ICE and play, which happen before the window starts).
    if (allExpectedReady) {
      await page.evaluate(() => {
        const state = (window as InstrumentedWindow).__webobsSoak;
        if (state) state.beginObservation();
      });
    }
    const readyAt = Date.now();
    const timeline: Array<Record<string, unknown>> = [];
    const record = (snapshot: ObservedSnapshot, sources: Record<string, unknown> | null, final: boolean) => {
      const at = snapshot.observationStartedAtMs === null ? 0 : snapshot.atMs - snapshot.observationStartedAtMs;
      const sample = {
        at,
        final,
        atMs: snapshot.atMs,
        instrumentedAtMs: snapshot.instrumentedAtMs,
        actionAtMs: snapshot.actionAtMs,
        observationStartedAtMs: snapshot.observationStartedAtMs,
        entries: snapshot.entries,
        events: snapshot.events,
        sources,
      };
      timeline.push(sample);
      appendFileSync(path.join(directory, 'browser-soak-timeline.jsonl'), JSON.stringify(sample) + '\n');
      console.log(`[browser-soak] ${Math.round(at / 1000)}s ` + snapshot.entries.map((entry) =>
        `${entry.id}=${entry.presentedFrames}p/${entry.decodedFrames}d/${entry.mediaTimeSeconds.toFixed(1)}s`).join(' '));
    };

    if (allExpectedReady) {
      const observationEnd = readyAt + observationSeconds * 1000;
      const stopAt = stopAfterSeconds === null ? observationEnd : Math.min(observationEnd, readyAt + stopAfterSeconds * 1000);
      while (Date.now() < stopAt) {
        await page.waitForTimeout(Math.min(15_000, Math.max(500, stopAt - Date.now())));
        record(await snap(), await engineSources(), false);
      }
    } else {
      // Without every expected source there is no valid observation window; keep
      // the evidence that exists, but do not spend the full window pretending.
      record(await snap(), await engineSources(), false);
    }

    // Order matters: final snapshot, then evidence, then (only afterwards) does
    // the test end and Playwright close the page.
    const finalSnapshot = await snap();
    const finalSources = await engineSources();
    record(finalSnapshot, finalSources, true);

    // The duration comes from the page's monotonic clock, the same clock the
    // frame counters and the in-progress gap use.
    const durationSeconds = finalSnapshot.observationStartedAtMs === null ? 0
      : (finalSnapshot.atMs - finalSnapshot.observationStartedAtMs) / 1000;
    const entriesById = new Map(finalSnapshot.entries.map((entry) => [entry.id, entry]));
    const programEntry = entriesById.get('program') ?? null;
    const inputs = ((finalSources?.sources ?? []) as Array<{ id: string; state?: string }>)
      .map((source) => ({ id: source.id, state: String(source.state ?? 'unknown') }));
    const unhealthySamples = timeline.filter((sample) => {
      const sources = sample.sources as { sources?: Array<{ state?: string }> } | null;
      return (sources?.sources ?? []).some((source) => source.state !== 'healthy');
    }).length;

    const verdict = buildVerdict({
      runId,
      mode,
      sourceType,
      targetFps: explicitTargetFps ?? undefined,
      expected,
      observed: finalSnapshot.entries,
      observation: {
        installedBeforeAction: finalSnapshot.actionAtMs !== null
          && finalSnapshot.instrumentedAtMs <= finalSnapshot.actionAtMs,
        modeSwitch: switched ? 'ok' : 'failed',
        allExpectedReady,
        // No valid window without every expected source: that is incomplete, and
        // the expected-sources check fails as well.
        complete: allExpectedReady,
        earlyTeardown: !allExpectedReady,
        durationSeconds,
        smoke,
        finalSnapshotWritten: true,
      },
      program: mode === 'composite' && programEntry ? {
        ...programEntry,
        targetFps: targetFpsMap.program ?? explicitTargetFps ?? null,
        inputsHealthy: inputs,
        unhealthySamples,
      } : undefined,
      excusedStallWindows,
      limitations: [
        smoke ? 'this is a smoke run: shorter than the formal observation window' : null,
        allExpectedReady ? null : 'not every expected source produced a frame',
      ].filter(Boolean),
    });

    const report = {
      ...verdict,
      baseUrl,
      browserVersion: page.context().browser()?.version() ?? '',
      observedObservationSeconds: observationSeconds,
      allExpectedReady,
      samples: timeline.length,
      events: finalSnapshot.events,
    };
    writeFileSync(path.join(directory, 'browser-soak.json'), JSON.stringify(report, null, 2));
    writeFileSync(path.join(directory, 'browser-soak-timeline.json'), JSON.stringify(timeline, null, 2));
    writeFileSync(path.join(directory, 'browser-soak.md'), [
      `# Browser soak — ${runId}`,
      '',
      `- mode: ${mode}, source type: ${sourceType}, expected targets: ${JSON.stringify(expected)}`,
      `- duration: ${durationSeconds.toFixed(0)}s (formal window ${MIN_FORMAL_SECONDS}s), smoke: ${smoke}`,
      `- browser: ${report.browserVersion}, all expected sources ready: ${allExpectedReady}`,
      `- thresholds: first frame ${FIRST_FRAME_BUDGET_MS}ms, reopen ${REOPEN_BUDGET_MS}ms, stall ${STALL_BUDGET_MS}ms, decoded ratio ${FPS_RATIO}`,
      '',
      '| source | decoded fps | target | ratio | presented fps | received fps | first frame | max gap | in-progress gap | media time | generations |',
      '|---|---|---|---|---|---|---|---|---|---|---|',
      ...verdict.measured.map((row) => `| ${row.id} | ${row.decodedFps ?? 'unknown'} | ${row.targetFps ?? 'none'} | ${row.decodedRatio ?? 'n/a'} | ${row.presentedFps ?? 'unknown'} | ${row.receivedFps ?? 'unknown'} | ${row.firstFrameMs ?? 'never'} | ${row.endedMaxGapMs} | ${row.inProgressGapMsAtEnd ?? 'n/a'} | ${row.mediaTimeSeconds ?? 'n/a'} | ${row.generations} |`),
      '',
      ...verdict.checks.map((item) => `- ${item.passed ? 'PASS' : 'FAIL'}${item.blocking ? '' : ' (reported)'} — ${item.name}: ${item.detail}`),
      '',
      ...verdict.notes.map((note) => `- note: ${note}`),
      '',
      `Verdict: ${verdict.status}`,
      '',
    ].join('\n'));
    console.log(`[browser-soak] evidence ${directory}`);
    console.log(`[browser-soak] verdict ${verdict.status}`);

    if (!smoke) {
      expect(verdict.status,
        `the formal soak must pass; failing checks: ${verdict.checks.filter((item) => item.blocking && !item.passed).map((item) => item.id).join(', ') || '(none)'}`)
        .toBe(STATUS.PASS);
    } else {
      expect(statusIsPass(verdict.status),
        `the smoke run must not report a failure; verdict ${verdict.status}`).toBe(true);
      expect(verdict.status).not.toBe(STATUS.PASS);
    }
  });
});
