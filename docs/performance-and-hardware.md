# 视频硬件与性能验收指南

## 1. 执行链原则

v1 默认优先级是 Gateway Direct relay、Gateway Direct 单轨必要转码、Hybrid hardware transcode、Composite hardware、Composite software fallback。Gateway Direct-only 进程不会调用 `obs_startup`，因此没有服务端视频解码、场景合成或 H.264 编码；但 MediaMTX 仍在 WHEP reader 存在时拉取并转发 RTP/WebRTC 包，所以当前 `direct` 是网关直通，不是 Docker 退出媒体数据面的真直连。

```text
True Direct (v2 planned): Camera/local endpoint -------------> local client decode (Docker video bytes = 0)
Gateway Direct (v1):      Camera -> Docker MediaMTX relay ----> Browser GPU decode
Composite:                Camera -> VAAPI decode -> GPU scene -> VAAPI encode -> Program
Fallback:                 Camera -> software decode -> llvmpipe -> x264 -> Program
```

Hybrid 会分别判断视频和音频：兼容轨道使用 copy，不兼容轨道才转码。AMD 路径使用 VAAPI decode 与 `h264_vaapi`；真实 probe 或运行失败时回落 `libx264`，日志不包含来源 URL。

## 2. AMD VA-API 部署

宿主先确认 render node 和驱动：

```bash
ls -l /dev/dri/renderD128
vainfo --display drm --device /dev/dri/renderD128
```

Docker：

```bash
docker compose -f compose.yaml -f compose.m6-vaapi.yaml up -d --build
```

Fedora/Podman 见 [`deploy/README-podman.md`](../deploy/README-podman.md)。容器内可执行：

```bash
docker exec web-camera-monitor-wall vainfo --display drm --device /dev/dri/renderD128
```

`GET /api/v1/system/capabilities` 分开返回 `devicePresent`、`vaDriverLoaded`、`encodeSupported`、`decodeSupported`、`runtimeProbePassed`、`selected`、`fallback` 与 `fallbackReason`。要求 VAAPI 时的通过状态是 requested 为 `auto`/`vaapi`、selected 为 `vaapi`、fallback 为 false，且 VAAPI 的全部必要布尔值为 true。

Renderer 使用 `WEBOBS_RENDERER=auto|hardware|software`。`auto` 在 VAAPI probe 成功后尝试 Weston headless EGL 和 Xwayland，并拒绝 llvmpipe/softpipe；失败后启动 Xvfb llvmpipe。Gateway Direct-only 显示 `idle`，因为它根本不需要场景 renderer。硬解可全局设置 `WEBOBS_HARDWARE_DECODE=auto|on|off`，并由 Camera Registry 的逐设备值及 Scene source 覆盖。

## 3. Gateway Direct/Hybrid 诊断

实时监看中的每路 tile 会显示：

- `DIRECT RELAY` 或 `HYBRID`；
- Video/Audio 分别为 copy 或 transcode；
- 服务端视频 Decode/Encode 开关及 fallback 原因；
- LOW（转发）、MEDIUM（音频转码）或 HIGH（视频转码/Composite）成本。

“系统状态 / 视频加速”每 5 秒读取 `/api/v1/system/processes`，拆分 `webobsd`、`mediamtx`、`ffmpeg`、`caddy`、`obs-browser` 的 CPU/RSS，并显示 RTSP TCP session 数、AMD GFX busy、OBS engine 与 Composite publisher 是否活动。首次 CPU 采样为 0，第二次起按相邻 `/proc` tick 计算。

## 4. 标准 benchmark

对完全相同的 1/4/9 路来源分别启动待测模式，再运行：

```bash
./scripts/benchmark-video-pipelines.sh --label direct-4 --duration 120
./scripts/benchmark-video-pipelines.sh --label composite-vaapi-4 --duration 120
./scripts/benchmark-video-pipelines.sh --label hybrid-cpu-4 --duration 120
./scripts/benchmark-video-pipelines.sh --label hybrid-vaapi-4 --duration 120
```

CSV 记录容器 CPU、内存/网络、逐进程 CPU/RSS、FFmpeg 进程数、RTSP session 与 GPU busy。另用 `radeontop`、`amdgpu_top` 或宿主等价工具记录 GFX、VCN Decode、VCN Encode，并记录端到端延迟。结果属于本地测试产物，不应提交 Git。

Gateway Direct 验收不绑定一个不可靠的固定百分比，而要求：浏览器兼容 H.264/Opus 或 G.711 来源不出现 FFmpeg transcoder；`engineActive=false`、`compositePublisherActive=false`；增加摄像机时 CPU 不出现接近软件解码/编码的线性增长。它仍会产生 Docker 网络流量和 MediaMTX 上游会话。若失败，依次检查 Hybrid 原因、Program reader、FFmpeg 进程、RTSP session 重复和浏览器是否仍持有旧 WHEP session。v2 True Direct 的独立零媒体数据面门禁见 [true-direct-v2.md](true-direct-v2.md)。
