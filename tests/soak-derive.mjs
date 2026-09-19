#!/usr/bin/env node
/**
 * Recomputes a soak verdict from the incremental evidence a run leaves behind.
 *
 * A long soak can be interrupted (a session or CI boundary, a kill) before it
 * writes its own summary.  Both drivers append as they go, so the samples that
 * were taken are still evidence: the browser soak writes
 * browser-soak-timeline.jsonl and the server sampler writes samples.jsonl.
 * This tool turns those into the same tables the drivers would have produced and
 * writes derived-summary.json / derived-browser-summary.{json,md} next to them.
 *
 * Usage:
 *   node tests/soak-derive.mjs --browser tests/artifacts/browser-soak/<run> \
 *     [--soak tests/artifacts/soak/<run>] [--targets targets.json] [--mode direct]
 *
 * A targets file maps source id to its nominal frame rate, e.g.
 *   { "camera-abc": 25 }
 */
import { existsSync, readFileSync, writeFileSync } from 'node:fs';
import path from 'node:path';

const THRESHOLDS = {
  firstFrameMs: 20_000,
  maxUnexpectedStallMs: 3_000,
  decodedFpsRatio: 0.9,
};

function parseArguments(argv) {
  const options = { browser: '', soak: '', targets: '', mode: '' };
  for (let index = 0; index < argv.length; index++) {
    const key = argv[index];
    const value = argv[index + 1];
    const take = () => { if (value === undefined) throw new Error(`${key} needs a value`); index++; return value; };
    if (key === '--browser') options.browser = take();
    else if (key === '--soak') options.soak = take();
    else if (key === '--targets') options.targets = take();
    else if (key === '--mode') options.mode = take();
    else throw new Error(`unknown argument ${key}`);
  }
  if (!options.browser && !options.soak) throw new Error('at least one of --browser or --soak is required');
  return options;
}

function readJsonLines(file) {
  return readFileSync(file, 'utf8').split('\n').filter(Boolean).map((line) => JSON.parse(line));
}

function deriveBrowser(directory, targets) {
  const timelineFile = path.join(directory, 'browser-soak-timeline.jsonl');
  if (!existsSync(timelineFile)) return null;
  const samples = readJsonLines(timelineFile);
  const last = samples.at(-1);
  const durationSeconds = last.at / 1000;

  const measured = last.entries.map((entry) => {
    const perSample = samples.map((sample) => sample.entries.find((item) => item.id === entry.id)).filter(Boolean);
    const final = perSample.at(-1);
    const fps = final.frames / durationSeconds;
    const decodedFps = final.decodedFrames === null || final.decodedFrames === undefined
      ? null : Number((final.decodedFrames / durationSeconds).toFixed(2));
    const target = targets[entry.id] ?? null;
    return {
      id: entry.id,
      frames: final.frames,
      measuredFps: Number(fps.toFixed(2)),
      decodedFps,
      decodedFrames: final.decodedFrames ?? null,
      droppedFrames: final.droppedFrames ?? null,
      targetFps: target,
      fpsRatio: target ? Number((fps / target).toFixed(3)) : null,
      firstFrameMs: final.firstFrameMs,
      lastMediaTime: Number(final.lastMediaTime.toFixed(1)),
      maxGapMs: Math.max(0, ...perSample.map((item) => item.maxGapMs ?? 0)),
    };
  });

  const checks = [
    { name: 'every tile advanced its media time', passed: measured.length > 0 && measured.every((m) => m.lastMediaTime > 1) },
    { name: 'no unexpected frame gap beyond 3s', passed: measured.every((m) => m.maxGapMs <= THRESHOLDS.maxUnexpectedStallMs) },
    { name: 'first frame within 20s', passed: measured.every((m) => m.firstFrameMs !== null && m.firstFrameMs <= THRESHOLDS.firstFrameMs) },
    {
      name: `decoded frame rate at least ${THRESHOLDS.decodedFpsRatio * 100}% of the nominal target`,
      passed: measured.every((m) => m.fpsRatio === null || m.fpsRatio >= THRESHOLDS.decodedFpsRatio),
    },
  ];

  const report = {
    runId: path.basename(directory),
    derived: true,
    note: 'recomputed from browser-soak-timeline.jsonl because the run did not write its own summary',
    durationSeconds: Number(durationSeconds.toFixed(1)),
    samples: samples.length,
    measured,
    checks,
    passed: checks.every((check) => check.passed) && measured.length > 0,
  };
  writeFileSync(path.join(directory, 'derived-browser-summary.json'), JSON.stringify(report, null, 2));
  writeFileSync(path.join(directory, 'derived-browser-summary.md'), [
    `# Browser soak (derived) — ${report.runId}`, '',
    `- duration: ${durationSeconds.toFixed(0)}s over ${samples.length} samples`, '',
    '| source | frames | fps | decoded fps | target | ratio | first frame ms | last media time | max gap ms |',
    '|---|---|---|---|---|---|---|---|---|',
    ...measured.map((m) => `| ${m.id} | ${m.frames} | ${m.measuredFps} | ${m.decodedFps ?? 'n/a'} | ${m.targetFps ?? 'n/a'} | ${m.fpsRatio ?? 'n/a'} | ${m.firstFrameMs ?? 'n/a'} | ${m.lastMediaTime} | ${m.maxGapMs} |`),
    '',
    ...checks.map((check) => `- ${check.passed ? 'PASS' : 'FAIL'} — ${check.name}`),
    '', report.passed ? 'Verdict: PASS' : 'Verdict: FAIL', '',
  ].join('\n'));
  return report;
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
  const summary = {
    derived: true,
    samples: samples.length,
    first: samples[0].timestamp,
    last: samples.at(-1).timestamp,
    routes,
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
  const report = deriveBrowser(options.browser, targets);
  if (!report) console.error(`no browser-soak-timeline.jsonl under ${options.browser}`);
  else {
    console.log(`browser: ${report.samples} samples over ${report.durationSeconds}s — ${report.passed ? 'PASS' : 'FAIL'}`);
    console.table(report.measured);
  }
}
if (options.soak) {
  const summary = deriveSoak(options.soak);
  if (!summary) console.error(`no samples.jsonl under ${options.soak}`);
  else console.log(`server: ${summary.samples} samples, ${summary.routes.length} routes, ${summary.routesReadyAndGrowing} ready+growing, ${summary.routesNeverReady} never ready`);
}
