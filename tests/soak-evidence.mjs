#!/usr/bin/env node
/**
 * Reproducible acceptance sampler for the feedback-5 playback soaks.
 *
 * It records, per run: a run id, the exact code revision, the configuration
 * digest, the measured renderer/encoder, a timeline of MediaMTX route state and
 * per-source frame progress, and a conclusion against the documented
 * thresholds.  Evidence lands in a run-scoped directory so two runs can never
 * overwrite each other, and credentials are never written to it.
 *
 * Usage:
 *   node tests/soak-evidence.mjs --label composite-1080p --minutes 30  *     --mode composite --target-fps 30
 *
 * Environment overrides (all optional):
 *   WEBOBS_MEDIAMTX_API   default http://127.0.0.1:9997
 *   WEBOBS_CORE_API       default http://127.0.0.1:8080
 *   WEBOBS_SOAK_EVIDENCE  default tests/artifacts/soak
 */
import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { appendFileSync, existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = fileURLToPath(new URL('../', import.meta.url));

/** Documented acceptance thresholds (docs/feedback-5-followup-2026-09-18.md). */
const THRESHOLDS = {
  firstFrameMs: 20_000,
  readyRouteReopenMs: 8_000,
  decodedFpsRatio: 0.9,
  maxUnexpectedStallMs: 3_000,
  singleSourceRecoveryMs: 15_000,
};

function parseArguments(argv) {
  const options = {
    label: 'soak', minutes: 30, intervalSeconds: 60, mode: 'direct',
    targetFps: 30, mediamtx: process.env.WEBOBS_MEDIAMTX_API || 'http://127.0.0.1:9997',
    core: process.env.WEBOBS_CORE_API || 'http://127.0.0.1:8080',
    out: process.env.WEBOBS_SOAK_EVIDENCE || path.join(root, 'tests/artifacts/soak'),
    browserVersion: process.env.WEBOBS_SOAK_BROWSER || '',
  };
  for (let index = 0; index < argv.length; index++) {
    const key = argv[index];
    const value = argv[index + 1];
    const take = () => { if (value === undefined) throw new Error(`${key} needs a value`); index++; return value; };
    if (key === '--label') options.label = take();
    else if (key === '--minutes') options.minutes = Number(take());
    else if (key === '--interval') options.intervalSeconds = Number(take());
    else if (key === '--mode') options.mode = take();
    else if (key === '--target-fps') options.targetFps = Number(take());
    else if (key === '--mediamtx') options.mediamtx = take();
    else if (key === '--core') options.core = take();
    else if (key === '--out') options.out = take();
    else if (key === '--browser-version') options.browserVersion = take();
    else throw new Error(`unknown argument ${key}`);
  }
  if (!Number.isFinite(options.minutes) || options.minutes <= 0) throw new Error('--minutes must be positive');
  if (!Number.isFinite(options.intervalSeconds) || options.intervalSeconds <= 0) throw new Error('--interval must be positive');
  return options;
}

function git(...args) {
  try {
    return execFileSync('git', args, { cwd: root, encoding: 'utf8' }).trim();
  } catch {
    return '';
  }
}

/** Basic credentials for the control plane, read from the ignored secrets dir. */
function controlPlaneAuthorization() {
  const read = (name) => {
    const file = path.join(root, 'secrets', name);
    return existsSync(file) ? readFileSync(file, 'utf8').trim() : '';
  };
  const user = process.env.WEBOBS_DEV_USER || read('webobs-dev-username.txt');
  const password = process.env.WEBOBS_DEV_PASSWORD || read('webobs-dev-password.txt');
  if (!user || !password) return '';
  return 'Basic ' + Buffer.from(`${user}:${password}`).toString('base64');
}

async function getJson(url, authorization) {
  const response = await fetch(url, {
    headers: authorization ? { authorization } : {},
    signal: AbortSignal.timeout(8000),
  });
  if (!response.ok) throw new Error(`${url} -> HTTP ${response.status}`);
  return response.json();
}

async function mediaPaths(mediamtx) {
  const body = await getJson(`${mediamtx}/v3/paths/list?itemsPerPage=1000`);
  return body.items ?? [];
}

function digestSceneDocument() {
  const sceneFile = process.env.WEBOBS_SCENE_FILE;
  if (!sceneFile || !existsSync(sceneFile)) return { path: sceneFile || '', sha256: '', sources: 0, canvas: null };
  const bytes = readFileSync(sceneFile);
  try {
    const document = JSON.parse(bytes.toString('utf8'));
    return {
      path: path.basename(sceneFile),
      sha256: createHash('sha256').update(bytes).digest('hex'),
      sources: (document.sources ?? []).length,
      canvas: document.canvas ?? null,
    };
  } catch {
    return { path: path.basename(sceneFile), sha256: createHash('sha256').update(bytes).digest('hex'), sources: 0, canvas: null };
  }
}

async function sample(options, authorization) {
  const [paths, program, sources] = await Promise.all([
    mediaPaths(options.mediamtx),
    getJson(`${options.core}/api/v1/program/status`, authorization).catch((error) => ({ error: String(error.message) })),
    getJson(`${options.core}/api/v1/sources/status`, authorization).catch((error) => ({ error: String(error.message) })),
  ]);
  return {
    timestamp: new Date().toISOString(),
    program,
    sources,
    routes: paths.map((item) => ({
      name: item.name,
      ready: item.ready === true,
      tracks: item.tracks ?? [],
      readers: (item.readers ?? []).length,
      bytesReceived: item.bytesReceived ?? 0,
      bytesSent: item.bytesSent ?? 0,
      inboundFramesInError: item.inboundFramesInError ?? 0,
      width: item.tracks2?.find((track) => track.codec === 'H264')?.codecProps?.width ?? null,
      height: item.tracks2?.find((track) => track.codec === 'H264')?.codecProps?.height ?? null,
    })),
  };
}

function summarize(options, meta, samples) {
  const routeSamples = samples.map((entry) => entry.routes);
  const routeNames = [...new Set(routeSamples.flat().map((route) => route.name))];
  const routes = routeNames.map((name) => {
    const seen = routeSamples.flat().filter((route) => route.name === name);
    const first = seen[0];
    const last = seen.at(-1);
    return {
      name,
      samples: seen.length,
      readySamples: seen.filter((route) => route.ready).length,
      firstBytes: first?.bytesReceived ?? 0,
      lastBytes: last?.bytesReceived ?? 0,
      bytesGrowing: (last?.bytesReceived ?? 0) > (first?.bytesReceived ?? 0),
      framesInError: last?.inboundFramesInError ?? 0,
      tracks: [...new Set(seen.flatMap((route) => route.tracks))].sort(),
      width: first?.width ?? null,
      height: first?.height ?? null,
    };
  });

  const sourceSamples = samples.map((entry) => entry.sources?.sources ?? []);
  const sourceIds = [...new Set(sourceSamples.flat().map((source) => source.id))];
  const sources = sourceIds.map((id) => {
    const seen = sourceSamples.flat().filter((source) => source.id === id);
    const ages = seen.map((source) => source.last_frame_age_ms ?? source.lastFrameAgeMs ?? -1)
      .filter((age) => Number.isFinite(age) && age >= 0);
    const restarts = Math.max(0, ...seen.map((source) => source.restart_count ?? source.restartCount ?? 0));
    return {
      id,
      samples: seen.length,
      states: [...new Set(seen.map((source) => source.state))].sort(),
      maxFrameAgeMs: ages.length ? Math.max(...ages) : null,
      maxUnexpectedStallMs: ages.length ? Math.max(...ages) : null,
      restarts,
    };
  });

  const unhealthy = samples.filter((entry) => (entry.sources?.unhealthy ?? 0) > 0).length;
  const visible = Math.max(0, ...samples.map((entry) => entry.sources?.visible ?? 0));
  const programReady = samples.filter((entry) => entry.program?.publish === 'publishing').length;
  const stalls = sources.filter((source) => source.maxFrameAgeMs !== null &&
    source.maxFrameAgeMs > THRESHOLDS.maxUnexpectedStallMs);
  const recovered = sources.every((source) => source.restarts === 0);
  const routeEvidence = options.mode === 'composite'
    ? routes.filter((route) => route.name === 'program' && route.readySamples === route.samples && route.bytesGrowing).length === 1
    : routes.filter((route) => route.bytesGrowing && route.readySamples > 0).length >= 1;

  const checks = [
    {
      name: 'every visible source kept producing frames',
      passed: visible > 0 && stalls.length === 0 && sources.every((source) => source.samples === samples.length),
      detail: stalls.length
        ? `frame age exceeded ${THRESHOLDS.maxUnexpectedStallMs}ms: ${stalls.map((s) => `${s.id}=${s.maxFrameAgeMs}ms`).join(', ')}`
        : `${sources.length} sources sampled, visible=${visible}`,
    },
    {
      name: 'no source restarted during the run',
      passed: recovered,
      detail: sources.filter((source) => source.restarts > 0).map((source) => `${source.id}:${source.restarts}`).join(', ') || 'restartCount stayed 0',
    },
    {
      name: 'no sample reported unhealthy sources',
      passed: unhealthy === 0,
      detail: `${unhealthy} of ${samples.length} samples had unhealthy>0`,
    },
    {
      name: 'media routes stayed ready and kept growing',
      passed: routeEvidence,
      detail: routes.map((route) => `${route.name} ready=${route.readySamples}/${route.samples} bytes ${route.firstBytes}->${route.lastBytes}`).join('; '),
    },
  ];
  if (options.mode === 'composite') {
    checks.push({
      name: 'program publishing for every sample',
      passed: programReady === samples.length && samples.length > 0,
      detail: `${programReady} of ${samples.length} samples reported publish=publishing`,
    });
  }

  return {
    runId: meta.runId,
    revision: meta.revision,
    mode: options.mode,
    durationMinutes: samples.length ? (new Date(samples.at(-1).timestamp) - new Date(samples[0].timestamp)) / 60000 : 0,
    thresholds: THRESHOLDS,
    targetFps: options.targetFps,
    renderer: meta.renderer,
    encoder: meta.encoder,
    browser: options.browserVersion,
    samples: samples.length,
    visibleSources: visible,
    routes,
    sources,
    checks,
    passed: checks.every((check) => check.passed),
    // The browser-side frame rate and first-frame numbers are measured by
    // web/tests/local-runtime/browser-soak.spec.ts and merged in manually.
    browserMeasured: false,
  };
}

function renderMarkdown(summary, options) {
  const lines = [
    `# Soak evidence — ${summary.runId}`,
    '',
    `- revision: \`${summary.revision}\``,
    `- mode: ${summary.mode}, target fps: ${summary.targetFps}, sampler interval: ${options.intervalSeconds}s`,
    `- renderer: ${summary.renderer?.selected ?? 'unknown'} (requested ${summary.renderer?.requested ?? '?'}), encoder: ${summary.encoder?.selected ?? 'unknown'}`,
    `- samples: ${summary.samples}, covered ${summary.durationMinutes.toFixed(1)} minutes`,
    `- browser: ${summary.browser || 'not recorded'}`,
    '',
    '| check | result | detail |',
    '|---|---|---|',
    ...summary.checks.map((check) => `| ${check.name} | ${check.passed ? 'PASS' : 'FAIL'} | ${check.detail} |`),
    '',
    '## Sources',
    '',
    '| source | samples | states | max frame age (ms) | restarts |',
    '|---|---|---|---|---|',
    ...summary.sources.map((source) => `| ${source.id} | ${source.samples} | ${source.states.join(',')} | ${source.maxFrameAgeMs ?? 'n/a'} | ${source.restarts} |`),
    '',
    '## Routes',
    '',
    '| route | ready samples | tracks | bytes | frames in error |',
    '|---|---|---|---|---|',
    ...summary.routes.map((route) => `| ${route.name} | ${route.readySamples}/${route.samples} | ${route.tracks.join(',')} | ${route.firstBytes} → ${route.lastBytes} | ${route.framesInError} |`),
    '',
    summary.passed ? 'Sampler verdict: PASS' : 'Sampler verdict: FAIL',
    '',
  ];
  return lines.join('\n');
}

async function main() {
  const options = parseArguments(process.argv.slice(2));
  const revision = git('rev-parse', 'HEAD');
  // Only tracked modifications invalidate the evidence; the repository keeps
  // unrelated untracked files that the acceptance must not depend on.
  const dirty = git('status', '--porcelain', '--untracked-files=no').length > 0;
  const stamp = new Date().toISOString().replace(/[:.]/g, '-');
  const runId = `${stamp}-${options.label}-${revision.slice(0, 7)}`;
  const directory = path.join(options.out, runId);
  mkdirSync(directory, { recursive: true });
  const authorization = controlPlaneAuthorization();

  const capabilities = await getJson(`${options.core}/api/v1/system/capabilities`, authorization)
    .catch(() => ({}));
  const meta = {
    runId,
    revision,
    dirtyWorkingTree: dirty,
    startedAt: new Date().toISOString(),
    label: options.label,
    mode: options.mode,
    targetFps: options.targetFps,
    intervalSeconds: options.intervalSeconds,
    plannedMinutes: options.minutes,
    node: process.version,
    platform: `${process.platform}-${process.arch}`,
    scene: digestSceneDocument(),
    renderer: capabilities.renderer ?? null,
    encoder: capabilities.videoEncoder ?? null,
    thresholds: THRESHOLDS,
  };
  writeFileSync(path.join(directory, 'meta.json'), JSON.stringify(meta, null, 2));
  console.log(`[soak] run ${runId}`);
  console.log(`[soak] revision ${revision}${dirty ? ' (dirty working tree)' : ''}`);
  console.log(`[soak] evidence ${directory}`);

  const deadline = Date.now() + options.minutes * 60_000;
  const samples = [];
  const samplesFile = path.join(directory, 'samples.jsonl');
  while (Date.now() < deadline) {
    try {
      const entry = await sample(options, authorization);
      samples.push(entry);
      appendFileSync(samplesFile, JSON.stringify(entry) + '\n');
      const healthy = entry.sources?.healthy ?? 0;
      const visible = entry.sources?.visible ?? 0;
      console.log(`[soak] ${entry.timestamp} routes=${entry.routes.length} visible=${visible} healthy=${healthy} publish=${entry.program?.publish ?? '?'}`);
    } catch (error) {
      console.error(`[soak] sample failed: ${error.message}`);
    }
    await new Promise((resolve) => setTimeout(resolve, options.intervalSeconds * 1000));
  }

  const summary = summarize(options, meta, samples);
  writeFileSync(path.join(directory, 'summary.json'), JSON.stringify(summary, null, 2));
  writeFileSync(path.join(directory, 'summary.md'), renderMarkdown(summary, options));
  console.log(`[soak] ${summary.passed ? 'PASS' : 'FAIL'} — ${directory}`);
  process.exitCode = summary.passed ? 0 : 1;
}

main().catch((error) => {
  console.error(`[soak] fatal: ${error.message}`);
  process.exitCode = 2;
});
