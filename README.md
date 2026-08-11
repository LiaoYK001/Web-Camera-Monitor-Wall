# Web Camera Monitor Wall

一个基于 `libobs` 的无桌面 Web 监控墙/合成器项目。仓库已经完成 **M0 Headless Proof**：无需 OBS Qt 界面，也能在 Linux Docker 容器中完成下面的闭环。

```text
RTSP camera -> libobs ffmpeg_source -> OBS scene -> obs_x264 -> video-only MP4
```

当前开发版本已能从持久化场景启动多路 RTSP 合成，但还没有 Web UI、HTTP API、WebRTC、正式 MediaMTX 服务、输出音轨或硬件编码；这些继续按路线图实现。

开发路线、里程碑验收标准和当前进度见 [ROADMAP.md](ROADMAP.md)。**M0 已通过全部验收；M1 Web Control 正在开发，当前已建立版本化场景、原子私有存储，并将多路布局接入 libobs 运行时。**场景与持久化契约见 [docs/scene-schema-v1.md](docs/scene-schema-v1.md)。

`WEBOBS_SCENE_FILE` 默认指向 `/config/webobs/scene.json`。首次启动使用 `WEBOBS_RTSP_URL` 创建并保存单路场景；后续启动以场景文件为准。手工编辑场景文件前应停止容器，且真实 RTSP 凭据不得提交到 Git。

## M0 技术基线

- OBS Studio `32.1.2`，固定 submodule 提交 `fb4d98bf88fae5fc85cb11fc57f7c5e309282194`
- Ubuntu 24.04、C++20、CMake 3.28+、x86_64
- X11/EGL + Xvfb + Mesa 软件合成
- x264 CBR、`veryfast`、High Profile、2 秒关键帧间隔
- RTSP 默认使用 TCP，硬件解码关闭
- 产品运行时只有一个 Docker 镜像，不开放网络端口

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

默认输出到 `recordings/webobs-<UTC timestamp>.mp4`。若 `WEBOBS_DURATION_SECONDS=0`，录制会持续到 `Ctrl+C` 或容器收到 `SIGTERM`；停止时会完成 muxer 和 MP4 封装。已有的显式输出文件不会被覆盖。

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

## 命令行接口

容器配置优先级为：命令行参数 > `WEBOBS_*` 环境变量 > 默认值。

```text
webobsd
  --rtsp-url <url>
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

烟测中的 MediaMTX 和 FFmpeg 只负责产生本地测试图 RTSP，不会进入产品镜像。测试夹具会从 MediaMTX 官方 GitHub Release 下载固定的 `v1.18.2` Linux amd64 二进制并校验 SHA-256，不依赖可变标签。测试会构建项目、录制约 10 秒，再检查：

- MP4 存在且可完整解码
- 唯一视频轨为 H.264
- 不含音频轨
- 分辨率为 640×360
- 帧率为 10 FPS
- 时长在预期范围内
- 首帧不是空黑画面
- 4:3 测试源在 16:9 画布中等比居中，左右黑边对称且中心画面有效

同一入口还覆盖缺失 URL、无法连接、错误输出目录、已有文件拒绝覆盖、日志凭据脱敏，以及容器收到 `SIGTERM` 后完整冲洗并封装 MP4。

烟测和真实摄像头验收会先执行公开仓库审计：检查 Git 索引中没有 `.env`、录像、测试产物、私钥文件或高置信度令牌，只允许明确列出的 RTSP 测试占位符，并确认 Git/Docker 忽略规则及 OBS submodule 固定提交未漂移。也可以单独运行 `./tests/run-public-audit.ps1` 或 `./tests/run-public-audit.sh`；审计只读取 Git 索引，不读取本地未跟踪 `.env` 的内容。

PowerShell：

```powershell
./tests/run-smoke.ps1
```

如果三个测试镜像已经成功构建，而 registry 暂时不可用，可显式复用本地镜像：`./tests/run-smoke.ps1 -SkipBuild`。这不会跳过录制、解码、失败路径或 SIGTERM 验收。

Linux shell：

```bash
./tests/run-smoke.sh
```

Linux 下对应使用 `WEBOBS_SKIP_BUILD=1 ./tests/run-smoke.sh`。

成功产物位于 `tests/artifacts/smoke.mp4`；SIGTERM 用例还会生成 `tests/artifacts/signal.mp4`。该目录内容不会进入 Git。

## 本地 CMake 结构

Docker 构建会先配置 OBS，并只编译以下目标：

```text
libobs
libobs-opengl
obs-ffmpeg
obs-x264
obs-ffmpeg-mux
```

之后编译 `webobsd` 和无外部测试框架的 CTest 单元测试。单元测试覆盖参数边界、CLI/环境变量优先级和 RTSP 凭据脱敏。

## 退出状态

| 状态 | 含义 |
| ---: | --- |
| 0 | 成功或录制开始前收到正常停止信号 |
| 2 | 配置或命令行无效 |
| 3 | libobs、图形、音频或模块初始化失败 |
| 4 | RTSP 在超时前没有产生视频帧 |
| 5 | 编码器、muxer、目录或录制输出失败 |
| 6 | 最终 video-only MP4 封装失败 |

## 许可证

本项目采用 `GPL-2.0-or-later`。OBS Studio 及其 submodule 保留各自的上游版权和许可证声明。

漏洞报告和凭据处理要求见 [SECURITY.md](SECURITY.md)。
