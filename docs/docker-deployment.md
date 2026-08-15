# Docker 源码构建与部署指南

本文面向从 Git 仓库克隆代码、在部署主机自行构建产品镜像的操作者。命令均在仓库根目录执行。

> 当前项目已完成 M0–M5，正在开发 M6 Production。文件认证、限流、健康检查、指标、审计日志、来源自动恢复、硬件编码安全回退、校验备份恢复，以及单镜像受信 HTTPS/TURN 部署已经具备；镜像来源证明和自动升级回滚仍未完成。基础 HTTP 模式只能用于主机回环，远程部署必须使用本指南的 production 覆盖。

## 1. 部署组成与数据边界

产品部署只有一个 `webobs` 容器。容器内包含 `webobsd`、libobs、MediaMTX、固定版本 Caddy、Web 编辑器、Xvfb 和 Mesa 软件渲染环境。

| 内容 | 默认位置 | 持久性 |
| --- | --- | --- |
| 产品镜像 | `webobs:m0` | Docker 镜像存储 |
| 场景配置 | Docker volume `webobs-config` 中的 `/config/webobs/scene.json` | `docker compose down` 后保留 |
| 录像 | 主机仓库的 `recordings/` 映射到 `/recordings` | 主机文件 |
| 私有运行配置 | 主机 `.env` | Git 忽略，必须限制访问 |
| Basic 认证凭据 | 主机 `secrets/` 下的两个文件 | Git 忽略，通过 Compose secrets 只读挂载 |
| TLS 证书/私钥与 TURN 凭据 | 主机 `secrets/` 下的四个文件 | Git 忽略，通过 Compose secrets 只读挂载 |
| Docker 日志 | `json-file`，默认 `10m × 3` | 由 Docker 轮转 |

`docker compose down --volumes` 会删除场景卷，不能作为普通停机命令使用。录像位于主机目录，不会随卷删除，但仍应单独备份。

## 2. 前置条件

支持的产品平台目前只有 `linux/amd64`（x86_64）。ARM64、Windows containers 和 macOS 原生容器不是当前构建目标。

编码默认值为 `WEBOBS_VIDEO_ENCODER=auto`。无 GPU 设备时自动使用 x264；不要为了消除软件编码日志而给容器 `--privileged`。Linux 主机若存在支持 H.264 编码的 VAAPI render node，可在 `.env` 中设置 `WEBOBS_VAAPI_DEVICE=/dev/dri/renderD128`，然后显式加入设备覆盖：

```bash
docker compose -f compose.yaml -f compose.m6-vaapi.yaml up -d --build
```

程序同时要求设备节点可访问且 OBS 编码器已注册，初始化失败仍会回退 x264。可通过受认证的 `/api/v1/system/capabilities` 或 `webobs_video_encoder_selected`、`webobs_video_encoder_fallback`、`webobs_video_encoder_available` 指标确认结果。当前镜像构建了 x264 与 VAAPI；QSV/NVENC 探测结果用于明确报告不支持状态，不会把设备存在误报为可用编码器。Docker Desktop/WSL2 是否能传递 GPU 取决于宿主配置，未挂载 render node 时按软件基线验收。

- Git，能够递归拉取 submodule。
- Docker Engine 和 Docker Compose v2，或启用 WSL2/Linux containers 的 Docker Desktop。
- 构建期间可访问 Ubuntu、GitHub、OBS/CEF 下载源以及 Docker 基础镜像源。
- 建议至少 8 GB 可用内存、20 GB 可用磁盘。首次构建明显慢于缓存构建。
- 部署主机能够访问摄像头；浏览器能够访问部署主机发布的 HTTP 和 WebRTC UDP 端口。

开始前检查：

```bash
git --version
docker version
docker compose version
docker info --format '{{.OSType}}/{{.Architecture}}'
```

最后一条应返回类似 `linux/x86_64`。Docker Desktop 用户还应确认当前处于 Linux containers 模式。

## 3. 克隆并验证固定依赖

必须递归克隆，OBS 自身还包含构建所需的 submodule：

```bash
git clone --recurse-submodules https://github.com/LiaoYK001/Web-Camera-Monitor-Wall.git
cd Web-Camera-Monitor-Wall
git submodule update --init --recursive
```

已有工作副本更新后执行：

```bash
git pull --ff-only
git submodule sync --recursive
git submodule update --init --recursive
```

验证仓库状态和 OBS 固定提交：

```bash
git status --short
git -C obs/obs-studio rev-parse HEAD
```

第二条必须输出：

