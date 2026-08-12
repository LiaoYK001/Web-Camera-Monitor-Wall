# Roadmap / 项目路线图

> Last updated / 最后更新：2026-08-13

This roadmap describes milestone order and acceptance gates, not promised release dates. Priorities may change based on validation results and maintainer capacity.

本路线图描述里程碑顺序和验收门禁，不承诺具体发布日期。优先级可能根据验证结果和维护能力调整。

## Current position / 当前位置

**✅ M3 — Direct & Hybrid 已完成；当前位置推进到 M4 Browser Sources 的设计与依赖评估，M4 尚未开始施工。**

M0 through M3 are complete. M3 creates random source-scoped MediaMTX pull paths on demand, exposes only same-origin WHEP resources, shares scene geometry between browser and libobs rendering, keeps compatible codecs on passthrough, and starts H.264 transcoding only for incompatible sources. Deterministic Direct/Hybrid, live mutation, disconnect/reconnect, route cleanup, and private real-source gates all pass. M4 dependency and security design is next and has not started.

M0 至 M3 已全部完成。M3 会按需创建随机且按来源隔离的 MediaMTX 拉流路径，只向浏览器暴露同源 WHEP，并让浏览器与 libobs 共享场景几何数据；兼容编码保持直通，仅为不兼容来源启动按需 H.264 转码。确定性 Direct/Hybrid、在线场景变更、断流重连、路由清理及私有真实来源门禁均已通过。下一步是 M4 依赖与安全设计，尚未开始施工。

