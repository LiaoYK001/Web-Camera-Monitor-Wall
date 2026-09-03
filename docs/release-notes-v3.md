# v3 analytics release line / v3 分析发布线

Status / 状态：implementation is on `dev`; `v3.0` and `v3.1` remain unreleased until revision-bound private platform gates pass / 实现已进入 `dev`；`v3.0` 与 `v3.1` 必须等待绑定同一 revision 的本机平台门禁通过后才发布。

## v3.0 / v3-M1

- Adds per-Camera/Profile motion and scene-change policy tuning with an atomic Registry v3 migration.
- Uses ONVIF native events first, then a bounded browser Dedicated Worker over downsampled same-origin frames. Cross-origin MJPEG pixel access is reported as unsupported and never starts a hidden server media path.
- Adds schema-versioned DetectionSignal v2, replay/rate/timestamp/coordinate validation, scoped runtime sessions and the `#/analytics` workspace.
- Keeps ordinary RTSP in Gateway/Hybrid and preserves the True Direct zero-server-media boundary for WHEP/HLS/MJPEG.

## v3.1 / v3-M2

- Adds a same-origin, SHA-256 verified ONNX SSD-MobileNetV1 person-only model asset.
- Browser inference prefers WebGPU and falls back to single-thread WASM; model output is letterboxed back to normalized source coordinates and limited to 16 boxes.
- Adds an administrator-controlled, CPU-only detector job contract with worker-only scheduling, mTLS/generation fencing, a 60-second Camera/Profile-bound media Grant, bounded RGBA frame requests/results and resource reservations. Worker failures never stop recording; without an explicitly configured loopback frame source the job fails closed.
- No face recognition, identity tracking, emotion inference, screenshots, raw frames, Camera secrets or unrestricted URLs are stored or published.

## Release boundary / 发布边界

Only the Local-first PWA Docker image is a release artifact. EXE, APK and
production IWA bundles remain out of scope. A release must use the local
publisher after public audit, v1/v2 regressions, Windows Chrome/Edge gates and
WSL2 Chromium/Worker gates have produced fresh receipts for the exact commit.
