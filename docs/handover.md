# 交接手册 / Handover Manual — Web Camera Monitor Wall

> 适用版本 / Version：**v3.2**（正式发布 2026-09-22）。本手册在 `dev` 的 `bf996ce` 上维护；`main` 停在发布提交 `fc6fe71`。
> 读者 / Audience：接手本项目的开发者与运维。
> 约定 / Convention：文中「未提交」= 存在于工作区但**不在 Git 索引**中，新克隆不会携带。引用文件均给出仓库内路径。

---

## 0. 如何使用本手册 / How to use

先读这四份仓库内文件，它们是权威来源，本手册是索引与补充：

| 优先级 | 文件 | 作用 |
| --- | --- | --- |
| 1 | `docs/versioning-and-branches.md` | 版本号、分支职责、GHCR 标签语义（**发布前必读**） |
| 2 | `docs/development.md`（**未提交**） | Windows/Linux 本地开发统一流程（native/frontend/container） |
| 3 | `docs/local-platform-gates.md` | 本机 Windows + WSL2 私有门禁与收据（receipt）契约 |
| 4 | `ROADMAP.md` | 里程碑、当前进度、验收证据、未关闭项 |

建议顺序：§1 → §2 → §3（工作区与移交清单）→ §4（Day 1）→ §5/§6（架构）→ §7（契约）→ §8（开发）→ §9/§10（分支与提交规范）→ §11（测试）→ §12（发布）→ §13（路线图）→ §14（陷阱与待决项）。

---

## 1. 项目是什么 / What this is

基于 **OBS `libobs`** 的无桌面 Web 监控墙：RTSP 摄像机 → libobs Scene → 录制 MP4（H.264/AAC）与浏览器播放（WHEP/WebRTC）；附带 Gateway Direct 网关、Local-first PWA、NVR、事件/自动化、ONVIF 设备运维与可选多节点扩展。

```text
RTSP camera -> libobs ffmpeg_source -> OBS scene -> H.264/AAC MP4
                                                   -> H.264/Opus WHIP/WHEP
```

**核心不变量（改错会破坏产品契约）**

- 默认 **Gateway Direct-only** 运行**完全不初始化** OBS 解码/合成/编码；只有 Program 录制或显式启用 Composite 才启动 libobs 复合运行时（`core/src/obs_engine.cpp`：`composite_runtime_active = recording_enabled || composite_enabled`）。
- API v1 的 `direct` 是**经 Docker/MediaMTX 的网关直通**，**不是**绕过服务器的真直连；普通 RTSP 永远不会变成浏览器 HTTPS 真直连。
- Scene 只保存 Camera/Profile **ID**，凭据通过未提交 Git 的 Secret 引用解析；API、WebSocket、metrics、审计、Grant、同步文档**永不**回显 URL、凭据、路径、PID 或客户端地址。
- 认证是**单操作员边界**（文件型凭据），不是 RBAC；v2.3 的 RBAC 属于集群控制面。
- 录像完整性优先于分析；画布变更不得中断归档；锁定证据永不参与保留清理。
- 已经发布的版本 Tag **不可移动**；禁止强推。

**技术栈**：Ubuntu 24.04 / C++20 / CMake 3.28+ / OBS Studio 32.1.2（固定 submodule `fb4d98bf…`）· React 19.2 + TypeScript 7 + Vite 8 · Python 侧车 · MediaMTX 1.18.2 · libdatachannel 0.21.0 · Caddy 2.11.4 · 单容器 Docker/Podman 镜像。

**非目标**：Windows EXE / Android APK / IWA 发布门禁（原生客户端已冻结）；实验性 Chromium IWA RTSP/TCP 不在稳定门禁内；多厂商 ONVIF 兼容性测试是兼容证据而非发布阻塞项。

---

## 2. 当前状态快照 / Current state（核对 2026-09-22）

| 项 | 值 |
| --- | --- |
| 当前正式版本 | **v3.2**（GitHub Release `Latest`，`published_at` 2026-09-22T04:32:47Z，immutable） |
| 版本日期 vs 实际发布 | 版本日期 2026-09-21；实际发布 2026-09-22（`published_at` 不回填） |
| 发布 Tag 提交 | `5ab5da0fa4d2ac67af2ac52c7ee3d64f75ae82cc` |
| 分支 | `main` = `fc6fe71`（v3.2 发布提交）；`dev` = `bf996ce`，**领先 `origin/dev` 3 个提交**（反馈6、局域网联调、投影窗口修复） |
| 镜像 | `ghcr.io/liaoyk001/web-camera-monitor-wall` |
| OCI index digest | `sha256:1bbb0c2608c977b2e04386846dcb11674d9f6996a4c8e0b01bb6f1be58999953` |
| 指向该 digest 的标签 | `v3.2`、`latest`、`v3.1`、`sha-5ab5da0fa4d2`（**同一镜像，未重建**） |
| 镜像内嵌构建标识 | `3.1.0-dev.5ab5da0fa4d2`，milestone `v3-M2-dev`（保留标识，非另一个版本） |
| Release 附件 | `webobs-source-v3.2.tar.gz`（43,490,848 B）+ `.sha256` |
| 历史 Tag | `v1.2, v1.2.1, v2.0, v2.0.1, v2.1, v2.2, v2.3, v2.3.1, v3.0, v3.1, v3.2` |
| 遗留草稿 | "已弃用草稿：请使用v3.2 / Superseded draft: use v3.2"（tag_name=`v3.1`，仍为 Draft）；`release-draft-3.0-16101ce3699d` |

**本次发布的例外（必须如实传递）**：按用户明确授权**跳过了全部长测**（30 分钟稳态、长时真实相机、GPU 验收），只跑短回归、静态检查与构建校验。历史验收（受控 Direct/Hybrid 12/12、真实 Direct/Hybrid 8/9、真实 Composite 13/13）**不是**本次镜像的重新验收。常规稳定版门禁**保持不变**，后续版本不继承该豁免。

**最重要的未关闭项**：`back_3` 冷启动首帧 **23,945 ms > 20,000 ms 预算**。归因边界：缺口在「相机→网关上游」已确立；链路丢包 / 编码器负载 / 冷启动行为三者谁为主**未确立**。未改动任何相机配置，未放宽任何验收门槛。见 `docs/feedback-5-source-limitation-report.md`。

---

## 3. 工作区状态与移交清单 / Working-tree state

**当前工作树完全干净**：`git status --porcelain` 为空，既无未提交改动，也无未跟踪文件。

> 历史提醒 / History：本手册首版撰写时曾有 **17 个未跟踪文件**（含当时的统一开发指南 `docs/development.md` 与 Linux 启动器 `scripts/dev.sh`）。它们已由 `e056376 manual-1` 一并提交入库，该风险已消除。若你检出的分支早于该提交，请先确认这批文件存在。

**仍需手工移交的内容**（都不在 Git 中，且被 `.gitignore` 覆盖）：

| 内容 | 说明 |
| --- | --- |
| `secrets/` | 开发凭据（`webobs-dev-username.txt` = `admin`、`webobs-dev-password.txt`）与生产 TLS/认证文件来源（生产凭据是**宿主机明文文件**，见 §12） |
| `recordings/`、`tests/artifacts/` | 录像与门禁证据（含私有端点，禁止上传公开 Issue） |
| `build/` | 发布产物（`build/release-assets/**`）、原生缓存与临时日志 |
| `gate/` | 私有门禁夹具；必须在检出目录之外使用 |

**待办**：`dev` 领先 `origin/dev` 3 个提交且尚未 push（按 §9/§10：不自动 push，需维护者确认）。

---

## 4. Day 1 快速上手 / First day

**前置**：Windows 11 + WSL2 Ubuntu 24.04（或 Linux）；Node.js 24 LTS、Git、Python 3.12+；Docker Desktop 仅在做镜像/容器联调时需要。建议 ≥8 GB RAM、20 GB 磁盘（首次编译 OBS 较慢）。

```powershell
git clone --recurse-submodules https://github.com/LiaoYK001/Web-Camera-Monitor-Wall.git
cd Web-Camera-Monitor-Wall
.\scripts\dev.ps1 -Setup      # 仅首次：经 WSL root 装依赖、拉 submodule、校验 MediaMTX
.\scripts\dev.ps1              # 日常：编译原生后端 + 启动 Vite
```

```bash
# Linux / WSL 首次（scripts/dev.sh 当前未提交，需先取得）
bash scripts/dev.sh --setup
bash scripts/dev.sh
```

- 前端 **http://127.0.0.1:5173**，原生 API **http://127.0.0.1:8080**（Vite 代理，ws:true）。
- 停止：`scripts/stop-dev.ps1` / `bash scripts/stop-dev.sh`（按会话令牌停止，不强杀其他进程）。
- 开发登录：`secrets/webobs-dev-username.txt`（本机内容 `admin`）/ `webobs-dev-password.txt`（32 B，明文）。
- 原生数据在 WSL 用户 `~/.cache/webobs-dev/<仓库路径摘要>/`（`data/`、`logs/`、`recordings/`），**与 Docker 数据卷相互独立、不自动迁移**。

