# Roadmap / 项目路线图

> Last updated / 最后更新：2026-09-03

This roadmap describes milestone order and acceptance gates, not promised release dates. Priorities may change based on validation results and maintainer capacity.

本路线图描述里程碑顺序和验收门禁，不承诺具体发布日期。优先级可能根据验证结果和维护能力调整。

## Local development access and configuration policy / 本地开发访问与配置策略

本项目当前及后续默认的本地开发入口（`http://127.0.0.1:5173` 的 Vite
前端与回环 Docker API）**不要求用户名或密码**。基础 `compose.yaml` 固定关闭
集群/RBAC 认证；只有维护者明确选择认证/生产 overlay、启用 HTTPS 远程部署或
后续需求明确要求时，才启用登录 Session/Basic 兼容。网络故障、Vite 代理暂时
不可用或后端重启不得被误报为“需要密码”，页面应显示服务不可用并允许重试。

用户配置不按登录用户名分叉。Local-first PWA 使用浏览器本机加密的配置档案，
用户可以在全局“配置”菜单选择、保存多个档案，并在“系统设置”中创建有界备份、
导出 JSON、导入和恢复。档案只保存脱敏的 Scene v5、布局和本机偏好；导出/备份
永远不包含密码、Token、Secret、RTSP/HTTP 端点、userinfo、文件路径或客户端地址。
服务器生产配置仍由管理员 API/SQLite 管理，不会因为选择本机档案而被覆盖。

The default local development entry (`http://127.0.0.1:5173` Vite frontend plus
the loopback Docker API) **does not require a username or password**. The base
`compose.yaml` keeps cluster/RBAC authentication disabled. Login Session/Basic
compatibility is enabled only by an explicit authentication/production overlay,
remote HTTPS deployment, or a later requirement. A proxy outage or backend
restart must show an unavailable/retry state rather than a password form.

Configuration is selected by browser-local profiles, not split by login user.
Profiles are encrypted locally and can be selected from the global Config menu;
Settings provides bounded backup, JSON export, import, and restore. Bundles contain
only redacted Scene v5/layout/local preferences and never credentials, tokens,
secrets, endpoints, userinfo, paths, or client addresses. Selecting a profile never
overwrites the server configuration.

Canonical milestone names use `v<major>-M<number>`. Historical validation prose may retain its original short `M<number>` label so prior evidence remains traceable; the mapping is defined in [docs/versioning-and-branches.md](docs/versioning-and-branches.md).

规范里程碑名称使用 `v<主版本>-M<序号>`。历史验收段落可保留当时的短名称 `M<序号>` 以维持证据可追溯性；映射见 [docs/versioning-and-branches.md](docs/versioning-and-branches.md)。

## Current position / 当前位置

**✅ `v2-M7 / v2.3.1` 已完成并作为当前稳定版本发布；🚧 v3-M1/M2 与 v3.0.1 体验修正正在 `dev` 收口，尚未发布。**

**✅ `v2-M7 / v2.3.1` is complete and published as the current stable release; 🚧 v3-M1/M2 and the v3.0.1 experience correction slice are being finalized on `dev` and are not released yet.**

`v2.3.1` is the current stable carrier for v2-M7. It preserves every v2.2 operations and True Direct boundary, adds optional scale-out while keeping `standalone` as the default one-image deployment, and does not restore native package publication. v3-M1/M2 implementation is now active on `dev`; analytics switches remain off by default until the corresponding release gates pass.

The `v3.0.1` preview correction slice is implemented on `dev`: OBS/classic workspace preferences, per-source telemetry and audio threshold borders, centralized issue reporting, and safe idempotent import of legacy Studio camera/RTSP sources. Preview publication is restricted to `--prerelease`, uses build version `3.0.1-pre.1`, leaves `latest` unchanged, and accepts real endpoints only through process environment injection.

`v2.3.1` 是 v2-M7 的当前稳定载体。它保留 v2.2 的全部运维能力与真直连边界，在默认单镜像 `standalone` 部署之外增加可选横向扩展，且不恢复原生包发布。下一条规划产品线为 v3 分析功能，其逐流开关仍默认关闭。

本轮 `v3.0.1` 预发布修正已在 `dev` 实现：OBS 风格/经典工作区偏好、逐来源统计与音频阈值边框、问题中心归集，以及旧 Studio 摄像机/RTSP 来源的受管、幂等导入。预发布只允许使用 `--prerelease`，构建版本为 `3.0.1-pre.1`，不会移动 `latest`；真实端点仍只通过进程环境注入。

The Qt/GStreamer/Android implementation and its prior source gates remain in the repository for security maintenance and research. The native workflow has no tag trigger, requires an explicit frozen-candidate confirmation, and cannot publish v2.0 artifacts / Qt/GStreamer/Android 实现及既有源码门禁继续留在仓库供安全维护与研究；原生工作流没有 Tag 触发器，要求显式冻结候选确认，且不能发布 v2.0 产物。

The v1-M10 implementation includes the Registry/Adapter foundation, authenticated Profile T/S media, PTZ, presets, snapshots, PullPoint events, guarded talk, bounded interface discovery and clock-skew correction. v1-M11 adds an isolated SQLite WAL event service, normalized native/software events, masks/zones, detector provider v1, NVR event windows, search/acknowledgement, rules and a bounded signed Webhook/MQTT outbox. Deterministic protocol/event/notification fixtures pass, and a redacted Canon WV-HTTP Server Push MJPEG endpoint negotiated real media and decoded five frames. Multi-vendor model/firmware testing continues as compatibility evidence rather than a release blocker.

v1-M10 实现包含 Registry/Adapter 底座、带认证 Profile T/S 媒体、PTZ、预置位、快照、PullPoint 事件、受控对讲、指定接口发现及时钟偏移校正。v1-M11 增加隔离的 SQLite WAL 事件服务、统一原生/软件事件、遮罩/区域、Detector Provider v1、NVR 事件窗口、检索/确认、规则及有界签名 Webhook/MQTT 发件箱。确定性协议、事件与通知夹具均通过，且一个脱敏 Canon WV-HTTP Server Push MJPEG 端点已完成真实媒体协商与五帧解码。多厂商型号/固件测试继续作为兼容证据，不再阻塞发布。

The `v1.0` series contains v1-M1 through v1-M6. The `v1.1` milestone family contains v1-M7 through v1-M11; `v1.2` is the final v1 closure release and introduces no v1-M12. `v2.0` starts at v2-M1 with a measurable True Direct contract.

`v1.0` 系列包含 v1-M1 至 v1-M6，`v1.1` 里程碑族包含 v1-M7 至 v1-M11；`v1.2` 是 v1 的最终收口版本，不新增 v1-M12。`v2.0` 从 v2-M1 开始，以可测量的真直连契约为核心。

