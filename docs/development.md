# 本地开发：Windows / Linux

日常开发无需 Docker Desktop、Podman 或镜像。`dev.ps1` 和 `dev.sh` 共用同一个启动器，默认编译并运行真实 C++/Python 后端，再启动 Vite。镜像构建放在功能完成后的集成与部署验收阶段。

## 1. 选好运行方式

| 模式 | 适合的工作 | 本机需求 | 是否构建镜像 |
| --- | --- | --- | --- |
| `native`（默认） | Web、C++ API、账号、设备、事件、NVR、Gateway Direct 联调 | Node 24 + Linux 原生依赖；Windows 用 WSL2 | 否；首次编译 OBS 核心，之后增量编译 |
| `frontend` | 只修改 Web，连接已有测试后端 | Node 24 + Corepack | 否 |
| `container` | 完整媒体功能/已有镜像的兼容联调 | Node 24 + 已启动的 Docker/Podman + Compose | 仅显式 `-Build` / `--build` |

原生模式运行仓库中的 C++ 核心和 Python 服务，数据库持久化。为缩短首次准备时间，原生模式只构建 libobs 核心，不构建 OBS 插件/CEF。服务端 Composite、OBS 浏览器源和发布部署仍需在完整镜像中验收。RTSP 的兼容轨道由 Gateway 转发，不兼容轨道通过 FFmpeg 按需转为 H.264/Opus。

首次打开 `http://127.0.0.1:5173` 时在页面创建管理员账号。之后在任何浏览器用同一账号登录即可读取服务器上的摄像机、场景、监看设置和配置预设，不再需要八位浏览器配对码。登录 Cookie 在每次正常访问后续期，连续 7 天未访问才会过期。摄像机通过受认证的同源网关播放。Windows/WSL2 局域网模式会启用 TCP 8190 媒体入口和 Windows 侧中继；其他设备访问 `https://<本机局域网 IP>:5173/`，首次打开需信任开发自签证书。

## 2. Windows 首次准备

建议 Windows 11 + WSL2 Ubuntu 24.04，Windows PowerShell 5.1 和 PowerShell 7 均支持。Windows 安装 Node.js 24 LTS 与 Git，重新打开终端，然后执行：

```powershell
node --version
npm install -g corepack
wsl --install -d Ubuntu-24.04
```

WSL 已安装时跳过安装命令；首次发行版初始化按系统提示创建 Linux 用户。Windows 日常开发使用 Windows Node，Linux 后端通过 WSL 运行，不需要在 WSL 安装另一份 Node。

```powershell
git clone https://github.com/LiaoYK001/Web-Camera-Monitor-Wall.git
cd Web-Camera-Monitor-Wall
.\scripts\dev.ps1 -Setup
```

`-Setup` 只在首次或缺少系统依赖时使用：通过 WSL root 安装 Ubuntu 软件包，编译与服务仍以默认普通 Linux 用户运行。首次需要网络下载软件包、OBS 子模块、前端依赖和经过 SHA-256 校验的 MediaMTX。脚本不修改全局执行策略；若机器策略禁止脚本，可在遵循本机管理要求的前提下直接执行 `node scripts/dev.mjs --setup`。

其他发行版名称可指定 `-Distro Ubuntu-24.04`；用 `wsl -l -v` 查看名称。自动依赖安装支持 Ubuntu 24.04 x86_64。

## 3. Linux 首次准备

推荐 Ubuntu 24.04 x86_64，Node.js 24 LTS、Git 和 Python 3.12+。其他 Linux 需自行安装同等开发库，自动 apt 安装会明确拒绝不支持的发行版。

```bash
node --version
npm install -g corepack
git clone https://github.com/LiaoYK001/Web-Camera-Monitor-Wall.git
cd Web-Camera-Monitor-Wall
bash scripts/dev.sh --setup
```