**第一周建议**：跑通 §8 启动器 → 跑 §11「最小验证路径」→ 读 §7 契约 → 选一个 §13 未关闭项或 §14 待决项。

---

## 5. 架构总览 / Architecture

**单容器多进程**：`ENTRYPOINT ["/usr/bin/tini","--","/opt/webobs/entrypoint.sh"]`，`docker/entrypoint.sh`（924 行）是唯一进程管理器；行为由 `WEBOBS_NODE_ROLE`（`standalone|controller|recorder|worker`，默认 `standalone`）决定。

```text
Browser/PWA --8443 HTTPS--> Caddy --127.0.0.1:8080--> webobsd (C++, 内嵌 libobs)
Browser/PWA --8189/udp WebRTC-------------------------------------------> MediaMTX
webobsd --反代 WHEP--> MediaMTX(8554 rtsp / 8889 webrtc / 9997 api, 仅回环)
webobsd --反代--> camera-registry:8092 | nvrd:8091 | events:8093
                 client-control:8094 | cluster:8095(admin) + 9443(mTLS 集群)
libobs --WHIP--> MediaMTX --RTSP on demand--> 摄像机
libobs --> Xvfb :99 / Weston+Xwayland ; libobs --> /recordings/*.mp4
每个子进程一条 mkfifo 日志管道 --> webobs-log-filter(凭据脱敏)
```

| 进程 | 端口（默认） | 绑定 | 启动条件 |
| --- | --- | --- | --- |
| `webobsd`（C++，内嵌 libobs） | 8080 HTTP | 默认 127.0.0.1；base compose 为 0.0.0.0 | 始终；唯一被 wait 的前台进程 |
| Caddy | 8443 HTTPS | 0.0.0.0 | `WEBOBS_TLS_ENABLED=true`，反代 127.0.0.1:8080 |
| MediaMTX | 8554/8889/9997（回环）+ 8189/udp | 容器内回环 | `WEBOBS_WEBRTC_ENABLED`（standalone 默认 true） |
| `nvrd` | 8091 | 127.0.0.1 | `WEBOBS_NVR_ENABLED`（默认 false） |
| camera-registry | 8092 | 127.0.0.1 | 默认 true |
| events | 8093 | 127.0.0.1 | 默认 true |
| client-control | 8094 | 127.0.0.1 | 默认 true（端口本身拒绝直接管理请求） |
| cluster | 8095 admin + 9443 mTLS | 回环 | `WEBOBS_CLUSTER_ENABLED`（base false / 生产 true）；`CLUSTER_LISTEN=false` 默认关 |
| node-agent | 无监听 | — | 仅 recorder/worker，需 `WEBOBS_CONTROLLER_URL` + 集群 CA |
| detector-worker | 无监听 | — | 由 node-agent 加载；ONNX `ssd_mobilenet_v1_12` |
| s3-archive / encrypted-backup | 无监听 | — | `WEBOBS_ARCHIVE_ENABLED` / `WEBOBS_ENCRYPTED_BACKUP_ENABLED` |
| Xvfb `:99`(1920×1080×24) 或 Weston+Xwayland | — | — | auto：硬件 EGL 探测成功走 Weston，否则回退 Xvfb/llvmpipe |

**进程间全部是 127.0.0.1 HTTP/RTSP，没有 unix socket。** 任一子进程异常退出 → 退出码 3 并停 `webobsd`。EXPOSE `8080 8443 9443 8189/udp`。

**媒体数据流**

- **录制**：obs-ffmpeg-mux 先写临时 MKV，停止后 FFmpeg **stream copy** 成 MP4（不二次编码）→ `/recordings/webobs-<UTC>.mp4`。
- **推流**：obs-webrtc（libdatachannel）WHIP → MediaMTX `program` → 浏览器 WHEP。
- **Direct（网关直通）**：Camera → MediaMTX `direct-<32hex>` → 浏览器；不初始化 OBS。`true-direct` 是**尚未实现**的独立能力，不得由 `direct` 暗含。
- **Hybrid**：只对不兼容轨按需转码（`gateway/transcode-on-demand.sh` 生成 `hybrid-<32hex>` / `audio-<hash>-tN` / `mix-<hash>`）。
- **Composite**：解码 → libobs 渲染/混音 → x264 CBR veryfast（2 s IDR）或 VA-API → WHIP。
- **能力回退**（`core/src/studio_document.cpp` 的 `analyze_scene_capability`）：requested=`direct` 时若存在非 rtsp/camera 源、非空 filters、或 item 的 rotation/opacity/blend_mode 非默认 ⇒ `exact=false`；hybrid 仍是 hybrid，direct 降级为 composite；**composite 请求不降级**。渲染回退会导出 `WEBOBS_RENDERER_SELECTED / FALLBACK / FALLBACK_REASON`。
- MediaMTX 只做信令与包转发；`gateway/mediamtx.yml` 仅监听回环，`authMethod=internal` 且只允许 `127.0.0.1/::1` 读写 `program/direct-/audio-/mix-/hybrid-` 路径。

**Compose 覆盖矩阵**

| 文件 | 用途 |
| --- | --- |
| `compose.yaml` | 基线：回环开发；LISTEN 0.0.0.0 + insecure、WebRTC on、Composite/Cluster off |
| `compose.m6-production.yaml` | 生产 HTTPS：LISTEN=127.0.0.1、TLS+Caddy、Secure Cookie、TURN、cluster on、6 个 secrets、端口 override 8443/8189 |
| `compose.m6-auth.yaml` | 只加文件认证 + 集群开关 + 回环兼容 `SESSION_COOKIE_SECURE=false` |
| `compose.m6-vaapi.yaml` | 挂 `/dev/dri/renderD128` 与 encoder/renderer/hwdecode |
| `compose.m6-backup.yaml` | 挂 `./backups:/backups` |
| `compose.dev.yaml`（未提交） | 本地镜像 `webobs:dev`、`WEBOBS_TEST_TMPDIR=/dev/shm`、开发 secrets |
| `deploy/compose.podman.example.yaml` | Podman：host 网络、GHCR 镜像、`:Z` 卷标签、自定义端口 28777 |

---

## 6. 代码结构与目录职责 / Code layout

| 目录 | 职责（关键文件） |
| --- | --- |
| `core/` | C++ 控制面与 libobs 运行时：`core/src`（20 cpp）+ `core/include/webobs`（16 hpp）+ `core/tests/common_tests.cpp` |
| `gateway/` | MediaMTX 配置与按需转码：`mediamtx.yml`、`transcode-on-demand.sh` |
| `camera/` | Camera Registry / ONVIF 适配：`camera_registry.py`（3274 行） |
| `nvr/` | 逐摄像机 NVR 与证据：`nvr_service.py`（1642 行） |
| `events/` | 事件/移动/规则/通知发件箱：`event_service.py` |
| `analytics/` | 一方人员检测运行时：`detector_worker.py`、`detector-requirements.lock`、`install_runtime.py` |
| `providers/` | 外部 Provider 契约：`provider-v1.openapi.yaml`、`provider-v1.schema.json` |
| `v2/` | v2 客户端注册/授权/媒体路径：`client_control_service.py` |
| `archive/` | S3 兼容异步归档：`s3_archive.py` |
| `backup/` | 加密灾备 + 升级守卫：`encrypted_backup.py`、`preupgrade_guard.py` |
| `cluster/` | 集群/RBAC/放置/租约：`cluster_service.py`（2234 行）、`node_agent.py` |
| `web/` | React PWA：`src/`、`public/`、`vite.config.ts`、`playwright*.config.ts` |
| `clients/` | **冻结**的 Qt/GStreamer/Android 原生客户端与打包脚本 |
| `docker/` | `Dockerfile`（605 行、12 阶段）、`entrypoint.sh`、`Caddyfile`、`backup.sh` |
| `deploy/` | Podman 示例与说明 |
| `scripts/` | 开发/门禁/发布脚本（见 §8/§12） |
| `tests/` | 跨模块门禁与 fixture（rtsp/mediamtx/browser fixture、`m7/` 集群门禁） |
| `assets/` `recordings/` `backups/` | 只读素材源 / MP4 落盘 / 加密备份落盘 |
| `obs/` `docs/` `.github/` | OBS 32.1.2 submodule、文档、CI |

**`core/src` 核心模块**

| 文件 | 职责 |
| --- | --- |
| `main.cpp` / `config.cpp` | 入口；CLI flags + `WEBOBS_*` 环境解析、校验、凭据文件读取 |
| `control_server.cpp`（4110 行） | HTTP 控制面、反代、会话、静态资源、CSP 与安全头 |
| `obs_engine.cpp` | libobs 生命周期与输出编排（Direct-only 判定在此） |
| `obs_scene_runtime.cpp`（1484 行） | OBS 场景构建、来源健康、音频路由 |
| `scene_controller.cpp` / `scene_document.cpp` / `scene_store.cpp` / `scene_mutation.cpp` | 场景快照并发 / Scene 模型与迁移 / 原子持久化 / revision 乐观并发 |
| `studio_document.cpp` / `studio_store.cpp` / `studio_controller.cpp` | Studio 多场景、转场、能力分析 / 持久化 / API 与撤销重做 |
| `video_encoder.cpp` / `audio_tracks.cpp` | x264/VAAPI/QSV/NVENC 探测选择 / ffprobe 音轨描述 |
| `authentication.cpp` | Basic + 会话 + 失败限速（口令常量时间比较、**不做哈希**；会话 token 存 SHA-256） |
| `browser_security.cpp` / `audit_event.cpp` / `redaction.cpp` / `log_filter.cpp` | 浏览器源策略 / 结构化审计 / 凭据脱敏 |
| `scene_tool.cpp` | 离线 CLI 校验与迁移 |

