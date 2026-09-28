# v3 analytics release line / v3 分析发布线

Status / 状态：the `v3.0.1` preview correction slice remains on `dev`; `v3.0`/`v3.0.1` and `v3.1` are not stable releases. The next available stable candidate is `v3.3`, pending its release gates / `v3.0.1` 预发布修正仍在 `dev`；`v3.0`/`v3.0.1` 与 `v3.1` 均非稳定版。下一个可用稳定候选为 `v3.3`，仍待发布门禁通过。

See the current bilingual release candidate notes in [release-notes-v3.3.md](release-notes-v3.3.md). / 当前双语发布候选说明见 [release-notes-v3.3.md](release-notes-v3.3.md)。

## v3.0.1 preview correction / v3.0.1 预发布修正

- Adds an encrypted, browser-local OBS-style workspace preference with a fully retained classic style, bounded dock reorder/region/size controls and safe default recovery.
- Adds per-source telemetry/audio-meter preferences, real measured audio threshold borders and event promotion hooks without writing overlays into Scene v5 or recordings.
- Keeps monitor tiles clean: media fallback, first-frame, authorization and runtime details are aggregated into the Problem Center with bounded technical fields.
- Adds administrator-side, revision-checked and idempotent import coordination for legacy Studio camera/RTSP sources; embedded credentials are never imported and are reported as requiring a Secret reference.

预发布候选默认构建版本为 `3.0.1-pre.1`、里程碑为 `v3-M2`，仅用于用户测试，不移动 `latest`，也不替代 v3.1 稳定门禁。

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
