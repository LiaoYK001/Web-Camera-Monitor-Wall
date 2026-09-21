# v3 analytics runtime / v3 分析运行时

This document describes the implementation boundary for v3-M1/v3-M2. It is a
development contract, not a claim that the private release gates have passed.

## Execution order / 执行顺序

For each Camera/Profile, motion and scene-change use the following order:

1. Camera-native ONVIF event when the approved Profile advertises it.
2. Browser Dedicated Worker for same-origin WHEP/HLS/Gateway video frames.
3. An administrator-approved server Worker only when a runtime plan explicitly
   returns `worker` and the user accepts the server media increment.
4. `unsupported` with a visible reason. There is no hidden server fallback.

Person boxes use the browser WebGPU execution provider first and single-thread
WASM second. The model is a same-origin, SHA-256 verified static asset. A
server Worker is optional, CPU-only in this release line, and never receives a
Camera Secret or unrestricted URL. Its image layer includes hash-locked
`onnxruntime==1.29.0` and NumPy wheels; deployments that deliberately omit
that optional layer fail closed with `runtime_unavailable` rather than silently
switching to an unbounded CPU implementation.

## API / API

The public control proxy exposes `/api/v3/analytics/*` while preserving API v1
and v2. Runtime plans are short-lived (10 minutes), bound to one Camera and
Profile, and carry no credentials. Signal batches contain at most 32 signals;
the server validates the session, enabled policy, timestamp, replay ID,
confidence and normalized boxes before forwarding bounded event metadata.

`person` signals must include a model SHA-256. Server-generated event sources
are `browser-motion` and `browser-detector`; clients cannot choose an arbitrary
source. Signals are rate limited to 60 per client and 12 per Profile per
minute. Session close is an idempotent `DELETE` and removes replay state.

The implemented endpoints are:

```text
GET    /api/v3/analytics/policies
PATCH  /api/v3/analytics/policies                 (baseRevision + <=256 items)
POST   /api/v3/analytics/runtime-plans             (one Camera/Profile session)
GET    /api/v3/analytics/status
POST   /api/v3/analytics/signals/batch             (X-WebObs-Analytics-Session)
POST   /api/v3/analytics/runtime-sessions/{id}/renew (same owner/scope, +10 minutes)
DELETE /api/v3/analytics/runtime-sessions/{id}
GET/POST /api/v2/analytics-jobs                    (administrator Worker jobs)

An approved Worker claims a job over mTLS.  The claim response contains a
60-second, Camera/Profile-bound `mediaGrant` whose token is stored only as a
SHA-256 hash.  The Worker presents it on
`GET /internal/v1/analytics/jobs/{jobId}/frame`; the controller accepts at most
60 bounded `160x90` RGBA JSON frames from the explicitly configured
`WEBOBS_ANALYTICS_MEDIA_ENDPOINT` loopback source.  No camera URL, Secret or
arbitrary filesystem path is sent to the Worker.  The grant is renewed with
the job lease and revoked atomically when the job completes or fails.  If no
loopback frame source is configured, the job fails with
`analytics_media_unavailable` rather than silently starting a decoder or
transcoder.
```

Policy writes are atomic and scoped: the control boundary parses every item in
a batch, rejects mixed Camera IDs, and applies the caller's RBAC camera scope
before the loopback Registry sees the request. Runtime plans report execution,
owner, transport, expiry and `serverMediaExpected`; an ordinary RTSP plan is
never reported as browser True Direct.

Runtime sessions are renewed only while a visible client is actively using the
profile. Renewal is owner-bound and cannot change the Camera/Profile or grant
new capabilities; a failed renewal is handled as a normal expiry/reconnect,
not as a silent authorization extension.

## Model supply chain / 模型供应链

`web/public/models/person-model.manifest.json` fixes the model id, source,
license and SHA-256. `personDetector.ts` downloads only that same-origin path,
verifies the digest with WebCrypto, and caches bytes after verification. No CDN
script or remote model is used. The model is an ONNX Model Zoo SSD-MobileNetV1
opset-12 person-only asset; its license and digest are recorded in
`web/public/models/NOTICE.txt`.

## Privacy / 隐私

Frames are downsampled in the browser and transferred only to a local Worker.
They are not put into IndexedDB, events, logs, backups or release artifacts.
Persisted analytics data is limited to bounded signal metadata, normalized
person boxes, confidence, model identity and timestamps. No face recognition,
identity tracking, emotion inference or biometric database is implemented.

## Operational commands / 运维命令

The `#/analytics` workspace shows each Profile's policy, planned execution,
sampling and whether Docker media is expected. Use `#/devices` for per-Profile
switches and `#/monitor` to see bounded detection boxes. Ordinary RTSP remains
Gateway/Hybrid in a normal PWA; it is never labelled True Direct.

Before a v3.0 or v3.1 release, create revision-bound private receipts under
`build/private-gates` and run the corresponding verifier. Self-hosted runners
remain disabled by default; do not publish a tag or GHCR digest until the
Windows and WSL2 gates have been executed on the exact commit.