**前端**：React 19.2 + TS 7 + Vite 8；入口 `web/src/main.tsx`（Trusted Types + workbox）→ `LoginGate` → `App.tsx`。**无 react-router**：`WorkspaceShell.tsx` 用 hash 路由 `areaFromHash()`，11 个产品区（monitor/studio/devices/audio/analytics/events/archive/storage/settings/admin/clients）。状态为 React hooks + REST/SSE（`api.ts`），本地态走 IndexedDB；`src/` 为扁平目录（43 文件）。构建产物 `web/dist` → 镜像 `/opt/webobs/ui`。PWA 用 injectManifest + 自研 `sw.ts`；**更新需 `WEBOBS_ACTIVATE_UPDATE`**（故意不 skipWaiting，避免播放中混用两个构建）。

**持久化（删掉会怎样）**

| 容器内路径 | 宿主机 | 内容 | 删除后果 |
| --- | --- | --- | --- |
| `/config/webobs` | 卷 `webobs-config` | `scene.json`、`studio.json`、`auth-sessions.db`、`cameras.db`、`events.db`、`nvr.db`/`nvr.json`、`v2-clients.db`、`cluster.sqlite3`、`archive.json`(+queue)、`shared-scenes-v2.json`、`keys/client-grant-signing.key`(0600)、升级标记与备份 | 场景/相机/会话/审计/授权全部丢失，只能靠加密备份恢复 |
| `/config/obs` | 卷内 | obs-browser CEF 缓存 | 无害，启动时清理重建 |
| `/recordings` | `./recordings` | 节目 MP4 + `nvr/<camera>/YYYY/MM/DD` + `catalog.sqlite3` | 录像不可恢复；DB 幂等对账并隔离孤儿 |
| `/assets` | `./assets:ro` | 图片/媒体源素材 | 相关源失效 |
| `/backups` | `./backups` | 15 分钟周期加密配置备份 | 失去灾备 |
| `/run/secrets/*` | `./secrets` 或外部文件 | TLS、auth、TURN、cluster 证书/CA/token、backup key、camera 凭据、archive/notification CA | **启动即 fail-closed，退出码 3** |

---

## 7. 对外契约与行为规则 / Contracts

> 权威：`docs/api-v1.md`、`docs/api-v2.md`、`docs/scene-schema-v1..v5.md`、`docs/true-direct-v2.md`、`docs/local-first-pwa.md`、`docs/nvr-core.md`、`docs/timeline-evidence.md`、`docs/events-and-automation.md`。

### 7.1 API v1 面

**公开（免认证）**：`GET /`、`/assets/*` 哈希资源、`GET /api/v1/health|ready`（探针不含配置细节）。其余全部过统一认证门。

| 域 | 端点 | 关键约定 |
| --- | --- | --- |
| metrics | `GET /metrics` | Prometheus；编码器标签仅 `x264/vaapi/qsv/nvenc`；不含 URL/ID/用户名 |
| auth | `POST /auth/login`、`GET /auth/session`、`POST /auth/logout` | login 下发 `webobs_session` Cookie |
| scene/studio | `GET/PUT /scene`、`GET/PUT /studio`、`POST /studio/{take,undo,redo}`、`GET /studio/capabilities` | ETag=`"<rev>"`、`If-Match` **必填**；错误码 403 origin_rejected / 409 runtime_rejected / 412 revision_conflict / 413 / 415 / 422 invalid_scene / 428 / 431 / 503 |
| sources | `GET /sources/status`、`POST /sources/{id}/whep`、`DELETE …/session/{token}` | `state=idle|starting|healthy|stale|recovering`；未知源 404；browser 源 409 composite_only |
| playback | `GET /playback/capabilities`、`/program/status`、`POST /program/whep` | **唯一**浏览器信令入口；201+Location；403/413/415/502 |
| system | `GET /system/capabilities`、`/system/processes` | 每后端报 devicePresent/encodeSupported/decodeSupported/runtimeProbePassed/encoderAvailable/ready |
| cameras/ONVIF | `GET/POST /cameras`、`GET/PUT/DELETE /cameras/{id}`、`POST /camera-detect|/onvif/discover|/onvif/probe`、`…/onvif/sync|ptz|presets|snapshot|events/pull|talk`、`GET /cameras/{id}/operations` | 拒内嵌 userinfo 与 `credentialsRef` 穿越；凭据只在 `/run/secrets/webobs-camera-credentials/<ref>.json`；PTZ 100–2000 ms 自动停 + 逐机限速 |
| nvr | `/api/v1/nvr/*`（health/status/config/segments/timeline/media/locks/events/metrics） | timeline ≤31 天；`GET /config` 端点替换为 `rtsp://***` |
| 证据 | `POST /api/v1/nvr/exports|/snapshots`、`GET /thumbnails/{id}` | 1–4 机、≤24 h、fast\|exact、逐文件 SHA-256；清单不含 URL/凭据/路径 |
| 事件 | `GET/POST /events`、`PUT /events/{id}/acknowledgement`、`/motion-zones`、`POST /motion/evaluate`、`/detector-providers`、`/event-rules`、`GET /notification-outbox`、`POST …/process` | 发件箱 ≤4096、24 h 过期、≤8 次重试 |
| 分析策略 | `GET/PUT /cameras/analytics-policies` | 1–256 原子批；**只存策略，不起管线** |
| WebSocket | `/api/v1/ws` | `scene.snapshot`/`scene.updated`；只读，写走 HTTP PUT |

**认证语义（容易踩）**：**唯一会返回 `authentication_disabled`(404) 的是 `POST /api/v1/auth/login`**（未配置凭据文件且无集群身份，或会话库不可用）。`GET /auth/session` 此时返回 200 `{"authenticated":false,"authenticationEnabled":false}`。认证关闭时其他端点全部放行；开启后未认证返回 401 `authentication_required`（**不带** `WWW-Authenticate`，避免浏览器 Basic 弹窗），失败超阈值返回 429 `auth_rate_limited` + `Retry-After`。**v1 没有 /backup 端点**（备份属 v2.3 的 `/api/v2/backup-jobs`）。

### 7.2 API v2 面

v1 完全不变；v2 增加**设备配对**与可独立测量的 `true-direct`。要点：

- `POST /api/v2/enrollments` 公开（≤32 pending）；审批/列举/撤销需管理员会话或 Basic，并加瞬时 256-bit 内部 token；**8094 端口拒绝直接管理请求**。
- 授权模型是 Camera/Profile **grant**：权限 `view|ptz|talk|snapshot|record-local`（view 必选）；`web`/`chromium-iwa` 强制 `credentialMode=none`；Grant 格式 `webobs-browser-grant-v1`，**Ed25519 签名 + X25519 密封 CBOR，只含元数据、永不含 credentials**。
- v2.3 引入 RBAC（内置 admin/operator/viewer/auditor/exporter + Camera/Group scope，**默认拒绝**）。
- 共享场景 `/config/webobs/shared-scenes-v2.json`：schemaVersion 1、≤64 个场景、只允许 Camera/文字/纯色/图片/两级嵌套，拒原始 URL 与 endpoint/凭据/secret/token/未知字段。
- 同步 `POST /api/v2/client/sync`：≤64 mutation、字段级 409、等值重试幂等；**物理地址/媒体端点/凭据引用永不是同步文档**。

### 7.3 Scene schema 演进（v1→v6）

| 版本 | 新增/变更 |
| --- | --- |
| v1 | `schemaVersion`+`revision`；仅 RTSP；≤64 源/256 项；ID 限 `[A-Za-z0-9._-]`≤64 B；1 MiB 上限且拒未知/重复键；0600 临时文件 + 原子重命名 + 0700 目录 |
| v2 | 增 `browser` 源（≤8、宽高 16–8192、FPS 1–60、CSS ≤32 KiB）；来源默认拒绝 + `WEBOBS_BROWSER_ALLOWED_ORIGINS` 精确匹配；拒 URL userinfo，公开视图 query/fragment → `?***`/`#***` |
| v3 | 统一音频：`muted / volume(0–1) / syncOffsetMs(±10000) / monitoring(off\|monitor-only\|monitor-and-output) / audioTrack(1–6)` |
| v4 | Canvas Studio：位置/连续 zIndex/visible/lock/groupId/crop/contain\|cover\|stretch/有限旋转/opacity/blend；画布 16–8192 偶数；滤镜按序 ≤16（crop-pad、opacity、color-correction、mask-blend、lut、scaling、delay），LUT/遮罩限 `/assets/`、`/recordings/` |
| v5 | 增 `kind:"camera"`：`cameraId`/`profileId`（各 1–64 稳定 ID）+ `hardwareDecode∈auto\|on\|off`；**camera 源不得含原始 URL** |
| **v6（实现当前值）** | `audioInputs` 取代单 `audioTrack`（legacy=5）；校验器只接受 5/6。**文档仍写 v5 为当前契约，属文档滞后** |