```text
fb4d98bf88fae5fc85cb11fc57f7c5e309282194
```

生产或长期运行环境还应记录根仓库提交，不要只记录分支名：

```bash
git rev-parse HEAD
```

## 4. 创建私有配置

### 4.1 复制环境文件

PowerShell：

```powershell
Copy-Item .env.example .env
notepad .env
```

Linux shell：

```bash
cp .env.example .env
chmod 600 .env
${EDITOR:-vi} .env
```

至少把 `WEBOBS_RTSP_URL` 改为完整的私有摄像头地址。真实地址、账号、密码和查询令牌只能保存在本机 `.env`，不得写入 Compose、文档、提交、Issue 或公开日志附件。

| 变量 | 建议 |
| --- | --- |
| `WEBOBS_RTSP_URL` | 首次场景引导使用的私有 RTSP URL |
| `WEBOBS_BIND_ADDRESS` | 本机部署保持 `127.0.0.1` |
| `WEBOBS_HTTP_PORT` | 默认 `8080`，冲突时换未占用端口 |
| `WEBOBS_WEBRTC_ADDITIONAL_HOSTS` | 本机使用 `127.0.0.1`；受信代理部署时填写浏览器可达地址 |
| `WEBOBS_WEBRTC_UDP_PORT` | 默认 `8189/udp` |
| `WEBOBS_OUTPUT` | 留空时按 UTC 时间生成录像名 |
| `WEBOBS_DURATION_SECONDS` | `0` 表示持续运行，直至 SIGTERM/Ctrl+C |
| `WEBOBS_WIDTH` / `HEIGHT` / `FPS` | 按 CPU 预算调整；默认 1920×1080@30 |
| `WEBOBS_BITRATE_KBPS` | 默认 6000 Kbps |
| `WEBOBS_RTSP_TRANSPORT` | 默认 `tcp`，只有明确需要时才改 `udp` |
| `WEBOBS_LOG_MAX_SIZE` / `FILES` | 保持有限值，默认三份、每份 10 MiB |

### 4.2 理解首次场景引导

`WEBOBS_RTSP_URL` 只在 `/config/webobs/scene.json` 不存在时创建第一路来源。场景写入 `webobs-config` 卷后，后续启动以持久化场景为准；修改 `.env` 中的 URL 不会自动替换已有场景。

后续改地址应优先通过 Web 编辑器保存。若需要手工编辑，应先停止容器、备份场景，再修改卷中的文件。删除整个 volume 会同时删除所有持久化场景。

### 4.3 可选：创建文件型认证凭据

即使只绑定主机回环地址，长期运行也建议启用认证覆盖。用户名为 1–64 个可打印 ASCII 字符且不能含冒号；密码为 16–256 字节且不能含控制字符。

PowerShell（密码通过系统凭据对话框输入，不进入命令历史）：

```powershell
New-Item -ItemType Directory -Force secrets | Out-Null
Set-Content -NoNewline secrets/webobs-auth-username.txt 'operator'
$credential = Get-Credential -UserName 'operator' -Message '输入至少 16 字节的 WebOBS 密码'
[IO.File]::WriteAllText(
    (Join-Path (Resolve-Path secrets) 'webobs-auth-password.txt'),
    $credential.GetNetworkCredential().Password)
Remove-Variable credential
```

Linux shell：

```bash
umask 077
mkdir -p secrets
printf '%s' 'operator' > secrets/webobs-auth-username.txt
read -rsp 'WebOBS password (16-256 bytes): ' WEBOBS_LOCAL_PASSWORD
printf '%s' "$WEBOBS_LOCAL_PASSWORD" > secrets/webobs-auth-password.txt
unset WEBOBS_LOCAL_PASSWORD
chmod 600 secrets/webobs-auth-username.txt secrets/webobs-auth-password.txt
```

在 `.env` 中取消下面两项的注释：

```dotenv
WEBOBS_AUTH_USERNAME_SOURCE=./secrets/webobs-auth-username.txt
WEBOBS_AUTH_PASSWORD_SOURCE=./secrets/webobs-auth-password.txt
```

不要把明文密码直接放入 `.env`；覆盖文件只接受文件路径。

## 5. 从源码构建镜像

先解析 Compose，`--quiet` 可避免把展开后的环境值打印到终端或 CI 日志：

```bash
docker compose --env-file .env -f compose.yaml config --quiet
```

构建产品服务：

```bash
docker compose --env-file .env -f compose.yaml build --pull webobs
```

