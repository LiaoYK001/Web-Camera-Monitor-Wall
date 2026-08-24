# v2 True Direct architecture / v2 真直连架构

> Status / 状态：`v2-M1` implementation in progress on `dev`; not yet accepted / `dev` 正在实施 `v2-M1`，尚未完成验收
>
> Current implementation / 当前实现：v1 provides **Gateway Direct / Direct Relay**, not True Direct / v1 提供的是**网关直通**，不是真直连

## 1. Precise terminology / 精确定义

| Mode / 模式 | Media path / 媒体路径 | Server video work / 服务端视频工作 | Is Docker in the media data plane? / Docker 是否经过媒体数据 |
| --- | --- | --- | --- |
| True Direct / 真直连（v2 目标） | Camera or local endpoint → client / 摄像机或本地端点 → 客户端 | None / 无 | **No / 否** |
| Gateway Direct / 网关直通（v1 当前 `direct`） | Camera → MediaMTX in Docker → WHEP/WebRTC → browser / 摄像机 → Docker 内 MediaMTX → 浏览器 | Packet forwarding only when compatible / 兼容时只转发数据包 | **Yes / 是** |
| Hybrid / 混合 | Camera → on-demand per-track conversion → browser / 摄像机 → 按需逐轨转换 → 浏览器 | Only incompatible tracks are converted / 只转换不兼容轨道 | **Yes / 是** |
| Composite / 服务端合成 | Camera → decode → libobs render/mix → encode → browser / 摄像机 → 解码 → libobs 合成 → 编码 → 浏览器 | Decode, render and encode / 解码、渲染、编码 | **Yes / 是** |

The existing API value `direct` remains stable throughout API v1, but its display name is **Gateway Direct / Direct Relay**. Renaming the enum would break existing scenes and clients without changing the actual topology. `true-direct` is a separate future capability and must never be inferred from `direct`.

现有 API v1 的 `direct` 值保持兼容，但界面名称统一为**网关直通 / Direct Relay**。仅修改枚举名称既会破坏现有场景和客户端，也不会改变真实拓扑。未来的 `true-direct` 是独立能力，绝不能从 `direct` 暗中推断。

## 2. v2.0 core proposition / v2.0 核心卖点

**One camera registry and canvas model, multiple local runtimes, with an optional Docker control plane that is outside the media path by default.**

**一份 Camera Registry 与画布模型，多种本地运行端；Docker 默认只作为可选控制面，不进入媒体数据面。**

- Android and desktop clients connect to camera profiles directly, decode with local hardware, and render the shared layout locally / Android 与桌面客户端直接连接摄像机 Profile，使用本机硬件解码并在本地渲染共享布局。
- The Docker Web service may provide static UI assets, device/scene synchronization, authorization policy, discovery coordination and optional signaling, but True Direct video bytes do not traverse it / Docker Web 可提供静态界面、设备/场景同步、授权策略、发现协调与可选信令，但真直连视频字节不经过它。
- A local/offline client can retain an encrypted, revocable copy of approved device and scene metadata and continue operating when Docker is unavailable / 本地或离线客户端可保存经授权、加密且可撤销的设备与场景元数据，并在 Docker 不可用时继续运行。
- Gateway Direct, Hybrid and Composite remain explicit fallbacks for browser compatibility, remote access, filters, overlays, transitions, unified Program output and server-side recording / 网关直通、Hybrid 与 Composite 继续作为浏览器兼容、远程访问、滤镜、叠字、转场、统一节目输出及服务端录像的显式后备。

This makes v2 a local-first monitoring platform rather than a promise that every web browser can decode every camera protocol.

这使 v2 成为“本地优先”的监控平台，而不是声称任意浏览器都能解码任意摄像机协议。

## 3. Browser and client boundary / 浏览器与客户端边界

A standard browser cannot open ordinary `rtsp://` streams directly. True Direct therefore requires at least one of these paths:

普通浏览器不能直接打开常规 `rtsp://` 流。真直连必须使用以下至少一种路径：

1. A native Android or desktop client connects to RTSP/ONVIF and decodes locally / 原生 Android 或桌面客户端直接连接 RTSP/ONVIF 并本地解码。
2. A local companion process exposes a loopback-only, authenticated browser-compatible transport while the camera traffic remains on that device / 本机伴随进程通过仅回环、受认证的浏览器兼容协议提供媒体，摄像机流量仍只到该客户端设备。
3. The camera or an operator-selected local endpoint natively provides WebRTC/WHEP/HLS or another browser-compatible transport under acceptable origin and TLS policy / 摄像机或操作者指定的本地端点原生提供 WebRTC/WHEP/HLS 等浏览器兼容协议，并满足 Origin 与 TLS 策略。

Loading HTML, JavaScript or a PWA shell from Docker does not by itself make RTSP True Direct. If MediaMTX in Docker receives or forwards the packets, the mode is Gateway Direct.

从 Docker 加载 HTML、JavaScript 或 PWA 外壳，本身不会让 RTSP 变成真直连。只要 Docker 内 MediaMTX 接收或转发了媒体包，该模式就是网关直通。

## 4. Topology negotiation / 拓扑协商

The low-server-cost selection order for v2 is:

v2 的低服务端成本优先级为：