```text
M0 complete       M1 complete       M2 complete       M3 complete       M4 Browser Sources
M0 已完成      -> M1 已完成      -> M2 已完成      -> M3 已完成      -> M4 浏览器源
✅                ✅                ✅                ✅                ⬜ NEXT
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

M0 已于 2026-08-11 在真实摄像头门禁通过后完成。后续修改采集链路时应重新运行 `run-real-camera`，并继续使用 `run-smoke` 作为确定性回归门禁。真实 RTSP URL 只应通过当前进程环境或本地 `.env` 提供，不得写入仓库、日志附件或提交历史。

### Latest validation evidence / 最新验收证据

- Environment / 环境：Docker Desktop 4.86.0、Engine 29.7.2、Compose 5.3.1、BuildKit 0.32.2，WSL2 Linux/amd64。
- Build / 构建：multi-stage product image and pinned test fixtures built successfully; container CTest reports 100% pass and runtime `ldd` finds no missing library / 产品镜像和固定版本测试夹具构建成功；容器内 CTest 100% 通过，运行时动态库无缺失。
- Synthetic recording / 合成录制：a 640×480 source is proportionally centered in a 640×360 canvas with symmetric black bars; H.264, 10 FPS, video-only, fully decodable, and non-black center / 640×480 来源等比居中适配 640×360 画布且左右黑边对称；H.264、10 FPS、仅视频轨、可完整解码且中心非黑。
- Contracts / 契约：missing URL, invalid output directory, unreachable RTSP, existing-output refusal, credential masking, and SIGTERM finalization all pass / 无 URL、错误目录、连接失败、拒绝覆盖、凭据脱敏和 SIGTERM 完整封装均通过。
- Public-repository audit / 公开仓库审计：the Git index rejects sensitive/generated paths, high-confidence secrets, unapproved RTSP credentials, ignore-rule drift, and OBS pin drift / Git 索引会拒绝敏感或生成文件、高置信度密钥、未批准 RTSP 凭据、忽略规则漂移及 OBS 固定提交漂移。
- Real camera / 真实摄像头：a private 640×360 source produced a 30.100-second H.264 1920×1080, 30 FPS, video-only MP4 that passed full decode and non-black-frame validation; no private URL or credential is recorded here / 私有 640×360 来源生成 30.100 秒 H.264 1920×1080、30 FPS、仅视频 MP4，并通过完整解码与非黑帧校验；此处不记录私有地址或凭据。
- M1 control plane / M1 控制面：live add/remove, transforms, crop, ordering, visibility, decoded-frame texture priming, atomic item replacement, unreachable-source rollback, ETag/WebSocket synchronization, private persistence, and same-container restart pass together; three consecutive mutation recordings of at least 18 seconds contain no black frame, and each restarted scene produces another decodable MP4 / 在线增删、变换、裁切、层级、可见性、解码帧纹理预装、原子 item 替换、不可达来源回滚、ETag/WebSocket 同步、私有持久化及同容器重启联合通过；连续三轮至少 18 秒动态变更录像均无黑帧，每次重启恢复场景后均可再次生成可解码 MP4。
- M1 browser editor / M1 浏览器编辑器：pinned React 19.2.8, TypeScript 7.0.2, and Vite 8.1.5 build successfully; the product image serves the editor and hashed assets with restrictive headers, traversal rejection, and same-origin API/WebSocket access / 固定版本 React 19.2.8、TypeScript 7.0.2 与 Vite 8.1.5 构建成功；产品镜像可在严格响应头、目录穿越拒绝及同源 API/WebSocket 约束下提供编辑器和哈希资源。
- M1 real-camera gate rehearsal / M1 真实门禁演练：both PowerShell and POSIX-shell entry points passed; the isolated gate added and removed a duplicate RTSP source through the API, applied move/resize/mute/volume, destroyed its credential-bearing volume, and produced recordings up to 20.1 seconds with zero blackout frames using the MediaMTX fixture / PowerShell 与 POSIX Shell 两套入口均通过；隔离门禁通过 API 增删同源 RTSP、应用移动/缩放/静音/音量、销毁含凭据配置卷，并使用 MediaMTX 夹具生成最长 20.1 秒且空黑帧为零的录像；该证据不替代真实摄像头复验。
- M1 real-camera acceptance / M1 真实摄像头验收：a private source passed live add/remove, move/resize, mute, and volume mutations while recording; the finalized H.264 1920×1080, 30 FPS, video-only MP4 is 38.3 seconds long, fully decodable, and contains zero blackout frames; the endpoint is intentionally omitted / 私有来源在录制期间通过在线增删、移动/缩放、静音和音量变更；最终 H.264 1920×1080、30 FPS、仅视频 MP4 时长 38.3 秒，可完整解码且空黑帧为零；此处有意省略端点信息。
- M2 browser WebRTC / M2 浏览器 WebRTC：an isolated Chrome session established a same-origin WHEP H.264 reader, survived a full product-container restart through automatic reconnect, and produced a second 21.6-second 640×360, 10 FPS, video-only, fully decodable, non-black MP4; wrong content type, foreign Origin, oversized SDP, and forged session tokens were rejected / 隔离 Chrome 通过同源 WHEP 建立 H.264 reader，并在产品容器完整重启后自动重连；第二轮生成 21.6 秒 640×360、10 FPS、仅视频、可完整解码且非黑的 MP4，同时错误媒体类型、外部 Origin、超大 SDP 和伪造令牌均被拒绝。
- M2 real-camera acceptance / M2 真实摄像头验收：a private source sustained same-origin WHEP/H.264 playback in isolated Chrome and produced a 38.966-second 1920×1080, 30 FPS, video-only MP4 that passed full decode with zero black frames; the product stopped with exit code 0, and no private endpoint or credential is recorded here / 私有来源在隔离 Chrome 中持续完成同源 WHEP/H.264 播放，并生成 38.966 秒 1920×1080、30 FPS、仅视频 MP4，完整解码且黑帧为零；产品以状态码 0 停止，此处不记录私有端点或凭据。
- M3 Direct foundation / M3 直达底座：isolated Chrome established two concurrent H.264 readers through source-scoped same-origin WHEP routes backed by random 128-bit internal paths; capability responses exposed neither RTSP nor internal endpoints, origin/content/source boundary tests passed, and the concurrent run produced a 26.8-second 640×360, 10 FPS, fully decodable MP4 with zero black frames / 隔离 Chrome 通过按来源限定的同源 WHEP 路由并发建立两路 H.264 reader，内部路径为随机 128-bit 名称；能力响应未暴露 RTSP 或内部端点，Origin、媒体类型和来源边界测试通过，并在并发运行中生成 26.8 秒 640×360、10 FPS、可完整解码且零黑帧 MP4。
- M3 selective Hybrid / M3 选择性混合：the deterministic H.264/HEVC scene classified H.264 as passthrough and HEVC as transcode, ran exactly one on-demand FFmpeg/x264 process, released it after the browser page closed, and produced a 25.3-second 640×360, 10 FPS recording with zero black frames; subsequent Direct and Composite reconnect regressions also passed / 确定性 H.264/HEVC 场景将 H.264 分类为直通、HEVC 分类为转码，只运行一个按需 FFmpeg/x264 进程并在浏览器页面关闭后释放；生成 25.3 秒 640×360、10 FPS、零黑帧录像，后续 Direct 与 Composite 重连回归亦通过。
- M3 lifecycle / M3 生命周期：an isolated Direct browser survived an HEVC publisher outage, rebuilt WHEP after recovery, switched one live source from Hybrid to Direct and back, replaced the opaque Hybrid route, removed the source and its transcoder, and produced a 49.1-second 640×360, 10 FPS H.264 recording with zero black frames / 隔离 Direct 浏览器在 HEVC 发布端断流后完成恢复与 WHEP 重建，将同一在线来源从 Hybrid 切换为 Direct 再切回、替换不透明 Hybrid 路径，并在移除来源后释放转码器；生成 49.1 秒 640×360、10 FPS、零黑帧 H.264 录像。
- M3 real-camera acceptance / M3 真实摄像头验收：a private H.264 source used source-scoped same-origin Direct WHEP passthrough in isolated Chrome and produced a finalized 30.8-second 640×360, 10 FPS recording with zero black frames; capability responses and persisted evidence contain no private endpoint / 私有 H.264 来源在隔离 Chrome 中通过按来源限定的同源 Direct WHEP 直通，并生成完成封装的 30.8 秒 640×360、10 FPS、零黑帧录像；能力响应和持久化证据均不包含私有端点。

## Milestones / 里程碑

| Milestone | Status / 状态 | Primary outcome / 核心成果 | Exit gate / 完成门禁 |
| --- | --- | --- | --- |
| M0 — Headless Proof | ✅ Complete / 已完成 | One RTSP source rendered by libobs and recorded as H.264 MP4 / 单路 RTSP 经 libobs 合成并录制为 H.264 MP4 | Docker build, synthetic RTSP, and real RTSP all pass / 三类验收全部通过 |
| M1 — Web Control | ✅ Complete / 已完成 | Web UI, API, persistent scene model, RTSP source CRUD and transforms / Web UI、API、场景持久化、来源管理和画面变换 | Browser edits and libobs use the same scene state; recording remains stable / 浏览器与 libobs 共用同一场景状态，录制稳定 |
| M2 — Composite WebRTC | ✅ Complete / 已完成 | Publish the server-composited program through WHIP/MediaMTX and play through WHEP/WebRTC / 服务端合成画面通过 WHIP/MediaMTX 发布并在浏览器播放 | Low-latency browser playback survives reconnects in one product container / 单容器内低延迟播放和重连通过 |
| M3 — Direct & Hybrid | ✅ Complete / 已完成 | Direct camera playback in browsers, client/server mode switching, selective transcoding / 浏览器直连播放、客户端/服务端模式切换和选择性转码 | Shared layout behaves consistently across Direct and Composite modes / 两种模式共享布局且行为一致 |
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
- [x] Live libobs source CRUD, transforms, crop, ordering, mute, and volume / libobs 来源实时增删改、变换、裁切、排序、静音和音量
- [x] REST and WebSocket control with optimistic concurrency / 带乐观并发控制的 REST 与 WebSocket
- [x] React/TypeScript Web editor using the same scene document / 使用同一场景文档的 React/TypeScript Web 编辑器
- [x] Docker, synthetic RTSP, real camera, persistence, and security acceptance / Docker、合成 RTSP、真实摄像头、持久化与安全验收

### M2 — Composite WebRTC

- Add MediaMTX as an internal runtime service while preserving one product image / 将 MediaMTX 作为镜像内部服务，保持单产品镜像。
- Enable `obs-webrtc` and publish the program output through WHIP / 启用 `obs-webrtc`，通过 WHIP 发布合成画面。
- Provide WHEP/WebRTC playback, connection state, and reconnect behavior / 提供浏览器播放、连接状态和重连。
- Define LAN-first ICE defaults; TURN remains an explicit production dependency / 默认优先局域网 ICE，TURN 留到生产配置。

#### M2 progress / M2 进度

- [x] Package pinned MediaMTX 1.18.2 and its license in the single product image / 在单一产品镜像中打包固定版本 MediaMTX 1.18.2 及许可证
- [x] Keep signaling internal, expose explicit ICE/UDP, and supervise graceful multi-process shutdown / 保持信令内部监听、显式发布 ICE/UDP，并监督多进程优雅关停
- [x] Build and load `obs-webrtc`, then publish the libobs program through WHIP / 构建并加载 `obs-webrtc`，通过 WHIP 发布 libobs 合成画面
- [x] Proxy WHEP through the same-origin control server and add browser playback with reconnect / 通过同源控制服务代理 WHEP，并增加浏览器播放与重连
- [x] Pass deterministic container, browser, disconnect, security, and real-camera acceptance / 通过确定性容器、浏览器、断线、安全及真实摄像头验收

M2 completed on 2026-08-12 after deterministic browser reconnect and failure/security coverage passed, followed by at least 30 seconds of private real-source WHEP playback and finalized recording validation.

M2 已于 2026-08-12 完成：确定性浏览器重连、故障与安全覆盖通过后，私有真实来源又完成至少 30 秒的 WHEP 播放和最终录像验证。

### M3 — Direct & Hybrid

- Route compatible camera streams through MediaMTX without server composition / 兼容流通过 MediaMTX 直达浏览器，不经服务端合成。
- Reuse the same scene model for HTML/CSS client layout and libobs server layout / HTML/CSS 客户端布局和 libobs 服务端布局共用场景模型。
- Add capability detection and explicit Direct/Composite selection / 增加能力检测和明确的模式选择。
- Add selective transcoding only for browser-incompatible sources / 仅对浏览器不兼容来源进行选择性转码。
- Consider automatic mode selection only after explicit modes are reliable / 明确模式稳定后再考虑 Auto 模式。

#### M3 progress / M3 进度

- [x] Add source-scoped on-demand MediaMTX routes with opaque internal names / 增加按来源隔离、内部名称不透明的 MediaMTX 按需路由
- [x] Proxy Direct WHEP through same-origin endpoints without exposing RTSP or upstream locations / 通过同源端点代理 Direct WHEP，且不暴露 RTSP 或上游位置
- [x] Add explicit Composite/Direct selection and render Direct video with the shared scene geometry / 增加显式 Composite/Direct 选择，并用共享场景几何数据渲染 Direct 视频
- [x] Pass deterministic two-source Chrome, boundary-security, decode, and blackout acceptance / 通过确定性双路 Chrome、边界安全、解码与黑帧验收
- [x] Detect source codec/browser capability and transcode only incompatible sources / 探测来源编码与浏览器能力，仅转码不兼容来源
- [x] Add Hybrid per-source fallback and page-close cleanup acceptance / 增加 Hybrid 单源回退与页面关闭清理验收
- [x] Add live scene mutation and reconnect acceptance in Direct/Hybrid mode / 增加 Direct/Hybrid 模式下的在线场景变更与重连验收
- [x] Pass private real-camera Direct/Hybrid acceptance without endpoint leakage / 通过不泄漏端点的私有真实摄像头 Direct/Hybrid 验收

M3 completed on 2026-08-13 after deterministic Direct and selective Hybrid playback, live codec switching, source removal, publisher disconnect/reconnect, resource cleanup, and private real-source acceptance all passed without exposing upstream endpoints.

M3 已于 2026-08-13 完成：确定性 Direct、选择性 Hybrid、在线编码切换、来源移除、发布端断流重连、资源回收及私有真实来源验收均已通过，且未暴露上游端点。

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