构建会完成固定版本前端、MediaMTX、libdatachannel、CEF、OBS 32.1.2 和 `webobsd`，并在构建容器内执行 CTest、版本检查、动态库闭包和日志脱敏探针。最终镜像默认名为 `webobs:m0`。

检查镜像：

```bash
docker image inspect webobs:m0 --format '{{.Id}} {{.Os}}/{{.Architecture}}'
docker run --rm --entrypoint /opt/obs/bin/webobsd webobs:m0 --version
```

不要把 RTSP URL、密码或令牌作为 Docker build argument。构建参数可能出现在镜像历史、缓存或 provenance 中；摄像头配置只属于运行时配置。

## 6. 启动方式

### 6.1 本机回环模式

```bash
docker compose --env-file .env -f compose.yaml up -d --no-build webobs
docker compose --env-file .env -f compose.yaml ps
```

本机打开 `http://127.0.0.1:8080/`。基础 Compose 为本地开发兼容模式：容器内监听所有接口，但主机默认只发布到 `127.0.0.1`，且不启用认证。不要把 `WEBOBS_BIND_ADDRESS` 改为 `0.0.0.0` 后直接暴露此模式。

### 6.2 文件认证覆盖

Linux shell：

```bash
docker compose --env-file .env \
  -f compose.yaml \
  -f compose.m6-auth.yaml \
  up -d --no-build webobs
```

PowerShell：

```powershell
docker compose --env-file .env -f compose.yaml -f compose.m6-auth.yaml up -d --no-build webobs
```

认证覆盖会关闭无认证远程许可，并通过 `/run/secrets` 挂载凭据。除 `/api/v1/health` 和 `/api/v1/ready` 外，UI、REST、WebSocket、WHEP 和 `/metrics` 均要求 Basic 认证。

Basic 认证本身不加密连接。该覆盖只适用于主机回环；远程部署使用下一节的受信 HTTPS/TURN 覆盖。

### 6.3 受信 HTTPS 与 TURN 生产覆盖

`compose.m6-production.yaml` 仍只运行一个产品容器：固定为 Caddy `2.11.4` 的网关在容器内终止 TLS，`webobsd` 强制监听 `127.0.0.1`，Compose 只发布 HTTPS 和 WebRTC ICE 端口。Caddy 不自动申请证书；请使用 ACME 客户端或组织 PKI 在主机取得包含完整证书链的 PEM 文件，并把私钥权限限制为管理员可读。

TURN 是独立的生产依赖，不打包进产品容器。建议使用 Coturn 的 `use-auth-secret`/短期凭据模式，并优先提供 TCP 监听。创建以下受 Git 忽略的文件：

```text
secrets/webobs-auth-username.txt
secrets/webobs-auth-password.txt
secrets/webobs-tls-certificate.pem
secrets/webobs-tls-private-key.pem
secrets/webobs-turn-username.txt       # use-auth-secret 模式写 AUTH_SECRET
secrets/webobs-turn-password.txt       # Coturn static-auth-secret 的值
```

在 `.env` 中设置实际公开名称和文件路径；示例域名不能直接用于部署：

```dotenv
WEBOBS_BIND_ADDRESS=0.0.0.0
WEBOBS_HTTPS_PORT=443
WEBOBS_TLS_SERVER_NAME=monitor.example.com
WEBOBS_TLS_PUBLIC_AUTHORITY=monitor.example.com:443
WEBOBS_CONTROL_ALLOWED_ORIGINS=https://monitor.example.com
WEBOBS_TLS_CERTIFICATE_SOURCE=./secrets/webobs-tls-certificate.pem
WEBOBS_TLS_PRIVATE_KEY_SOURCE=./secrets/webobs-tls-private-key.pem
WEBOBS_AUTH_USERNAME_SOURCE=./secrets/webobs-auth-username.txt
WEBOBS_AUTH_PASSWORD_SOURCE=./secrets/webobs-auth-password.txt
WEBOBS_TURN_URL=turn:turn.example.com:3478?transport=tcp
WEBOBS_TURN_USERNAME_SOURCE=./secrets/webobs-turn-username.txt
WEBOBS_TURN_PASSWORD_SOURCE=./secrets/webobs-turn-password.txt
WEBOBS_TURN_CLIENT_ONLY=false
WEBOBS_WEBRTC_ADDITIONAL_HOSTS=monitor.example.com
```

`WEBOBS_TLS_SERVER_NAME` 必须与证书 SAN 匹配且不含端口；`WEBOBS_TLS_PUBLIC_AUTHORITY` 和 `WEBOBS_CONTROL_ALLOWED_ORIGINS` 必须与浏览器实际打开的外部 URL 完全一致。TURN URL 必须显式包含端口和 `transport=tcp`。如 TURN 只供浏览器侧使用而 MediaMTX 可直连，应显式设置 `WEBOBS_TURN_CLIENT_ONLY=true`。

