/** Bounded requests without requiring AbortSignal.any in older Android WebViews. */
export async function withRequestTimeout<T>(milliseconds: number, operation: (signal: AbortSignal) => Promise<T>, parent?: AbortSignal): Promise<T> {
  const controller = new AbortController();
  const abort = () => controller.abort(parent?.reason);
  const timer = window.setTimeout(() => controller.abort(new DOMException('请求超时', 'TimeoutError')), milliseconds);
  parent?.addEventListener('abort', abort, { once: true });
  if (parent?.aborted) abort();
  try {
    if (controller.signal.aborted) throw controller.signal.reason;
    return await operation(controller.signal);
  } finally {
    window.clearTimeout(timer);
    parent?.removeEventListener('abort', abort);
  }
}