```text
M0 + v1 complete -> v2-M1…M3 / v2.0 complete -> v2-M4/M5 / v2.1 complete -> v2-M6 / v2.2 complete -> v2-M7 / v2.3 complete -> v3-M1 / v3.0 -> v3-M2 / v3.1
M0 + v1 已完成   -> v2-M1…M3 / v2.0 已完成    -> v2-M4/M5 / v2.1 已完成    -> v2-M6 / v2.2 已完成    -> v2-M7 / v2.3 已完成    -> v3-M1 / v3.0 -> v3-M2 / v3.1
✅                  ✅                              ✅                            ✅                         ✅                         🚧                  ⏳
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

- v1-M10 deterministic device operations / v1-M10 确定性设备运维：the final linux/amd64 image passed ten Camera Registry/ONVIF/MJPEG tests covering Profile T/S, HTTP Digest, WS-Security with 120-second clock skew, generated TLS trust/rejection, private profile tokens, PTZ bounds/rate behavior, presets, snapshots, PullPoint normalization, guarded talk, credential-free audit and bounded Server Push MJPEG detection / 最终 linux/amd64 镜像通过 10 个 Camera Registry/ONVIF/MJPEG 测试，覆盖 Profile T/S、HTTP Digest、带 120 秒时钟偏移的 WS-Security、生成式 TLS 信任/拒绝、私有 Profile token、PTZ 边界/限速、预置位、快照、PullPoint 归一化、受控对讲、无凭据审计及有界 Server Push MJPEG 检测。
- v1-M11 deterministic events / v1-M11 确定性事件：six tests passed normalized event deduplication, acknowledgement audit, immutable segment linkage, include/exclude/privacy motion ground truth, debounce/cooldown, detector schema v1, rule/outbox ceiling, signed Webhook/authenticated MQTT frames, sub-50 ms reference p95 indexing and DNS-rebinding-resistant SSRF rejection / 6 个测试通过统一事件去重、确认审计、不可变分段关联、包含/排除/隐私移动真值、去抖/冷却、Detector schema v1、规则/发件箱上限、签名 Webhook/认证 MQTT 帧、参考环境低于 50 ms 的 p95 入库及抗 DNS 重绑定 SSRF 拒绝。
- v1.2 real external media / v1.2 真实外部媒体：a redacted Canon WV-HTTP endpoint returned Server Push MJPEG, negotiated 320×240 at 25 FPS and decoded five consecutive frames; no endpoint, frame or raw log is stored / 一个脱敏 Canon WV-HTTP 端点返回 Server Push MJPEG，实际协商 320×240、25 FPS 并连续解码五帧；未保存端点、帧或原始日志。
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
- M4 browser-source acceptance / M4 浏览器源验收：the pinned CEF/`obs-browser` runtime rendered an animated HTTP fixture through libobs, enforced default-deny and explicit private-network approval, redacted URL tokens, closed/recreated hidden browser instances, recovered after the renderer pool was killed, stayed within four renderer processes, removed its private profile on shutdown, and passed two consecutive final gates; the latest fully decodable 7.7-second 640×360, 10 FPS H.264 video-only MP4 had sampled YAVG 78.6251 / 固定 CEF/`obs-browser` 运行时通过 libobs 渲染动画 HTTP 夹具，验证默认拒绝与显式私网授权、URL 令牌脱敏、隐藏实例关闭/重建、renderer 池强杀后的恢复、最多四个 renderer、关停后私有 profile 清理，并连续两次通过最终门禁；最新 7.7 秒 640×360、10 FPS、H.264、仅视频且可完整解码的 MP4 抽样 YAVG 为 78.6251。
- M5 opening slice / M5 起步切片：schema-v3 migration and validation passed CTest, the React/TypeScript editor built successfully, and the final product image passed control-plane, Direct, Hybrid, browser-source, and lifecycle regressions. Audio settings round-tripped through the API and private persistence; the 16.8-second control-plane, 26.4-second Direct, 28.5-second Hybrid, and 55.7-second lifecycle recordings all contained zero black frames / schema v3 迁移与校验通过 CTest，React/TypeScript 编辑器构建成功，最终产品镜像通过控制面、Direct、Hybrid、浏览器源及生命周期回归；音频设置完成 API 往返与私有持久化，16.8 秒控制面、26.4 秒 Direct、28.5 秒 Hybrid 和 55.7 秒生命周期录像均为零黑帧。上述证据只验收 M5 底座，不代表有声音轨已经完成。
- M5 deterministic audio / M5 确定性音频：two synchronized sources covered native Opus and AAC-to-Opus Hybrid playback, one shared Direct Web Audio graph, default-muted user unlock, source reconnect, Composite H.264/Opus, and finalized H.264/AAC recordings. The final quarter-volume ratio was 0.281, the muted-source ratio 0.012, the measured 250 ms sync request produced a 220 ms effect within tolerance, and long-run drift was 0 ms / 两路同步来源覆盖原生 Opus、AAC 转 Opus Hybrid、共享 Direct Web Audio、默认静音与用户解锁、来源重连、Composite H.264/Opus 及最终 H.264/AAC 录像；最终四分之一音量比为 0.281，静音来源比为 0.012，250 ms 同步请求测得 220 ms 有效偏移并处于容差内，长时漂移为 0 ms。
- M5 real-audio acceptance / M5 真实音频验收：a private HEVC plus G.711 A-law source passed both Composite and Direct/Hybrid browser sessions and produced two finalized 30.941-second 640×360, 25 FPS H.264/AAC 48 kHz stereo recordings with non-silent audio and zero black frames. The endpoint and recordings remain private / 私有 HEVC + G.711 A-law 来源通过 Composite 与 Direct/Hybrid 浏览器会话，并生成两份 30.941 秒、640×360、25 FPS、H.264/AAC 48 kHz 双声道、非静音且零黑帧的最终录像；端点和录像保持私有。
- M6 opening security slice / M6 安全起步切片：file-backed credentials protected static UI, REST, WebSocket, and WHEP under one boundary; allowlisted HTTPS authorities passed while foreign Origin and Host values failed; three invalid credentials triggered a bounded `429` lockout and recovered after expiry; public probes, authenticated metrics, Docker health, credential-free logs, graceful stop, and a finalized 6.621-second recording passed together / 文件型凭据统一保护静态 UI、REST、WebSocket 与 WHEP；允许的 HTTPS authority 通过而外部 Origin/Host 被拒绝；三次错误凭据触发有限 `429` 锁定并在到期后恢复；公开探针、受认证指标、Docker 健康状态、无凭据日志、优雅停止及 6.621 秒最终录像联合通过。
- M6 compatibility regression / M6 兼容性回归：the rebuilt final image passed container CTest and dynamic-library closure, then the complete M0–M3 aggregate suite, M4 browser-source acceptance, and M5 deterministic audio acceptance; the latest M4 and M5 recordings were finalized at 12.621 and 38.921 seconds / 重建后的最终镜像通过容器 CTest 与动态库闭包，并继续通过 M0–M3 完整聚合套件、M4 浏览器源验收及 M5 确定性音频验收；最新 M4 与 M5 录像分别完整封装为 12.621 秒和 38.921 秒。
- M6 health and recovery / M6 健康与恢复：two visible RTSP sources started healthy, became stale after their publisher stopped, degraded readiness and aggregate metrics, requested bounded exponential-backoff libobs restarts, then returned healthy after publication resumed. Credential-free status output, structured authentication/scene/recovery audit events, clean exit, and a finalized 19.621-second H.264/AAC recording passed together / 两路可见 RTSP 来源从健康状态开始，在发布端停止后变为陈旧并降低 readiness 与聚合指标，按有界指数退避请求 libobs 重启，并在发布恢复后重新健康；无凭据状态输出、结构化认证/场景/恢复审计事件、正常退出及 19.621 秒 H.264/AAC 最终录像联合通过。
- M6 deployment documentation / M6 部署文档：source-build deployment, secure local configuration, lifecycle operations, manual backup/rollback, and GHCR manual/Actions publication and digest-pinned consumption are documented; Compose now accepts an explicit registry image and forwards browser-source security policy / 已记录源码构建部署、本地安全配置、生命周期操作、手工备份回滚、GHCR 手工/Actions 发布及 digest 固定消费流程；Compose 现可显式选择仓库镜像并正确传递浏览器源安全策略。
- M6 encoder capability and fallback / M6 编码能力与回退：the final image detected fixed CPU/VAAPI/QSV/NVENC capability classes without exposing device identities, an explicit unavailable NVENC request selected x264 with a visible fallback state, authenticated API/metrics reflected the result, and the 19.621-second H.264/AAC recovery recording still finalized correctly / 最终镜像在不暴露设备身份的前提下探测固定 CPU/VAAPI/QSV/NVENC 能力类别；显式请求不可用 NVENC 时选择 x264 并显示回退状态，受认证 API/指标正确反映结果，19.621 秒 H.264/AAC 恢复录像仍完整封装。
- M6 validated backup and restore / M6 校验备份与恢复：the final image created a mode-0600 scene archive and SHA-256 sidecar, verified checksum and tar paths, rejected restore without explicit confirmation, atomically reproduced the original validated scene, rejected corruption, and emitted no source URL / 最终镜像创建权限 0600 的场景归档及 SHA-256 sidecar，校验哈希与 tar 路径，拒绝无明确确认的恢复，原子还原并验证原始场景，拒绝损坏归档且不输出来源 URL。
- M6 trusted HTTPS and TURN / M6 受信 HTTPS 与 TURN：the pinned Caddy gateway served an operator-provided certificate with hardened headers while the backend remained unpublished on container loopback; file-backed TURN settings reached pinned MediaMTX exactly once, credentials stayed out of image/container configuration and logs, HTTPS health passed, and the one product container stopped cleanly / 固定版本 Caddy 使用操作者提供证书和安全响应头提供 HTTPS，后端留在容器回环且未发布；文件型 TURN 配置只向固定版本 MediaMTX 注入一次，凭据未进入镜像/容器配置和日志，HTTPS 健康检查及单产品容器停机均通过。
- M6 provenance and rollback / M6 来源证明与回滚：the release workflow is least-privilege and commit-pinned, emits linux/amd64 OCI labels, SBOM, max provenance, GitHub attestation, and a checksummed recursive corresponding-source bundle; a deterministic drill rejected an unhealthy candidate, restored the exact scene hash and prior image ID, then completed a healthy upgrade / 发布工作流使用最小权限并固定 action 提交，生成 linux/amd64 OCI 标签、SBOM、max provenance、GitHub attestation 及带校验和的递归对应源码包；确定性演练拒绝故障候选，恢复完全一致的场景哈希与旧 image ID，随后完成健康升级。
- M6 final regression / M6 最终回归：the final image passed the full M0–M3 aggregate suite, M4 browser-source gate, M5 deterministic audio gate, and every M6 authentication/recovery, backup/restore, HTTPS/TURN, and upgrade/rollback gate; the longest lifecycle recording finalized at 62.621 seconds with zero black frames / 最终镜像通过 M0–M3 聚合套件、M4 浏览器源、M5 确定性音频及全部 M6 认证恢复、备份恢复、HTTPS/TURN、升级回滚门禁；最长生命周期录像 62.621 秒完整封装且零黑帧。
- Browser session hardening / 浏览器会话加固：the browser now uses a server-side SQLite WAL session whose random token is stored only as SHA-256, slides after authenticated activity, expires after seven inactive days, prunes stale rows, and is delivered with `HttpOnly`, `Secure`, `SameSite=Strict`, and `Path=/`; Basic remains only for CLI and emergency compatibility / 浏览器现使用服务端 SQLite WAL Session，随机 token 仅以 SHA-256 保存，认证访问时滑动续期、连续七天无访问后失效并清理过期行，通过 `HttpOnly`、`Secure`、`SameSite=Strict`、`Path=/` Cookie 传递；Basic 仅保留给 CLI 和应急兼容。
- M7 Canvas Studio / M7 画布工作台：schema v4 and an atomic mode-0600 Studio store passed migration with byte-exact pre-v4 backup; six named scenes covered RTSP, image, media, text, color, nested/shared sources, ordered filters, advanced transforms, capability fallback, Preview isolation, same-ID retake, undo/redo, restart recovery, and 500 alternating Cut/Fade operations; the finalized H.264 recording decoded fully without black Program intervals and logs contained no fixture credentials / schema v4 与 `0600` 原子 Studio 存储通过带原始字节备份的迁移；六个命名场景覆盖 RTSP、图片、媒体、文字、色块、嵌套/共享来源、有序滤镜、高级变换、能力降级、Preview 隔离、同 ID 重新 Take、撤销重做、重启恢复及 500 次交替 Cut/Fade；最终 H.264 录像完整解码且无 Program 黑场，日志不含夹具凭据。

## Milestones / 里程碑

| Milestone | Status / 状态 | Primary outcome / 核心成果 | Exit gate / 完成门禁 |
| --- | --- | --- | --- |
| M0 — Headless Proof | ✅ Complete / 已完成 | One RTSP source rendered by libobs and recorded as H.264 MP4 / 单路 RTSP 经 libobs 合成并录制为 H.264 MP4 | Docker build, synthetic RTSP, and real RTSP all pass / 三类验收全部通过 |
| v1-M1 — Web Control | ✅ Complete / 已完成 | Web UI, API, persistent scene model, RTSP source CRUD and transforms / Web UI、API、场景持久化、来源管理和画面变换 | Browser edits and libobs use the same scene state; recording remains stable / 浏览器与 libobs 共用同一场景状态，录制稳定 |
| v1-M2 — Composite WebRTC | ✅ Complete / 已完成 | Publish the server-composited program through WHIP/MediaMTX and play through WHEP/WebRTC / 服务端合成画面通过 WHIP/MediaMTX 发布并在浏览器播放 | Low-latency browser playback survives reconnects in one product container / 单容器内低延迟播放和重连通过 |
| v1-M3 — Gateway Direct & Hybrid | ✅ Complete / 已完成 | Gateway Direct browser playback, client/server mode switching and selective transcoding / 浏览器网关直通、客户端/服务端模式切换和选择性转码 | Shared layout behaves consistently across Gateway Direct and Composite modes / 网关直通与合成模式共享布局且行为一致 |
| v1-M4 — Browser Sources | ✅ Complete / 已完成 | `obs-browser` sources for dashboards, satellite maps, overlays and embeddable media / 支持仪表盘、卫星图、叠加层和可嵌入媒体 | CEF lifecycle, isolation, recovery, and resource limits pass container tests / CEF 生命周期、隔离、恢复和资源限制通过测试 |
| v1-M5 — Audio | ✅ Complete / 已完成 | Per-source mute/volume, Web Audio in Gateway Direct, libobs mixing in Composite / 单源静音与音量、网关直通 Web Audio、Composite libobs 混音 | Multi-source sync, mute, volume, and output audio are verified / 多源同步、静音、音量和输出音轨通过验证 |
| v1-M6 — Production | ✅ Complete / 已完成 | Authentication, HTTPS, TURN, health checks, GPU detection, backup, observability and upgrades / 鉴权、HTTPS、TURN、健康检查、GPU 检测、备份、可观测性和升级 | Security review, upgrade/rollback, recovery, and documented deployment pass / 安全、升级回滚、恢复和部署文档验收通过 |
| v1-M7 — Canvas Studio | ✅ Complete / 已完成 | Scene collections, nested scenes/groups, filters, Preview/Program and transitions / 场景集合、嵌套场景/组、滤镜、预览/节目与转场 | Persistent multi-scene Studio workflow and Gateway Direct/Composite capability contract pass / 持久化多场景工作流与网关直通/合成能力契约通过 |
| v1-M8 — NVR Core | ✅ Implementation complete / 实现完成 | Independent per-camera segmented recording, catalog, retention and crash recovery / 独立逐路分段录像、目录、保留与崩溃恢复 | Deterministic recovery/retention gate passes; six-hour and private burn-ins remain release qualification / 确定性恢复/保留门禁通过；六小时及私有耐久属于发布资格验证 |
| v1-M9 — Timeline | ✅ Implementation complete / 实现完成 | Archive search, synchronized playback, clip export and evidence integrity / 归档检索、同步回放、片段导出与证据完整性 | UTC/gap, p95, Range, derived media, export/hash, lock/delete and audit gates pass / UTC/断档、p95、Range、派生媒体、导出/哈希、锁定/删除及审计门禁通过 |
| v1-M10 — Device Operations | ✅ Complete / 已完成 | Capability-driven Profile T/S media, PTZ, presets, events, snapshots and guarded talk / 能力驱动的 Profile T/S 媒体、PTZ、预置位、事件、快照与受控对讲 | Emulator plus bounded MJPEG fixture and redacted external media gate pass / 模拟器、有界 MJPEG 夹具及脱敏外部媒体门禁通过 |
| v1-M11 — Events & Detection | ✅ Complete / 已完成 | Native/software events, motion zones/masks, detector providers, rules and bounded notifications / 原生/软件事件、移动区域/遮罩、检测提供器、规则与有界通知 | Deterministic accuracy, isolation, queue, signed delivery and SSRF gates pass / 确定性准确度、隔离、队列、签名交付及 SSRF 门禁通过 |
| v2-M1 — True Direct Foundation | ✅ Complete / 已完成 | API/grant/planner/reference receiver plus isolated five-protocol architecture proof / API、Grant、规划器、参考接收端及隔离五协议架构证明 | Locked receiver, zero-payload, NVR coexistence and credential gates pass / 固定接收端、零负载、NVR 共存及凭据门禁全部通过 |
| v2-M2 — Local-first PWA | ✅ Complete / 已完成 | Cached app shell, encrypted expiring Registry/Scene and local-only Scene editing / 缓存应用壳、加密过期 Registry/Scene 与本地 Scene 编辑 | Published in v2.0.1 baseline / 已进入 v2.0.1 发布基线 |
| v2-M3 — Browser Media Runtime | ✅ Complete / 已完成 | WHEP/HLS/MJPEG True Direct and explicit RTSP Gateway / WHEP/HLS/MJPEG 真直连及明确 RTSP 网关 | Published in v2.0.1 baseline / 已进入 v2.0.1 发布基线 |
| v2-M4 — Offline Sync | ✅ Published in v2.1 / 已随 v2.1 发布 | Encrypted bidirectional Registry/Scene deltas, field conflicts, tombstones and bounded offline audit / 加密双向 Registry/Scene 增量、字段冲突、墓碑与有界离线审计 | Deterministic Linux service and browser IndexedDB matrices pass / Linux 服务与浏览器 IndexedDB 确定性矩阵通过 |
| v2-M5 — Monitor Layout & Telemetry | ✅ Published in v2.1 / 已随 v2.1 发布 | Telemetry, 1–16 M/S layout/rotation, low power and analytics controls / 统计、1–16 M/S 布局轮换、低功耗与分析控制 | Layout, telemetry, lifecycle and policy regressions pass without inventing unavailable measurements / 布局、统计、生命周期与策略回归通过，不虚构不可测数据 |
| v2-M6 — Operations Workspace | ✅ Published in v2.2 / 已随 v2.2 发布 | Source catalog, Profile preview, issues, settings and per-source audio / 来源目录、Profile 预览、问题、设置与逐源音频 | Registry v2 migration, truthful media/audio diagnostics and PWA regressions pass / Registry v2 迁移、真实媒体/音频诊断与 PWA 回归通过 |
| v2-M7 — Scale | ✅ Published in v2.3 / 已随 v2.3 发布 | RBAC, Controller/Recorder leases, multi-volume/S3, resource scheduling, integrations and encrypted DR / RBAC、Controller/Recorder 租约、多卷/S3、资源调度、集成与加密灾备 | 8/16/32 synthetic scale, fault injection, security and private platform gates pass / 8/16/32 合成规模、故障注入、安全与私有平台门禁通过 |
| v3-M1/M2 — Analytics | 🚧 In development / 开发中 | Motion/scene change, then person boxes / 运动与画面变化，随后人物框 | Browser Worker, hash-verified model, optional CPU Worker and bounded resource gates / 浏览器 Worker、摘要校验模型、可选 CPU Worker 与有界资源门禁 |

### v3 analytics implementation status / v3 分析实现状态

The v3 implementation is now present on `dev`, but neither `v3.0` nor `v3.1` is a release claim until revision-bound Windows and WSL2 private gates are executed. The following checklist records code that is implemented and the remaining release evidence; it intentionally does not turn local unit tests into platform acceptance.

v3 实现已经进入 `dev`，但在绑定 revision 的 Windows 与 WSL2 私有门禁执行前，不将 `v3.0` 或 `v3.1` 表述为已发布。以下清单区分已实现代码与仍需取得的发布证据，不把本地单元测试冒充平台验收。

- [x] Registry v2→v3 atomic analytics migration, nested motion/scene-change/person policies, bounded batch updates and legacy projections / Registry v2→v3 原子分析迁移、嵌套运动/画面变化/人物策略、有界批量更新与旧字段投影
- [x] v3 runtime-plan/session/signal APIs with expiry, replay/rate/coordinate checks, server-trusted source and RBAC scope enforcement / v3 运行计划、会话、信号 API，包含过期、重放/速率/坐标检查、服务端可信来源及 RBAC 作用域校验
- [x] Browser Worker motion and scene-change engine with include/exclude/privacy zones, low-power suppression and ONVIF-first execution / 带包含/排除/隐私区域、低功耗抑制及 ONVIF 优先策略的浏览器 Worker 运动和画面变化引擎
- [x] Pinned, same-origin, SHA-256 verified person model with WebGPU→WASM fallback, letterbox mapping and person-only post-processing / 固定同源且 SHA-256 校验的人物模型，支持 WebGPU→WASM 回退、等比填充坐标映射及仅 person 后处理
- [x] Optional CPU Detector Worker contract and generation/resource-aware job lifecycle; no implicit server media fallback / 可选 CPU Detector Worker 契约及带 generation/资源约束的任务生命周期；不隐式启用服务端媒体回退
- [x] Analytics workspace, detection status/boxes, model integrity issues, release receipt verifiers and Docker model supply-chain probe / 分析工作区、检测状态/框、模型完整性问题、发布回执校验器及 Docker 模型供应链探针
- [ ] Execute Windows Chrome/Edge and WSL2 Chromium v3-M1/v3-M2 private gates and bind receipts to one final commit / 执行 Windows Chrome/Edge 与 WSL2 Chromium 的 v3-M1/v3-M2 私有门禁，并将回执绑定到同一最终提交
- [ ] Re-run v1–v2.3 regression and public audit on the release candidate, then merge `dev → main` / 在发布候选上重跑 v1–v2.3 回归与公开审计，然后合并 `dev → main`
- [ ] Create immutable annotated `v3.0`/`v3.1` tags and publish GHCR images only after the corresponding receipt verifiers pass / 仅在对应回执校验通过后创建不可移动 annotated `v3.0`/`v3.1` 标签并发布 GHCR 镜像

## Milestone details / 里程碑详情

### v1-M1 — Web Control

- Introduce a versioned scene document as the single source of truth / 引入带版本的统一场景文档。
- Add REST/WebSocket control without depending on `obs-websocket` / 实现独立 REST/WebSocket 控制接口。
- Add, remove, move, resize, crop, reorder, mute, and configure RTSP sources / 支持 RTSP 来源增删、移动、缩放、裁切、层级、静音和配置。
- Persist scenes atomically and validate migrations / 原子持久化场景并验证迁移。
- Keep MP4 recording as the output while the control plane stabilizes / 控制面稳定前仍以 MP4 录制作为输出。

#### v1-M1 progress / v1-M1 进度

- [x] Versioned scene schema, strict limits, deterministic JSON, and credential-redacted API view / 版本化场景 schema、严格边界、确定性 JSON 和凭据脱敏 API 视图
- [x] Atomic persistence, restrictive permissions, and schema migration / 原子持久化、严格文件权限和 schema 迁移
- [x] Live libobs source CRUD, transforms, crop, ordering, mute, and volume / libobs 来源实时增删改、变换、裁切、排序、静音和音量
- [x] REST and WebSocket control with optimistic concurrency / 带乐观并发控制的 REST 与 WebSocket
- [x] React/TypeScript Web editor using the same scene document / 使用同一场景文档的 React/TypeScript Web 编辑器
- [x] Docker, synthetic RTSP, real camera, persistence, and security acceptance / Docker、合成 RTSP、真实摄像头、持久化与安全验收

### v1-M2 — Composite WebRTC

- Add MediaMTX as an internal runtime service while preserving one product image / 将 MediaMTX 作为镜像内部服务，保持单产品镜像。
- Enable `obs-webrtc` and publish the program output through WHIP / 启用 `obs-webrtc`，通过 WHIP 发布合成画面。
- Provide WHEP/WebRTC playback, connection state, and reconnect behavior / 提供浏览器播放、连接状态和重连。
- Define LAN-first ICE defaults; TURN remains an explicit production dependency / 默认优先局域网 ICE，TURN 留到生产配置。

#### v1-M2 progress / v1-M2 进度

- [x] Package pinned MediaMTX 1.18.2 and its license in the single product image / 在单一产品镜像中打包固定版本 MediaMTX 1.18.2 及许可证
- [x] Keep signaling internal, expose explicit ICE/UDP, and supervise graceful multi-process shutdown / 保持信令内部监听、显式发布 ICE/UDP，并监督多进程优雅关停
- [x] Build and load `obs-webrtc`, then publish the libobs program through WHIP / 构建并加载 `obs-webrtc`，通过 WHIP 发布 libobs 合成画面
- [x] Proxy WHEP through the same-origin control server and add browser playback with reconnect / 通过同源控制服务代理 WHEP，并增加浏览器播放与重连
- [x] Pass deterministic container, browser, disconnect, security, and real-camera acceptance / 通过确定性容器、浏览器、断线、安全及真实摄像头验收

M2 completed on 2026-08-12 after deterministic browser reconnect and failure/security coverage passed, followed by at least 30 seconds of private real-source WHEP playback and finalized recording validation.

M2 已于 2026-08-12 完成：确定性浏览器重连、故障与安全覆盖通过后，私有真实来源又完成至少 30 秒的 WHEP 播放和最终录像验证。

### v1-M3 — Gateway Direct & Hybrid

- Route compatible camera streams through MediaMTX without server composition / 兼容流通过 MediaMTX 直达浏览器，不经服务端合成。
- Reuse the same scene model for HTML/CSS client layout and libobs server layout / HTML/CSS 客户端布局和 libobs 服务端布局共用场景模型。
- Add capability detection and explicit Direct/Composite selection / 增加能力检测和明确的模式选择。
- Add selective transcoding only for browser-incompatible sources / 仅对浏览器不兼容来源进行选择性转码。
- Consider automatic mode selection only after explicit modes are reliable / 明确模式稳定后再考虑 Auto 模式。

#### v1-M3 progress / v1-M3 进度

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

### v1-M4 — Browser Sources

- Build and package pinned `obs-browser`/CEF dependencies / 构建并打包固定版本的 `obs-browser`/CEF。
- Support dashboards, local overlays, satellite maps, and approved embeds / 支持仪表盘、本地叠加层、卫星图和允许嵌入的媒体。
- Add URL policy, local-network access controls, process limits, crash recovery, and cache cleanup / 增加 URL 策略、内网访问控制、进程限制、崩溃恢复和缓存清理。
- Evaluate hardware-backed graphics without making it a prerequisite / 评估硬件图形加速，但不将其设为前置条件。

#### v1-M4 progress / v1-M4 进度

- [x] Pin and package the OBS-matched CEF archive, `obs-browser`, helper binary, resources, and runtime libraries / 固定并打包与 OBS 匹配的 CEF 归档、`obs-browser`、helper、资源及运行库
- [x] Add strict schema-v2 browser sources to persistence, REST/WebSocket, editor, and libobs rendering / 在持久化、REST/WebSocket、编辑器和 libobs 渲染中加入严格的 schema v2 浏览器源
- [x] Enforce exact origins, separate private-network opt-in, DNS checks, URL redaction, and Composite-only Direct capabilities / 实施精确 Origin、独立私网开关、DNS 检查、URL 脱敏和 Direct 模式 Composite-only 能力
- [x] Bound CEF renderers, close/recreate hidden instances, reload crashed renderers, and remove private profiles / 限制 CEF renderer、关闭/重建隐藏实例、重载崩溃 renderer 并清理私有 profile
- [x] Pass deterministic policy, lifecycle, recovery, resource, cache, decode, and non-black recording acceptance / 通过确定性策略、生命周期、恢复、资源、缓存、解码和非黑录像验收
- [x] Keep Mesa software rendering as the portable baseline; leave optional GPU detection and fallback selection to M6 / 保持 Mesa 软件渲染为可移植基线，将可选 GPU 检测与回退选择留到 M6

M4 completed on 2026-08-14 after the exact pinned browser runtime passed container build/link checks and the deterministic animated-page acceptance covered policy, lifecycle, renderer recovery, resource ceilings, cache cleanup, redaction, graceful shutdown, and non-black MP4 finalization.

M4 已于 2026-08-14 完成：精确固定的浏览器运行时通过容器构建与动态链接检查，动画页面确定性门禁覆盖策略、生命周期、renderer 恢复、资源上限、缓存清理、脱敏、优雅停止及非黑 MP4 完整封装。

### v1-M5 — Audio

- Define one UI model for mute, volume, sync offset, monitoring, and track assignment / 统一静音、音量、同步偏移、监听和轨道分配模型。
- Implement Web Audio mixing for Direct mode / 为 Direct 模式实现 Web Audio 混音。
- Implement libobs mixing and Opus/WebRTC output for Composite mode / 为 Composite 模式实现 libobs 混音及 Opus/WebRTC 输出。
- Test drift, reconnects, simultaneous sources, and browser autoplay constraints / 测试漂移、重连、多源并发和浏览器自动播放限制。

#### v1-M5 progress / v1-M5 进度

- [x] Introduce schema v3 with mute, volume, sync offset, monitoring, and track assignment plus v0/v1/v2 migration / 引入统一静音、音量、同步偏移、监听和音轨分配的 schema v3，并支持 v0/v1/v2 迁移
- [x] Apply the unified fields to libobs sources and verify API round-trip/private persistence / 将统一字段应用到 libobs 来源并验证 API 往返与私有持久化
- [x] Negotiate Direct receive-only audio while keeping autoplay muted until an explicit user gesture / Direct 协商 recvonly 音频，并在明确用户手势前保持自动播放静音
- [x] Implement and verify multi-source Web Audio mixing in Direct mode / 实现并验证 Direct 多来源 Web Audio 混音
- [x] Publish mixed Opus audio in Composite WebRTC and finalize H.264/AAC MP4 recordings / 在 Composite WebRTC 发布 Opus 混音，并封装 H.264/AAC MP4 录像
- [x] Pass real audio source, mute/volume/sync, drift, reconnect, autoplay, and finalized-output gates / 通过真实音频来源、静音/音量/同步、漂移、重连、自动播放和最终输出门禁

M5 completed on 2026-08-15 after deterministic multi-source audio and full M0–M4 regressions passed, followed by two private real-audio 30-second Composite/Direct acceptance runs. M6 started afterward and remains in progress.

M5 已于 2026-08-15 完成：多来源确定性音频及 M0–M4 全回归通过后，又完成两轮私有真实音频源的 30 秒 Composite/Direct 验收。随后 M6 已开始开发，目前仍在进行中。

### v1-M6 — Production

- Add authentication and authorization before exposing control endpoints outside a trusted LAN / 控制接口离开可信局域网前加入认证和授权。
- Add HTTPS, secure headers, rate limits, audit logs, and secret-file integration / 加入 HTTPS、安全响应头、限流、审计日志和 secret 文件集成。
- Add health/readiness checks, structured metrics, bounded logs, and automatic recovery / 加入健康检查、指标、日志限制和自动恢复。
- Detect CPU, VAAPI/QSV, and NVIDIA capabilities with safe software fallbacks / 检测 CPU、VAAPI/QSV 和 NVIDIA 能力，并保留安全的软件回退。
- Document backup, restore, upgrade, rollback, image provenance, and GPL source distribution / 记录备份恢复、升级回滚、镜像来源和 GPL 源码分发流程。

#### v1-M6 progress / v1-M6 进度

- [x] Add paired file-backed Basic credentials with fixed-size constant-time comparison / 增加配对文件型 Basic 凭据和固定长度恒定时间比较
- [x] Protect UI/assets, REST, WebSocket, Program/Source WHEP, and metrics under one authentication boundary / 以统一认证边界保护 UI/资源、REST、WebSocket、Program/Source WHEP 与指标
- [x] Add explicit remote HTTPS Origin/Host authorization and bounded per-client authentication-failure rate limiting / 增加明确的远程 HTTPS Origin/Host 授权与逐客户端有限认证失败限流
- [x] Add public detail-free liveness/readiness, authenticated Prometheus baseline metrics, and Docker healthcheck / 增加不暴露细节的公开存活/就绪探针、受认证 Prometheus 基线指标和 Docker healthcheck
- [x] Add a Compose secret-file overlay, deterministic authentication/redaction acceptance, and deployment boundary documentation / 增加 Compose secret 文件覆盖、确定性认证/脱敏验收和部署边界文档
- [x] Add trusted HTTPS termination deployment and TURN configuration/acceptance / 增加受信 HTTPS 终止部署与 TURN 配置/验收
- [x] Add structured audit logs, bounded log retention, frame-freshness source health, exponential-backoff reconnect, and recovery acceptance / 增加结构化审计日志、有界日志保留、帧新鲜度来源健康、指数退避重连与恢复验收
- [x] Document source-build deployment and GHCR publication/consumption with immutable image selection / 记录源码构建部署、GHCR 发布消费及不可变镜像选择流程
- [x] Add CPU/VAAPI/QSV/NVIDIA detection with safe software fallback / 增加 CPU/VAAPI/QSV/NVIDIA 检测及安全软件回退
- [x] Add validated scene backup/restore with explicit confirmation and corruption rejection / 增加带明确确认、损坏拒绝的校验场景备份恢复
- [x] Add image provenance, automated upgrade/rollback, and GPL source-distribution verification / 增加镜像来源、自动升级回滚及 GPL 源码分发验证

M6 completed on 2026-08-15 after the full M0–M5 compatibility regression and every M6 production gate passed. M7 started afterward.

M6 已于 2026-08-15 在 M0–M5 全兼容回归及全部 M6 生产门禁通过后完成；随后开始 M7。

### v1-M7 — Canvas Studio / 画布工作台

#### v1-M7 progress / v1-M7 进度

- [x] Add schema v4 sources for image, media, text, color, and nested scenes plus ordered bounded filters / 增加图片、媒体、文字、色块、嵌套场景及有界有序滤镜
- [x] Add item lock, logical groups, rotation, opacity, blend modes, fit/fill/stretch, crop, numeric transforms, multi-select, snapping, alignment, and distribution / 增加锁定、逻辑分组、旋转、透明度、混合、缩放裁切、数值变换、多选吸附、对齐与分布
- [x] Add a private atomic Studio collection for 1–64 scenes, two-level acyclic nesting, templates, copy/reorder/delete, and JSON import/export / 增加 1–64 场景的私有原子 Studio 集合、两层无环嵌套、模板、复制排序删除及 JSON 导入导出
- [x] Isolate Preview and Program and implement atomic Cut/Fade Take, including changed-definition retake for the same scene ID / 隔离 Preview 与 Program，并实现原子 Cut/Fade Take 及同场景变更后重新 Take
- [x] Add transactional bounded undo/redo, restart persistence, schema migration, and exact pre-v4 backup / 增加事务性有界撤销重做、重启持久化、schema 迁移及原始 v4 前备份
- [x] Publish credential-free Direct/Hybrid/Composite capability analysis and show fallback reasons in the editor / 发布无凭据的播放能力分析并在编辑器显示降级原因
- [x] Pass six-scene mixed-source acceptance, same-ID retake, 500 Cut/Fade operations, H.264 decode, black-frame, persistence, permissions, and log-redaction gates / 通过六场景混合来源、同 ID Take、500 次转场、解码、黑帧、持久化、权限及日志脱敏门禁

M7 completed on 2026-08-15. Arbitrary plug-ins, desktop capture, unrestricted scripts, and pixel-perfect OBS desktop replication remain intentionally excluded. M8 starts from this verified Studio baseline and keeps per-camera archive lifecycles independent from Program composition.

M7 已于 2026-08-15 完成。任意插件、桌面采集、不受限脚本和 OBS 桌面 UI 像素级复刻仍明确排除。M8 从该已验证 Studio 底座开始，并保持逐路归档生命周期独立于 Program 合成。

### v1-M8 — NVR Core / NVR 核心

#### v1-M8 progress / v1-M8 进度

- [x] Add an opt-in loopback-only NVR process inside the single product container / 在单产品容器内增加默认关闭、仅回环监听的 NVR 进程
- [x] Implement at most 64 independent continuous/scheduled/event/off workers with main/sub and copy/transcode policy / 实现最多 64 路独立 worker，支持连续/计划/事件/关闭、主辅码流及复制/转码策略
- [x] Finalize UTC fragmented MP4 segments into a mode-0600 SQLite WAL catalog / 将 UTC fragmented MP4 分段写入权限 0600 的 SQLite WAL 目录
- [x] Recover partial/orphan/missing state idempotently and survive arbitrary-phase product-container kill / 幂等恢复残片/孤立/缺失状态并通过产品容器任意阶段强杀
- [x] Enforce age/quota/free-space retention, evidence locks, pre-event ring, health and stable-label metrics / 执行时长/配额/剩余空间保留、证据锁、事件前环、健康及固定标签指标
- [x] Proxy the NVR namespace through the existing authentication/Origin boundary and preserve secrets across redacted config round trips / 通过现有认证/Origin 边界代理 NVR 命名空间，并在脱敏配置往返时保留密钥
- [x] Pass the four-camera deterministic copy/transcode, policy, crash, retention, read-only, decode and redaction gate / 通过四路复制/转码、策略、崩溃、保留、只读、解码与脱敏确定性门禁
- [ ] Complete the optional six-hour fixture soak and private 24-hour release burn-in on deployment hardware / 在部署硬件完成可选六小时夹具耐久和私有 24 小时发布耐久

M8 implementation completed on 2026-08-15. Long-duration burn-ins are deliberately recorded as release qualification rather than claimed by the short deterministic development gate. M9 starts from the verified archive/catalog contract documented in [docs/nvr-core.md](docs/nvr-core.md).

M8 实现于 2026-08-15 完成。长时耐久被明确记录为发布资格验证，不由短时确定性开发门禁冒充完成。M9 从 [docs/nvr-core.md](docs/nvr-core.md) 所述已验证归档/目录契约继续。

### v1-M9 — Timeline, Playback & Evidence / 时间线、回放与证据

#### v1-M9 progress / v1-M9 进度

- [x] Add bounded 31-day UTC timeline queries with per-camera segments, retention boundaries and explicit offline/missing/corrupt gaps / 增加最长 31 天的有界 UTC 时间线查询、逐路片段、保留边界及明确离线/缺失/损坏断档
- [x] Add one-to-four-player shared UTC play/pause/seek/speed/frame-step controls with a 250 ms correction threshold / 增加 1–4 播放器共享 UTC 播放/暂停/跳转/倍速/逐帧控制及 250 ms 纠偏阈值
- [x] Add HTTP Range, transient playback retention locks and gap recovery / 增加 HTTP Range、回放临时保留锁和断档恢复
- [x] Add four-slot thumbnail generation, bounded cache and SHA-256 snapshots / 增加四槽缩略图生成、有界缓存和带 SHA-256 的截图
- [x] Add four-camera stream-copy export and exact H.264 re-encode with logical program association / 增加四路码流复制导出、精确 H.264 重编码及逻辑节目录像关联
- [x] Add path-free schema-v1 manifests with requested/effective range, tracks, IDs, software version, audit ID and per-file hashes / 增加不含路径的 schema-v1 清单，记录请求/实际范围、轨道、ID、软件版本、审计 ID 和逐文件哈希
- [x] Add authenticated same-origin UI/API operations and audit for playback, snapshot, export, download, lock/unlock and delete / 增加受认证同源 UI/API 操作，并审计回放、截图、导出、下载、锁定/解锁及删除
- [x] Pass final-image TypeScript/Vite build and deterministic UTC/gap, p95, Range, JPEG, export, FFprobe, hash, conflict and redaction gate / 通过最终镜像 TypeScript/Vite 构建及 UTC/断档、p95、Range、JPEG、导出、FFprobe、哈希、冲突与脱敏确定性门禁

v1-M9 implementation completed on 2026-08-15. The deterministic reference run measured 40 local timeline queries at 10.8 ms p95. This is development evidence, not a universal storage guarantee; target deployments must repeat the measurement and browser/DST observation described in [docs/timeline-evidence.md](docs/timeline-evidence.md). v1-M10 development is now in progress.

v1-M9 实现于 2026-08-15 完成。确定性参考运行测得 40 次本地时间线查询 p95 为 10.8 ms。该数值是开发证据，不是所有存储的性能承诺；目标部署必须重跑 [docs/timeline-evidence.md](docs/timeline-evidence.md) 所述测量及浏览器/DST 观察。v1-M10 现已进入实施阶段。

v1-M9 was fully re-run from the current worktree image on 2026-08-23 while opening v1-M10. The complete UTC/gap, Range, JPEG, four-camera fast/exact export, hash, lock/delete and audit gate passed; 40 local timeline queries measured 4.8 ms p95. This regression result is environment-specific evidence, not a production latency guarantee.

v1-M10 开始阶段于 2026-08-23 使用当前工作树最终镜像完整重跑 v1-M9。UTC/断档、Range、JPEG、四路快速/精确导出、哈希、锁定/删除及审计门禁全部通过；40 次本地时间线查询 p95 为 4.8 ms。该回归结果仅是当前环境证据，不构成生产延迟承诺。

### v1-M10 — Device Operations & Camera Adapters / 设备运维与摄像机适配

#### v1-M10 progress / v1-M10 进度

- [x] Add a SQLite WAL Camera Registry with stable Camera/Profile IDs and credential references / 增加使用 SQLite WAL、稳定 Camera/Profile ID 和凭据引用的 Camera Registry
- [x] Migrate Scene v5 and NVR configuration from embedded camera URLs to registry references / 将 Scene v5 与 NVR 配置从内嵌摄像机 URL 迁移到 Registry 引用
- [x] Add explicit RTSP, MJPEG, Snapshot, HLS, HTTP-FLV, WHEP, SRT, RTP and V4L2 adapter contracts / 增加明确的 RTSP、MJPEG、Snapshot、HLS、HTTP-FLV、WHEP、SRT、RTP 与 V4L2 Adapter 契约
- [x] Add bounded ONVIF WS-Discovery and WebUI device registration/automatic detection / 增加有界 ONVIF WS-Discovery 与 WebUI 设备注册/自动检测
- [x] Support an empty first-run Scene/Registry without an RTSP bootstrap secret / 支持无需 RTSP bootstrap secret 的空 Scene/Registry 首次启动
- [x] Reject embedded credentials and token-like URL query values at the Registry boundary / 在 Registry 边界拒绝内嵌凭据和类似 token 的 URL 查询值
- [x] Implement authenticated Profile T media profiles and Profile S compatibility fallback / 实现带认证的 Profile T 媒体 Profile 与 Profile S 兼容回退
- [x] Implement capability-driven PTZ, presets, events, snapshots and guarded two-way talk / 实现能力驱动的 PTZ、预置位、事件、快照及受控双向对讲
- [x] Pass the pinned emulator plus a redacted real external camera transport decode gate / 通过固定模拟器及脱敏真实外部摄像机传输解码门禁
- [ ] Continue model/firmware-specific multi-vendor compatibility qualification without blocking v1.2 / 持续执行具体型号/固件的多厂商兼容验证，但不阻塞 v1.2

The deterministic emulator covers Digest, WS-Security, clock skew, Profile T/S and device operations. The external media tier verifies real transport and decoding but does not claim ONVIF conformance or device controls. Model/firmware-specific vendor qualification remains deliberately open as an ongoing compatibility program; see [docs/camera-compatibility-qualification.md](docs/camera-compatibility-qualification.md).

确定性模拟器覆盖 Digest、WS-Security、时钟偏移、Profile T/S 与设备操作；外部媒体层验证真实传输与解码，但不代表 ONVIF 合规或设备控制。具体型号/固件的厂商验证作为持续兼容项目有意保持开放，详见 [docs/camera-compatibility-qualification.md](docs/camera-compatibility-qualification.md)。

#### v1-M11 progress / v1-M11 进度

- [x] Normalize native/software events and immutable NVR segment references / 统一原生/软件事件与不可变 NVR 分段引用
- [x] Add include zones, exclude/privacy masks, sensitivity, debounce and cooldown / 增加包含区、排除/隐私遮罩、灵敏度、去抖与冷却
- [x] Add detector-provider schema v1 with bounded batches and failure isolation / 增加带有界批量和故障隔离的 Detector Provider schema v1
- [x] Add event search, acknowledgement notes and audit / 增加事件检索、确认备注与审计
- [x] Add rule predicates and a bounded deduplicated Webhook/MQTT outbox / 增加规则条件及有界去重 Webhook/MQTT 发件箱
- [x] Pass deterministic motion, deduplication, linkage, provider and SSRF fixtures / 通过移动、去重、关联、Provider 与 SSRF 确定性夹具
- [x] Verify signed Webhook and authenticated MQTT delivery frames without disclosing Secret values / 验证签名 Webhook 与认证 MQTT 交付帧且不泄露 Secret 值
- [ ] Continue real-camera event accuracy sampling as non-blocking compatibility evidence / 持续采样真实摄像机事件准确度，作为非阻塞兼容证据

## Cross-cutting rules / 贯穿规则

- **One scene model / 一份场景模型：** client and server rendering must not develop incompatible layouts.
- **One camera registry, two graphs / 一份摄像机资产，两条执行链：** live libobs composition and per-camera NVR capture share identity/capabilities but have independent lifecycles; canvas changes cannot interrupt archives.
- **One product image / 一个产品镜像：** test fixtures may use multiple containers; product deployment remains one image.
- **Pinned dependencies / 固定依赖：** OBS, MediaMTX, CEF, and protocol-facing dependencies use reviewed versions rather than moving branches.
- **Security by milestone / 分阶段安全：** no Internet-facing control plane before authentication, TLS, and authorization exist.
- **No secret leakage / 不泄漏凭据：** real RTSP URLs, tokens, recordings, and unredacted logs never enter Git, images, or issue reports.
- **Deterministic acceptance / 确定性验收：** every milestone adds automated tests and an explicit exit gate before the next milestone begins.
- **Software fallback first / 软件回退优先：** hardware acceleration improves performance but must not be required for basic operation.
- **Recording integrity before analytics / 录像完整性优先：** event detection, notifications, and search must fail independently without blocking or corrupting per-camera recording.

## Expanded scope and exclusions / 扩展范围与排除项

Per-camera continuous recording, retention, timeline playback, ONVIF device operations, events, bounded detection providers, local True Direct runtimes, operator UX, and forensic export are explicit v1-M8 through v2 commitments. They are implemented beside—not inside—the libobs composition graph. See [docs/future-milestones.md](docs/future-milestones.md) for the staged boundaries.

逐路连续录像、保留、时间线回放、ONVIF 设备运维、事件、有界检测提供器、本地真直连运行端、值守体验和取证导出现在是 v1-M8 至 v2 的明确承诺；它们位于 libobs 合成图旁侧而非内部。分阶段边界见 [docs/future-milestones.md](docs/future-milestones.md)。

Hosted multi-tenant SaaS, vendor P2P-cloud credential brokerage, access-control/door actuation, biometric identity databases, and a promise of unlimited camera density remain outside this roadmap. v2.0 uses a Local-first PWA for True Direct only where the browser supports the approved protocol; it never claims that an ordinary PWA can decode RTSP.

托管多租户 SaaS、厂商 P2P 云凭据代理、门禁/开门控制、生物身份数据库及无限摄像机密度承诺仍在路线图之外。v2.0 使用 Local-first PWA：WHEP/HLS/MJPEG 满足 HTTPS/CORS/授权条件时由浏览器真直连；普通 PWA 不解码 RTSP，必须明确经过 Docker Gateway/Hybrid。实验 IWA 不属于稳定发布门禁。