解析配置时使用 `--quiet`，避免把本机路径扩展内容写进 CI 日志：

```bash
docker compose --env-file .env \
  -f compose.yaml \
  -f compose.m6-production.yaml \
  config --quiet
docker compose --env-file .env \
  -f compose.yaml \
  -f compose.m6-production.yaml \
  up -d --no-build webobs
```

公网防火墙只开放 HTTPS、MediaMTX 的 `8189/udp`（需要直连 ICE 时）以及外部 TURN 服务要求的 TCP/relay 端口；不要发布容器的 `8080`。TURN 密钥不会进入镜像或 Docker inspect 的 Compose 环境，但容器 root 仍能读取挂载 secret，因此应限制 Docker daemon 与主机管理员权限。证书轮换后使用 `docker compose ... up -d --force-recreate webobs` 重新挂载并加载文件。

## 7. 启动后验证

Linux shell：

```bash
curl --fail http://127.0.0.1:8080/api/v1/health
curl --fail http://127.0.0.1:8080/api/v1/ready
docker compose --env-file .env ps
docker compose --env-file .env logs --tail 100 webobs
```

PowerShell：

```powershell
curl.exe --fail http://127.0.0.1:8080/api/v1/health
curl.exe --fail http://127.0.0.1:8080/api/v1/ready
docker compose --env-file .env ps
docker compose --env-file .env logs --tail 100 webobs
```

预期行为：

- `/api/v1/health` 返回 `200`，表示进程存活。
- `/api/v1/ready` 在录制输出、WebRTC 和可见来源都准备好后返回 `200`。
- 来源启动或断流期间 readiness 可以暂时返回 `503`；RTSP 来源会按有界指数退避自动重启。
- `docker compose ps` 最终显示容器为 `healthy`。
- `recordings/` 中出现录像；收到正常停止信号后 MP4 才完成最终封装。

日志会隐藏已识别 URL 的凭据、查询和片段，但仍可能含主机名、来源 ID、内部状态和操作时间。不要把原始日志直接发布到公开 Issue。

## 8. 日常运维

```bash
# 状态、日志和资源
docker compose ps
docker compose logs --tail 200 webobs
docker stats --no-stream

# 重启，不重建镜像
docker compose restart webobs

# 正常停止，给 muxer 足够时间封装
docker compose stop -t 20 webobs

# 删除容器和网络但保留场景卷
docker compose down
```

不要使用 `docker kill`，它不给应用冲洗 muxer 的机会，可能留下未完成的临时文件。

## 9. 一致性备份与恢复

产品镜像内置 `/opt/webobs/bin/webobs-backup` 与场景校验器。备份覆盖当前 M6 的持久化场景：创建前验证 schema，把 `scene.json` 写入权限为 `0600` 的 tar.gz，并生成同名 SHA-256 sidecar。恢复会先校验 sidecar 格式、归档哈希、tar 路径、符号/硬链接及场景 schema，最后在配置卷内原子替换 `scene.json`。

备份可能包含完整 RTSP 凭据。SHA-256 只提供完整性检查，不提供加密或来源认证；`backups/` 已被 Git 忽略，但仍必须位于加密介质并限制主机访问。不要把归档、sidecar、解压内容或恢复诊断上传到公开 Issue。

先使用备份覆盖挂载受忽略的主机 `backups/` 目录，正常停止应用以取得一致快照，再运行一次性维护命令：

```bash
docker compose -f compose.yaml -f compose.m6-backup.yaml stop -t 20 webobs
docker compose -f compose.yaml -f compose.m6-backup.yaml run --rm --no-deps \
  --entrypoint /opt/webobs/bin/webobs-backup webobs create
docker compose -f compose.yaml -f compose.m6-backup.yaml start webobs
```

工具输出 UTC 文件名，例如 `/backups/webobs-config-20260815T103000Z.tar.gz`。可在不启动产品入口的情况下复验：

```bash
docker compose -f compose.yaml -f compose.m6-backup.yaml run --rm --no-deps \
  --entrypoint /opt/webobs/bin/webobs-backup webobs \
  verify /backups/webobs-config-20260815T103000Z.tar.gz
```

恢复是破坏性操作，必须先停止服务、为当前状态再做一份备份，并显式提供确认值。归档文件名只能使用字母、数字、点、下划线和连字符，且必须直接位于 `/backups`：

