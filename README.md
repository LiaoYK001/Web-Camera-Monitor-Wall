# Web Camera Monitor Wall

一个基于 `libobs` 的无桌面 Web 监控墙、Gateway Direct WebRTC 网关与 NVR 项目。仓库已实现 **M0 及 v1-M1 至 v1-M11**，当前处于最终 v1 系列版本 **v1.2 发布资格验证阶段**。

```text
RTSP camera -> libobs ffmpeg_source -> OBS scene -> H.264/AAC MP4
                                                   -> H.264/Opus WHIP/WHEP
```

当前版本新增 SQLite WAL Camera Registry、受控 ONVIF PTZ/预置位/快照/事件/对讲，以及隔离的事件、移动检测区/隐私遮罩、Detector Provider、规则和有界通知发件箱。默认 Gateway Direct-only 运行完全不初始化 OBS 解码、合成或编码；只有录制或启用 Composite 才启动 libobs。VA-API 会分别报告设备、驱动、编解码能力和真实运行探测，失败时明确回退；Hybrid 只转码不兼容轨道。

开发路线、门禁和当前阻塞见 [ROADMAP.md](ROADMAP.md)。v1-M10/M11 的确定性 Digest/WS-Security/TLS、事件及 Webhook/MQTT 交付契约已通过测试，但 v1.2 Tag/`latest` 仍要求私下三厂商真实设备矩阵。当前 `direct` 是媒体仍经过 Docker/MediaMTX 的“网关直通”，v2.0 才以 Docker 默认退出媒体数据面为核心目标。事件安全边界见 [事件、检测与自动化](docs/events-and-automation.md)，版本与分支规则见 [版本策略](docs/versioning-and-branches.md)。

`WEBOBS_SCENE_FILE` 默认指向 `/config/webobs/scene.json`。空配置首次启动会创建空 Scene/Camera Registry，直接在 WebUI 的“设备管理”中添加设备；`WEBOBS_RTSP_URL` 只保留为一次性兼容 bootstrap，不再是部署必填项。Scene v5 只保存 Camera/Profile ID，凭据通过未提交 Git 的 Secret 引用解析。

## 运行技术基线

- OBS Studio `32.1.2`，固定 submodule 提交 `fb4d98bf88fae5fc85cb11fc57f7c5e309282194`
- Ubuntu 24.04、C++20、CMake 3.28+、x86_64
- `renderer=auto|hardware|software`；AMD render node 就绪时使用 GPU，失败时回退 Xvfb/llvmpipe
- x264 CBR、`veryfast`、High Profile、2 秒关键帧间隔
- RTSP 默认 TCP，硬件解码支持全局与逐摄像机 `auto|on|off`
- 产品运行时只有一个 Docker 镜像；M1 Compose 仅向主机回环地址发布控制端口
- MediaMTX `1.18.2` 固定版本与 SHA-256 校验后打包进产品镜像，内部信令仅监听容器回环地址
- libdatachannel `0.21.0` 固定到审核提交并使用 Ubuntu OpenSSL 3 后端，避免与系统 FFmpeg 的 Mbed TLS 2.x ABI 冲突
- `obs-browser` 固定到 OBS 32.1.2 的递归 submodule 状态，CEF 固定为 6533 revision 6 并校验精确 SHA-256

OBS 的 `ffmpeg_muxer` 同时连接 H.264 视频和 AAC 48 kHz 双声道编码器，先写入私有临时 MKV；停止并冲洗后，FFmpeg 以 stream copy 封装为 H.264/AAC MP4，画面和声音都不会被二次编码，成功后删除临时文件。无可听来源或全部来源静音时，AAC 轨仍存在但内容为静音。

## 前置条件

- Docker Desktop，启用 WSL2 与 Linux containers
- Docker Compose v2
- Git
- 建议给 Docker 分配至少 8 GB 内存并预留 20 GB 磁盘；首次编译 OBS 会花费较长时间

克隆时必须初始化递归 submodule：

```bash
git clone --recurse-submodules https://github.com/LiaoYK001/Web-Camera-Monitor-Wall.git
cd Web-Camera-Monitor-Wall
git submodule update --init --recursive
```

已存在的工作副本只需执行最后一条命令。

## 首次启动与添加摄像机

PowerShell：

```powershell
Copy-Item .env.example .env
notepad .env
docker compose up --build --abort-on-container-exit
```

Linux/macOS shell：

```bash
cp .env.example .env
${EDITOR:-vi} .env
docker compose up --build --abort-on-container-exit
```

