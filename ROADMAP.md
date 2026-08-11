# Roadmap / 项目路线图

> Last updated / 最后更新：2026-08-11

This roadmap describes milestone order and acceptance gates, not promised release dates. Priorities may change based on validation results and maintainer capacity.

本路线图描述里程碑顺序和验收门禁，不承诺具体发布日期。优先级可能根据验证结果和维护能力调整。

## Current position / 当前位置

**🟡 M1 — Web Control：持久场景已接入多来源 libobs 启动；当前实现录制期间的实时变更。**

M0 is complete. M1 now loads persistent multi-source scenes into libobs with transforms, crop, ordering, visibility, mute, volume, and partial-source timeout tolerance. The current batch adds live mutations while recording; REST/WebSocket control and the browser editor follow it.

M0 已全部完成。M1 现可将持久化多来源场景加载进 libobs，应用变换、裁切、层级、可见性、静音和音量，并容忍部分来源超时；当前批次继续实现录制期间实时变更，之后接入 REST/WebSocket 和浏览器编辑器。

```text
M0 implementation       Docker + synthetic RTSP       Real RTSP       M1 Web Control
实现完成             -> 构建与合成流验收通过        -> 真实摄像头   -> Web 控制
✅                      ✅                              ✅               🟡 CURRENT
```

### M0 acceptance / M0 验收

- [x] Pin OBS Studio 32.1.2 and recursive submodules / 固定 OBS Studio 32.1.2 及递归 submodule
- [x] Implement `RTSP → libobs Scene → x264 → video-only MP4` / 实现核心录制闭环
- [x] Add Xvfb/Mesa headless runtime and single-container product Compose / 增加无头运行环境和单容器 Compose
- [x] Add configuration, redaction, failure-path, and SIGTERM tests / 增加配置、脱敏、失败路径和信号测试
- [x] Pass source, YAML, Dockerfile, shell, security, and Git static checks / 通过静态检查
- [x] Run the complete multi-stage Docker build / 完成多阶段 Docker 构建
- [x] Pass the MediaMTX + FFmpeg synthetic RTSP smoke test / 通过合成 RTSP 烟测
- [x] Record at least 30 seconds from a real camera and verify playback, finalization, and redaction / 使用真实摄像头录制至少 30 秒并验证播放、封装和脱敏

M0 completed on 2026-08-11 after the real-camera gate passed. Re-run `./tests/run-real-camera.ps1` on Docker Desktop with WSL2 Linux containers, or `./tests/run-real-camera.sh` on Linux, when changing the capture pipeline. The `run-smoke` scripts remain the deterministic regression gate.

M0 已于 2026-08-11 在真实摄像头门禁通过后完成。后续修改采集链路时应重新运行 `run-real-camera`，并继续使用 `run-smoke` 作为确定性回归门禁。真实 RTSP URL 只应通过本地 `.env` 提供，不得写入仓库、日志附件或提交历史。

### Latest validation evidence / 最新验收证据

- Environment / 环境：Docker Desktop 4.86.0、Engine 29.7.2、Compose 5.3.1、BuildKit 0.32.2，WSL2 Linux/amd64。
- Build / 构建：multi-stage product image and pinned test fixtures built successfully; container CTest reports 100% pass and runtime `ldd` finds no missing library / 产品镜像和固定版本测试夹具构建成功；容器内 CTest 100% 通过，运行时动态库无缺失。
- Synthetic recording / 合成录制：a 640×480 source is proportionally centered in a 640×360 canvas with symmetric black bars; H.264, 10 FPS, video-only, fully decodable, and non-black center / 640×480 来源等比居中适配 640×360 画布且左右黑边对称；H.264、10 FPS、仅视频轨、可完整解码且中心非黑。
- Contracts / 契约：missing URL, invalid output directory, unreachable RTSP, existing-output refusal, credential masking, and SIGTERM finalization all pass / 无 URL、错误目录、连接失败、拒绝覆盖、凭据脱敏和 SIGTERM 完整封装均通过。
- Public-repository audit / 公开仓库审计：the Git index rejects sensitive/generated paths, high-confidence secrets, unapproved RTSP credentials, ignore-rule drift, and OBS pin drift / Git 索引会拒绝敏感或生成文件、高置信度密钥、未批准 RTSP 凭据、忽略规则漂移及 OBS 固定提交漂移。
- Real camera / 真实摄像头：a private 640×360 source produced a 30.100-second H.264 1920×1080, 30 FPS, video-only MP4 that passed full decode and non-black-frame validation; no private URL or credential is recorded here / 私有 640×360 来源生成 30.100 秒 H.264 1920×1080、30 FPS、仅视频 MP4，并通过完整解码与非黑帧校验；此处不记录私有地址或凭据。