**为什么 Scene 只存 ID**：Scene 会经 REST/WebSocket/离线快照/导出配置公开，而含 userinfo 的 RTSP URL 是 libobs 建连必需的本机秘密材料。Registry 只把 `credentialsRef` 解析给内部消费方，API 只回引用。

**迁移**：首次迁移写 `<scene>.pre-v5.backup`(0600) → 补安全默认 → 全量校验 → 原子替换；旧 RTSP 源继续有效（v0 无 revision 特判，低版本补齐 audio/filters/items 后一次性升版）。

### 7.4 行为契约/不变量（逐条有据）

1. 默认 Gateway Direct-only 不初始化 OBS 解码/合成/编码；该模式 `/ready` 仍 ready 且 `engineActive=false`。NVR 是独立进程、**不持有 libobs、不发布额外端口**，FFmpeg 用固定参数数组、无 shell。
2. `direct` 恒为 Gateway Direct：v1 **不接受也不通告** `true-direct`；只要 Docker 内 MediaMTX 接收或转发媒体包就算网关直通。
3. **HTTP 摄像机不会被误报为 HTTPS 浏览器直连**：`allowInsecureHttp` 只授权 Docker Gateway/NVR 拉流，不加入 PWA CSP、不绕过 Mixed Content、不让 Profile 取得真直连资格；直连资格由服务端判定，不信任客户端布尔。
4. 导出配置必须脱敏：本机 profile 只含脱敏投影，导出/导入前 `assertRedacted` 拒绝 `rtsp(s)://…@` 与 password/credentials/secret/token/rtspUrl/url/filePath/endpoint 键。
5. 脱敏占位符（`***:***@`、`rtsp://***`）**不能创建新秘密**：仅当仍指向同一既有源时恢复存储凭据；新源或改端点必须提交完整 URL。
6. 策略/计划本身不启动媒体链；`true-direct-only` 计划返回 409 而非静默回退。
7. 用户选择不静默启动第二套服务端媒体图；后备需归属激活租约，观看端关闭/租约释放/客户端撤销即销毁按需路由；单 Tile 同时只允许一条实时链。
8. 低功耗不请求 Docker 转码；普通 PWA 的 RTSP 永远显示 `Camera → Docker → Browser`。
9. 锁定证据永不参与保留清理；锁定/在读片段删除返回冲突。

### 7.5 安全边界

- 认证：v1 单操作员、非 RBAC；v2.3 起 RBAC + Camera/Group scope、默认拒绝。
- Host/Origin：本地 authority 恒放行；远程 authority 必须来自显式白名单 HTTPS Origin；带 Origin 的请求其 authority 必须等于 Host；WebSocket 升级同规则。
- **不返回任何 CORS 授权**，只设 CORP `same-origin`。
- Cookie：`webobs_session=…; Path=/; HttpOnly; SameSite=Strict; Max-Age=<inactivity>[; Secure]`；生产必须 `Secure=true`。
- 限流：无效凭据按客户端地址 + 窗口计数（缺失凭据不消耗预算）；PTZ 逐机限速；探针并发 1/机、全局 4。
- 体积/时长：JSON 1 MiB、WHEP SDP 64 KiB、headers 16 KiB、读取 15 s、静态单文件 2 MiB。
- 响应头：严格 CSP（`default-src 'none'` … `require-trusted-types-for 'script'`）+ nosniff + X-Frame-Options DENY + no-referrer + Permissions-Policy + CORP；响应禁缓存。
- Secret 规则：摄像机凭据 `/run/secrets/webobs-camera-credentials/<ref>.json`、通知 `/run/secrets/webobs-notifications/<ref>.json`、集群 CA/私钥/token 均须 `/run/secrets` 或节点私有卷；API 与 SQLite 只保存引用/摘要。
- 凭据文件字节规则：用户名 1–64 B 可打印 ASCII **禁冒号**；密码 16–256 B 禁控制字节；必须成对、绝对路径、常规文件、≤4096 B；允许并移除**一个**尾部换行（含 CRLF）；启动读一次、永不入日志。

### 7.6 前端行为逻辑

- **离线策略**：UI 代码、画布变换与获批快照从浏览器存储执行，**实时视频绝不作为离线缓存**；装 PWA 不会让 RTSP 变浏览器兼容。SW 由仓库自有（不从 CDN 取）：跨源请求与 `/api/**`、`/recordings`、`/metrics`、WHEP/媒体后缀一律 NetworkOnly；`/assets/` 哈希资源 CacheFirst；导航 NetworkFirst(3 s) 且 denylist，失败回落 `/offline.html`。
- **本机配置 Profile**：`LocalConfigProfile` 只含脱敏投影，**浏览器本地、与登录用户无关**；存 IndexedDB `webobs-local-v1` 的 `runtimeMeta`，AES-GCM + 不可导出包装密钥；上限 32 profile / 20 备份 / 名称 64 / 导入包 2 MiB。**登出/撤销只清 identity/snapshot/localScenes/auditQueue/syncQueue/syncState 与 lease/monitor-view/workspace-layout，配置 profile 与备份保留。**
- **IndexedDB**：文档写 5 个 store，**代码已是 7 个**（+syncQueue/syncState，DB version 2）——文档滞后。
- **本地服务不可用**：会话探测失败**不当作"需要登录"**（否则后端重启会卡死本地开发）；有离线授权 → "离线授权模式 · 修改只保存在本机"；否则显示"本地服务暂不可用" + "重新检查"。
- **更新提示**：`onNeedRefresh` → "应用新版本"按钮 → 用户点击才激活并 reload。

### 7.7 改错会破坏兼容性的雷区

1. 改 `direct` 枚举名或其语义，或用 `true-direct` 回填。
2. **Scene 版本号**：实现 current=**6**、legacy=5，文档仍写 v5；按文档写死 5 会直接失败。
3. 删 `audioTrack` 或从 `audioInputs` 派生它（代码显式不派生，旧播放路径仍读它）。
4. 破坏 `zIndex` 从 0 起连续唯一、画布偶数尺寸 → 序列化与 libobs 层级顺序不确定。
5. 把脱敏占位符当真实值写回，或允许它创建新源/新秘密。
6. 在 API/WS/metrics/审计/问题中心/Grant/同步文档中加入 URL、凭据、路径、PID、客户端地址。
7. 改错误信封 `{"error":{"code","message"},"revision"}` 或 403/409/412/413/415/422/428/431/503 语义。
8. 丢 `If-Match`/revision：缺失=428、过期=412；Scene/Studio/v2 catalog/settings/audio PATCH 全依赖。
9. 改 IndexedDB 名/store 集合/version 或删 `runtimeMeta` 键 → 丢本机 profile、租约、离线快照。
10. SW 改成 skipWaiting 立即激活 → 播放中混两个构建。
11. 把 NVR `.partial/.pre-event/.quarantine`/缩略图/导出路径当静态目录，或直接复制运行中的 SQLite 当备份。
12. v2：`web`/`chromium-iwa` 必须 `credentialMode=none`；`targetClientId` 更新立即失效旧会话/令牌；撤销失败只能置 `weakRevocation=true`，不得冒充强撤销。

---

## 8. 开发流程与工具链 / Development workflow

> 权威文档：`docs/development.md`（未提交）。**日常开发默认不需要 Docker**。

| 模式 | 用途 | 本机需求 | 构建镜像 |
| --- | --- | --- | --- |
| `native`（默认） | Web、C++ API、账号、设备、事件、NVR、Gateway Direct 联调 | Node 24 + Linux 原生依赖（Windows 用 WSL2） | 否，首次编译 libobs 核心 |
| `frontend` | 只改 Web，连已有后端 | Node 24 + Corepack | 否 |
| `container` | 完整媒体功能/已有镜像联调 | Docker/Podman + Compose | 仅显式 `-Build`/`--build` |

**常用命令**：`dev.ps1`/`dev.sh`（转发到 `scripts/dev.mjs`）、`-Check`/`--check`、`-Help`/`--help`、`-Port 5175`、`-Mode frontend -Api http://127.0.0.1:8080`、`-Mode container -Engine podman`、`-Distro Ubuntu-24.04`、`-Composite`、`-Soak`。

**端口**：前端 5173（Vite HMR）· API 8080 · 侧车 8091–8095 · 媒体 8190/tcp、8189/udp、8554、8889、9997。端口占用时脚本**拒绝启动且不强杀**。

**`dev-local.ps1`/`dev-local.sh` 是 Docker 路线**：只允许在 `dev` 分支运行，用 `compose.yaml`（镜像 `webobs:dev`），动作 start/status/logs/debug/frontend/test/build/hotfix/shell，**从不打 tag、不 push**。**不要用 `docker compose down --volumes`**（会清掉本地 Registry/Scene/Session）。

