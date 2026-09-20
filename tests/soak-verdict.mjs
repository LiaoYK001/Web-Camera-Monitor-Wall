/**
 * Pure verdict logic for the browser soak acceptance (feedback-5).
 *
 * Both the long-run driver (web/tests/local-runtime/browser-soak.spec.ts) and the
 * tool that recomputes a run from its incremental evidence (tests/soak-derive.mjs)
 * call buildVerdict(), so a run cannot pass one path and fail the other.
 *
 * The rules exist because the first version of this harness claimed PASS on runs
 * it had not actually observed:
 *
 *  - it only computed a gap when the next frame arrived, so a stream that stopped
 *    for good at the end of the run contributed no gap at all;
 *  - it recorded a gap only when the gap exceeded 1000 ms and then printed 0 ms
 *    as "the largest gap", which reads like a perfect run;
 *  - it derived the frame rate from requestVideoFrameCallback presentation counts
 *    and labelled them decoded frames;
 *  - it did not assert that every expected source was observed at all;
 *  - a run that ended early, lost its player, or never wrote a final snapshot
 *    could still be recomputed into a PASS.
 *
 * Every rule below is therefore explicit, and every input it needs is an
 * argument: buildVerdict() never guesses a target, an expected set or a
 * duration, and it never treats missing data as good news.
 */

/** Thresholds, unchanged from the agreed acceptance plan. */
export const FIRST_FRAME_BUDGET_MS = 20_000;
export const REOPEN_BUDGET_MS = 8_000;
export const STALL_BUDGET_MS = 3_000;
export const FPS_RATIO = 0.9;
/** A formal soak covers at least this many seconds of valid observation. */
export const MIN_FORMAL_SECONDS = 1800;

export const STATUS = {
  PASS: 'PASS',
  FAIL: 'FAIL',
  INCOMPLETE: 'INCOMPLETE',
  SMOKE_PASS: 'SMOKE_PASS',
  SMOKE_FAIL: 'SMOKE_FAIL',
};