## Milestones / 里程碑

| Milestone | Status / 状态 | Primary outcome / 核心成果 | Exit gate / 完成门禁 |
| --- | --- | --- | --- |
| M0 — Headless Proof | ✅ Complete / 已完成 | One RTSP source rendered by libobs and recorded as H.264 MP4 / 单路 RTSP 经 libobs 合成并录制为 H.264 MP4 | Docker build, synthetic RTSP, and real RTSP all pass / 三类验收全部通过 |
| M1 — Web Control | 🟡 In progress / 进行中 | Web UI, API, persistent scene model, RTSP source CRUD and transforms / Web UI、API、场景持久化、来源管理和画面变换 | Browser edits and libobs use the same scene state; recording remains stable / 浏览器与 libobs 共用同一场景状态，录制稳定 |
| M2 — Composite WebRTC | ⬜ Planned / 计划中 | Publish the server-composited program through WHIP/MediaMTX and play through WHEP/WebRTC / 服务端合成画面通过 WHIP/MediaMTX 发布并在浏览器播放 | Low-latency browser playback survives reconnects in one product container / 单容器内低延迟播放和重连通过 |
| M3 — Direct & Hybrid | ⬜ Planned / 计划中 | Direct camera playback in browsers, client/server mode switching, selective transcoding / 浏览器直连播放、客户端/服务端模式切换和选择性转码 | Shared layout behaves consistently across Direct and Composite modes / 两种模式共享布局且行为一致 |
| M4 — Browser Sources | ⬜ Planned / 计划中 | `obs-browser` sources for dashboards, satellite maps, overlays and embeddable media / 支持仪表盘、卫星图、叠加层和可嵌入媒体 | CEF lifecycle, isolation, recovery, and resource limits pass container tests / CEF 生命周期、隔离、恢复和资源限制通过测试 |
| M5 — Audio | ⬜ Planned / 计划中 | Per-source mute/volume, Web Audio in Direct mode, libobs mixing in Composite mode / 单源静音与音量、Direct Web Audio、Composite libobs 混音 | Multi-source sync, mute, volume, and output audio are verified / 多源同步、静音、音量和输出音轨通过验证 |
| M6 — Production | ⬜ Planned / 计划中 | Authentication, HTTPS, TURN, health checks, GPU detection, backup, observability and upgrades / 鉴权、HTTPS、TURN、健康检查、GPU 检测、备份、可观测性和升级 | Security review, upgrade/rollback, recovery, and documented deployment pass / 安全、升级回滚、恢复和部署文档验收通过 |

## Milestone details / 里程碑详情

### M1 — Web Control

- Introduce a versioned scene document as the single source of truth / 引入带版本的统一场景文档。
- Add REST/WebSocket control without depending on `obs-websocket` / 实现独立 REST/WebSocket 控制接口。
- Add, remove, move, resize, crop, reorder, mute, and configure RTSP sources / 支持 RTSP 来源增删、移动、缩放、裁切、层级、静音和配置。
- Persist scenes atomically and validate migrations / 原子持久化场景并验证迁移。
- Keep MP4 recording as the output while the control plane stabilizes / 控制面稳定前仍以 MP4 录制作为输出。

#### M1 progress / M1 进度

- [x] Versioned scene schema, strict limits, deterministic JSON, and credential-redacted API view / 版本化场景 schema、严格边界、确定性 JSON 和凭据脱敏 API 视图
- [x] Atomic persistence, restrictive permissions, and schema migration / 原子持久化、严格文件权限和 schema 迁移
- [ ] Live libobs source CRUD, transforms, crop, ordering, mute, and volume / libobs 来源实时增删改、变换、裁切、排序、静音和音量
- [ ] REST and WebSocket control with optimistic concurrency / 带乐观并发控制的 REST 与 WebSocket
- [ ] React/TypeScript Web editor using the same scene document / 使用同一场景文档的 React/TypeScript Web 编辑器
- [ ] Docker, synthetic RTSP, real camera, persistence, and security acceptance / Docker、合成 RTSP、真实摄像头、持久化与安全验收

### M2 — Composite WebRTC