**依赖**：`scripts/dev-native.py` 的 `PACKAGES`（CMake ≥3.28、GCC C++20、Boost、FFmpeg 6.1 dev、Jansson、OpenSSL、SQLite、libsodium、X11/GL/EGL），仅支持 Linux x86_64；Node ≥24。首次需网络与 sudo 密码；pnpm 失败会重试 3 次并提示检查代理。

**关键限制**

- 原生模式**只编译 libobs 核心**，不构建 OBS 插件/CEF → **服务端 Composite、OBS 浏览器源、GPU、跨机器媒体连通性必须在完整镜像中验证**；原生启动成功 ≠ 发布验收。
- 前端 `node_modules` **不跨 Windows/Linux 共用**；两端同时开发请用两个独立 checkout。
- `WEBOBS_DEV_OBS_SOURCE` 可指向 Linux 侧 OBS 源码绝对路径；否则 OBS 依赖按 submodule 提交缓存，**不含其未提交修改**。
- 编译失败看 `logs/build.log`（启动提示会给路径）。
- 启动器回归：`node --test tests/test-dev-launcher.mjs`（9/9）。
- 完整镜像与跨机测试：`cd web && corepack pnpm build && corepack pnpm test:local` → `docker build -f docker/Dockerfile -t webobs:review .` → `docker save`/`load` → 目标机 `docker run`（`docs/development.md` §7 有完整示例）。

---

## 9. 分支与版本策略 / Branch & version policy

> 权威：`docs/versioning-and-branches.md`（2026-08-24 生效，2026-09-22 增补顺位规则）。

| 分支 | 职责 | 版本身份 | 发布 |
| --- | --- | --- | --- |
| `main` | 稳定发布集成与热修基线 | 发布系列 `vX.Y` | 不可变发布 Tag 与稳定 GHCR 别名从此产生 |
| `dev` | 活跃里程碑集成 | 里程碑 `vX-MN` | 可移动 `dev`/`sha-*`；里程碑检查点可打不可变 Tag |

功能开发以 `dev` 为目标；发布系列门禁通过后经**发布 PR** 合入 `main`。热修从 `main` 分出、合回 `main` 后同步回 `dev`。**禁止强推、禁止移动已发布 Tag。**

**版本号**：发布系列 `v<major>.<minor>`（可加 patch，如 `v1.2.1`）；里程碑 `v<major>-M<序号>`，序号不补零。里程碑是工程门禁，不是日期。

**🔴 编号顺位规则（v3.1 事故后新增，务必遵守）**：发布 `vB.A` 时若编号已被占用、被**不可变 Release 保留**或存在针对该编号的限制，**不覆盖/删除/强推旧 Tag**，改用 `vB.(A+1)` 继续递增直到首个可用编号（`v3.1 → v3.2`，`v3.9 → v3.10`），主版本不变。跳号**不新增功能、不改里程碑、不放宽验收、不重建已选定镜像**。

反向约束：**网络/TLS 错误、身份失效、通用权限不足、全仓库规则限制、构建/测试失败都不是"编号不可用"** —— 按原因排查，必要时停下请维护者处理，**禁止用跳号绕过访问控制或无限重试**。

**GHCR 标签语义**：`latest`（可移动稳定别名）· `vX.Y`/`vX.Y.Z`（不可变发布镜像）· `dev`（可移动开发镜像）· `vX-MN`（不可变里程碑检查点）· `sha-xxxxxxxxxxxx`（不可变源码身份）· `@sha256:…`（生产部署锁定）。

**里程碑→版本**：`v1.0`=M1–M6 · `v1.1`=M7–M11 · `v1.2`/`v1.2.1`=v1 收口 · `v2.0`=M1–M3 · `v2.1`=M4/M5 · `v2.2`=M6 · `v2.3`/`v2.3.1`=M7 · `v3.0`=v3-M1（不可移动预览）· `v3.0.1`=v3-M2 预发布修正 · `v3.1`=不可用编号 · **`v3.2`=v3-M2 + 反馈 5（当前基底）**。

---

## 10. 提交与协作规范 / Commit & collaboration rules

> 规范原文：`docs/feedback-5-next-plan.md` §0、`docs/feedback-5-continuous-execution-2026-09-19.md` §6/§7（**均为未提交文件**）。这是维护者对协作方的**硬性要求**。

**语言要求**：开发过程、技术分析可用英文；但**每个 commit 的标题与正文、PR 标题与 description、变更/验收说明必须中英文双语**，两种语言表达**相同**的事实与限制。面向用户的最终结论**以中文为主**并附英文。**不要**为补翻译改写历史、不要强推。

**格式**（Conventional Commits + 双语标题）：

```text
fix(audio): 修复空选轨与输出总线混用 / Fix empty selections and output-bus confusion

中文：<具体问题、改变后的行为>
English: <The same problem and resulting behavior>

验证 / Validation: <实际执行的测试和结果>
限制 / Limitations: <仍待完成的验收>
```

**实际统计（近 400 条）**：`feat` 90、`fix` 76、`docs` 53、`test` 19、`chore` 12、`ci` 7、`refactor` 7、`diag` 4；**231/278 条标题含 ` / ` 双语**；92 条正文含 `验证/Validation`、57 条含 `限制/Limitations`；**无 `Co-authored-by`**；合并提交用 `merge:` 前缀。常用 scope：`composite`、`acceptance`、`audio`、`gateway`、`dev`、`soak`、`release`、`scene`、`web`、`core`。

**提交纪律**：按**主题**分批提交；不改写旧历史；**不自动 push、不自动发布**；**不把无关文件塞进提交**（不要用 `git add -A`，按路径显式添加）；测试证据必须**注明实际被测提交**，旧提交的测试数字不能复制给新 HEAD；每次提交后**继续下一项**。

**持续执行协议（若沿用原协作方式）**：按「取未完成项 → 实现 → 针对性测试 → 修复 → 提交 → 下一项」循环；每约 60 秒给简短进度；同一症状复现两次且无新证据时先补日志/缩小实验，而非盲目重试；不使用全局 `pkill`、不重启整个 WSL/系统来回避诊断；清理只限本次拥有的进程/路由，**原始相机配置与用户场景必须保留**。维护 `docs/feedback-5-progress.md` 检查点。

**允许最终交接的条件（三类，满足其一才停）**：① 全部实现与验收门槛通过且证据可定位；② 独立可完成工作已做完，余项确需当前无法获得的权限/设备/来源/用户决定（须给失败证据、已试过的不同办法、最小所需操作）；③ 用户明确暂停/停止或平台强制终止（保存检查点、如实标记未完成）。**"尚未调查"或"测试耗时长"不属于停止理由。**

---

## 11. 测试与验收体系 / Testing & acceptance

### 11.1 分层与规模

| 层 | 位置 / 命令 | 规模与要求 |
| --- | --- | --- |
| C++ CTest | `core/tests/common_tests.cpp`；`cmake -S . -B build/webobs -DWEBOBS_BUILD_TESTS=ON && cmake --build build/webobs && ctest --test-dir build/webobs --output-on-failure` | 13 组函数、241 条 `expect()`；镜像构建时强制跑（`docker/Dockerfile`） |
| Python unittest | `tests/test_*.py`（11 个）；`python3 -m unittest discover -s tests -p 'test_*.py'` | 114 个测试（camera_registry 26、cluster 28、v2_client_control 24、event 7、node_agent 7、nvr 5、m7_receipts 4、s3 4、detector 3、backup 3、preupgrade 3） |
| 前端 | **无 vitest**（全仓 0 引用），只有 Playwright | `pnpm test:pwa`（2）· `pnpm test:local[:chrome]`（local-runtime 34，含 1 例 soak 默认 skip）· `-c playwright.m7.config.ts`（4） |
| Node 回归 | `node --test tests/test-dev-launcher.mjs tests/test-soak-verdict.mjs tests/test-transcoder*.mjs` | 判定器 19/19、启动器 9/9、转码器 7/7 + 6/6 |

### 11.2 集成/烟测

`tests/compose.smoke.yaml`（19 服务）：夹具 mediamtx（v1.18.2 固定 SHA-256）、RTSP H.264、HEVC、440 Hz/880 Hz AAC、browser-fixture；产品服务 `webobs`(M0 10 s/640×360/10 fps)、`webobs-multi`(M1)、`control`(18080)、`nvr`(18087)、`webrtc`(18081)、`direct`(18082)、`hybrid`(18083)、`browser`(18084)、`audio`(18085)、`auth`(18086)、`tls-turn`(18443)、`real-control`；validator `probe-recording` 校验 H.264/AAC/分辨率/时长/非黑场/黑边对称。

跑法：`./tests/run-smoke.ps1 [-SkipBuild]` 或 `WEBOBS_SKIP_BUILD=1 ./tests/run-smoke.sh`。链路：public-audit → webobs→validator → multi→validator → run-contracts（退出码/凭据脱敏/SIGTERM 封装）→ control-plane → webrtc → direct → hybrid → m3-lifecycle。首次含 OBS 镜像构建最久；`-SkipBuild` 约十分钟级。

### 11.3 真机与专项门禁

