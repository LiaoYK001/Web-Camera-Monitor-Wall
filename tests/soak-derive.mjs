#!/usr/bin/env node
/**
 * Recomputes a soak verdict from the incremental evidence a run leaves behind.
 *
 * A long soak can be interrupted (a session or CI boundary, a kill) before it
 * writes its own summary.  Both drivers append as they go, so the samples that
 * were taken are still evidence: the browser soak writes
 * browser-soak-timeline.jsonl and the server sampler writes samples.jsonl.
 *
 * The derived browser verdict runs through the same rules as the driver
 * (tests/soak-verdict.mjs) and it never fills a gap with a guess: a recording
 * that lacks the in-progress frame age, the sampling start or a final snapshot is
 * reported as unverifiable/incomplete rather than recomputed into a PASS.
 *
 * Usage:
 *   node tests/soak-derive.mjs --browser tests/artifacts/browser-soak/<run> \
 *     --targets targets.json --expected a,b,c --mode direct --source-type real
 *   node tests/soak-derive.mjs --soak tests/artifacts/soak/<run>
 *
 * A targets file maps source id to its nominal frame rate, e.g. { "camera-abc": 25 }.
 */
import { existsSync, readFileSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import {
  MIN_FORMAL_SECONDS, buildVerdict,
} from './soak-verdict.mjs';

const THRESHOLDS = {
  firstFrameMs: 20_000,
  maxUnexpectedStallMs: 3_000,
  decodedFpsRatio: 0.9,
};

function parseArguments(argv) {
  const options = {
    browser: '', soak: '', targets: '', mode: '', sourceType: 'unknown',
    expected: '', smoke: false,
  };
  for (let index = 0; index < argv.length; index++) {
    const key = argv[index];
    const value = argv[index + 1];
    const take = () => { if (value === undefined) throw new Error(`${key} needs a value`); index++; return value; };
    if (key === '--browser') options.browser = take();
    else if (key === '--soak') options.soak = take();
    else if (key === '--targets') options.targets = take();
    else if (key === '--mode') options.mode = take();
    else if (key === '--source-type') options.sourceType = take();
    else if (key === '--expected') options.expected = take();
    else if (key === '--smoke') options.smoke = true;
    else throw new Error(`unknown argument ${key}`);
  }
  if (!options.browser && !options.soak) throw new Error('at least one of --browser or --soak is required');
  return options;
}

function readJsonLines(file) {
  return readFileSync(file, 'utf8').split('\n').filter(Boolean).map((line) => JSON.parse(line));
}

function has(entry, key) {
  return entry !== undefined && entry !== null && entry[key] !== undefined && entry[key] !== null;
}

function deriveBrowser(directory, targets, options) {
  const timelineFile = path.join(directory, 'browser-soak-timeline.jsonl');
  if (!existsSync(timelineFile)) return null;
  const samples = readJsonLines(timelineFile);
  if (!samples.length) return null;
  const last = samples.at(-1);
  const durationSeconds = Number(last.at ?? 0) / 1000;

  // The expected set must come from outside the recording: a set read back from
  // the recording itself could never notice that a source never appeared.
  const expectedIds = options.expected
    ? options.expected.split(',').map((value) => value.trim()).filter(Boolean)
    : Object.keys(targets);
  const expected = expectedIds.map((id) => ({ id, targetFps: targets[id] ?? undefined }));

  // Recordings made before the harness fix use the older field names.  Reading a
  // measurement under its old name is not fabrication; inventing one that was
  // never captured would be, and the legacy decoded counter is exactly that: it
  // was a single-element snapshot (0 after teardown), not a per-generation total.
  const legacy = (last.entries ?? []).every((entry) => entry.presentedFrames === undefined);
  const observed = (last.entries ?? []).map((entry) => ({
    id: entry.id,
    presentedFrames: entry.presentedFrames ?? entry.frames ?? null,
    decodedFrames: legacy ? null : (entry.decodedFrames ?? null),
    receivedFrames: entry.receivedFrames ?? null,
    firstFrameMs: entry.firstFrameMs ?? null,
    endedMaxGapMs: entry.endedMaxGapMs ?? entry.maxGapMs ?? null,
    inProgressGapMsAtEnd: entry.inProgressGapMsAtEnd ?? null,
    longStalls: entry.longStalls ?? [],
    mediaTimeSeconds: entry.mediaTimeSeconds ?? entry.lastMediaTime ?? null,
    generations: entry.generations ?? null,
    counterResets: entry.counterResets ?? null,
    teardownCount: entry.teardownCount ?? null,
  }));

  // Anything the recording never captured is unverifiable, not passing.
  const unverifiableChecks = [];
  if (!(last.entries ?? []).every((entry) => has(entry, 'inProgressGapMsAtEnd'))) unverifiableChecks.push('frame-stall');
  if (last.actionAtMs === undefined || last.actionAtMs === null
    || last.instrumentedAtMs === undefined || last.instrumentedAtMs === null) unverifiableChecks.push('sampling-before-action');
  if (!(last.entries ?? []).every((entry) => has(entry, 'generations'))) unverifiableChecks.push('counter-integrity');
  if (legacy) unverifiableChecks.push('decoded-frame-rate');
  if (!expectedIds.length) unverifiableChecks.push('expected-sources');

  const programEntry = (last.entries ?? []).find((entry) => entry.id === 'program');
  const inputs = (last.sources?.sources ?? []).map((source) => ({ id: source.id, state: String(source.state ?? 'unknown') }));
  const unhealthySamples = samples.filter((sample) =>
    (sample.sources?.sources ?? []).some((source) => source.state !== 'healthy')).length;

  const verdict = buildVerdict({
    runId: path.basename(directory),
    mode: options.mode || 'direct',
    sourceType: options.sourceType,
    expected,
    observed,
    observation: {
      installedBeforeAction: (last.actionAtMs !== undefined && last.actionAtMs !== null
        && last.instrumentedAtMs !== undefined && last.instrumentedAtMs !== null
        && last.instrumentedAtMs <= last.actionAtMs) || null,
      modeSwitch: 'ok',
      allExpectedReady: null,
      // Only a run whose last sample is marked final closed its observation
      // window in the right order; anything else is incomplete.
      complete: last.final === true,
      earlyTeardown: last.final !== true,
      durationSeconds,
      smoke: options.smoke,
      finalSnapshotWritten: last.final === true,
    },
    program: (options.mode === 'composite' && programEntry) ? {
      ...programEntry,
      targetFps: targets.program ?? null,
      inputsHealthy: inputs,
      unhealthySamples,
    } : undefined,
    unverifiableChecks,
    limitations: [
      'derived from browser-soak-timeline.jsonl because the run did not write its own summary',
      last.final === true ? null : 'the recording has no final sample: the run was interrupted',
    ].filter(Boolean),
  });

  const report = {
    ...verdict,
    derived: true,
    note: 'recomputed from browser-soak-timeline.jsonl; the original samples are left untouched',
    samples: samples.length,
  };
  writeFileSync(path.join(directory, 'derived-browser-summary.json'), JSON.stringify(report, null, 2));
  writeFileSync(path.join(directory, 'derived-browser-summary.md'), [
    `# Browser soak (derived) — ${report.runId}`, '',
    `- duration: ${durationSeconds.toFixed(0)}s over ${samples.length} samples (formal window ${MIN_FORMAL_SECONDS}s)`,
    `- derived verdict: ${report.status}`, '',
    '| source | decoded fps | target | ratio | presented fps | first frame ms | ended max gap ms | in-progress gap ms | last media time |',
    '|---|---|---|---|---|---|---|---|---|',
    ...report.measured.map((row) => `| ${row.id} | ${row.decodedFps ?? 'unknown'} | ${row.targetFps ?? 'none'} | ${row.decodedRatio ?? 'n/a'} | ${row.presentedFps ?? 'unknown'} | ${row.firstFrameMs ?? 'never'} | ${row.endedMaxGapMs} | ${row.inProgressGapMsAtEnd ?? 'unknown'} | ${row.mediaTimeSeconds ?? 'n/a'} |`),
    '',
    ...report.checks.map((item) => `- ${item.passed ? 'PASS' : (item.unverifiable ? 'UNVERIFIABLE' : 'FAIL')}${item.blocking ? '' : ' (reported)'} — ${item.name}: ${item.detail}`),
    '',
    ...report.notes.map((note) => `- note: ${note}`),
    '', `Verdict: ${report.status}`, '',
  ].join('\n'));
  return { report, thresholds: THRESHOLDS };
}

function deriveSoak(directory) {
  const samplesFile = path.join(directory, 'samples.jsonl');
  if (!existsSync(samplesFile)) return null;
  const samples = readJsonLines(samplesFile);
  const routeNames = [...new Set(samples.flatMap((s) => s.routes.map((r) => r.name)))].sort();
  const routes = routeNames.map((name) => {
    const seen = samples.flatMap((s) => s.routes.filter((r) => r.name === name));
    const first = seen[0];
    const last = seen.at(-1);
    return {
      name,
      samples: seen.length,
      readySamples: seen.filter((r) => r.ready).length,
      bytesFirst: first?.bytesReceived ?? 0,
      bytesLast: last?.bytesReceived ?? 0,
      growing: (last?.bytesReceived ?? 0) > (first?.bytesReceived ?? 0),
      tracks: [...new Set(seen.flatMap((r) => r.tracks))].sort(),
    };
  });
  const sourceSamples = samples.map((entry) => entry.sources?.sources ?? []);
  const sourceIds = [...new Set(sourceSamples.flat().map((source) => source.id))];
  const sources = sourceIds.map((id) => {
    const seen = sourceSamples.flat().filter((source) => source.id === id);
    const ages = seen.map((source) => source.last_frame_age_ms ?? source.lastFrameAgeMs ?? -1)
      .filter((age) => Number.isFinite(age) && age >= 0);
    return {
      id,
      samples: seen.length,
      states: [...new Set(seen.map((source) => source.state))].sort(),
      maxFrameAgeMs: ages.length ? Math.max(...ages) : null,
      restarts: Math.max(0, ...seen.map((source) => source.restart_count ?? source.restartCount ?? 0)),
    };
  });
  const unhealthySamples = samples.filter((entry) => (entry.sources?.unhealthy ?? 0) > 0).length;
  const summary = {
    derived: true,
    samples: samples.length,
    first: samples[0].timestamp,
    last: samples.at(-1).timestamp,
    routes,
    sources,
    unhealthySamples,
    routesReadyAndGrowing: routes.filter((r) => r.readySamples >= r.samples - 1 && r.growing).length,
    routesNeverReady: routes.filter((r) => r.readySamples === 0).length,
  };
  writeFileSync(path.join(directory, 'derived-summary.json'), JSON.stringify(summary, null, 2));
  return summary;
}

const options = parseArguments(process.argv.slice(2));
const targets = options.targets && existsSync(options.targets)
  ? JSON.parse(readFileSync(options.targets, 'utf8')) : {};

if (options.browser) {
  const derived = deriveBrowser(options.browser, targets, options);
  if (!derived) console.error(`no browser-soak-timeline.jsonl under ${options.browser}`);
  else {
    const { report } = derived;
    console.log(`browser: ${report.samples} samples over ${report.durationSeconds}s — ${report.status}`);
    for (const item of report.checks) {
      console.log(`  ${item.passed ? 'PASS' : (item.unverifiable ? 'UNVERIFIABLE' : 'FAIL')} ${item.id}: ${item.detail}`);
    }
  }
}
if (options.soak) {
  const summary = deriveSoak(options.soak);
  if (!summary) console.error(`no samples.jsonl under ${options.soak}`);
  else console.log(`server: ${summary.samples} samples, ${summary.routes.length} routes, ${summary.routesReadyAndGrowing} ready+growing, ${summary.routesNeverReady} never ready, ${summary.unhealthySamples} unhealthy samples`);
}
