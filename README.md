# Web Camera Monitor Wall

一个基于 `libobs` 的无桌面 Web 监控墙/合成器项目。仓库已完成 **M0 Headless Proof、M1 Web Control 和 M2 Composite WebRTC**：无需 OBS Qt 界面，也能在 Linux Docker 容器中完成下面的闭环。

```text
RTSP camera -> libobs ffmpeg_source -> OBS scene -> obs_x264 -> video-only MP4
```

当前开发版本已能从持久化场景启动多路 RTSP 合成，并通过随产品镜像提供的 React/TypeScript 编辑器及本机 REST/WebSocket 接口，在录制期间原子更新布局和来源。M2 已在同一产品镜像中通过固定版本 MediaMTX 和 `obs-webrtc` 发布 WHIP/H.264；M3 正在增加每路摄像头按需直达浏览器的 WHEP 路径，并让 Direct 与 Composite 复用同一场景布局。输出音轨与硬件编码尚未加入。

开发路线、里程碑验收标准和当前进度见 [ROADMAP.md](ROADMAP.md)。**M0、M1 与 M2 已通过全部验收；当前处于 M3 Direct & Hybrid。**场景与持久化契约见 [docs/scene-schema-v1.md](docs/scene-schema-v1.md)，控制协议见 [docs/api-v1.md](docs/api-v1.md)。

`WEBOBS_SCENE_FILE` 默认指向 `/config/webobs/scene.json`。首次启动使用 `WEBOBS_RTSP_URL` 创建并保存单路场景；后续启动以场景文件为准。手工编辑场景文件前应停止容器，且真实 RTSP 凭据不得提交到 Git。

## M0 技术基线

- OBS Studio `32.1.2`，固定 submodule 提交 `fb4d98bf88fae5fc85cb11fc57f7c5e309282194`
- Ubuntu 24.04、C++20、CMake 3.28+、x86_64
- X11/EGL + Xvfb + Mesa 软件合成
- x264 CBR、`veryfast`、High Profile、2 秒关键帧间隔
- RTSP 默认使用 TCP，硬件解码关闭
- 产品运行时只有一个 Docker 镜像；M1 Compose 仅向主机回环地址发布控制端口
- MediaMTX `1.18.2` 固定版本与 SHA-256 校验后打包进产品镜像，内部信令仅监听容器回环地址
- libdatachannel `0.21.0` 固定到审核提交并使用 Ubuntu OpenSSL 3 后端，避免与系统 FFmpeg 的 Mbed TLS 2.x ABI 冲突

OBS 的 `ffmpeg_muxer` 要求同时连接视频和音频编码器。M0 会写入一个带静音 AAC 的临时 MKV，停止后通过 FFmpeg stream copy 生成只有 H.264 视频轨的最终 MP4；画面不会被二次编码，临时文件成功后会删除。

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

## 使用真实摄像头

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

至少修改：

```dotenv
WEBOBS_RTSP_URL=rtsp://user:password@camera-host:554/stream
```

默认输出到 `recordings/webobs-<UTC timestamp>.mp4`。`WEBOBS_DURATION_SECONDS=0` 时录制和控制接口会持续运行到 `Ctrl+C` 或容器收到 `SIGTERM`；停止时会完成 muxer 和 MP4 封装。已有的显式输出文件不会被覆盖。

Compose 只把 `8080` 发布到主机 `127.0.0.1`。启动后在本机浏览器打开 `http://127.0.0.1:8080/` 即可使用场景编辑器，也可直接检查控制接口：

```bash
curl http://127.0.0.1:8080/api/v1/health
curl http://127.0.0.1:8080/api/v1/scene
```

M1 尚无认证、TLS 或远程暴露承诺。不要将端口映射改为所有网卡，也不要通过公网反向代理发布；完整的本地安全约束和更新示例见 [控制 API 文档](docs/api-v1.md)。

编辑器默认显示“实时节目”，通过 recvonly WHEP 播放 libobs 合成后的 H.264 画面；切换到“布局编辑”可进行来源增删、RTSP 传输方式、静音/音量、拖动、缩放、适配模式、裁切、可见性和层级调整。修改先保留在浏览器草稿中，点击“保存场景”后以 ETag/`If-Match` 提交；WebSocket 会同步其他本地标签页的已提交版本并提示冲突。页面不会显示已存储的 RTSP 用户名或密码。

M3 的实时节目区可显式选择“服务端合成”或“浏览器直达”。Direct 模式为每个可见来源建立独立的同源 WHEP 会话，并以同一份场景文档应用位置、尺寸、层级、可见性、裁切及 contain/cover/stretch；可用 `http://127.0.0.1:8080/#direct` 直接进入。内部 MediaMTX 路径使用每次进程启动随机生成的 128-bit 名称，RTSP 只在 reader 存在时按需拉取，能力接口和浏览器不会收到 RTSP 地址或内部路径。当前仅完成浏览器兼容流的 Direct 路径；不兼容编码的检测与选择性转码仍在后续 M3 批次中。

浏览器只访问本站 `/api/v1/program/whep`。服务端把 offer 转发到固定的容器回环 MediaMTX，并把上游会话地址改写为随机同源令牌；任意上游 URL、跨源 offer、超过 64 KiB 的 SDP 和伪造会话令牌都会被拒绝。浏览器等待 ICE 收集完成后一次性提交 offer，断线以 1–8 秒退避重连，并在页面关闭时尽力删除会话；M2 暂不实现 trickle ICE/PATCH。

RTSP URL 可能被 OBS 插件写入日志，因此核心日志处理器会把 `rtsp://user:password@host/...` 统一改写成 `rtsp://***:***@host/...`。不要把真实 URL 写入 Compose、README 或提交到 Git。