Linux 的 `--setup` 使用 sudo 安装系统依赖，可能要求输入**本机 sudo 密码**；这与项目登录账号不同。不要使用 sudo 启动整个开发脚本，以免缓存和前端依赖属于 root。系统依赖清单在 `scripts/dev-native.py` 的 `PACKAGES` 中，包括 CMake 3.28+、GCC/C++20、Boost 1.83+、FFmpeg 6.1 开发库、Jansson、OpenSSL、SQLite、libsodium 与 X11/OpenGL 开发库。

## 4. 日常启动和停止

| 操作 | Windows PowerShell | Linux / WSL shell |
| --- | --- | --- |
| 启动原生开发 | `.\scripts\dev.ps1` | `bash scripts/dev.sh` |
| 只检查环境 | `.\scripts\dev.ps1 -Check` | `bash scripts/dev.sh --check` |
| 查看帮助 | `.\scripts\dev.ps1 -Help` | `bash scripts/dev.sh --help` |
| 前端改用 5175 | `.\scripts\dev.ps1 -Port 5175` | `bash scripts/dev.sh --port 5175` |
| 停止默认会话 | `.\scripts\stop-dev.ps1` | `bash scripts/stop-dev.sh` |
| 停止 5175 会话 | `.\scripts\stop-dev.ps1 -Port 5175` | `bash scripts/stop-dev.sh --port 5175` |

脚本从任何当前目录运行均可；例如在 `scripts` 下直接运行 `./dev.ps1` 或 `bash dev.sh`。默认前端地址 **http://127.0.0.1:5173**，真实 API 地址 **http://127.0.0.1:8080**。本地前端通过 Vite 代理访问 API；原生 8080 的静态页只有在 `web/dist` 已构建时可用，日常请使用 5173。

启动时看到以下进度即可判断当前阶段：

```text
[WebOBS] 模式：native | Node ... | 前端端口 5173
[native] [1/4] 增量编译 OBS 核心；日志：.../logs/build.log
[native] [2/4] 增量编译项目 C++ 后端
[native] [3/4] 下载并校验 MediaMTX（仅首次）
[native] [4/4] 启动 Python 服务、媒体网关和 C++ API
[native] [OK] camera / events / clients / cluster / nvr / core
[WebOBS] 就绪：http://127.0.0.1:5173
```

前端修改自动热更新。C++ 或 Python 修改后 Ctrl+C 再运行，CMake/Ninja 复用已有产物，Python 从源码重新加载。首次编译日志持续写入 `logs/build.log`，并在失败时显示末尾错误，避免将编译器大量输出淹没启动说明。

Ctrl+C 停止本次原生服务和前端，保留数据。停止脚本通过本次会话的随机令牌发送本机停止请求，不根据端口强杀其他程序；`build/dev-session-<端口>.json` 是被 Git 忽略的临时状态。容器模式停止前端后，容器保留运行，需另行 `docker compose -f compose.yaml -f compose.dev.yaml stop`。

前端 `node_modules` 不跨 Windows/Linux 共用。同一平台启动时会根据 package.json、锁文件、平台和架构判断是否同步依赖；未变化时跳过安装。若同时在 Windows 和 WSL 开发前端，请使用两个独立 checkout。

## 5. 账号、数据和日志

- 首次启动或旧数据库尚无管理员时，登录页开放一次管理员注册。密码至少 16 字节。管理员可在“集群与权限”中添加其他账号；之后注册入口关闭。
- 原生数据与编译产物位于 Linux 用户的 `~/.cache/webobs-dev/<仓库路径摘要>/`。Windows 也在 WSL 的 Linux 文件系统保存源码缓存和编译产物，避免跨 NTFS 扫描大量小文件。Windows 工作副本的 C++ 修改在每次启动时同步；OBS 依赖按子模块提交缓存，不包含其未提交修改。若需修改 OBS 本身，请在 Linux checkout 开发，或在 Linux 启动环境中指定 `WEBOBS_DEV_OBS_SOURCE` 为待调试源码的绝对路径。实际路径在每次启动中显示。
- `data/` 保存账号、会话、设备和场景；`recordings/` 保存本地录像；`logs/` 按服务保存日志；`obs*`、`core*` 保存依赖源码快照及增量编译产物；`source/` 是 Windows C++ 源码的自动同步副本，不要在这里编辑。
- 原生数据库与 Docker Compose 数据卷**相互独立**。切换模式不会自动迁移账号和设备。更换仓库路径会使用新的缓存/数据库目录。
- 此模式固定监听本机回环，启用本机 HTTP Cookie 设置与开放注册。不要将该开发配置直接作为公网部署配置。