- Add MediaMTX as an internal runtime service while preserving one product image / 将 MediaMTX 作为镜像内部服务，保持单产品镜像。
- Enable `obs-webrtc` and publish the program output through WHIP / 启用 `obs-webrtc`，通过 WHIP 发布合成画面。
- Provide WHEP/WebRTC playback, connection state, and reconnect behavior / 提供浏览器播放、连接状态和重连。
- Define LAN-first ICE defaults; TURN remains an explicit production dependency / 默认优先局域网 ICE，TURN 留到生产配置。

### M3 — Direct & Hybrid

- Route compatible camera streams through MediaMTX without server composition / 兼容流通过 MediaMTX 直达浏览器，不经服务端合成。
- Reuse the same scene model for HTML/CSS client layout and libobs server layout / HTML/CSS 客户端布局和 libobs 服务端布局共用场景模型。
- Add capability detection and explicit Direct/Composite selection / 增加能力检测和明确的模式选择。
- Add selective transcoding only for browser-incompatible sources / 仅对浏览器不兼容来源进行选择性转码。
- Consider automatic mode selection only after explicit modes are reliable / 明确模式稳定后再考虑 Auto 模式。

### M4 — Browser Sources

- Build and package pinned `obs-browser`/CEF dependencies / 构建并打包固定版本的 `obs-browser`/CEF。
- Support dashboards, local overlays, satellite maps, and approved embeds / 支持仪表盘、本地叠加层、卫星图和允许嵌入的媒体。
- Add URL policy, local-network access controls, process limits, crash recovery, and cache cleanup / 增加 URL 策略、内网访问控制、进程限制、崩溃恢复和缓存清理。
- Evaluate hardware-backed graphics without making it a prerequisite / 评估硬件图形加速，但不将其设为前置条件。

### M5 — Audio

- Define one UI model for mute, volume, sync offset, monitoring, and track assignment / 统一静音、音量、同步偏移、监听和轨道分配模型。
- Implement Web Audio mixing for Direct mode / 为 Direct 模式实现 Web Audio 混音。
- Implement libobs mixing and Opus/WebRTC output for Composite mode / 为 Composite 模式实现 libobs 混音及 Opus/WebRTC 输出。
- Test drift, reconnects, simultaneous sources, and browser autoplay constraints / 测试漂移、重连、多源并发和浏览器自动播放限制。

### M6 — Production

- Add authentication and authorization before exposing control endpoints outside a trusted LAN / 控制接口离开可信局域网前加入认证和授权。
- Add HTTPS, secure headers, rate limits, audit logs, and secret-file integration / 加入 HTTPS、安全响应头、限流、审计日志和 secret 文件集成。
- Add health/readiness checks, structured metrics, bounded logs, and automatic recovery / 加入健康检查、指标、日志限制和自动恢复。
- Detect CPU, VAAPI/QSV, and NVIDIA capabilities with safe software fallbacks / 检测 CPU、VAAPI/QSV 和 NVIDIA 能力，并保留安全的软件回退。
- Document backup, restore, upgrade, rollback, image provenance, and GPL source distribution / 记录备份恢复、升级回滚、镜像来源和 GPL 源码分发流程。

## Cross-cutting rules / 贯穿规则

- **One scene model / 一份场景模型：** client and server rendering must not develop incompatible layouts.
- **One product image / 一个产品镜像：** test fixtures may use multiple containers; product deployment remains one image.
- **Pinned dependencies / 固定依赖：** OBS, MediaMTX, CEF, and protocol-facing dependencies use reviewed versions rather than moving branches.
- **Security by milestone / 分阶段安全：** no Internet-facing control plane before authentication, TLS, and authorization exist.
- **No secret leakage / 不泄漏凭据：** real RTSP URLs, tokens, recordings, and unredacted logs never enter Git, images, or issue reports.
- **Deterministic acceptance / 确定性验收：** every milestone adds automated tests and an explicit exit gate before the next milestone begins.
- **Software fallback first / 软件回退优先：** hardware acceleration improves performance but must not be required for basic operation.

## Out of scope for the current roadmap / 当前路线图范围外

Traditional NVR features—24×7 recording databases, event timelines, retention policies, object detection, and forensic search—are not core roadmap commitments. They may be integrated with systems such as Frigate later instead of being embedded into the compositor.

传统 NVR 的 24×7 录像数据库、事件时间线、保留策略、目标检测和取证搜索不属于当前核心承诺。后续可与 Frigate 等系统集成，而不必塞入合成器核心。
