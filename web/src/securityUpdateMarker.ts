/**
 * Durable record of a forced service-worker security replacement.
 *
 * The replacement worker writes this record while it installs and `activate`
 * keeps it, so the freshly navigated document can still tell the user what the
 * forced replacement cost.  Cache Storage is the only medium both the worker and
 * the page can reach across a reload without a message channel, and the record
 * contains nothing but a timestamp.
 *
 * Only an explicit user action clears the record (see ./pwaContinuity).
 */
export const SECURITY_UPDATE_CACHE = 'webobs-security-update-v1';
export const SECURITY_UPDATE_MARKER_PATH = '/__webobs-security-update__';
export const SECURITY_UPDATE_FORMAT = 'webobs-security-update-v1';

export interface SecurityUpdateMarker {
  format: typeof SECURITY_UPDATE_FORMAT;
  /** Wall-clock time of the replacement install; null when the record is unreadable. */
  requiredAt: number | null;
}

function markerRequest(): Request {
  return new Request(new URL(SECURITY_UPDATE_MARKER_PATH, location.origin).href);
}

export async function writeSecurityUpdateMarker(requiredAt: number = Date.now()): Promise<void> {
  const cache = await caches.open(SECURITY_UPDATE_CACHE);
  const value: SecurityUpdateMarker = { format: SECURITY_UPDATE_FORMAT, requiredAt };
  await cache.put(markerRequest(), new Response(JSON.stringify(value), {
    headers: { 'Content-Type': 'application/json' },
  }));
}

export async function readSecurityUpdateMarker(): Promise<SecurityUpdateMarker | null> {
  if (typeof caches === 'undefined') return null;
  if (!(await caches.keys()).includes(SECURITY_UPDATE_CACHE)) return null;
  const cache = await caches.open(SECURITY_UPDATE_CACHE);
  const stored = await cache.match(markerRequest());
  if (!stored) return null;
  try {
    const body = await stored.json() as Partial<SecurityUpdateMarker>;
    if (!body || body.format !== SECURITY_UPDATE_FORMAT) return null;
    return { format: SECURITY_UPDATE_FORMAT, requiredAt: Number.isFinite(body.requiredAt) ? Number(body.requiredAt) : null };
  } catch {
    // An unreadable record still proves a replacement happened.  Fail towards the
    // honest notice instead of silently reporting "no update".
    return { format: SECURITY_UPDATE_FORMAT, requiredAt: null };
  }
}

/** Explicit user action only: never called by an automatic timer or sync run. */
export async function clearSecurityUpdateMarker(): Promise<void> {
  if (typeof caches === 'undefined') return;
  if (!(await caches.keys()).includes(SECURITY_UPDATE_CACHE)) return;
  const cache = await caches.open(SECURITY_UPDATE_CACHE);
  await cache.delete(markerRequest());
}
