import { expect, test } from '@playwright/test';
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
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
}

type InstrumentedWindow = Window & { __webobsSoak?: { startedAt: number } };

test.describe('feedback-5 soak', () => {
  test.skip(!enabled, 'set WEBOBS_SOAK=1 to run the long playback soak');
  test(`keeps the ${mode} wall playing for the configured duration`, async ({ page }) => {
    test.setTimeout((minutes + 6) * 60_000);
    const runId = `${new Date().toISOString().replace(/[:.]/g, '-')}-${mode}`;
    const directory = path.join(evidenceRoot, runId);
    mkdirSync(directory, { recursive: true });

    await page.goto(baseUrl);
    const loginHeading = page.getByRole('heading', { name: '登录监控工作台' });
    if (await loginHeading.isVisible().catch(() => false)) {
      const user = process.env.WEBOBS_DEV_USERNAME || secret('webobs-dev-username.txt');
      const password = process.env.WEBOBS_DEV_PASSWORD || secret('webobs-dev-password.txt');
      expect(user, 'a development username must be available for the real login path').not.toBe('');
      await page.getByLabel('用户名', { exact: true }).fill(user);
      await page.getByLabel('密码', { exact: true }).fill(password);
      await page.getByRole('button', { name: '登录', exact: true }).click();
    }
    await expect(page.getByRole('button', { name: '退出登录' })).toBeVisible({ timeout: 30_000 });

    // Switch to the playback mode under test through the real UI controls.
    const modeButton = page.getByRole('button', { name: mode === 'composite' ? '服务端合成' : '网关直通' });
    if (await modeButton.count()) await modeButton.first().click();

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
        document.querySelectorAll('.direct-tile[data-source-id]').forEach((tile) => {
          const video = tile.querySelector('video');
          const id = tile.getAttribute('data-source-id');
          if (video && id) attach(id, video as HTMLVideoElement);
        });
        const program = document.querySelector('video[aria-label="实时合成节目画面"]');
        if (program) attach('program', program as HTMLVideoElement);
      };
      scan();
      window.setInterval(scan, 2000);
    });

    const startedAt = Date.now();
    const deadline = startedAt + minutes * 60_000;
    const timeline: Array<{ at: number; entries: SourceSample[] }> = [];
    while (Date.now() < deadline) {
      await page.waitForTimeout(15_000);
      const snapshot = await page.evaluate(() => {
        const state = (window as InstrumentedWindow).__webobsSoak as unknown as {
          entries: Record<string, SourceSample>;
        };
        return Object.values(state?.entries ?? {}).map((entry) => ({
          id: entry.id, frames: entry.frames, firstFrameMs: entry.firstFrameMs,
          lastMediaTime: entry.lastMediaTime, maxGapMs: entry.maxGapMs, gaps: entry.gaps.slice(-20),
        }));
      });
      timeline.push({ at: Date.now() - startedAt, entries: snapshot });
      console.log(`[browser-soak] ${Math.round((Date.now() - startedAt) / 1000)}s ` +
        snapshot.map((entry) => `${entry.id}=${entry.frames}f/${entry.lastMediaTime.toFixed(1)}s`).join(' '));
    }

    const durationSeconds = (Date.now() - startedAt) / 1000;
    const final = timeline.at(-1)?.entries ?? [];
    const measured = final.map((entry) => {
      const target = targetFpsMap[entry.id] ?? targetFps;
      const fps = entry.frames / durationSeconds;
      return {
        id: entry.id,
        frames: entry.frames,
        measuredFps: Number(fps.toFixed(2)),
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