| 脚本 | 验收内容 | 需要真机？ |
| --- | --- | --- |
| `run-real-camera.ps1/.sh` | M0 真实 RTSP → MP4 | 是（`WEBOBS_REAL_USE_SYNTHETIC=1` 可替代） |
| `run-m1-real-camera.ps1/.sh` | M1 事务控制面 + 双画面（`tests/rtsp-fixture/m1-real-control.sh` 断言 API） | 是（`-UseSyntheticFixture` 可离线） |
| `run-m2-real-camera.ps1` | M2 Composite；`-PlaybackMode direct`→M3 Direct；`-RequireAudio`→M5 音频 | 是（需 Chrome，`WEBOBS_CHROME_BIN`） |
| `run-m3-lifecycle.ps1`、`run-m5-audio.ps1` | 实时改动/重连；合成双音轨 CDP 验证 | 否 |
| `run-m6-auth/backup/tls-turn/upgrade.ps1` | 认证会话、加密备份、TLS+TURN（自签 `monitor.test:18443`）、升级回滚 | 否（需 pwsh7 + curl.exe） |
| `run-m7-studio.ps1`、`run-m8-nvr.ps1`、`run-m9-timeline.ps1` | Studio/schema/Cut-Fade；NVR 分段；时间线归档 | 否（需 pwsh7） |
| `run-m10-real-mjpeg.ps1/.sh` | 私有 MJPEG 五帧解码、禁内嵌凭据、输出重删 | 是（`WEBOBS_REAL_MJPEG_URL`） |
| 合成组：`run-control-plane`、`run-browser-source`、`run-webrtc`、`run-direct`、`run-hybrid`、`run-v2-true-direct` | 各模式确定性回归 | 否 |

### 11.4 长稳（soak）与判定器

- `tests/soak-evidence.mjs`：服务端采样器（`--minutes 30 --interval 60`），读 MediaMTX `/v3/paths/list` + `/api/v1/program/status` + `/sources/status`，写 `meta.json`（revision/dirty/scene sha256/renderer/encoder）、`samples.jsonl`、`summary.json/.md`。
- `tests/soak-verdict.mjs`：纯函数判定。**阈值**：首帧 20000 ms、已就绪路由重开 8000 ms、停顿 3000 ms、解码帧率比 0.9、正式窗口 1800 s。状态 `PASS/FAIL/INCOMPLETE/SMOKE_PASS/SMOKE_FAIL`。
- **13 项判据**（Composite；Direct 无 program 项 = 12）：expected-sources、targets-defined、sampling-before-action、mode-switch、continuous-observation、duration、media-time、first-frame、frame-stall、decoded-frame-rate、presented-smoothness（非阻塞）、counter-integrity（非阻塞）、program-and-inputs（仅 composite）。
- **SMOKE_PASS ≠ PASS**：时长 < 1800 s 或 `WEBOBS_SOAK_SMOKE=1` ⇒ 永远只能 SMOKE_PASS；观测不完整（`complete!==true` / `earlyTeardown` / 未写最终快照）⇒ INCOMPLETE。`tests/test-soak-verdict.mjs` 19/19 锁死这些反例。
- **excused window**：`WEBOBS_SOAK_EXCUSED_WINDOWS='[{"id":"camera-x","fromMs":F,"toMs":T}]'`；仅当停顿区间**完整落在窗内**才豁免，窗外仍按 3 s 判（故障注入专用）。
- `tests/soak-derive.mjs`：从证据重算，缺字段进 `unverifiableChecks`（不判过），不覆盖原始证据。
- **证据目录**（`/tests/artifacts/*` 全部 gitignore）：`soak/<ISO>-<label>-<短commit>/{meta.json,samples.jsonl,summary.json,summary.md}`；`browser-soak/<ISO>-<mode>/{browser-soak.json,.md,browser-soak-timeline.json,.jsonl,derived-*.json,.md}`；`audio-regression/{case1-3.wav,result.json}`。

### 11.5 平台门禁与收据（receipt）

- 目录 `build/private-gates/`（`/build/` 已忽略，收据不公开）。
- 契约与文件：`windows.json`、`linux-wsl2-chromium.json` = `webobs-local-gate-receipt-v2`；`v3-m1-{windows,linux,regression}.json`；`v3-m2-{windows,linux,model,regression}.json`；`m7-scale-{8,16,32}.json`、`m7-faults.json`、`windows-m7-admin.json` = `webobs-m7-gate-receipt-v1`。
- 校验强度：逐文件**非符号链接、≤64 KB、UTF-8 JSON、字段集合精确相等**、contract/name/platform/kind 匹配、`revision == git rev-parse HEAD`、checks **集合与数量**精确相等（防重复）、`completedAt` 带时区且 **48 h 内**（不得超前 5 分钟）；m7 另校 `cameraCount` 与时长下限（≥900 s）。
- 生成：`scripts/run-private-pwa-gate.py`、`run-private-v3-gate.py`（调用**检出目录之外**的私有 harness，只接受 `WEBOBS_PRIVATE_GATE_RESULT` 的精确检查集合并全为 true，随后丢弃原始日志/端点/录像）；m7 由 `tests/m7/verify-scale.py --write-receipt`、`tests/m7/write-windows-receipt.py` 写。
- 校验器：`scripts/verify-local-gate-receipts.py`、`verify-v3-m1-gate-receipts.py`、`verify-v3-m2-gate-receipts.py`、`verify-m7-gate-receipts.py`；策略本身在 CI 有回归测试（`clients/tests/test_local_gate_receipts.py`、`test_release_workflow_policy.py`）。
- **分工**：GitHub-hosted Actions 只做公开、无 Secret 的审计/typecheck/build；私有平台门禁与 OCI 发布在维护者 Windows + WSL2 本机交互执行。**不得伪造同 revision 回执。**

### 11.6 命令清单

**新开发者最小路径（无相机）**

```bash
./tests/run-public-audit.sh
python3 -m unittest discover -s tests -p 'test_*.py'
node --test tests/test-dev-launcher.mjs tests/test-soak-verdict.mjs tests/test-transcoder*.mjs
cd web && pnpm install --frozen-lockfile && pnpm typecheck && pnpm test:iwa && pnpm build && pnpm test:local && pnpm test:pwa && cd ..
WEBOBS_SKIP_BUILD=1 ./tests/run-smoke.sh
```

**发布前完整路径**

```powershell
.\scripts\test-web-runtime-windows.ps1                      # 基线
.\scripts\test-web-runtime-windows.ps1 -ReleaseGate -PrivateGateCommand C:\webobs-gates\run-gate.cmd
.\scripts\test-web-runtime-windows.ps1 -V3Milestone v3-M2 -PrivateV3GateCommand $env:WEBOBS_PRIVATE_V3_GATE_COMMAND
python scripts\verify-local-gate-receipts.py
.\scripts\release-image-local.ps1 -Image ghcr.io/<owner>/web-camera-monitor-wall -Version v3.2
```

```bash
./scripts/test-web-runtime-wsl2.sh --release-gate --private-gate-command /opt/webobs-gates/run-gate.sh
./scripts/test-web-runtime-wsl2.sh --v3-milestone v3-M2 --private-v3-gate-command "$WEBOBS_PRIVATE_V3_GATE_COMMAND"
node tests/soak-evidence.mjs --label composite-1080p --mode composite --target-fps 30 --minutes 30
```

差异：`*.sh` 门禁要求 Git 索引 `100755` 位；m6/m7/m8/m9 的 PowerShell 门禁需 pwsh7 + Git Bash；CTest 在 Linux/WSL2 原生，Windows 走 `dev-native.py` 或容器 `core-builder`。

### 11.7 测试侧已知缺口

1. 「零来源重启」判据无最终结论（Composite 30 分钟仅剩此项，源于两路不稳定真实相机）。
2. `soak-evidence.mjs` 在 Direct/Hybrid 下 `visible=0`，三条 engine 检查 `detail` 为 not applicable 但 `passed` 仍 false ⇒ 服务端 summary 恒 FAIL，仅可参考；`browserMeasured:false`，浏览器帧率/首帧需手工合并，**两套证据没有单一发布判据**。
3. 早期长稳缺 final/间隔/代次字段，按新判定器只能派生成 INCOMPLETE。
4. 摄像机兼容 Tier C（厂商矩阵）无自动化；Tier B 仅 2026-08-24 一次 Canon WV-HTTP 记录；`run-m10-real-mjpeg` 每次需人工提供私有 URL。
5. `build/private-gates/` 收据无法在仓库内产生，CI 不校验收据，v3-M1/M2/m7 发布门禁依赖维护者本机。
6. `tests/test-immutable-release-assets.sh`、`verify-video-shift.sh`、`audio-regression.mjs`、M7 8/16/32×900 s 与故障注入仅手工/ `-Long` 运行，无 CI 触发；`clients/tests` 设备门禁未纳入 `test-local-full.ps1`。
7. `browser-soak.spec.ts` 默认 skip（需 `WEBOBS_SOAK=1`），不在任何例行套件内。

---

## 12. 发布流程 / Release procedure

