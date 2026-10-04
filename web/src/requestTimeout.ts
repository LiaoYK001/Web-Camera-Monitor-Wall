/** Bounded requests without requiring AbortSignal.any in older Android WebViews. */
export async function withRequestTimeout<T>(milliseconds: number, operation: (signal: AbortSignal) => Promise<T>, parent?: AbortSignal): Promise<T> {
  const controller = new AbortController();
  let cancelled = false, cancellationReason: unknown;
  let rejectCancellation!: (reason: unknown) => void;
  const cancellation = new Promise<never>((_resolve, reject) => { rejectCancellation = reject; });
  const cancel = (reason: unknown) => {
    if (cancelled) return;
    cancelled = true; cancellationReason = reason;
    // Deliver the actual deadline/owner reason before a transport substitutes
    // AbortError. Racing also bounds transports that ignore cancellation.
    rejectCancellation(reason);
    controller.abort(reason);
  };
  const abort = () => {
    const reason = parent?.reason;
    cancel(reason === undefined ? new DOMException('请求已取消', 'AbortError') : reason);
  };
  const timer = window.setTimeout(() => cancel(new DOMException('请求超时', 'TimeoutError')), milliseconds);
  parent?.addEventListener('abort', abort, { once: true });
  if (parent?.aborted) abort();
  const request = Promise.resolve().then(() => {
    if (cancelled) throw cancellationReason;
    return operation(controller.signal);
  });
  try {
    return await Promise.race([cancellation, request]);
  } finally {
    window.clearTimeout(timer);
    parent?.removeEventListener('abort', abort);
  }
}