function numberOrNull(value) {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function rounded(value, digits = 2) {
  return value === null ? null : Number(value.toFixed(digits));
}

function coversExcusedWindow(run, sourceId, fromMs, toMs) {
  const windows = Array.isArray(run.excusedStallWindows) ? run.excusedStallWindows : [];
  return windows.some((window) => {
    if (window.id !== sourceId) return false;
    const start = numberOrNull(window.fromMs);
    const end = numberOrNull(window.toMs);
    if (start === null || end === null) return false;
    return fromMs >= start && toMs <= end;
  });
}

/**
 * Turns one observed source into the numbers the checks need.
 *
 * `decodedFrames`/`presentedFrames` are accumulated totals across player
 * generations (a replaced <video> element gets fresh counters, so the driver
 * adds each generation's delta instead of reading the element once).
 */
export function measureSource(run, source, expected) {
  const durationSeconds = numberOrNull(run.observation?.durationSeconds) ?? 0;
  const targetFps = numberOrNull(source.targetFps) ?? numberOrNull(expected?.targetFps) ?? numberOrNull(run.targetFps);
  const presentedFrames = numberOrNull(source.presentedFrames);
  const decodedFrames = numberOrNull(source.decodedFrames);
  const receivedFrames = numberOrNull(source.receivedFrames);
  const presentedFps = presentedFrames === null || durationSeconds <= 0 ? null : presentedFrames / durationSeconds;
  const decodedFps = decodedFrames === null || durationSeconds <= 0 ? null : decodedFrames / durationSeconds;
  const receivedFps = receivedFrames === null || durationSeconds <= 0 ? null : receivedFrames / durationSeconds;

  const endedMaxGapMs = numberOrNull(source.endedMaxGapMs) ?? 0;
  const inProgressGapMsAtEnd = numberOrNull(source.inProgressGapMsAtEnd);
  // A stream that never produced another frame still has an in-progress gap;
  // that age must count as an observed stall, not vanish.
  const effectiveMaxGapMs = Math.max(endedMaxGapMs, inProgressGapMsAtEnd ?? 0);

  const stalls = (Array.isArray(source.longStalls) ? source.longStalls : [])
    .map((stall) => ({
      id: source.id,
      fromMs: numberOrNull(stall.fromMs),
      toMs: numberOrNull(stall.toMs),
      gapMs: numberOrNull(stall.gapMs),
    }))
    .filter((stall) => stall.toMs !== null);
  const unexpectedStalls = stalls.filter((stall) => !coversExcusedWindow(run, source.id, stall.fromMs ?? 0, stall.toMs));

  const trailingStall = inProgressGapMsAtEnd !== null && inProgressGapMsAtEnd > STALL_BUDGET_MS
    && !coversExcusedWindow(run, source.id, source.lastFrameAtMs ?? 0, (source.lastFrameAtMs ?? 0) + inProgressGapMsAtEnd);

  return {
    id: source.id,
    expected: Boolean(expected),
    sourceType: source.sourceType ?? run.sourceType ?? 'unknown',
    targetFps,
    presentedFrames,
    decodedFrames,
    receivedFrames,
    presentedFps: rounded(presentedFps),
    decodedFps: rounded(decodedFps),
    receivedFps: rounded(receivedFps),
    decodedRatio: targetFps && decodedFps !== null ? rounded(decodedFps / targetFps, 3) : null,
    presentedRatio: targetFps && presentedFps !== null ? rounded(presentedFps / targetFps, 3) : null,
    firstFrameMs: numberOrNull(source.firstFrameMs),
    endedMaxGapMs,
    inProgressGapMsAtEnd,
    effectiveMaxGapMs,
    longStalls: stalls,
    unexpectedStalls: unexpectedStalls.length,
    trailingStallWithoutRecovery: Boolean(trailingStall),
    mediaTimeSeconds: numberOrNull(source.mediaTimeSeconds),
    generations: numberOrNull(source.generations) ?? 0,
    counterResets: numberOrNull(source.counterResets) ?? 0,
    teardownCount: numberOrNull(source.teardownCount) ?? 0,
  };
}

export function measureRun(run) {
  const expected = Array.isArray(run.expected) ? run.expected : [];
  const observed = Array.isArray(run.observed) ? run.observed : [];
  const observedById = new Map(observed.map((source) => [source.id, source]));
  const rows = expected.map((entry) => measureSource(run, observedById.get(entry.id) ?? { id: entry.id }, entry));
  const extras = observed.filter((source) => !expected.some((entry) => entry.id === source.id))
    .map((source) => measureSource(run, source, null));
  return { rows, extras, observedById };
}

function check(id, name, passed, detail, blocking = true) {
  return { id, name, passed: Boolean(passed), detail, blocking };
}

/**
 * Builds the verdict for one run.
 *
 * Input (all required unless noted):
 *   runId, mode ('direct'|'composite'), sourceType ('real'|'synthetic'|'unknown'),
 *   targetFps, expected: [{ id, targetFps }], observed: [ ...see measureSource ],
 *   observation: { installedBeforeAction, modeSwitch, allExpectedReady, complete,
 *                  earlyTeardown, durationSeconds, smoke, finalSnapshotWritten },
 *   program (composite only), excusedStallWindows (optional),
 *   limitations (optional strings).
 */
export function buildVerdict(run) {
  const observation = run.observation ?? {};
  const durationSeconds = numberOrNull(observation.durationSeconds) ?? 0;
  const smoke = observation.smoke === true;
  const { rows, extras } = measureRun(run);
  const expected = Array.isArray(run.expected) ? run.expected : [];
  const checks = [];

  const missing = expected.filter((entry) => !rows.find((row) => row.id === entry.id)).map((entry) => entry.id);
  const unobserved = rows.filter((row) => row.presentedFrames === null && row.decodedFrames === null && row.firstFrameMs === null).map((row) => row.id);
  checks.push(check('expected-sources',
    'every expected source was declared and observed',
    expected.length > 0 && missing.length === 0 && unobserved.length === 0,
    expected.length === 0
      ? 'no expected source set was supplied, so completeness cannot be judged'
      : [missing.length ? `missing from the plan: ${missing.join(', ')}` : '',
         unobserved.length ? `never observed playing: ${unobserved.join(', ')}` : '',
         extras.length ? `extra sources observed (informational): ${extras.map((row) => row.id).join(', ')}` : '',
        ].filter(Boolean).join('; ') || `all ${expected.length} expected sources observed`));

  const undefinedTargets = rows.filter((row) => row.targetFps === null || !(row.targetFps > 0)).map((row) => row.id);
  checks.push(check('targets-defined',
    'every expected source has a positive target frame rate',
    rows.length > 0 && undefinedTargets.length === 0,
    undefinedTargets.length ? `no target for: ${undefinedTargets.join(', ')}`
      : rows.map((row) => `${row.id}=${row.targetFps}`).join(', ')));

  checks.push(check('sampling-before-action',
    'sampling was installed before the start action was triggered',
    observation.installedBeforeAction === true,
    observation.installedBeforeAction === true
      ? 'the observer was installed before the mode switch, so the first frame covers plan, queue, activation, ICE and play'
      : 'the observer was installed after the start action, so the measured first frame is incomplete'));

  checks.push(check('mode-switch',
    'the requested playback mode was actually switched on',
    observation.modeSwitch === 'ok',
    `mode switch: ${observation.modeSwitch ?? 'unknown'}`));

  checks.push(check('continuous-observation',
    'the observation was complete and the final snapshot was written before teardown',
    observation.complete === true && observation.earlyTeardown !== true && observation.finalSnapshotWritten !== false,
    observation.earlyTeardown === true ? 'the run was torn down before the observation window ended'
      : observation.complete === true ? 'final snapshot taken and evidence written before any teardown'
      : 'the observation window never completed'));

  // Duration decides whether a result may be called formal; a run that declares
  // itself a smoke run is not failed for being short, it is simply never PASS.
  checks.push(check('duration',
    `at least ${MIN_FORMAL_SECONDS}s of valid observation for a formal result`,
    durationSeconds >= MIN_FORMAL_SECONDS,
    `${durationSeconds.toFixed(1)}s of valid observation`,
    smoke !== true));

  const stalledMedia = rows.filter((row) => row.mediaTimeSeconds === null || row.mediaTimeSeconds <= 1).map((row) => row.id);
  checks.push(check('media-time',
    'every expected source advanced its media time',
    rows.length > 0 && stalledMedia.length === 0,
    stalledMedia.length ? `did not advance: ${stalledMedia.join(', ')}`
      : rows.map((row) => `${row.id}=${row.mediaTimeSeconds}s`).join(', ')));

  const lateFirstFrame = rows.filter((row) => row.firstFrameMs === null || row.firstFrameMs > FIRST_FRAME_BUDGET_MS).map((row) => row.id);
  checks.push(check('first-frame',
    `first frame within ${FIRST_FRAME_BUDGET_MS}ms`,
    rows.length > 0 && lateFirstFrame.length === 0,
    rows.map((row) => `${row.id}=${row.firstFrameMs === null ? 'never' : `${row.firstFrameMs}ms`}`).join(', ')));

  // A trailing gap has no completed-stall entry behind it (the frame never came
  // back), so it must be able to fail the check on its own; an end-to-end run with
  // a stopped source exposed exactly that hole.
  const stalled = rows.filter((row) => row.effectiveMaxGapMs > STALL_BUDGET_MS
    && (row.unexpectedStalls > 0 || row.trailingStallWithoutRecovery)).map((row) => row.id);
  const trailing = rows.filter((row) => row.trailingStallWithoutRecovery).map((row) => row.id);
  checks.push(check('frame-stall',
    `no unexplained frame stall beyond ${STALL_BUDGET_MS}ms (including a stream that never returns)`,
    rows.length > 0 && stalled.length === 0,
    rows.map((row) => `${row.id}: max ${row.effectiveMaxGapMs}ms`
      + (row.inProgressGapMsAtEnd ? ` (${row.inProgressGapMsAtEnd}ms with no frame at the end)` : '')
      + (row.unexpectedStalls ? `, ${row.unexpectedStalls} unexplained stall(s)` : '')).join('; ')
      + (trailing.length ? `; no recovery observed for ${trailing.join(', ')}` : '')));

  const unknownDecoded = rows.filter((row) => row.decodedFps === null).map((row) => row.id);
  const slowDecoded = rows.filter((row) => row.decodedRatio !== null && row.decodedRatio < FPS_RATIO).map((row) => row.id);
  checks.push(check('decoded-frame-rate',
    `decoded frame rate is at least ${FPS_RATIO * 100}% of each target`,
    rows.length > 0 && unknownDecoded.length === 0 && slowDecoded.length === 0,
    rows.map((row) => `${row.id}: decoded ${row.decodedFps ?? 'unknown'}/${row.targetFps} fps (${row.decodedRatio ?? 'unknown'})`).join(', ')));

  // Presentation smoothness is reported next to the decoded rate, never instead
  // of it; the acceptance threshold is the decoded rate above.
  const slowPresented = rows.filter((row) => row.presentedRatio !== null && row.presentedRatio < FPS_RATIO).map((row) => row.id);
  checks.push(check('presented-smoothness',
    `presented frame rate is at least ${FPS_RATIO * 100}% of each target (reported, not the acceptance metric)`,
    rows.length > 0 && slowPresented.length === 0,
    rows.map((row) => `${row.id}: presented ${row.presentedFps ?? 'unknown'}/${row.targetFps} fps (${row.presentedRatio ?? 'unknown'})`).join(', '),
    false));

  const counterRows = rows.filter((row) => row.generations < 1 && row.counterResets > 0);
  checks.push(check('counter-integrity',
    'player generations were tracked (no unaccounted counter reset)',
    counterRows.length === 0,
    rows.map((row) => `${row.id}: ${row.generations} generation(s), ${row.counterResets} reset(s), ${row.teardownCount} teardown(s)`).join('; '),
    false));

  if (run.mode === 'composite') {
    // A healthy program frame rate is not evidence that the five inputs behind it
    // were healthy, so the per-input engine state sampled during the run is part
    // of the verdict rather than a separate report.
    const programPresent = Boolean(run.program);
    const programRow = programPresent ? measureSource(run, { ...run.program, id: 'program' }, { id: 'program', targetFps: run.program.targetFps ?? run.targetFps }) : null;
    const inputs = Array.isArray(run.program?.inputsHealthy) ? run.program.inputsHealthy : [];
    const unhealthyInputs = inputs.filter((input) => input.state !== 'healthy');
    const unhealthySamples = numberOrNull(run.program?.unhealthySamples);
    checks.push(check('program-and-inputs',
      'the composite program played and every input stayed healthy',
      programPresent
        && programRow.effectiveMaxGapMs <= STALL_BUDGET_MS
        && programRow.firstFrameMs !== null && programRow.firstFrameMs <= FIRST_FRAME_BUDGET_MS
        && inputs.length > 0 && unhealthyInputs.length === 0
        && (unhealthySamples === null || unhealthySamples === 0),
      !programPresent ? 'no program observation was recorded'
        : `program: first frame ${programRow.firstFrameMs ?? 'never'}ms, max gap ${programRow.effectiveMaxGapMs}ms, ${programRow.mediaTimeSeconds ?? 'unknown'}s; `
          + (inputs.length === 0 ? 'per-input engine state was not recorded'
            : `inputs: ${inputs.map((input) => `${input.id}=${input.state}`).join(', ')}`)
          + (unhealthySamples === null ? '' : `; samples reporting unhealthy: ${unhealthySamples}`)
          + (unhealthyInputs.length ? `; unhealthy inputs: ${unhealthyInputs.map((input) => input.id).join(', ')}` : '')));
  }

  // A recording that never captured a value cannot be used to claim the check
  // passed; the caller lists the checks it cannot verify and they fail here.
  const unverifiable = new Set(Array.isArray(run.unverifiableChecks) ? run.unverifiableChecks : []);
  for (const item of checks) {
    if (!unverifiable.has(item.id)) continue;
    item.passed = false;
    item.detail = `cannot be verified from this recording: ${item.detail}`;
    item.unverifiable = true;
  }

  const blocking = checks.filter((item) => item.blocking);
  const blockingPassed = blocking.every((item) => item.passed);
  // A run whose final snapshot was never written cannot be judged at all: the
  // evidence it would be judged from is exactly what is missing.
  const incomplete = observation.complete !== true || observation.earlyTeardown === true
    || observation.finalSnapshotWritten === false;
  let status;
  if (incomplete) status = STATUS.INCOMPLETE;
  else if (smoke) status = blockingPassed ? STATUS.SMOKE_PASS : STATUS.SMOKE_FAIL;
  else if (durationSeconds < MIN_FORMAL_SECONDS) status = STATUS.INCOMPLETE;
  else status = blockingPassed ? STATUS.PASS : STATUS.FAIL;

  return {
    runId: run.runId ?? 'unknown',
    mode: run.mode ?? 'direct',
    sourceType: run.sourceType ?? 'unknown',
    formal: status === STATUS.PASS || status === STATUS.FAIL,
    status,
    passed: status === STATUS.PASS,
    durationSeconds: rounded(durationSeconds, 1),
    thresholds: {
      firstFrameMs: FIRST_FRAME_BUDGET_MS,
      reopenMs: REOPEN_BUDGET_MS,
      stallMs: STALL_BUDGET_MS,
      decodedFpsRatio: FPS_RATIO,
      minFormalSeconds: MIN_FORMAL_SECONDS,
    },
    measured: rows,
    extraSources: extras,
    checks,
    unverifiableChecks: [...unverifiable],
    notes: [
      ...unverifiable.size ? [`not verifiable from this recording: ${[...unverifiable].join(', ')}`] : [],
      observation.installedBeforeAction === true ? null : 'first-frame timing did not start before the start action',
      observation.complete === true ? null : 'run ended without a complete observation window',
      ...(Array.isArray(run.limitations) ? run.limitations : []),
    ].filter(Boolean),
    smoke,
  };
}

export function statusIsPass(status) {
  return status === STATUS.PASS || status === STATUS.SMOKE_PASS;
}
