import { execFileSync } from 'node:child_process';
import { mkdtempSync, readFileSync, writeFileSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';

const derive = path.join(path.dirname(fileURLToPath(import.meta.url)), 'soak-derive.mjs');
import {
  buildVerdict, measureSource, MIN_FORMAL_SECONDS, STALL_BUDGET_MS, STATUS,
} from './soak-verdict.mjs';

/**
 * Regression tests for the acceptance verdict.
 *
 * Each case is a counter-example the previous harness got wrong: a stream that
 * stops for good, a run that ends early, a missing source, a replaced player, a
 * missing target.  A case "passes" when the verdict is the one the plan
 * requires, so a broken verdict fails the suite.
 */

const SOURCES = [
  'camera-mu2uub8u', 'camera-mu2uuez4', 'camera-mu2ux4qk', 'camera-mu2ux73u', 'camera-mu2ux99i',
];

function healthySource(id, overrides = {}) {
  const seconds = overrides.seconds ?? MIN_FORMAL_SECONDS;
  return {
    id,
    presentedFrames: Math.round(24.8 * seconds),
    decodedFrames: Math.round(24.8 * seconds),
    receivedFrames: Math.round(25 * seconds),
    firstFrameMs: 5000,
    endedMaxGapMs: 120,
    inProgressGapMsAtEnd: 40,
    longStalls: [],
    mediaTimeSeconds: seconds - 20,
    generations: 1,
    counterResets: 0,
    teardownCount: 0,
    ...overrides,
  };
}

function run(overrides = {}) {
  const durationSeconds = overrides.durationSeconds ?? MIN_FORMAL_SECONDS;
  const seconds = overrides.sourceSeconds ?? durationSeconds;
  const ids = overrides.ids ?? SOURCES;
  return {
    runId: 'test-run',
    mode: 'direct',
    sourceType: 'synthetic',
    targetFps: 25,
    expected: ids.map((id) => ({ id, targetFps: 25 })),
    observed: ids.map((id) => healthySource(id, { seconds, ...(overrides.perSource?.[id] ?? {}) })),
    observation: {
      installedBeforeAction: true,
      modeSwitch: 'ok',
      allExpectedReady: true,
      complete: true,
      earlyTeardown: false,
      durationSeconds,
      smoke: false,
      finalSnapshotWritten: true,
      ...(overrides.observation ?? {}),
    },
    ...(overrides.run ?? {}),
  };
}

function failingChecks(verdict) {
  return verdict.checks.filter((item) => item.blocking && !item.passed).map((item) => item.id);
}

test('a healthy 1800s five-source run passes', () => {
  const verdict = buildVerdict(run());
  assert.equal(verdict.status, STATUS.PASS);
  assert.equal(verdict.measured.length, 5);
});

test('a stream that stops for good in the last 20s fails instead of passing', () => {
  // The old harness only computed a gap when the next frame arrived, so this
  // exact shape produced "max gap 0ms" and a PASS.
  const verdict = buildVerdict(run({
    perSource: { 'camera-mu2ux99i': { inProgressGapMsAtEnd: 20_000, longStalls: [{ fromMs: 1_780_000, toMs: 1_800_000, gapMs: 20_000 }] } },
  }));
  assert.equal(verdict.status, STATUS.FAIL);
  assert.ok(failingChecks(verdict).includes('frame-stall'));
  const row = verdict.measured.find((item) => item.id === 'camera-mu2ux99i');
  assert.equal(row.effectiveMaxGapMs, 20_000);
  assert.ok(row.trailingStallWithoutRecovery, 'the trailing stall must be flagged');
});

test('a run that ends at 1790s is incomplete, never a formal pass', () => {
  const verdict = buildVerdict(run({ durationSeconds: 1790, sourceSeconds: 1790 }));
  assert.equal(verdict.status, STATUS.INCOMPLETE);
  assert.equal(verdict.passed, false);
  assert.ok(failingChecks(verdict).includes('duration'));
});

test('a short run can only ever be a smoke result', () => {
  const smoke = buildVerdict(run({ durationSeconds: 120, sourceSeconds: 120, observation: { smoke: true } }));
  assert.equal(smoke.status, STATUS.SMOKE_PASS);
  const unmarked = buildVerdict(run({ durationSeconds: 120, sourceSeconds: 120 }));
  assert.equal(unmarked.status, STATUS.INCOMPLETE);
});

test('one missing source fails the run even when the other four are perfect', () => {
  const ids = SOURCES.slice(0, 4);
  const verdict = buildVerdict(run({ ids: [...ids, SOURCES[4]], perSource: {} , observation: {}, run: {} , ...{} }));
  const partial = buildVerdict({
    ...run(),
    expected: SOURCES.map((id) => ({ id, targetFps: 25 })),
    observed: ids.map((id) => healthySource(id)),
  });
  assert.equal(verdict.status, STATUS.PASS);
  assert.equal(partial.status, STATUS.FAIL);
  assert.ok(failingChecks(partial).includes('expected-sources'));
});

test('a missing target fails instead of silently skipping the frame-rate check', () => {
  const base = run();
  const verdict = buildVerdict({
    ...base,
    expected: base.expected.map((entry) => (entry.id === 'camera-mu2ux4qk' ? { id: entry.id } : entry)),
    targetFps: undefined,
  });
  assert.equal(verdict.status, STATUS.FAIL);
  assert.ok(failingChecks(verdict).includes('targets-defined'));
});

test('replacing the video element mid-run keeps the run valid and the totals cumulative', () => {
  // Two generations: the element is replaced, its counters restart at zero, and
  // the driver accumulates each generation's delta.  The run must still pass and
  // the totals must not reset.
  const verdict = buildVerdict(run({
    perSource: {
      'camera-mu2uub8u': {
        generations: 2,
        teardownCount: 1,
        counterResets: 1,
        presentedFrames: 24_000 + 20_000,
        decodedFrames: 24_000 + 20_000,
        mediaTimeSeconds: 1_760,
      },
    },
  }));
  assert.equal(verdict.status, STATUS.PASS);
  const row = verdict.measured.find((item) => item.id === 'camera-mu2uub8u');
  assert.equal(row.generations, 2);
  assert.equal(row.counterResets, 1);
  assert.ok(row.decodedFrames > 40_000, 'frames from both generations must be counted');
});

test('a trailing gap fails even though no completed stall was recorded', () => {
  // The frame never returned, so no longStalls entry exists; only the in-progress
  // age carries the failure.  A stopped synthetic source produced exactly this
  // shape in an end-to-end run and the check wrongly passed.
  const verdict = buildVerdict(run({
    perSource: { 'camera-mu2ux4qk': {
      endedMaxGapMs: 206,
      inProgressGapMsAtEnd: 51_249,
      longStalls: [],
      presentedFrames: 1767,
      decodedFrames: 1795,
      mediaTimeSeconds: 71.7,
    } },
  }));
  assert.equal(verdict.status, STATUS.FAIL);
  assert.ok(failingChecks(verdict).includes('frame-stall'));
  const row = verdict.measured.find((item) => item.id === 'camera-mu2ux4qk');
  assert.equal(row.unexpectedStalls, 0);
  assert.equal(row.trailingStallWithoutRecovery, true);
});

test('a stall that recovers after more than 3s is still a failure', () => {
  const verdict = buildVerdict(run({
    perSource: { 'camera-mu2ux73u': { endedMaxGapMs: 4_200, longStalls: [{ fromMs: 600_000, toMs: 604_200, gapMs: 4_200 }] } },
  }));
  assert.equal(verdict.status, STATUS.FAIL);
  assert.ok(failingChecks(verdict).includes('frame-stall'));
});

test('a stall inside a declared fault-injection window is reported but excused', () => {
  const verdict = buildVerdict(run({
    perSource: { 'camera-mu2uuez4': { endedMaxGapMs: 62_000, longStalls: [{ fromMs: 300_000, toMs: 362_000, gapMs: 62_000 }] } },
    run: { excusedStallWindows: [{ id: 'camera-mu2uuez4', fromMs: 295_000, toMs: 365_000 }] },
  }));
  assert.equal(verdict.status, STATUS.PASS);
  const row = verdict.measured.find((item) => item.id === 'camera-mu2uuez4');
  assert.equal(row.longStalls.length, 1, 'the stall is still recorded');
  assert.equal(row.unexpectedStalls, 0);
  assert.equal(row.effectiveMaxGapMs, 62_000, 'the true maximum gap is recorded, not zero');
});

test('an early teardown or a missing final snapshot is incomplete', () => {
  const tornDown = buildVerdict(run({ observation: { complete: false, earlyTeardown: true } }));
  assert.equal(tornDown.status, STATUS.INCOMPLETE);
  const noSnapshot = buildVerdict(run({ observation: { finalSnapshotWritten: false } }));
  assert.equal(noSnapshot.status, STATUS.INCOMPLETE);
  assert.ok(failingChecks(noSnapshot).includes('continuous-observation'));
});

test('sampling installed after the start action, or a failed mode switch, cannot pass', () => {
  const late = buildVerdict(run({ observation: { installedBeforeAction: false } }));
  assert.equal(late.status, STATUS.FAIL);
  assert.ok(failingChecks(late).includes('sampling-before-action'));
  const unswitched = buildVerdict(run({ observation: { modeSwitch: 'failed' } }));
  assert.equal(unswitched.status, STATUS.FAIL);
  assert.ok(failingChecks(unswitched).includes('mode-switch'));
});

test('an unknown decoded count cannot be reported as a passing frame rate', () => {
  const verdict = buildVerdict(run({ perSource: { 'camera-mu2uub8u': { decodedFrames: null } } }));
  assert.equal(verdict.status, STATUS.FAIL);
  assert.ok(failingChecks(verdict).includes('decoded-frame-rate'));
  const row = verdict.measured.find((item) => item.id === 'camera-mu2uub8u');
  assert.equal(row.decodedFps, null);
  assert.notEqual(row.presentedFps, null, 'presented is still reported separately');
});

test('presented frames are reported separately from decoded frames', () => {
  const verdict = buildVerdict(run({ perSource: { 'camera-mu2uub8u': { presentedFrames: 24.0 * MIN_FORMAL_SECONDS, decodedFrames: 24.9 * MIN_FORMAL_SECONDS } } }));
  const row = verdict.measured.find((item) => item.id === 'camera-mu2uub8u');
  assert.equal(row.decodedFps, 24.9);
  assert.equal(row.presentedFps, 24.0);
  assert.ok(row.decodedRatio >= 0.9);
});

test('measureSource reports both the ended maximum gap and the in-progress age', () => {
  const row = measureSource(
    { observation: { durationSeconds: 100 }, targetFps: 25 },
    { id: 'x', presentedFrames: 2500, endedMaxGapMs: 1200, inProgressGapMsAtEnd: STALL_BUDGET_MS + 500, firstFrameMs: 3000, mediaTimeSeconds: 99 },
    { id: 'x', targetFps: 25 },
  );
  assert.equal(row.endedMaxGapMs, 1200);
  assert.equal(row.inProgressGapMsAtEnd, 3500);
  assert.equal(row.effectiveMaxGapMs, 3500);
  assert.equal(row.decodedFps, null);
});

test('a composite run checks the program and its inputs, not only the program', () => {
  const base = run();
  const composite = {
    ...base,
    mode: 'composite',
    expected: [{ id: 'program', targetFps: 30 }],
    observed: [{
      ...healthySource('program'),
      targetFps: 30,
      presentedFrames: Math.round(29.2 * MIN_FORMAL_SECONDS),
      decodedFrames: Math.round(29.2 * MIN_FORMAL_SECONDS),
      receivedFrames: Math.round(29.6 * MIN_FORMAL_SECONDS),
    }],
    program: {
      id: 'program',
      presentedFrames: 29.2 * MIN_FORMAL_SECONDS,
      decodedFrames: 29.2 * MIN_FORMAL_SECONDS,
      firstFrameMs: 3500,
      endedMaxGapMs: 0,
      inProgressGapMsAtEnd: 30,
      mediaTimeSeconds: MIN_FORMAL_SECONDS - 5,
      generations: 1,
      targetFps: 30,
      inputsHealthy: SOURCES.map((id) => ({ id, state: 'healthy' })),
    },
  };
  const ok = buildVerdict(composite);
  assert.equal(ok.status, STATUS.PASS);
  const degraded = buildVerdict({ ...composite, program: { ...composite.program, inputsHealthy: [{ id: SOURCES[0], state: 'restarting' }] } });
  assert.equal(degraded.status, STATUS.FAIL);
  assert.ok(failingChecks(degraded).includes('program-and-inputs'));
});
// ---- the recompute path must obey the same rules as the driver ----

function sampleEntry(id, seconds, overrides = {}) {
  return {
    id,
    presentedFrames: Math.round(24.8 * seconds),
    decodedFrames: Math.round(24.8 * seconds),
    receivedFrames: Math.round(25 * seconds),
    firstFrameMs: 5000,
    endedMaxGapMs: 120,
    inProgressGapMsAtEnd: 40,
    longStalls: [],
    mediaTimeSeconds: seconds - 20,
    generations: 1,
    counterResets: 0,
    teardownCount: 0,
    ...overrides,
  };
}

function writeTimeline(entries, options = {}) {
  const directory = mkdtempSync(path.join(os.tmpdir(), 'webobs-derive-'));
  const at = options.at ?? MIN_FORMAL_SECONDS * 1000;
  const sample = {
    at,
    final: options.final !== false,
    atMs: at,
    instrumentedAtMs: 10,
    actionAtMs: 20,
    entries,
    events: [],
    sources: options.sources ?? null,
  };
  writeFileSync(path.join(directory, 'browser-soak-timeline.jsonl'), JSON.stringify(sample) + '\n');
  const targets = path.join(directory, 'targets.json');
  writeFileSync(targets, JSON.stringify(Object.fromEntries(entries.map((entry) => [entry.id, 25]))));
  return { directory, targets };
}

function runDerive(directory, targets, extra = []) {
  execFileSync(process.execPath, [derive, '--browser', directory, '--targets', targets, '--mode', 'direct', ...extra], { stdio: 'pipe' });
  return JSON.parse(readFileSync(path.join(directory, 'derived-browser-summary.json'), 'utf8'));
}

test('a recomputed run with a final sample and full metrics can pass', () => {
  const { directory, targets } = writeTimeline(SOURCES.map((id) => sampleEntry(id, MIN_FORMAL_SECONDS)));
  const report = runDerive(directory, targets);
  assert.equal(report.status, STATUS.PASS);
  assert.equal(report.derived, true);
});

test('an interrupted recording is incomplete, never a derived pass', () => {
  const { directory, targets } = writeTimeline(SOURCES.map((id) => sampleEntry(id, 900)), { final: false, at: 900_000 });
  const report = runDerive(directory, targets);
  assert.equal(report.status, STATUS.INCOMPLETE);
  assert.equal(report.passed, false);
});

test('a recording without the in-progress frame age cannot be derived into a pass', () => {
  // The shape of the original 2026-09-19/20 recordings: no in-progress gap, no
  // sampling start, no generation counters, no decoded totals.
  const entries = SOURCES.map((id) => {
    const entry = sampleEntry(id, MIN_FORMAL_SECONDS);
    delete entry.inProgressGapMsAtEnd;
    delete entry.generations;
    delete entry.counterResets;
    delete entry.teardownCount;
    delete entry.decodedFrames;
    return entry;
  });
  const directory = mkdtempSync(path.join(os.tmpdir(), 'webobs-derive-'));
  writeFileSync(path.join(directory, 'browser-soak-timeline.jsonl'),
    JSON.stringify({ at: MIN_FORMAL_SECONDS * 1000, final: true, entries, events: [] }) + '\n');
  const targets = path.join(directory, 'targets.json');
  writeFileSync(targets, JSON.stringify(Object.fromEntries(SOURCES.map((id) => [id, 25]))));
  const report = runDerive(directory, targets);
  assert.notEqual(report.status, STATUS.PASS);
  const frameStall = report.checks.find((item) => item.id === 'frame-stall');
  assert.equal(frameStall.unverifiable, true);
  const sampling = report.checks.find((item) => item.id === 'sampling-before-action');
  assert.equal(sampling.unverifiable, true);
});

test('a short recording is not a formal pass even when every metric looks good', () => {
  const { directory, targets } = writeTimeline(SOURCES.map((id) => sampleEntry(id, 120)), { at: 120_000 });
  const report = runDerive(directory, targets);
  assert.equal(report.status, STATUS.INCOMPLETE);
});