```bash
docker compose -f compose.yaml -f compose.m6-backup.yaml stop -t 20 webobs
docker compose -f compose.yaml -f compose.m6-backup.yaml run --rm --no-deps \
  --entrypoint /opt/webobs/bin/webobs-backup webobs create before-restore.tar.gz
docker compose -f compose.yaml -f compose.m6-backup.yaml run --rm --no-deps \
  -e WEBOBS_RESTORE_CONFIRM=replace-scene \
  --entrypoint /opt/webobs/bin/webobs-backup webobs \
  restore /backups/webobs-config-20260815T103000Z.tar.gz
docker compose -f compose.yaml -f compose.m6-backup.yaml start webobs
curl --fail http://127.0.0.1:8080/api/v1/ready
```

`.env`、`secrets/` 和录像不进入场景归档，必须分别使用受控加密备份。M8 引入录像目录数据库时会扩展此格式并保留版本化迁移，不会把运行中 SQLite 文件直接塞入当前 M6 归档。

## 10. 源码更新与回滚

更新前记录当前提交，停止容器并备份场景、`.env`、认证文件和重要录像，再给当前镜像增加本地回滚标签：

```bash
git rev-parse HEAD
docker image tag webobs:m0 webobs:rollback-before-upgrade
git fetch --tags origin
git pull --ff-only
git submodule sync --recursive
git submodule update --init --recursive
docker compose --env-file .env build --pull webobs
docker compose --env-file .env up -d --no-build --force-recreate webobs
```

升级后验证 health、ready、Web 编辑、WebRTC 和新录像。不要仅凭容器处于 `running` 判断升级成功。

需要镜像回滚时：

```bash
docker compose stop -t 20 webobs
docker image tag webobs:rollback-before-upgrade webobs:m0
docker compose --env-file .env up -d --no-build --force-recreate webobs
```

如果新版本已迁移场景格式，还必须恢复升级前场景。源码也应切回记录的提交并递归同步 submodule。长期部署更推荐使用带版本或 digest 的仓库镜像，并通过 `WEBOBS_IMAGE` 切换；详见 [GHCR 指南](ghcr.md)。

## 11. 常见问题

### `obs/obs-studio` 为空或构建找不到 OBS

```bash
git submodule sync --recursive
git submodule update --init --recursive
```

### 构建提示架构不支持

当前 Dockerfile 明确拒绝非 `amd64` 目标。请在 x86_64 Linux builder 上构建，不要用 QEMU 把它误标为已支持的 ARM64 镜像。

### 首次构建很慢或磁盘不足

确认 Docker 可用空间至少约 20 GB；先用 `docker system df` 判断占用。不要运行会误删其他项目 volume 的无范围清理命令。

### 修改 `.env` 后摄像头没有变化

已有 `scene.json` 时不会重新执行 URL 引导。通过 UI 修改来源，或在停机和备份后处理场景文件。

### UI 可打开但实时视频不可用

检查 readiness、摄像头网络连通性、RTSP TCP/UDP 设置、主机 `8189/udp` 防火墙、`WEBOBS_WEBRTC_ADDITIONAL_HOSTS` 和来源恢复日志。

### 容器反复 unhealthy

`ready` 会把录制停止、WebRTC 未准备或可见来源无新帧视为失败。检查来源状态和日志，不要通过删除 HEALTHCHECK 掩盖故障。

### 想彻底重置场景

先备份并确认 Compose 项目。以下命令具有破坏性，会删除场景卷：

```bash
docker compose down --volumes
```

下次启动将再次使用 `.env` 中的 `WEBOBS_RTSP_URL` 创建初始场景。

## 12. 部署验收清单

- [ ] 根仓库提交和 OBS submodule 提交已记录。
- [ ] `.env`、`secrets/`、备份和录像均未被 Git 跟踪。
- [ ] Compose `config --quiet` 与产品镜像构建成功。
- [ ] 镜像报告 `linux/amd64`，`webobsd --version` 正常。
- [ ] 基础 HTTP 只绑定回环；远程模式只发布受信 HTTPS 与所需 ICE 端口，未发布后端 8080。
- [ ] health、ready、Docker healthcheck 均通过。
- [ ] Web 编辑、Composite/Direct 播放和正常停止后的 MP4 已验证。
- [ ] 日志中没有明文凭据，日志轮转值保持有限。
- [ ] 场景和录像备份已实际恢复演练，而不仅是“存在备份文件”。
- [ ] 更新与回滚使用明确提交、版本标签或镜像 digest，不依赖浮动 `latest`。
