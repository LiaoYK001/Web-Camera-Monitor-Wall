# WebObs Native client / WebObs 本地客户端

This directory contains the v2 Qt 6/QML and C++20 reference runtime. It uses GStreamer for media and the same stable Camera ID/Profile ID plus Scene v5 transform model as the server. It is development source, not a published v2.0 binary yet.

本目录是 v2 的 Qt 6/QML + C++20 参考运行端。媒体由 GStreamer 处理，Camera ID、Profile ID 与 Scene v5 变换模型和服务端保持一致。当前仍是开发源码，不是已经发布的 v2.0 客户端。

## Locked dependencies / 固定依赖

Release builds require exactly Qt 6.11.2, GStreamer 1.28.6 and libsodium 1.0.22. Authoritative source URLs and SHA-256 values are stored in `dependencies.lock.json`. CMake rejects other versions by default. `WEBOBS_ENFORCE_LOCKED_DEPENDENCIES=OFF` exists only for the Ubuntu compile-diagnostic Docker stage and must never produce a release artifact.

发布构建严格要求 Qt 6.11.2、GStreamer 1.28.6 和 libsodium 1.0.22。权威源码地址及 SHA-256 位于 `dependencies.lock.json`。CMake 默认拒绝其他版本；`WEBOBS_ENFORCE_LOCKED_DEPENDENCIES=OFF` 只用于 Ubuntu 源码编译诊断，禁止用其产物发布。

The lock also records the official Windows x86_64 installer and Android universal bundle used by future platform packages. Validate the lock before downloading, then verify every downloaded file before installation or extraction:

lock 文件还固定了后续平台包使用的官方 Windows x86_64 安装器和 Android universal bundle。下载前先校验 lock，安装或解压前必须逐个校验下载文件：

```bash
python3 clients/scripts/verify_dependency_lock.py
python3 clients/scripts/verify_dependency_lock.py \
  --artifact gstreamer-android-universal=/private/downloads/gstreamer-1.0-android-universal-1.28.6.tar.xz
```

The verifier never downloads artifacts and paths under private build caches must not enter Git. A successful metadata-only check does not prove that a platform package was built or tested.

校验器不会自动下载文件，私有构建缓存路径不得进入 Git。仅通过元数据校验不代表平台安装包已经构建或验收。

```bash
cmake -S clients -B clients/build -G Ninja -DCMAKE_BUILD_TYPE=RelWithDebInfo
cmake --build clients/build --parallel
```

Required GStreamer plug-ins include `rtspsrc`, `uridecodebin3`, `decodebin3`, `qml6glsink`, `whepclientsrc`, H.264/H.265 RTP depayloaders/parsers, Matroska muxing, platform hardware decoders and audio output. Qt Quick Controls and Qt5Compat GraphicalEffects are dynamically deployed for the bounded local Studio filter subset. Packaging must omit Qt WebEngine, include third-party licenses and produce SHA-256, SPDX SBOM and Sigstore bundles.

所需 GStreamer 插件包括 RTSP、URI 解码、`qml6glsink`、WHEP、H.264/H.265 RTP 解包/解析、Matroska 封装、平台硬解及音频输出。打包必须动态链接 LGPL Qt 模块，不引入 Qt WebEngine，并附第三方许可证与 SBOM。

## Security and offline behavior / 安全与离线行为

- Enrollment proves possession of an Ed25519 key and an X25519 key using deterministic CBOR. The ten-minute pairing code is approved in WebUI → Local clients.
- The signed grant is sealed to the client. The cached copy remains ciphertext inside DPAPI, Secret Service or Android Keystore-backed storage. If secure storage is unavailable, the identity is memory-only.
- An offline grant expires after 30 days. Each successful bootstrap renews it; an online revoked client is rejected on the next ten-second validation. A fully offline client cannot learn revocation before its existing grant expires.
- Camera credentials never enter Scene JSON, logs, metrics or arbitrary browser JavaScript. Reused camera accounts are explicitly marked `weakRevocation`; immediate offline invalidation requires rotating that camera password.
- Control HTTP is accepted only on loopback. Non-loopback control requires HTTPS. True Direct is LAN/user-managed-VPN only; WAN automatically plans a visible fallback unless `true-direct-only` forbids it.

