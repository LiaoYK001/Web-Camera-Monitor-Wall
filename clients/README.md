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

Required GStreamer plug-ins include `rtspsrc`, `uridecodebin3`, `decodebin3`, `qml6glsink`, `whepclientsrc`, H.264/H.265 RTP depayloaders/parsers, Matroska muxing, platform hardware decoders and audio output. Packaging must dynamically link LGPL Qt modules, omit Qt WebEngine, include third-party licenses and produce an SBOM.

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

## Current evidence boundary / 当前证据边界

The source builds and links in the repository diagnostic stage, the server cryptographic/API tests pass with pinned libsodium, and first video readiness is based on an actual decoded video buffer rather than state transition alone. Windows 11, Fedora and Android signed packages, multi-tile performance, hardware-decode, sleep/network recovery and 30-minute hardware gates remain required before v2-M2/v2-M3 or v2.0 can be declared complete.

源码已通过仓库诊断阶段编译链接；服务端固定 libsodium 的密码学/API 测试通过；首帧就绪以实际解码视频 Buffer 为准，而不是仅依赖状态切换。Windows 11、Fedora、Android 正式签名包，多宫格性能、硬解、睡眠/网络恢复及 30 分钟硬件门禁仍未完成，因此不得宣称 v2-M2、v2-M3 或 v2.0 已完成。
