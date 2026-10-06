# 浏览器归档回放边界 / Browser archive playback bounds

## Policy, not device qualification / 策略不等于设备验收

S3 playback uses the product-authenticated ticket endpoint, then downloads the
presigned HTTPS object without product cookies, Authorization headers or referrer.
Redirects, URL userinfo and fragments are rejected. The complete byte count and
SHA-256 must match the ticket before any playback Blob is exposed.

**The browser in-memory limit is 32 MiB (33,554,432 bytes), reduced from 512 MiB.**
This is a conservative engineering guard, **not** a measured safe maximum on any
Android phone, WebView, desktop or browser. Larger archived recordings remain
stored; this browser path refuses them before the object fetch. It does not
silently truncate media, skip verification or fall back to an unbounded download.
A future larger-file path needs separately verified bounded hashing/storage and
reference-device measurement; this change does not implement such a path.

浏览器内存回放硬上限为 **32 MiB**。这是保守工程限制，不代表手机或 WebView
已通过最大文件规格验收。大文件不会被删除，但此浏览器路径拒绝回放；不会
降级为无界下载或跳过完整摘要校验。提高上限前必须完成目标参考设备实测。

- A single **60-second total deadline** includes ticket acquisition, headers,
  streaming body and the complete SHA-256 check. A component AbortSignal cancels
  the same operation. The existing request-timeout utility bounds even a
  transport that ignores abort, without requiring AbortSignal.any/timeout.
- The media body must support streaming. A single exact-ticket-size buffer is
  allocated only after ticket validation and available header checks. Every
  incoming chunk is checked against remaining declared bytes and the hard cap
  **before copying**. Content-Length is only an early rejection check: a missing
  or lying header cannot bypass actual cumulative byte validation.
- Overflow, abort and timeout cancel the reader; reader locks are released.
  Cancellation is initiated but never awaited, since cancel itself can hang.
  Late headers are closed rather than used. Failed size/hash checks produce no
  playable Blob and no Object URL.
- Full SHA-256 still uses WebCrypto, which is not incremental or cancellable.
  The payload buffer, WebCrypto input copy, Blob backing storage, browser network
  buffers and video decoding may coexist. **32 MiB bounds accepted payload, not
  total process RAM.** Abort suppresses late digest results; it cannot stop work
  already inside WebCrypto. Memory reclamation is controlled by the browser/GC.
- No real S3, camera, physical phone, WebView memory-pressure, installed desktop,
  APK, soak, release build or publication qualification is implied by fixtures.

## UI integration / 页面接入

[The hook](<../web/src/useArchivedRecording.ts>) owns one active selection and one
Object URL. [The download module](<../web/src/archiveDownload.ts>) owns the total
deadline and byte/hash validation. [The API wrapper](<../web/src/api.ts>) only
acquires the product ticket with the owned signal and delegates verification.

Use one hook instance per archive playback surface:

~~~tsx
const archive = useArchivedRecording();
// returns { preview, loading, busy, error, select, close }
// preview: { segmentId, cameraId, url } | null
// loading: { segmentId, cameraId } | null

<button onClick={() => void archive.select(segment.id, segment.cameraId)}>
  校验并回放
</button>
{archive.busy && <button onClick={archive.close}>取消下载</button>}
{archive.error && <div role="alert">{archive.error}</div>}
{archive.preview && <>
  <button onClick={archive.close}>关闭</button>
  <video key={archive.preview.url} src={archive.preview.url} controls playsInline />
</>}
~~~

Remove the old local archive preview/loading state, async playArchived function,
fetchVerifiedArchivedRecording import and Object URL cleanup effect from the
integrating component. Do not duplicate URL creation/revocation or append a
caller-owned async success/error callback. Derive success text directly from
archive.preview. Disable the currently downloading selection (compare both
segmentId and cameraId); selecting a different recording synchronously aborts
and replaces the previous owner. Repeating the same pending selection does not
start a second request. Alternatively disable all selection buttons while busy.

Replacement, close and unmount invalidate the owner before abort, revoke the
previous Object URL exactly once and ignore late success/error results. Busy
work uses the existing draft-navigation guard with a download-specific message;
users can cancel before navigating. A unique archive-playback hook key reports
pending work through the shared desktop/Android install-preflight contract.
Management forms should report their own work separately, not report the hook a
second time. Read cancellation is not a server-side mutation rollback.

## Focused fixtures / 快速失败用例

[The archive tests](<../web/tests/local-runtime/archive-playback.spec.ts>) run
synthetic ReadableStreams and real browser WebCrypto/React lifecycle behavior:
actual streaming overflow, early Content-Length rejection, truncated body,
wrong complete hash, invalid/over-cap tickets, unsafe endpoint forms, abort,
hanging ticket/headers/body/digest, a hanging cancel promise, late results,
duplicate selection, URL cleanup, unmount and navigation/install-preflight flags.
The fixture deliberately forbids response.arrayBuffer(). Fake-clock deadlines
keep these checks fast; no external archive endpoint or camera is contacted.

~~~powershell
# From web/, with already installed repository dependencies and Chromium:
node node_modules/typescript/lib/tsc.js --noEmit
node node_modules/@playwright/test/cli.js test -c playwright.archive.config.ts --project=chromium
~~~

[The isolated config](<../web/playwright.archive.config.ts>) uses loopback port
4186 and a dedicated test-results-archive directory; it does not replace the
normal application or touch devices. These tests show logical bounds and
ownership, **not a maximum-size decode/memory qualification**. Reference-phone
maximum-size playback under memory pressure, real object-store CORS/connection
cancellation and candidate-build checks remain separate release work.