正常部署无需填写 RTSP bootstrap。启动后打开 WebUI，进入“设备管理”，可以手工添加 Camera Source Adapter 或进行 ONVIF 发现；地址禁止内嵌账号密码。若使用旧式 `WEBOBS_RTSP_URL` bootstrap，则默认输出到 `recordings/webobs-<UTC timestamp>.mp4`，停止时会完成 muxer 和 MP4 封装。

Compose 只把 `8080` 发布到主机 `127.0.0.1`。启动后在本机浏览器打开 `http://127.0.0.1:8080/` 即可使用场景编辑器，也可直接检查控制接口：

```bash
curl http://127.0.0.1:8080/api/v1/health
curl http://127.0.0.1:8080/api/v1/scene
```

基础 Compose 仍是仅回环、无认证的本机开发模式。不要直接把端口映射改为所有网卡；需要认证时，先在受 Git 忽略的 `secrets/` 中分别创建用户名文件和至少 16 字节的密码文件，再使用覆盖文件：

```bash
docker compose -f compose.yaml -f compose.m6-auth.yaml up --build
```

该覆盖会挂载凭据文件并关闭旧的无认证非回环许可。本机 HTTP 覆盖仅为兼容测试；远程部署必须使用 `compose.m6-production.yaml` 的 HTTPS。浏览器使用 HttpOnly Session Cookie，连续 7 天未访问才失效；Basic 仅保留给 CLI/应急自动化。登录页与其静态资源公开加载，业务 API、WebSocket、WHEP 与 `/metrics` 仍需认证；健康探针保持公开。

运行时每 500 ms 汇总一次可见来源帧状态。RTSP 来源超过 `WEBOBS_SOURCE_STALE_SECONDS` 没有产生新帧后，readiness 会降为 `503`，并从 `WEBOBS_SOURCE_RECOVERY_BASE_SECONDS` 起按指数退避调用 libobs 媒体重启，间隔不超过 `WEBOBS_SOURCE_RECOVERY_MAX_SECONDS`；新帧恢复后 readiness 自动回到 `200`。受认证的 `/api/v1/sources/status` 只返回来源 ID、类型、状态、帧龄和重启次数，不返回 URL。认证失败、场景变更和来源恢复会写入经过统一 URL 脱敏的单行 JSON 审计事件；基础 Compose 默认把 Docker `json-file` 日志限制为 `10m × 3`，可通过 `.env` 中的有界值调整。

M6 的视频编码器默认使用 `WEBOBS_VIDEO_ENCODER=auto`：容器会分别探测 x264、VAAPI、QSV 和 NVENC 的设备与 OBS 编码器模块，只有两者同时可用才会选择硬件后端；显式请求不可用后端或硬件初始化失败时会记录不含设备标识的警告并安全回退 x264。当前产品镜像提供 x264 和 Linux VAAPI 实现，QSV/NVENC 会被报告为未就绪而不会误选。受认证的 `/api/v1/system/capabilities` 与固定标签 Prometheus 指标公开实际选择和回退状态。Linux 主机需要显式使用 `compose.m6-vaapi.yaml` 挂载 render node；Docker Desktop 未提供 GPU 时保持软件基线：

```bash
docker compose -f compose.yaml -f compose.m6-vaapi.yaml up --build
```

编辑器默认显示“实时节目”，通过 recvonly WHEP 播放 libobs 合成后的 H.264/Opus 节目；声音默认关闭，必须通过用户点击启用。切换到“布局编辑”可进行来源增删、RTSP 传输方式、静音/音量/同步偏移/监听/音轨、拖动、缩放、适配模式、裁切、可见性和层级调整。修改先保留在浏览器草稿中，点击“保存场景”后以 ETag/`If-Match` 提交；WebSocket 会同步其他本地标签页的已提交版本并提示冲突。页面不会显示已存储的 RTSP 用户名或密码。

M4 编辑器还可添加 `http`/`https` 浏览器源。浏览器源默认全部拒绝，管理员必须在 `WEBOBS_BROWSER_ALLOWED_ORIGINS` 中列出精确 Origin；访问单标签主机、localhost、私网地址或解析到私网的 DNS 名称还必须显式启用 `WEBOBS_BROWSER_ALLOW_PRIVATE_NETWORKS=true`。公开 API 与产品日志会隐藏 URL 查询和片段值。浏览器源在 Direct 模式中明确标为 Composite-only，不会获得来源级 WHEP 端点。完整边界和迁移规则见 [scene schema v2](docs/scene-schema-v2.md)。