1. `true-direct`: client-to-camera/local endpoint; client decode and render / 客户端直连摄像机或本地端点，本地解码与渲染。
2. `gateway-direct`: server packet forwarding without video decode/encode / 服务端只转发包，不做视频解码或编码。
3. `hybrid`: convert only incompatible tracks, preferring local or hardware conversion / 只转换不兼容轨道，优先本地或硬件转换。
4. `composite`: server decode/render/encode when OBS-class functions are requested / 需要 OBS 类能力时由服务端解码、渲染和编码。

Every source exposes the selected topology, reason, decoder, renderer, encoder, upstream session owner and fallback reason. A user choice never silently starts another server media graph.

每个来源都展示已选拓扑、原因、解码器、渲染器、编码器、上游会话所有者及回退原因；用户选择一种模式时，不得在后台静默启动另一套服务端媒体图。

## 5. Security contract / 安全契约

- Camera credentials are never embedded in scene JSON, URLs returned to arbitrary page JavaScript, logs, metrics, support bundles, Git or public test artifacts / 摄像机凭据不进入场景 JSON、返回任意页面 JavaScript 的 URL、日志、指标、支持包、Git 或公开测试产物。
- Native/local clients use explicit enrollment, least-privilege camera-profile grants, revocation and OS-backed secret storage where available / 原生或本地客户端使用显式配对、最小权限 Profile 授权、可撤销凭据，并尽可能使用系统密钥存储。
- Local companion endpoints bind to loopback by default, authenticate every request, reject foreign origins and do not expose camera credentials / 本机伴随端点默认只监听回环，认证每个请求，拒绝外部 Origin，且不暴露摄像机凭据。
- Discovery and direct LAN access are opt-in and bounded to operator-approved interfaces and ranges / 发现与局域网直连需显式启用，并限制在操作者批准的接口和范围内。
- Offline metadata is encrypted, expires or is revocable, and never converts an online administrator credential into a permanent portable secret / 离线元数据必须加密、可过期或撤销，不能把在线管理员凭据变成永久可携带密钥。

## 6. Acceptance gate / 完成门禁

`v2-M1` cannot claim True Direct until all of these are automated or repeatably evidenced:

只有下列条件均获得自动化或可重复证据后，`v2-M1` 才能宣称真直连：

- For an active True Direct camera, Docker has no camera upstream session, MediaMTX reader, FFmpeg transcoder, libobs source or Program encoder attributable to that view / 真直连画面活动时，Docker 内不存在归属于该画面的摄像机上游会话、MediaMTX reader、FFmpeg 转码器、libobs 来源或 Program 编码器。
- Server interface counters or packet capture show zero video payload bytes for the session after bounded control/bootstrap exchange / 有界控制或启动交换结束后，服务端网卡计数或抓包证明该会话的视频负载字节为零。
- The UI and API report `true-direct`; any fallback changes the visible mode and reason before media starts / UI 与 API 报告 `true-direct`；任何回退都必须在媒体开始前改变可见模式并说明原因。
- Local hardware decode, multi-tile layout and reconnect pass on published Android/desktop reference profiles / 本地硬解、多宫格布局与重连在公开 Android/桌面参考配置上通过。
- An enrolled client can start from its encrypted cache while Docker is unavailable, within a documented offline authorization window / 已配对客户端可在 Docker 不可用时从加密缓存启动，并遵守公开的离线授权时限。
- Credential, origin, loopback, revocation, downgrade and public-repository redaction tests pass / 凭据、Origin、回环、撤销、降级与公开仓库脱敏测试通过。

The API/grant/planner, administrator approval UI and Qt/GStreamer reference source are implemented and pass deterministic cryptographic, proxy, WebUI and compile gates. `tests/run-v2-true-direct.{sh,ps1}` additionally places Docker on a control-only network, completes enrollment and an encrypted Grant, decodes an H.264 RTSP stream in the client fixture, and proves that Docker cannot resolve the camera network and has no MediaMTX/FFmpeg/Program helper. This is architecture-level evidence, not the locked Qt receiver or hardware acceptance. H.265, MJPEG, HLS and WHEP under the locked release dependencies, packet-counter evidence, 1–16-viewer/NVR coexistence and platform hardware gates remain open. Until they pass, product text must say **True Direct development preview** and must not describe Gateway Direct as server-bypass delivery.

API/Grant/规划器、管理员批准界面及 Qt/GStreamer 参考源码已经实现，并通过确定性密码学、代理、WebUI 与编译门禁。`tests/run-v2-true-direct.{sh,ps1}` 还会让 Docker 只接控制网络，完成配对与加密 Grant，由客户端夹具解码 H.264 RTSP，并证明 Docker 无法解析摄像机网络且不存在 MediaMTX/FFmpeg/Program helper；这只是架构级证据，不是固定 Qt 接收端或硬件验收。固定发布依赖下的 H.265、MJPEG、HLS、WHEP、包计数证据、1～16 观看端与 NVR 共存及平台硬件门禁仍未完成。在这些证据完成前，产品文案只能写“真直连开发预览”，不得把网关直通描述为绕过服务端的数据路径。

Run the architecture fixture only with a locally built development image; it uses public synthetic credentials and endpoints and writes no private evidence:

架构夹具只针对本地开发镜像运行，使用公开的合成凭据与端点，不写入私有验收证据：

```powershell
./tests/run-v2-true-direct.ps1 -Image webobs:v2-m1-dev
```

```bash
WEBOBS_TEST_IMAGE=webobs:v2-m1-dev ./tests/run-v2-true-direct.sh
```