旧版本的 `secrets/webobs-dev-*.txt` 不再用于新登录。升级已有开发数据时，如账号库里只有普通用户且没有管理员，页面会开放一次管理员注册。

## 6. 只开发 Web / 使用已有后端

```powershell
.\scripts\dev.ps1 -Mode frontend -Api http://127.0.0.1:8080
```

```bash
bash scripts/dev.sh --mode frontend --api http://127.0.0.1:8080
```

此模式先检查后端健康状态，不会悄悄退化成 mock 或离线登录。已有后端的 `WEBOBS_CONTROL_ALLOWED_ORIGINS` 必须包含实际前端 Origin，例如 `http://127.0.0.1:5173`；后端证书及 Secure Cookie 也必须匹配测试入口，远端 HTTPS 服务建议通过对应的 HTTPS 开发入口联调。不要在 `--api` 中写账号密码。

## 7. 功能完成后再镜像化与跨机器测试

先完成源码检查与本地联调，再构建完整产品镜像：

```bash
cd web
corepack pnpm build
corepack pnpm test:local
cd ..
# Docker 或 Podman 二选一；完整镜像包含 OBS 插件、CEF 等。
docker build -f docker/Dockerfile -t webobs:review .
# podman build -f docker/Dockerfile -t webobs:review .
docker save -o webobs-review.tar webobs:review
# podman save --format docker-archive -o webobs-review.tar webobs:review
```

复制 tar 到测试机器后，用对应引擎加载 `docker load -i webobs-review.tar` 或 `podman load -i webobs-review.tar`。测试机器无需源码编译环境。以下以 Linux 测试机 Docker 为例，Podman 可将命令名替换为 `podman`（SELinux 主机目录挂载按本机要求加 `:Z`）：

```bash
mkdir -p secrets assets recordings
# 在 secrets 下创建 webobs-dev-username.txt / webobs-dev-password.txt，密码至少 16 字节。
docker run -d --name webobs-review \
  -p 127.0.0.1:8080:8080 -p 127.0.0.1:8189:8189/udp \
  -v webobs-review-config:/config/webobs \
  -v "$PWD/secrets:/run/secrets:ro" \
  -v "$PWD/assets:/assets:ro" -v "$PWD/recordings:/recordings" \
  -e WEBOBS_LISTEN_ADDRESS=0.0.0.0 \
  -e WEBOBS_AUTH_USERNAME_FILE=/run/secrets/webobs-dev-username.txt \
  -e WEBOBS_AUTH_PASSWORD_FILE=/run/secrets/webobs-dev-password.txt \
  -e WEBOBS_SESSION_COOKIE_SECURE=false \
  -e WEBOBS_WEBRTC_ENABLED=true -e WEBOBS_COMPOSITE_ENABLED=false \
  webobs:review
docker logs --tail 100 webobs-review
curl --fail http://127.0.0.1:8080/api/v1/health
```

这是在测试机器本机浏览器访问的示例。跨主机浏览器、摄像机和 GPU 测试还需要配置实际媒体 ICE 地址、HTTPS、来源白名单和设备挂载；详见 README 部署章节与已有生产 Compose 覆盖。对外服务采用 `compose.m6-production.yaml`，不要直接开放上述本机 HTTP 端口。Podman 的 `compose` 命令依赖外部 Compose provider；若 provider 不支持项目覆盖中的 `!override`，使用上述 `podman run` 测试或升级 provider。当前机器未安装 Podman，Podman 部署需在目标机实际验收。

保留的容器开发入口不再自动构建：