实时节目区可显式选择“服务端合成”或“网关直通”。API v1 继续使用兼容值 `direct`，但这不是绕过服务器的真直连：每个可见 RTSP 来源仍由 Docker 内 MediaMTX 按需拉取，再通过独立的同源 WHEP 会话转发给浏览器；兼容流不做服务端视频解码、合成或编码，但媒体包仍经过 Docker。可用 `http://127.0.0.1:8080/#direct` 直接进入。内部 MediaMTX 路径使用每次进程启动随机生成的 128-bit 名称，能力接口和浏览器不会收到 RTSP 地址或内部路径。服务会探测视频与音频：浏览器兼容组合转发，不兼容的视频或音频只在存在 reader 时按轨转为 H.264/Opus，页面关闭后释放转码进程。所有网关直通 `<video>` 始终静音，用户点击“启用声音”后才由一个共享 Web Audio 图按每路静音、音量和相对同步偏移输出，避免多元素重复播放。v2 的 True Direct 将由 Android/桌面本地运行端或受控本机伴随服务直接连接设备，Docker 默认只提供 UI/Registry/策略/可选信令且不承载视频数据；普通浏览器不能直接解码常规 RTSP，因此不作虚假承诺。

浏览器只访问本站 `/api/v1/program/whep`。服务端把 offer 转发到固定的容器回环 MediaMTX，并把上游会话地址改写为随机同源令牌；任意上游 URL、跨源 offer、超过 64 KiB 的 SDP 和伪造会话令牌都会被拒绝。浏览器等待 ICE 收集完成后一次性提交 offer，断线以 1–8 秒退避重连，并在页面关闭时尽力删除会话；M2 暂不实现 trickle ICE/PATCH。

RTSP URL 可能被 OBS 插件写入日志，因此核心日志处理器会把 `rtsp://user:password@host/...` 统一改写成 `rtsp://***:***@host/...`。不要把真实 URL 写入 Compose、README 或提交到 Git。

### M0 真实摄像头验收

配置本地 `.env` 后，使用专用入口录制至少 30 秒并自动执行完整解码、H.264、AAC 48 kHz 双声道、分辨率、帧率、时长和非黑帧检查。每次运行使用新的 UTC 文件名，不会覆盖已有录像。

PowerShell：

```powershell
./tests/run-real-camera.ps1
```

已有本地镜像时可使用 `./tests/run-real-camera.ps1 -SkipBuild`。非默认画布可显式传入，例如 `-Width 1280 -Height 720 -Fps 25`。

Linux/macOS shell：

```bash
./tests/run-real-camera.sh
```

shell 入口通过 `WEBOBS_REAL_WIDTH`、`WEBOBS_REAL_HEIGHT`、`WEBOBS_REAL_FPS` 等变量覆盖验收参数；使用 `WEBOBS_SKIP_BUILD=1` 复用已有镜像。可用 `WEBOBS_ENV_FILE` 指向另一个未入库的环境文件。

录像保存在忽略的 `recordings/`，经过二次脱敏的本地日志保存在忽略的 `tests/artifacts/`。脚本不会把 URL 放入命令行，也不会保存检测到凭据泄漏的原始日志。即使日志已脱敏，也不要将真实摄像头日志或录像上传到公开 Issue。

### M1 真实摄像头验收

M1 使用独立门禁验证真实来源在持续录制期间接受 Web 控制：先把既有画面缩放到左侧并通过 API 在线添加同一摄像头的第二个来源，验证静音和音量配置后删除原来源，再把新来源恢复为全画布。测试至少继续录制 30 秒，停止后验证 H.264/AAC、分辨率、FPS、完整解码和逐帧无空黑场。

PowerShell：

```powershell
./tests/run-m1-real-camera.ps1
```

默认从本地 `.env` 读取地址；也可在当前 PowerShell 会话中临时设置 `WEBOBS_RTSP_URL`，脚本会直接使用它而不要求创建文件。显式传入 `-EnvFile` 时，该文件优先于当前进程环境。

已有当前产品和测试镜像时可增加 `-SkipBuild`。Linux shell 使用：

```bash
./tests/run-m1-real-camera.sh
```

shell 参数沿用 `WEBOBS_ENV_FILE`、`WEBOBS_REAL_*` 和 `WEBOBS_SKIP_BUILD=1`。门禁不会把私有 URL 放入 Docker、curl 或 jq 命令参数；URL 只通过环境进入隔离测试网络，场景凭据只存在于一次性命名卷，结束时随测试项目销毁。原始容器日志先在内存中检查凭据泄漏，写入忽略目录前会进一步隐藏整个 RTSP 端点。

POSIX Shell 同样支持直接设置当前进程的 `WEBOBS_RTSP_URL`；配置优先级为 `WEBOBS_ENV_FILE` 指定文件、当前进程 `WEBOBS_RTSP_URL`、默认本地 `.env`。

