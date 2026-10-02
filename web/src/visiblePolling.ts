import { isPageVisible, subscribePageVisibility } from './pageVisibility';

/** Read-only UI polling: one request at a time; hidden pages retain their last result. */
export function startVisiblePolling(task: (signal: AbortSignal) => Promise<void>, intervalMs: number) {
  let stopped = false;
  let paused = false;
  let timer: number | undefined;
  let request: AbortController | null = null;
  let pending: Promise<void> | undefined;
  const cancel = () => {
    window.clearTimeout(timer); timer = undefined;
    request?.abort(); request = null; pending = undefined;
  };
  const refresh = (): Promise<void> => {
    if (stopped || paused || !isPageVisible()) return Promise.resolve();
    if (pending) return pending;
    window.clearTimeout(timer); timer = undefined;
    const controller = new AbortController(); request = controller;
    pending = Promise.resolve().then(() => {
      if (!controller.signal.aborted) return task(controller.signal);
    }).catch(() => undefined).finally(() => {
      if (request !== controller) return;
      controller.abort(); // Cancel unfinished sibling reads if a task failed early.
      request = null; pending = undefined;
      if (!stopped && !paused && isPageVisible()) timer = window.setTimeout(() => void refresh(), intervalMs);
    });
    return pending;
  };
  const visibility = () => {
    if (!isPageVisible()) cancel();
    else void refresh();
  };
  const unsubscribe = subscribePageVisibility(visibility);
  window.addEventListener('focus', visibility);
  window.addEventListener('online', visibility);
  void refresh();
  return {
    refresh,
    pause() { paused = true; cancel(); },
    resume() { paused = false; return refresh(); },
    stop() {
      stopped = true; cancel(); unsubscribe();
      window.removeEventListener('focus', visibility);
      window.removeEventListener('online', visibility);
    },
  };
}