> 权威：`docs/versioning-and-branches.md`、`docs/local-platform-gates.md`、`docs/docker-deployment.md`、`docs/ghcr.md`、`docs/manual-ghcr-release.md`。
> 脚本：`scripts/release-image-local.sh`（权威实现）/ `.ps1`（Windows 包装，需 Git for Windows `bash.exe`）。

**前置**：干净工作树 → `scripts/check-executable-bits.sh` → `tests/run-public-audit.sh` → **收据校验**（Windows + WSL2 两份、精确绑定当前提交、**48 h 内**）→ 按版本追加 `verify-v3-m2`/`verify-v3-m1`/`verify-m7`。环境变量 `GITHUB_REPOSITORY` 与 `GH_TOKEN`（classic PAT，需 `write:packages`）。

**正式版步骤**（`release-image-local.sh`）：

1. 参数校验（镜像必须 `^ghcr\.io/…` 小写；版本 `dev|vX.Y|vX.Y.Z`；第三参数只能 `--prerelease`）。
2. **必须从 `main` 运行**；远端已有同名 Tag 且不指向 HEAD → **拒绝覆盖**。
3. 公开审计 + 收据校验。
4. `docker buildx build --platform linux/amd64`，注入 `WEBOBS_BUILD_VERSION`/`WEBOBS_BUILD_MILESTONE` 与 `org.opencontainers.image.revision`/`.version`，`--provenance=mode=max --sbom=true`，推 `sha-<12位>`；`imagetools inspect` 取并校验 digest。
5. `create-source-bundle.sh` 生成 **`webobs-source-<version>.tar.gz` + `.sha256`**：校验 OBS submodule pin、递归 submodule 完整、确定性 tar（`--sort=name --mtime=@epoch --owner=0 --group=0 --numeric-owner` + `gzip -n`）、写 `SOURCE-REVISION`，拒绝 `.git/.env/secrets`；再由 `verify-source-bundle.sh` 校验。
6. 创建/复用 **Draft Release**（tag 名先用 `release-draft-<版本去v>-<sha12>`），用 `upload-release-assets-immutable.sh` **幂等**上传附件（同名同内容通过，同名异内容失败；Draft 资产必须走 `uploads.github.com`）。
7. 附件核验通过后创建并推送**不可变 annotated Tag**，Draft 的 `tag_name` 切到正式 Tag，尽力删除临时 `release-draft-*`。
8. `draft=false` → 9. `imagetools create --tag <image>:vX.Y --tag <image>:latest <image>@<digest>`，**逐标签复验 digest** → 10. `make_latest=true`。

**预览版（`--prerelease`）**：仅允许 `v3.0`/`v3.0.1`；**必须从 `dev` 运行且 HEAD 精确等于 `origin/dev`**；跳过私有收据但保留公开审计；只提升版本与 `sha-*`，**绝不移动 `latest`**。

**🔴 不可变 Release 的硬约束（v3.1 事故根因）**：GitHub Immutable Releases 一旦发布，Release 不可改（含 `tag_name`），且**被不可变 Release 用过的 Tag 名会被保留、无法重新创建**（`GH013 Cannot create ref due to creations being restricted`，连管理员 push 也可能被拒）。另外**已发布的不可变 Release 无法再上传附件**（`422 Cannot upload assets to an immutable release`）。因此：

- **必须先把附件挂到 Draft，再发布**（脚本顺序正是如此，不要颠倒）；
- **不要删除已发布的不可变 Release 去"重做"**——那会永久烧掉该 Tag 名（v3.1 就是这样丢失的）；
- 编号不可用时按 §9 **顺位递增**，并按脚本幂等语义复用同一 digest，**不重建镜像**；
- 复用原镜像时，必须在 Release 说明中披露**未改变的内嵌构建标识**。

**🔴 发布脚本尚未支持 `v3.2`（动手前必须改）**：`scripts/release-image-local.sh` 中

- 收据分支只有 `^v2\.3`、`^v3\.0`、`^v3\.1`（第 44–55 行）→ **`v3.2` 不匹配任何一个，会跳过 v3-M2 收据校验**；
- milestone 映射同样只有 `^v3\.1` → `v3-M2`（第 118–129 行）→ **`v3.2` 落到 `else` 被标成 `v2-M3`**；
- `--prerelease` 仍限 `v3.0`/`v3.0.1`。

**本次 v3.2 是"原镜像提升"而非脚本构建**，所以没有触发这两个缺陷。**下一个用脚本构建的 v3.2+ 版本必须先扩展这些正则（如 `^v3\.[12](\.|$)`）。**

**GHCR/凭据要点**：PAT classic 需 `write:packages`；新 package 默认 private 需手工改 public；package 未关联仓库时 Actions 无推送权；构建参数会进入镜像历史与 **public provenance**，**禁止**把相机地址/凭据放进 build arg 或提交 `.env`。

**部署侧凭据（明文）**：`WEBOBS_AUTH_USERNAME_FILE`/`PASSWORD_FILE` 指向**明文文件**（Compose `secrets: file:` 不加密），用户名 1–64 B、密码 16–256 B、文件**结尾只能有一个换行**，**只在进程启动时读一次** → 改完必须重启/重建容器；**改密码不会踢掉已登录会话**（需删除 `/config/webobs/auth-sessions.db*`）；失败锁定默认 5 次/60 s（429）。

---

## 13. 路线图与里程碑状态 / Roadmap status

**当前**：v3.2 为最新正式基底，后续开发**以 v3.2 为基底**，**本轮不启动下一版本**；已披露的长测例外与已知限制**不因本次发布关闭**。

| 里程碑 | 名称 | 状态 |
| --- | --- | --- |
| M0 | Headless Proof | ✅ 2026-08-11（真机门禁通过） |
| v1-M1…M6 | Web Control / Composite WebRTC / Gateway Direct & Hybrid / Browser Sources / Audio / Production | ✅（`v1.0`） |
| v1-M7…M11 | Canvas Studio / NVR Core / Timeline & Evidence / Device Operations / Events & Detection | ✅ 实现完成（`v1.1`；`v1.2`/`v1.2.1` 收口） |
| v2-M1…M3 | True Direct Foundation / Local-first PWA / Browser Media Runtime | ✅（`v2.0`/`v2.0.1`） |
| v2-M4/M5 | Offline Sync / Monitor Layout & Telemetry | ✅（`v2.1`） |
| v2-M6 | Operations Workspace | ✅（`v2.2`） |
| v2-M7 | Scale, Ecosystem & Resilience | ✅（`v2.3`/`v2.3.1`） |
| v3-M1 | 运动与大范围画面变化分析 | 预览载体 `v3.0`（不可移动） |
| v3-M2 | 监控工作区、遥测/音频叠层、旧来源迁移、反馈 5 | **v3.2 当前正式基底** |
| v3 后续 | 人物框等分析能力 | 🚧 未发布：Windows/WSL2 私有门禁须绑定同一提交，发布候选需重跑 v1–v2.3 回归 + 公开审计 + dev→main |

**未关闭项（按优先级）**

1. **`back_3` 冷启动首帧 23,945 ms > 20,000 ms**（真实五路 8/9）。已排除：判定器（20/20）、控制面串行激活、网关直通（151 帧/15 s ≈ 10.07 fps ≈ 直连 10.05）、x264 slice-thread、浏览器解码（720p25=25.00、1080p30=30.13 fps）、软件链路整体上限（受控五路 12/12，首帧 6.3–6.7 s）。**已确立**缺口在相机→网关上游；**未确立**上行带宽/丢包、相机编码负载、冷启动三者谁为主。候选方案 A 提高码率上限 / B 降分辨率或子码流 / C 链路排查 / D 转码缩放（产品变更）/ E 单路放宽预算（须显式记录）/ F 记为已知限制（推荐顺序 C→A→B→D）。**决定人：设备/网络现场/产品/验收负责人**；设备改动后须重测 9/9 并重跑 Composite 13/13。复现：`bash build/scratch/real-source-measure.sh 20`、`real-hybrid-e2e.sh`、五路 1800 s Playwright、`node --test tests/test-soak-verdict.mjs`。
2. **`front_3` 14.80 fps**、`back_3` 单读者 10.05 fps（标称 20，2960×1666），伴随 `Could not find ref with POC`。**20 s 冷启动单读者探测不是相机能力上限**（应用持续拉流时 back_3 达 19.96 fps）。
3. **Docker/vGPU 与跨设备音视频组合未验收**（按用户已确认范围留待后续）。
4. **NVENC/VA-API 路径未认证**：WSL D3D12 OpenGL 下 obs-nvenc 无法共享 CUDA 纹理（`CUDA_ERROR_OPERATING_SYSTEM`），五路 1080p NVENC 24.5 fps vs x264 29.7 fps，启动器默认 x264。
5. **"零来源重启"判据未过**：Composite 30 分钟全场 4 次重启（两路已知不稳定真实相机）。
6. **`/activate` 约 2.57 s/路串行**（单 io_context + 全局路由锁），来源慢时放大首帧。
7. 非阻塞开放项：v1-M8 六小时夹具耐久 + 24 h 私有 burn-in；v1-M10 多厂商兼容；v1-M11 真实相机事件准确度；真实相机多音轨未实测。