不使用真实摄像头时，可执行完全相同控制路径的 MediaMTX 合成演练：

```powershell
./tests/run-m1-real-camera.ps1 -SkipBuild -UseSyntheticFixture `
  -DurationSeconds 10 -Width 640 -Height 360 -Fps 10 `
  -BitrateKbps 800 -ConnectTimeoutSeconds 8
```

shell 对应设置 `WEBOBS_REAL_USE_SYNTHETIC=1`；合成演练只证明门禁编排和控制事务，不能替代最终真实摄像头复验。

### M2 真实摄像头验收

M2 门禁在隔离的产品 Compose 项目中启动真实来源，通过本机 headless Chrome 建立同源 WHEP/H.264/Opus 播放，持续至少 30 秒后优雅停止产品，并验证浏览器 reader、容器退出状态、日志脱敏和最终 MP4。当前录像必须为 H.264/AAC、指定分辨率与 FPS，可完整解码且无黑帧。

PowerShell：

```powershell
./tests/run-m2-real-camera.ps1
```

脚本按 `-EnvFile`、当前进程 `WEBOBS_RTSP_URL`、本地 `.env` 的顺序读取私有端点；已有镜像时可增加 `-SkipBuild`。端点只通过容器环境传入，一次性场景卷在退出时销毁；原始日志仅在内存中执行泄漏检查，写入忽略目录前会隐藏整个 RTSP 端点。此门禁要求可信的本机 Chrome，可用 `WEBOBS_CHROME_BIN` 指定其路径。

### M5 真实音频验收

M5 门禁要求 RTSP 来源实际包含音频。它依次运行至少 30 秒的 Composite 与 Direct/Hybrid 浏览器会话，先通过本地 API 将默认静音的来源显式设为音轨 1，再验证浏览器双轨 reader、容器正常退出、日志无端点泄漏，以及两份 H.264/AAC 48 kHz 双声道 MP4 均非静音、可完整解码且无黑帧。

```powershell
./tests/run-m5-real-audio.ps1 -SkipBuild
```

地址读取优先级与 M2/M3 门禁相同。录像和二次脱敏日志只写入受 Git 忽略的本地目录；不得把它们上传到公开 Issue。安防摄像头麦克风电平通常较低，真实源门禁使用可配置的响度下限来排除数字静音，而确定性音频门禁仍使用更严格的默认阈值。

## 命令行接口

容器配置优先级为：命令行参数 > `WEBOBS_*` 环境变量 > 默认值。

```text
webobsd
  --rtsp-url <url>
  --scene-file <absolute-path.json>
  --listen-address <127.0.0.1|::1|0.0.0.0|::>
  --http-port <0..65535>
  --allow-insecure-remote <true|false>
  --auth-username-file <absolute-path>
  --auth-password-file <absolute-path>
  --auth-failure-limit <1..100>
  --auth-failure-window-seconds <1..3600>
  --control-allowed-origins <comma-separated-https-origins>
  --source-stale-seconds <2..300>
  --source-recovery-base-seconds <1..300>
  --source-recovery-max-seconds <1..3600>
  --webrtc-enabled <true|false>
  --whip-url <absolute-http-or-https-url>
  --browser-allowed-origins <comma-separated-origins>
  --browser-allow-private-networks <true|false>
  --output <path.mp4>
  --duration-seconds <0..604800>
  --width <even 16..8192>
  --height <even 16..8192>
  --fps <1..120>
  --bitrate-kbps <50..100000>
  --connect-timeout-seconds <1..300>
  --rtsp-transport <tcp|udp>
  --log-level <error|warn|info|debug>
  --help
  --version
```

例如直接覆盖 Compose 的默认命令：

```bash
docker compose run --rm webobs \
  --rtsp-url "rtsp://user:password@camera/stream" \
  --output /recordings/manual.mp4 \
  --duration-seconds 30
```

## 确定性烟测

烟测中的独立 MediaMTX 和 FFmpeg 只负责产生本地测试图 RTSP，与产品镜像内为 M2 提供 WHIP/WHEP 路由的 MediaMTX 进程用途不同。两者都从官方 GitHub Release 获取固定的 `v1.18.2` Linux amd64 二进制并校验 SHA-256，不依赖可变标签。测试会构建项目、录制约 10 秒，再检查：

- MP4 存在且可完整解码
- 唯一视频轨为 H.264
- AAC、48 kHz、双声道音频轨存在且可完整解码
- 分辨率为 640×360
- 帧率为 10 FPS
- 时长在预期范围内
- 首帧不是空黑画面
- 4:3 测试源在 16:9 画布中等比居中，左右黑边对称且中心画面有效

