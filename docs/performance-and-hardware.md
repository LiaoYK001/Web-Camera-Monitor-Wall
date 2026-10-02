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

当前 Windows + RTX 3090 的 `dev-lan` 默认采用 Direct/WHEP 转发时，MediaMTX 处理网络包而不做视频编解码；服务端 NVIDIA Encoder/Decoder 显示 0% 并不代表没有使用浏览器的硬件解码。开启另一个监控页、Studio 实时布局预览或独立投影会增加读者和浏览器解码负载。先在“系统状态 / 视频加速”查看 MediaMTX、FFmpeg、OBS 的 CPU 与实例数，再按实际转码原因选择硬件路径；不要为了让 GPU 数字上升而把能直通的来源强制转码。Fedora/Podman 的 AMD 核显仅在 VA-API render node、容器设备挂载和运行探测同时通过时承担 Hybrid/Composite 编解码，Direct 转发同样不会消耗服务端视频编码器。

In Windows dev-lan, a compatible Direct/WHEP source is relayed by MediaMTX; server NVIDIA encoder/decoder activity may correctly remain at zero while the viewing browser decodes video. Extra monitor tabs, Studio live layout previews, and projector windows add readers and client decode work. Inspect MediaMTX, FFmpeg, and OBS CPU/instance counts before changing an encoder. On Fedora/Podman, the AMD iGPU is used for Hybrid/Composite only after the VA-API render node, device mapping, and runtime probe pass; Direct relay does not require server video encoding.

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

## 5. 浏览器更新开销 / Browser update cost

音频运行状态、音轨增减和增益/静音变化仍立即更新监控墙；100 ms 电平采样由电平表与音频状态组件单独订阅。阈值检测读取最新采样，不依赖视频组件重新渲染。隐藏页面暂停电平表绘制，返回时读取最新快照；普通浏览器的后台声音监听继续遵循用户设置，Android 的暂停/恢复仍由原生生命周期控制。收起混音器会停止该面板的电平订阅。

Runtime and track changes still update the wall immediately. Meter components subscribe separately to the 100 ms audio samples; threshold checks read fresh samples without rendering video tiles. Hidden pages pause meter rendering and refresh from the current snapshot on return. Browser background listening follows the user's setting; Android audio follows its native lifecycle. Collapsing the mixer removes its meter subscription.

账号偏好保留每 5 秒及重新聚焦时的同步，但相同的归一化配置保留对象引用，避免重复布局计算与重建轮播计时器。分析任务按配置采样率请求新视频帧，最多保留一个待处理帧回调；暂停后取消采样计时器和回调。音频工作台的 Composite 电平请求完成后等待 250 ms 再发起下一次，隐藏时取消请求，恢复时立即读取；过期响应和 Direct 电平事件不能覆盖 Composite 数据。

Account synchronization remains active every five seconds and on focus. Identical normalized preferences retain their object identity. Analytics requests fresh frames at the configured sample rate with at most one pending frame callback and cancels work on stop. Composite meters wait 250 ms after each completed request, cancel on hide, and refresh immediately on return. Stale responses and Direct meter events cannot overwrite Composite values.

可复现回归 / Reproducible regression:

```powershell
cd web
pnpm exec playwright test -c playwright.local.config.ts --project=chromium performance.spec.ts
```

该开发夹具使用 12 路 canvas 视频和变化的合成音频分析数据，记录 React Profiler 耗时、场景字段读取、连接建档次数与播放时间。一次本机 4 秒对比中，React 渲染累计耗时由约 376 ms 降至 16–21 ms，音频采样期间的布局读取由 4,960 次降至 0；12 个既有连接保持不变。时间值只作开发模式的局部性能证据，回归门禁使用无重复布局、持续播放与无额外连接等行为约束，不设置不稳定的耗时阈值。

The fixture uses 12 canvas video streams and changing synthetic analyser values. It records React Profiler duration, scene reads, session creation and playback progress. A local four-second comparison reduced accumulated React render time from approximately 376 ms to 16–21 ms and scene reads from 4,960 to zero, preserving all 12 connections. Timings describe this development fixture, not total CPU usage or physical-camera performance. Regression gates use stable behavioral checks rather than timing thresholds. Windows/Android protocol smoke tests and physical-camera qualification must be reported separately.

## 6. 后台读取与统计 / Background reads and statistics

系统状态、客户端授权、分析策略、节目诊断与固定 Scene 投影使用同一轮询生命周期：每页最多一个读取批次，完成后再等待原有间隔；浏览器隐藏或 Android Activity 进入后台时取消读取，返回前台、聚焦或网络恢复时立即刷新。最后成功结果保留在页面中。保存分析策略、批准/完成配对或撤销设备会取消先前读取，并在操作结束后重新读取；过期响应不能覆盖新结果，自动刷新也不会清除操作失败的提示。固定场景内容相同时保留对象，避免重算投影布局。这些规则仅适用于上述只读界面；账号同步、录像租约、播放连接及后台声音仍遵循各自生命周期。

System status, client authorization, analytics policies, program diagnostics and fixed Scene projectors allow one read batch per page, waiting the existing interval after completion. Reads are canceled when the browser or Android Activity is hidden, retaining the last successful result; visibility, focus and network recovery trigger a fresh read. Policy and client mutations invalidate prior reads and refresh afterward. Late responses cannot overwrite the result and polling cannot erase action failures. Identical fixed scenes retain object identity. Account synchronization, recording leases, media connections and background listening keep their own lifecycles.

每个 WebRTC peer 的诊断与弱网检测共享一个进行中的 `getStats()`，已完成的报告最多复用 200 ms（从请求发起时计时）；只留在内存中，连接关闭/替换时立即失效。帧率与速率使用报告自身时间戳，重复样本或计数器重置显示暂不可用，避免误报为零。音频存活检测也限制一个进行中的统计读取，并拒绝旧连接的晚到报告；原有弱网优化开关、拥塞阈值、抖动缓冲上限与音频后台存活策略保留。

Telemetry and congestion detection share one pending native `getStats()` per WebRTC peer, reusing completed reports for at most 200 ms from request start. Reports remain in memory and are invalidated on peer disposal. Rates use report timestamps; duplicate samples and counter resets are unavailable rather than misleading zeroes. Audio liveness allows one pending read and rejects old-peer results. Existing optimization controls, congestion thresholds, buffer bounds and background audio liveness remain active.

```powershell
cd web
pnpm exec playwright test -c playwright.local.config.ts --project=chromium polling-performance.spec.ts peer-stats-performance.spec.ts playback-optimization-runtime.spec.ts
```

测试用受控慢响应验证每端点最多一个请求、隐藏期间零新增读取、恢复立即读取、卸载取消最新请求、保存与读取的竞态，以及 12 个诊断读取加一个 watchdog 检查只触发一次原生统计。它们是合成浏览器回归，不代表真实摄像机、整机 CPU 或带宽的性能测量。

Controlled slow-response tests cover bounded reads, no new hidden-page requests, immediate resume, current-request cancellation on unmount, mutation races and one native sample for 12 telemetry consumers plus the watchdog. These are synthetic browser regressions, not physical-camera, whole-system CPU or bandwidth benchmarks.