```powershell
.\scripts\dev.ps1 -Mode container -Build   # 明确要求构建一次
.\scripts\dev.ps1 -Mode container          # 复用镜像
```

```bash
bash scripts/dev.sh --mode container --build
bash scripts/dev.sh --mode container --engine podman
```

`compose.dev.yaml` 为兼容开发镜像使用 `/dev/shm` 测试临时数据库；生产 Dockerfile 默认仍使用磁盘 `/tmp`。此前本机 WSL 虚拟磁盘事件索引 p95 约 60–72 ms，未满足生产构建 50 ms 门槛，因此开发镜像通过不代表生产磁盘性能通过。

## 8. 常见错误速查

### 来源与音轨探测 / Source and audio probing

HTTP 摄像机首页、Canon WV-HTTP/MJPEG 与可选转换服务的接入方法见 [go2rtc 协议转换指南 / go2rtc bridge guide](go2rtc-integration.md)。

- RTSP 的 `auto` 在系统默认也是 `auto` 时使用 TCP，适用于 WSL、NAT 和 VPN 链路；需要 UDP 时可在 Profile 中显式选择。使用 Tailscale 地址的设备仍需先建立 VPN 连接。
- 开启系统“来源自动恢复”后，注册表会自动探测已启用、尚未成功的媒体 Profile。失败后间隔至少 30 秒重试，连续 10 次失败后停止；成功后停止周期探测。状态与尝试次数保存在数据库，刷新网页不会重置。设备目录可见时每 30 秒刷新一次状态。
- 设备详情中的“自动探测”可切换为仅手动。网络恢复后点击“探测轨道”可以立即重试，即使此前已达到 10 次上限。成功会清除失败计数并更新设备在线状态。
- 音频工作台使用账号摄像机接口查询与播放音轨，不依赖旧全局场景。已有成功探测结果会直接复用；“重新探测”会先重新探测对应 Profile。“已确认无音轨”与“探测失败”分别显示，失败不会被当作无音频。
- 一个设备有任意已启用 Profile 探测成功时显示在线；所有已启用 Profile 探测失败时显示离线。这里表示最近的探测结果，持续播放期间的断流由播放器自身检测和重连。

RTSP `auto` defaults to TCP when the system default is also `auto`; explicitly select UDP if required. VPN-addressed cameras still require an active VPN connection. With source recovery enabled, the registry retries enabled, unsuccessful media profiles at least 30 seconds apart, stops after 10 consecutive failures, and stops polling after success. Attempts persist across restarts. The visible catalog refreshes every 30 seconds. Disable a profile's automatic probing for manual-only operation; a manual probe remains available after the retry limit. Successful probing clears the failure count and updates device health. Audio discovery and playback use account camera routes and reuse successful registry metadata; manual audio retry probes the profile again. Confirmed absence of audio is distinct from probe failure. Device health reflects the latest probe results; the player detects and reconnects interrupted playback separately.

| 提示 | 原因与处理 |
| --- | --- |
| `dockerDesktopLinuxEngine ... file specified` | 旧脚本强制访问未启动的 Docker 引擎。现在默认原生模式不访问 Docker；显式容器模式需先启动 Docker Desktop。 |
| 找不到 Ubuntu-24.04 | `wsl -l -v` 查看发行版；安装 Ubuntu 24.04 或传 `-Distro`。 |
| 缺少原生依赖 / CMake 版本不足 | 首次加 `-Setup` / `--setup`；自动安装基线为 Ubuntu 24.04。 |
| 前端端口已占用 | 在旧终端 Ctrl+C，或换 `-Port 5175` / `--port 5175`。 |
| 后端 8080/809x 等已占用 | 停止旧后端或本项目容器；原生内部服务使用固定端口，不同时运行两套。 |
| PowerShell 禁止执行脚本 | 按本机策略处理，或直接运行 `node scripts/dev.mjs`；脚本不更改执行策略。 |
| 编译失败 | 查看启动提示中的 `logs/build.log`；修复依赖后原命令重试，保留缓存。 |
| 前端出现 Origin / Cookie 错误 | 使用启动器显示的地址；已有后端须允许该前端 Origin，本机 HTTP 不能使用 Secure Cookie。 |
| 切换原生模式后账号/设备不见 | 原生数据与容器数据卷独立；使用开发管理员登录，需迁移时先备份数据库。 |
| 停止脚本找不到会话 | 确认端口参数；旧版启动器用原终端 Ctrl+C。脚本不会强杀其他进程。 |