### M0 真实摄像头验收

配置本地 `.env` 后，使用专用入口录制至少 30 秒并自动执行完整解码、H.264、仅视频轨、分辨率、帧率、时长和非黑帧检查。每次运行使用新的 UTC 文件名，不会覆盖已有录像。

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

M1 使用独立门禁验证真实来源在持续录制期间接受 Web 控制：先把既有画面缩放到左侧并通过 API 在线添加同一摄像头的第二个来源，验证静音和音量配置后删除原来源，再把新来源恢复为全画布。测试至少继续录制 30 秒，停止后验证 H.264、仅视频轨、分辨率、FPS、完整解码和逐帧无空黑场。

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

M2 门禁在隔离的产品 Compose 项目中启动真实来源，通过本机 headless Chrome 建立同源 WHEP/H.264 播放，持续至少 30 秒后优雅停止产品，并验证浏览器 reader、容器退出状态、日志脱敏和最终 MP4。录像必须为 H.264、仅视频轨、指定分辨率与 FPS，可完整解码且无黑帧。

PowerShell：

```powershell
./tests/run-m2-real-camera.ps1
```

脚本按 `-EnvFile`、当前进程 `WEBOBS_RTSP_URL`、本地 `.env` 的顺序读取私有端点；已有镜像时可增加 `-SkipBuild`。端点只通过容器环境传入，一次性场景卷在退出时销毁；原始日志仅在内存中执行泄漏检查，写入忽略目录前会隐藏整个 RTSP 端点。此门禁要求可信的本机 Chrome，可用 `WEBOBS_CHROME_BIN` 指定其路径。

## 命令行接口

容器配置优先级为：命令行参数 > `WEBOBS_*` 环境变量 > 默认值。

```text
webobsd
  --rtsp-url <url>
  --scene-file <absolute-path.json>
  --listen-address <127.0.0.1|::1|0.0.0.0|::>
  --http-port <0..65535>
  --allow-insecure-remote <true|false>
  --webrtc-enabled <true|false>
  --whip-url <absolute-http-or-https-url>
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
- 不含音频轨
- 分辨率为 640×360
- 帧率为 10 FPS
- 时长在预期范围内
- 首帧不是空黑画面
- 4:3 测试源在 16:9 画布中等比居中，左右黑边对称且中心画面有效

同一入口还覆盖缺失 URL、无法连接、错误输出目录、已有文件拒绝覆盖、日志凭据脱敏，以及容器收到 `SIGTERM` 后完整冲洗并封装 MP4。M1 控制面验收另外覆盖 REST、安全响应头、ETag/`If-Match`、WebSocket 快照与广播、Host/Origin 拒绝、请求大小限制、原子持久化权限、在线来源增删、裁切/层级/可见性、不可达新来源回滚、解码首帧纹理预装、原子无黑帧切换，以及同一容器重启后的场景和录像恢复。M2 验收使用隔离的 headless Chrome 建立同源 WHEP/H.264 reader，覆盖错误媒体类型、跨源、超大 SDP、伪造令牌，并在产品容器重启后要求同一浏览器自动建立第二个 reader；重启后的录像仍须通过完整 MP4 验证。

烟测和真实摄像头验收会先执行公开仓库审计：检查 Git 索引中没有 `.env`、录像、测试产物、私钥文件或高置信度令牌，只允许明确列出的 RTSP 测试占位符，并确认 Git/Docker 忽略规则及 OBS submodule 固定提交未漂移。也可以单独运行 `./tests/run-public-audit.ps1` 或 `./tests/run-public-audit.sh`；审计只读取 Git 索引，不读取本地未跟踪 `.env` 的内容。

PowerShell：

```powershell
./tests/run-smoke.ps1
```

只运行 M1 控制面验收可使用 `./tests/run-control-plane.ps1 -SkipBuild`；只运行 M2 浏览器与重连验收可使用 `./tests/run-webrtc.ps1 -SkipBuild`；只运行 M3 双路 Direct 验收可使用 `./tests/run-direct.ps1 -SkipBuild`。浏览器门禁默认查找本机 Chrome，也可通过 `WEBOBS_CHROME_BIN` 指定可信的 Chrome 可执行文件。

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
obs-ffmpeg-mux
```

`obs-webrtc` 使用固定的 libdatachannel `0.21.0` 构建。WHIP URL 不接受 userinfo、查询参数或片段，避免令牌混入插件调试日志；当前内置 MediaMTX 使用无凭据的容器回环端点。之后编译 `webobsd` 和无外部测试框架的 CTest 单元测试。单元测试覆盖参数边界、CLI/环境变量优先级、WHIP URL 安全约束、RTSP 凭据脱敏、场景解析/迁移/存储和乐观并发变更计划。

## 退出状态

| 状态 | 含义 |
| ---: | --- |
| 0 | 成功或录制开始前收到正常停止信号 |
| 2 | 配置或命令行无效 |
| 3 | libobs、图形、音频或模块初始化失败 |
| 4 | RTSP 在超时前没有产生视频帧 |
| 5 | 编码器、muxer、目录或录制输出失败 |
| 6 | 最终 video-only MP4 封装失败 |
| 7 | 场景文件加载、迁移或原子持久化失败 |
| 8 | HTTP/WebSocket 控制监听器启动失败 |

## 许可证

本项目采用 `GPL-2.0-or-later`。OBS Studio 及其 submodule 保留各自的上游版权和许可证声明。

漏洞报告和凭据处理要求见 [SECURITY.md](SECURITY.md)。
