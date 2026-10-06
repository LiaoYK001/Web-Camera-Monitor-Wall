import { DIAGNOSTIC_LIMITS, diagnosticSnapshot, injectedVersion, nativeObservationRevision, observeNative } from './diagnosticsRuntime';
import type {} from './desktopRuntime';

export const NATIVE_READ_TIMEOUT_MS = 1500;
export const SUPPORT_REPORT_FILENAME = 'webobs-support-report.json';

let nativePending: Promise<unknown> | null = null;

/** Read-only IPC, only after a user asks. No service queries, uploads or storage. */
async function readNative(): Promise<'observed' | 'unavailable' | 'timeout'> {
  const bridge = window.webobsDesktop;
  if (!bridge || typeof bridge.status !== 'function') return 'unavailable';
  const revision = nativeObservationRevision();
  nativePending ??= Promise.resolve().then(() => bridge.status()).finally(() => { nativePending = null; });
  let timer: ReturnType<typeof setTimeout> | undefined;
  try {
    // The marker makes late settlement harmless: only the winning result is retained.
    const result = await Promise.race([
      nativePending.then(value => ({ kind: 'observed' as const, value }), () => ({ kind: 'unavailable' as const })),
      new Promise<{ kind: 'timeout' }>(resolve => { timer = setTimeout(() => resolve({ kind: 'timeout' }), NATIVE_READ_TIMEOUT_MS); }),
    ]);
    if (result.kind === 'observed' && revision === nativeObservationRevision()) observeNative(result.value);
    return result.kind;
  } finally { if (timer !== undefined) clearTimeout(timer); }
}

export async function captureSupportReport(): Promise<string> {
  const nativeRead = await readNative();
  const snapshot = diagnosticSnapshot();
  const native = snapshot.native as { version?: string };
  const bridge = window.webobsDesktop;
  const report = { format: 'webobs-support-report-v1', scope: 'current-page-observations', clock: 'unix-utc-milliseconds',
    identity: { webUI: injectedVersion(typeof __WEBOBS_BUILD_VERSION__ === 'string' ? __WEBOBS_BUILD_VERSION__ : undefined),
      desktopApp: bridge ? native.version ?? 'unavailable' : 'unavailable',
      client: bridge ? 'desktop-bridge' : typeof window.webobsAndroidForeground === 'boolean' ? 'android-lifecycle-bridge' : 'browser',
      sourceRevision: 'unavailable', backend: 'unavailable', apk: 'unavailable', webView: 'unavailable', electron: 'unavailable' },
    nativeRead, coverage: { media: 'whep-connections-only', audio: 'direct-mixer-only', recorder: 'last-archive-view-query', exportJobs: 'last-jobs-view-query', services: 'unavailable', frameClock: 'page-observed-not-source-capture', lifecycle: 'since-page-load-or-session-reset' },
    limits: DIAGNOSTIC_LIMITS, ...snapshot };
  // Compact JSON preserves the useful samples under the hard UTF-8 ceiling.
  // A future schema change must fail closed rather than exporting an unbounded report.
  const text = JSON.stringify(report);
  if (new TextEncoder().encode(text).byteLength > DIAGNOSTIC_LIMITS.bytes) throw new Error('support_report_size_limit');
  return text;
}

/** Only called by the explicit download button; never uses a server-provided filename. */
export function downloadSupportReport(text: string): void {
  if (new TextEncoder().encode(text).byteLength > DIAGNOSTIC_LIMITS.bytes) throw new Error('support_report_size_limit');
  const url = URL.createObjectURL(new Blob([text], { type: 'application/json' }));
  const link = document.createElement('a'); link.href = url; link.download = SUPPORT_REPORT_FILENAME;
  try { document.body.appendChild(link); link.click(); }
  finally { link.remove(); window.setTimeout(() => URL.revokeObjectURL(url), 1000); }
}