## 监控混音与实时布局 / Monitor audio and live layout

- 真全屏、独立投影和窗口预览会隐藏 Audio Mixer 与操作栏，保留监控画面。
- 主监控页的 M 控制该来源静音，耳机按钮控制该来源的本地扬声器监听；先点击“启用声音”，并选择“扬声器 + 电平表”才能听到声音。音量、静音和监听选择随账号监控偏好保存。浏览器要求的首次启用声音操作仍需在每台设备上完成。
- 混音器和逐路声音设置默认只列出有音轨的来源；勾选“显示全部来源（包括无音轨）”可显示其余来源，并重试未知音轨。已确认无音轨的设备不会因网关附带的兼容静音轨而显示为有声音。逐轨选择和混音在“音频工作台”操作。
- Studio → 布局编辑默认开启“实时画面”：拖动和缩放时直接显示视频，不会因移动或调整尺寸重新建立连接。选中框的操作手柄位于其他交互框之上。可关闭“实时画面”减少解码开销；保存与 TAKE 流程保持原有语义。
- 长期运行优化包括复用电平采样缓冲区、空闲时停止采样、清理已完成的提升计时器和旧场景音轨、释放关闭后才返回的媒体会话，以及避免离线来源阻塞整个混音器启用。视频音轨与独立音频轨不会重复输出。

True fullscreen, projector and window preview hide the mixer and controls. On the monitor page, M mutes a source and the headphones button controls local speaker monitoring. Enable audio and select speaker output to hear it. Gain, mute and monitoring selections persist in account monitor preferences; each device still requires the browser's initial audio activation gesture. The mixer and per-source audio settings show audio-bearing sources by default. Enable “显示全部来源（包括无音轨）” to show other sources and retry unknown audio. Confirmed video-only cameras are not misclassified by silent gateway compatibility tracks. Manage individual audio tracks in the Audio workspace.

Studio layout editing now displays live video while moving and resizing items, without renegotiating their connections. Selected interaction handles stay above other interaction frames. Disable “实时画面” to reduce decoding work. Saving and TAKE keep their existing semantics. Long-running resource improvements reuse meter buffers, stop idle sampling, remove completed promotion timers and old scene tracks, release media sessions returned after closure, prevent offline play requests from blocking mixer activation, and avoid duplicate video/standalone audio output.

验证使用浏览器合成视频和模拟音频图，覆盖实时布局拖放、连接数量、全屏隐藏、偏好保存和资源释放；不能替代真实摄像机的长时间耐久测试。

Verification uses browser-generated video and a simulated audio graph to cover live drag/resize, connection counts, fullscreen hiding, preference persistence and resource cleanup. It does not replace a long-duration test with real cameras.

## 本次验证记录

- Windows PowerShell 5.1：默认原生启动、环境检查、管理员登录、注册、刷新会话、热更新、停止与增量重启通过；注册账号重启后仍可登录。
- Ubuntu 24.04 / WSL2：独立 Linux checkout 使用 `dev.sh` 编译并启动全部原生服务；登录、注册、刷新会话、热更新、停止、环境检查与启动器 5 项回归测试通过。
- Windows 启动器 5 项回归测试通过，涵盖帮助、非法参数、已有后端检查、后端不可用和端口占用；原生 C++ 单元测试通过。
- Docker 引擎关闭时的错误提示已验证；本次未新建镜像，未执行 Podman 或其他机器的部署测试。真实摄像头/GPU/完整媒体插件仍需按镜像验收流程验证。

启动器回归测试可在两端运行：`node --test tests/test-dev-launcher.mjs`。