同一入口还覆盖缺失 URL、无法连接、错误输出目录、已有文件拒绝覆盖、日志凭据脱敏，以及容器收到 `SIGTERM` 后完整冲洗并封装 MP4。M1–M5 验收覆盖事务性控制面、Composite/Direct/Hybrid WebRTC、浏览器源和确定性音频；M6 覆盖认证、恢复、指标、备份、TLS/TURN、来源证明与升级回滚；M7 覆盖 schema v4 原始迁移备份、六场景混合来源、Program/Preview 隔离、同 ID 重新 Take、撤销重做、重启恢复、权限与脱敏、500 次交替 Cut/Fade 以及最终 H.264 无黑场录像。

烟测和真实摄像头验收会先执行公开仓库审计：检查 Git 索引中没有 `.env`、录像、测试产物、私钥文件或高置信度令牌，只允许明确列出的 RTSP 测试占位符，并确认 Git/Docker 忽略规则及 OBS submodule 固定提交未漂移。也可以单独运行 `./tests/run-public-audit.ps1` 或 `./tests/run-public-audit.sh`；审计只读取 Git 索引，不读取本地未跟踪 `.env` 的内容。

PowerShell：

```powershell
./tests/run-smoke.ps1
```

只运行 M1 控制面验收可使用 `./tests/run-control-plane.ps1 -SkipBuild`；M2–M6 的分项命令保持不变；M7 完整 Studio 门禁使用 PowerShell 7 执行 `pwsh ./tests/run-m7-studio.ps1 -SkipBuild`。浏览器门禁默认查找本机 Chrome，也可通过 `WEBOBS_CHROME_BIN` 指定可信的 Chrome 可执行文件。

真实来源的 M3 Direct/Hybrid 门禁使用 `./tests/run-m3-real-camera.ps1 -SkipBuild`，M5 Composite + Direct/Hybrid 真实音频门禁使用 `./tests/run-m5-real-audio.ps1 -SkipBuild`。RTSP URL 只通过当前进程的 `WEBOBS_RTSP_URL` 或受 Git 忽略的本地 `.env` 提供；这些门禁会把录像和端点替换后的诊断日志分别写入受忽略的 `recordings/` 与 `tests/artifacts/`，不得将其作为公开附件提交。

如果三个测试镜像已经成功构建，而 registry 暂时不可用，可显式复用本地镜像：`./tests/run-smoke.ps1 -SkipBuild`。这不会跳过录制、解码、失败路径或 SIGTERM 验收。

Linux shell：

```bash
./tests/run-smoke.sh
```

Linux 下对应使用 `WEBOBS_SKIP_BUILD=1 ./tests/run-smoke.sh`。

成功产物位于 `tests/artifacts/smoke.mp4`；多来源、控制面、WebRTC 和 SIGTERM 用例还会生成各自的忽略产物。该目录内容不会进入 Git。

## 本地 CMake 结构

Docker 构建会先配置 OBS，并只编译以下目标：

```text
libobs
libobs-opengl
obs-ffmpeg
obs-x264
obs-webrtc
obs-browser
browser-helper
obs-ffmpeg-mux
```

`obs-webrtc` 使用固定的 libdatachannel `0.21.0` 构建；`obs-browser` 使用固定 CEF 并关闭依赖 Qt 前端的 panels。WHIP URL 不接受 userinfo、查询参数或片段，浏览器 URL 受精确 Origin 与私网策略约束；当前内置 MediaMTX 使用无凭据的容器回环端点。之后编译 `webobsd` 和无外部测试框架的 CTest 单元测试。单元测试覆盖参数边界、CLI/环境变量优先级、URL 安全与脱敏、场景解析/迁移/存储和乐观并发变更计划。

## 退出状态

| 状态 | 含义 |
| ---: | --- |
| 0 | 成功或录制开始前收到正常停止信号 |
| 2 | 配置或命令行无效 |
| 3 | libobs、图形、音频或模块初始化失败 |
| 4 | RTSP 在超时前没有产生视频帧 |
| 5 | 编码器、muxer、目录或录制输出失败 |
| 6 | 最终 H.264/AAC MP4 封装失败 |
| 7 | 场景文件加载、迁移或原子持久化失败 |
| 8 | HTTP/WebSocket 控制监听器启动失败 |

## 许可证

本项目采用 `GPL-2.0-or-later`。OBS Studio 及其 submodule 保留各自的上游版权和许可证声明。

漏洞报告和凭据处理要求见 [SECURITY.md](SECURITY.md)。
