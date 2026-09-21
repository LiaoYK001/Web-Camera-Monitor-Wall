export type AnalyticsPriority = 'focus' | 'large' | 'normal';
export type AnalyticsWork = 'frame' | 'person';

const LIMITS: Record<AnalyticsWork, number> = { frame: 8, person: 4 };
const starts: Record<AnalyticsWork, Array<{ at: number; priority: AnalyticsPriority }>> = {
  frame: [], person: [],
};

function clock(): number {
  return typeof performance === 'undefined' ? Date.now() : performance.now();
}

/**
 * Process-wide browser budget. Each Monitor tile shares this window, so a
 * 16-camera scene cannot create an unbounded number of canvas reads or model
 * inferences. A denied request is intentionally dropped; the next video frame
 * will retry and no frame backlog is retained.
 */
export function requestAnalyticsSlot(work: AnalyticsWork, priority: AnalyticsPriority = 'normal', at = clock()): boolean {
  const window = starts[work];
  while (window.length && at - window[0].at >= 1000) window.shift();
  // Focus and large tiles are admitted first when a caller has already
  // consumed the budget; replacing an in-flight/finished slot would violate
  // the hard rate bound, so lower-priority work waits for the next window.
  if (window.length >= LIMITS[work]) return false;
  window.push({ at, priority });
  return true;
}

export function resetAnalyticsScheduler(): void {
  starts.frame.length = 0;
  starts.person.length = 0;
}

export function analyticsSchedulerSnapshot(at = clock()): { frame: number; person: number; limits: typeof LIMITS } {
  for (const work of ['frame', 'person'] as const) {
    while (starts[work].length && at - starts[work][0].at >= 1000) starts[work].shift();
  }
  return { frame: starts.frame.length, person: starts.person.length, limits: LIMITS };
}