- 配对使用确定性 CBOR 证明 Ed25519/X25519 私钥持有，十分钟配对码在 WebUI“本地客户端”中批准。
- 签名 Grant 只向该客户端密封；缓存仍是密文，并由 DPAPI、Secret Service 或 Android Keystore 保护。安全存储不可用时只允许内存临时身份。
- 离线 Grant 为 30 天；成功 Bootstrap 会续期。在线撤销会在下一次十秒校验时生效，完全离线设备只能最迟在已有 Grant 到期时失效。
- 摄像机凭据不进入 Scene、日志、指标或普通网页 JavaScript。复用摄像机账号会标记 `weakRevocation`；要立即让离线副本失效必须轮换摄像机密码。
- 非回环控制只接受 HTTPS。真直连只承诺 LAN/用户自管 VPN；公网会显式规划后备，`true-direct-only` 则拒绝降级。

## Implemented desktop surface / 已实现桌面功能

- Native H.264/H.265 RTSP, Server Push MJPEG, HLS and WHEP adapters; RTSP defaults to TCP and decoded-buffer readiness has a three-second bound.
- 1/4/9/16 substream grids, one independent main-stream focus, per-tile decoder/FPS/drop/reconnect diagnostics, exponential reconnect and suspend/resume recovery.
- Local Preview/Program Studio with Cut/Fade, two nested levels, Camera/text/image/color sources, groups, lock/visibility, crop/rotation/opacity, contain/cover/stretch, alignment/snapping, color/opacity/mask/scaling filters and Scene v5 local save.
- PTZ, listening, ten-second Push-to-Talk, camera-native snapshot, decoded-frame local screenshot, crash-safe stream-copy MKV and no-reencode MP4 export.
- DPAPI/Secret Service identity storage, encrypted 30-day offline Grant cache, ten-second online revocation checks and explicit weak-revocation/fallback diagnostics.

- 支持 H.264/H.265 RTSP、Server Push MJPEG、HLS 与 WHEP；RTSP 默认 TCP，三秒内必须得到真实解码 Buffer。
- 支持 1/4/9/16 子码流宫格、一路独立主码流聚焦、逐路解码器/FPS/掉帧/重连诊断、指数退避重连与挂起恢复。
- 本地 Preview/Program Studio 支持 Cut/Fade、两级嵌套、Camera/文字/图片/色块、组、锁定/显隐、裁切/旋转/透明度、适应/填充/拉伸、对齐/吸附、颜色/透明度/遮罩/缩放滤镜及 Scene v5 本地保存。
- 支持 PTZ、监听、十秒按键对讲、摄像机原生快照、已解码画面的本地截图、抗崩溃 stream-copy MKV 与无重编码 MP4 导出。
- 使用 DPAPI/Secret Service 保存身份，缓存加密的 30 天离线 Grant，每十秒检查在线撤销，并明确展示弱撤销与降级原因。

## Current evidence boundary / 当前证据边界

The diagnostic client and model tests pass. The deterministic control-only fixture runs the production receive pipeline for H.264/H.265 RTSP, Server Push MJPEG and HLS, validates continuous decoded buffers, stream-copy recording/remux, redaction and absence of Docker media helpers. The release workflow requires exact-runtime WHEP plus private Windows/Fedora 16-substream + one-main, 30-minute, hardware-decode, under-1%-drop and zero-server-increment evidence. Those self-hosted gates and signed artifacts have not run in this workspace; v2-M1/v2-M2 remain open.

诊断客户端及模型测试已通过。确定性控制网络隔离夹具以生产接收管线运行 H.264/H.265 RTSP、Server Push MJPEG 与 HLS，并验证连续解码 Buffer、stream-copy 录像/remux、脱敏及 Docker 内无媒体 helper。发布工作流还强制执行固定运行时 WHEP，以及私有 Windows/Fedora 16 路子码流加一路主码流、30 分钟、硬解、掉帧低于 1% 和服务端零增量门禁。本工作区尚未执行这些 Self-hosted 门禁及生成签名产物，因此 v2-M1/v2-M2 仍未完成。