**范围与排除**：承诺范围是逐路连续录像、保留、时间线、ONVIF 设备运维、事件、有界检测 Provider、本地真直连端、值守体验、取证导出（位于 libobs 合成图**旁侧而非内部**）。**不做**：托管多租户 SaaS、厂商 P2P 云凭据代理、门禁/开门控制、生物身份数据库、无限摄像机密度承诺；普通 PWA **不解码 RTSP**。

---

## 14. 已知问题、陷阱与待决项 / Known issues, traps, open items

**产品/验收层**

1. `back_3` 首帧超预算——**唯一未通过判据**；不得据此宣称真实五路全达标。
2. GPU/Docker 路径未认证（§13-3/4）。
3. **长测豁免不继承**：v3.2 的免长测是**一次性用户授权**，不改变后续版本默认门禁；**不得伪造同 SHA 长测回执**。

**代码/文档不一致（交接必须处理）**

4. **发布脚本不认识 `v3.2`**（§12）：会跳过 v3-M2 收据校验并把 milestone 标成 `v2-M3`。**下一个脚本构建的 v3.2+ 必须先改正则。**
5. **开放注册未实现，但开关与文档都在**：`compose.dev.yaml` 与 `scripts/dev-native.py` 设置 `WEBOBS_REGISTRATION_ENABLED=true`，`docs/development.md` §5 声称"登录页支持开放注册"——但**全仓库没有任何代码读取该变量**（`core/src` 0 命中），`/api/v1/auth/options` 与 `/api/v1/auth/register` **只存在于未提交的 Playwright 规格** `web/tests/local-runtime/login-gate.spec.ts`（用 `page.route` mock 后端），`web/src` 无注册 UI。**当前只有 login / session / logout 三个端点。**
6. **Scene schema 文档滞后**：实现 current=**6**（`audioInputs` 取代单 `audioTrack`，legacy=5），文档仍以 v5 为当前契约；按文档写死 5 会失败。
7. **IndexedDB 文档滞后**：文档写 5 个 store，代码已是 7 个（+syncQueue/syncState，DB version 2）。
8. **`dev` 有 3 个提交未推送**（反馈6、局域网联调、投影窗口修复），`main` 仍停在 v3.2 发布提交 `fc6fe71`；推送与是否合入 `main` 需维护者决定（见 §3/§10）。

**工程陷阱**

9. **Windows CRLF 与 WSL git 不一致**：`.gitattributes` 为 `* text=auto`，`*.sh`/`*.py`/`Dockerfile` 强制 `eol=lf`。用**未配 `core.autocrlf=true`** 的 WSL git 跑 `create-source-bundle.sh` 会在「工作树必须干净」处**静默失败**（`git diff --quiet` 返回 1 + `set -e`），表现为退出码 1 且**无任何错误输出**。解决：用 Git for Windows bash（脚本支持 Cygwin 路径归一），或给 WSL git 显式设 `core.autocrlf=true`。**历史教训**：v1.2 曾因两个 Python 文件在 Windows 工作树为 CRLF，Linux 读 shebang 为 `python3\r`，容器烟测 Camera Registry 起不来，只能补发 **v1.2.1**。
10. **Docker CLI 的环境依赖**：`docker buildx` 需要可写的 `$DOCKER_CONFIG/buildx`（默认 `~/.docker/buildx`，其 `.lock` 不可写时报 `Access is denied`）；可用 `BUILDX_CONFIG` 指向工作区内目录绕过。`docker run/ps` 需要守护进程命名管道，受限环境报 `permission denied … npipe`。
11. **`git push` 在受限环境会因凭据助手失败**（MSYS `sh.exe` 无法创建信号管道 → `could not read Username`）：可改用 API 建 Tag/Ref，或配 `http.extraheader` + `credential.helper=`。
12. **执行位容易丢**：`check-executable-bits.sh` 与 `run-public-audit.sh` 要求一批 `.sh`/`.py` 在 Git index 中为 `100755`。
13. **不要用 `Get-Content` 读中文文档**（Windows PowerShell 默认 ANSI 会乱码），用 `-Encoding UTF8`。
14. **`secrets/` 是明文**：`chown` 部署用户、`chmod 600`、目录 `700`；SELinux 用 `:Z` 并在替换文件后 `restorecon`。构建参数会进镜像历史与公开 provenance，**绝不能**出现密码或 RTSP URL。
15. **不要把真实 RTSP URL、录像、私有门禁原始输出放进仓库或公开 Issue**；`gate/` 必须先复制到检出目录之外。
16. **`docker compose down --volumes` 会清空本地 Registry/Scene/Session**；原生数据与容器数据卷互不迁移。

**待决（需维护者/用户决定）**

17. `back_3`/`front_3` 的设备侧调整（报告列了选项，**未经确认不得改相机/NVR**）。
18. 是否补齐开放注册（§14-5）、是否把 §3 待推送的 3 个提交推送到 `origin/dev` 或合入 `main`、是否启动 v3-M2 之后的下一版本。
19. v3.1 被保留的 Tag 名是否请 GitHub Support 清理（当前以 v3.2 顺位规避）。
20. 是否把 `v3.2` 支持补进发布脚本与收据校验器（**建议在任何下一次发布前完成**）。
21. 是否补齐"Direct/Hybrid 下服务端 summary 恒 FAIL、浏览器证据需手工合并"的单一发布判据（§11.7-2）。

---

## 15. 附录 / Appendix

**命令速查**

| 目的 | 命令 |
| --- | --- |
| 启动原生开发 | `./scripts/dev.ps1` / `bash scripts/dev.sh` |
| 环境检查 / 帮助 | `dev.ps1 -Check` / `dev.ps1 -Help`（`dev.sh --check` / `--help`） |
| 停止会话 | `./scripts/stop-dev.ps1` / `bash scripts/stop-dev.sh` |
| 启动器回归 | `node --test tests/test-dev-launcher.mjs` |
| 公开审计 | `./tests/run-public-audit.sh` / `.ps1` |
| 执行位检查 | `./scripts/check-executable-bits.sh` |
| Python 单测 | `python3 -m unittest discover -s tests -p 'test_*.py'` |
| CTest | `cmake -S . -B build/webobs -DWEBOBS_BUILD_TESTS=ON && cmake --build build/webobs && ctest --test-dir build/webobs --output-on-failure` |
| 确定性烟测 | `./tests/run-smoke.ps1 -SkipBuild` / `WEBOBS_SKIP_BUILD=1 ./tests/run-smoke.sh` |
| 真机录制验收 | `./tests/run-real-camera.ps1` |
| 前端构建+本地测试 | `cd web && corepack pnpm build && corepack pnpm test:local` |
| 长稳采样 | `node tests/soak-evidence.mjs --label composite-1080p --mode composite --target-fps 30 --minutes 30` |
| 收据校验 | `python scripts/verify-local-gate-receipts.py` |
| 正式发布 | `.\scripts\release-image-local.ps1 -Image ghcr.io/<owner>/web-camera-monitor-wall -Version vX.Y` |
| 镜像个体验证 | `scripts/verify-image.ps1` |
| 对应源码包 | `bash scripts/create-source-bundle.sh vX.Y <abs-out-dir>` |
| 完整镜像 | `docker build -f docker/Dockerfile -t webobs:review .` |

**术语表**：`Direct`=网关直通（经 MediaMTX，非真直连）· `Hybrid`=不兼容轨按需 FFmpeg 转码 · `Composite`=服务端 libobs 合成 · `Program`=合成后的节目输出 · `True Direct`=受信 HTTPS PWA 直连获批 WHEP/HLS/MJPEG 端点（v2 正式路径）· `receipt/收据`=绑定 revision 的脱敏门禁回执（48 h 有效）· `soak`=长稳测试 · `milestone`=工程门禁（非发布日期）· `excused window`=故障注入豁免窗（须完整覆盖停顿区间）· `SMOKE_PASS`=短时/降规格通过与 `PASS` 严格区分。

**关键文件索引**

| 主题 | 文件 |
| --- | --- |
| 版本/分支/标签 | `docs/versioning-and-branches.md` |
| 本地开发 | `docs/development.md`（未提交）、`docs/local-dev.md` |
| 部署 | `docs/docker-deployment.md`、`deploy/README-podman.md` |
| 门禁/收据 | `docs/local-platform-gates.md` |
| API | `docs/api-v1.md`、`docs/api-v2.md` |
| 场景 | `docs/scene-schema-v1..v5.md`（实现已 v6） |
| 介质/真直连/PWA | `docs/true-direct-v2.md`、`docs/local-first-pwa.md`、`docs/monitor-view-and-analytics.md` |
| NVR/时间线/事件 | `docs/nvr-core.md`、`docs/timeline-evidence.md`、`docs/events-and-automation.md` |
| 设备/ONVIF | `docs/onvif-media.md`、`docs/camera-compatibility-qualification.md` |
| 安全 | `SECURITY.md`、`docs/api-v1.md` §Security boundary |
| 发布 | `docs/ghcr.md`、`docs/manual-ghcr-release.md`、`scripts/release-image-local.sh` |
| 进度/协作协议 | `ROADMAP.md`、`docs/feedback-5-*.md`（部分未提交） |
