# 反馈5 整改验收报告 / Feedback 5 acceptance report

> 基线：`5fec735` + 工作区未提交改动（本地启动脚本、转码器路径修复等）。
> 本报告区分**已在本机复现并验证**与**已实现但未在本轮实测**两项，不以页面绿灯代替媒体验证。
> Baseline: `5fec735` plus the uncommitted working tree. Each item is marked *verified* or *implemented, not yet run*.

## 自动化验证快照 / Automated verification snapshot

截至 `5d57d1a` 在 WSL2 Ubuntu-24.04 环境复现：

| 套件 | 命令 | 结果 |
|---|---|---|
| 前端类型检查 | `web\node_modules\.bin\tsc.CMD --noEmit` | 0 错误 |
| 前端运行时 | `playwright test -c playwright.local.config.ts --project=chrome`（monitor-view / wall-controls / playback-state） | 通过（含填充、几何、无音轨三态、首帧、退避、授权拒绝、编码探测） |
| Camera Registry | `python3 -m unittest tests.test_camera_registry` | 26/26 通过（含探测缓存并发合并/失效） |
| 启动器 | `node --test tests/test-dev-launcher.mjs` | 7/7 通过（含 Composite 参数与帮助） |
| C++ 核心 | `ninja -C ~/.cache/webobs-dev/<hash>/core-local` + `webobs-unit-tests` | 编译通过、单测全过（含 NVENC 就绪与 Program 分阶段状态） |

未列入上表的实测（真实五路长稳、端到端 Composite 发布、OBS 侧 NVENC、Docker/vGPU）仍需在具备来源的环境中执行，见文末“未在本轮实测”。

## 本机实测事实 / Verified on this machine

- GPU：NVIDIA GeForce RTX 3090（driver 616.92），WSL2 Ubuntu-24.04；**只有 `/dev/dxg`，没有 `/dev/nvidia0` / `/dev/nvidiactl`**。
- `libcuda.so.1` / `libnvcuvid.so.1` / `libnvidia-encode.so.1` 均在 `/usr/lib/wsl/lib` 可加载。
- ffmpeg 6.1.1：`h264_nvenc` / `hevc_nvenc` 编码小样与 `-hwaccel cuda` 解码小样**均通过**。
- 结论：反馈截图中 “NVIDIA NVENC 不可用” 的根因是 C++ 探测只认 `/dev/nvidia0`，与真实能力无关。

## F5-01 画面填充 / wall fill — 已实现并验证

- 自动布局改为确定性 squarified treemap：1/2/4/5/9/16 路与“两大三小”**覆盖率 100%**、无重叠、无越界、重复应用稳定。
- 新增 `MonitorView.fill`（默认 `stretch`）与逐来源覆盖；自动布局把有效 `scaleMode` 写入场景，Direct 与 Composite 共用同一有效布局。
- 视频、检测框、遮罩与叠加层统一走 `tileTransform`，检测框不再漂移。
- 验证：`monitor-view.spec.ts`（含新增 “fills the canvas…”、“keeps detection boxes…”）。

## F5-02 画面外诊断 / out-of-picture status — 已实现并验证

- 移除画面内黄色诊断按钮、状态胶囊与名称；新增画布外来源状态区（名称/实际状态/告警数/问题中心入口，可键盘操作）。
- 无画面时仅显示简洁占位，正常播放不再被按钮遮挡。
- 问题中心已按“来源+问题类型+组件”合并，并以 `resolved` 更新而非堆积。
- 验证：`wall-controls.spec.ts` 断言无 `.tile-status-button`/状态胶囊/名称，且有状态区。

## F5-03 NVIDIA 探测与加速 / NVIDIA detection and acceleration — 已实现，路径已实测

已实现并验证：
- `scripts/hardware-probe.py`：分别探测设备节点、库可加载、编码器注册、实际编码/解码小样，带超时与按环境签名缓存。
- C++：`video_encoder_backend_ready(kind, backend)` 按后端判定；NVENC 不再依赖 VA-API 字段，支持 `/dev/dxg` 与 `/dev/nvidia0`；硬件状态 JSON 分能力上报并新增 `libraryLoaded` 与硬件解码 `backend`。
- gateway 转码器：优先 CUDA 解码 + NVENC（`-preset p1 -tune ll -bf 0`），CUDA 不可用时软件解码 + NVENC 并标注“部分加速”，保留 VA-API/x264 回退。
- 验证：WSL 内 `g++` 编译并运行编码器就绪逻辑测试通过；增量构建 `webobsd`/`webobs-unit-tests` 成功；C++ 单测全部通过；`transcode-on-demand.sh` 语法检查通过，NVENC（CUDA 解码与软件解码两种）真实产出文件。

未在本轮实测 / not yet run：
- OBS 侧 NVENC 编码器（`obs-nvenc`）只有在 Composite 构建启用插件后才注册；本轮未执行该构建，因此 OBS 编码能力仍应显示为“未注册”。
- Docker / vGPU 实机验收按约定留待后续。

## F5-04 本地服务端合成 / native Composite — 启动链路已实现，端到端未实测

已实现：
- `-Composite` / `--composite` 贯通 PowerShell、Node、Python 启动器；不带参数保持 Direct-only 轻量默认。
- 构建缓存按功能组合隔离（`obs-composite` / `core-composite`），避免复用“仅 libobs”缓存。
- Composite 构建启用 OBS 插件但**显式排除 CEF/浏览器插件**，按需构建并校验 `obs-ffmpeg` / `obs-x264` / `obs-webrtc`，缺失时报具体模块名。
- 启动前运行硬件探测并导出 `WEBOBS_NVIDIA_*`；`WEBOBS_COMPOSITE_ENABLED` 随参数切换。
- 前端：分别显示未启用/依赖不完整/引擎失败/发布失败/浏览器连接失败，并给出 `.\scripts\dev.ps1 -Setup -Composite`、`.\scripts\dev.ps1 -Composite` 与日志目录。
- 后端分阶段状态：`/api/v1/program/status` 新增 `configuration`（disabled/incomplete/ready）、`engine`（stopped/ready）、`publish`（idle/publishing）与 `reason`（composite_disabled / webrtc_transport_disabled / engine_not_active / whip_output_not_ready），由运行状态如实推导，不再让前端只能显示“未知”。
- 验证：`python3 scripts/dev-native.py --check --composite` 通过；`tests/test-dev-launcher.mjs` 7/7 通过（含 Composite 帮助与参数校验）；C++ 核心重新编译通过且单测全过（含新增字段的 control_server）。

未在本轮实测 / not yet run（**不得视为已支持**）：
- 实际执行 `-Setup -Composite` 的 OBS 插件构建：本轮在 WSL 逐项复现出**具体阻塞点**（均为可执行的环境/脚本问题，非代码逻辑）：
  1. `libx264-dev` 缺失导致 obs-x264 无 `x264.h` —— 已加入 `dev-native.py` 的依赖列表；
  2. 仅加 `-DENABLE_PLUGINS=ON` 会在可选采集插件处配置失败（先 `LibAJANTV2`/aja，再 `XCB COMPOSITE`/linux-capture）—— 需显式 `-DENABLE_AJA=OFF -DENABLE_DECKLINK=OFF -DENABLE_VLC=OFF`（并可能补 `libxcb-composite0-dev`）；
  3. `check_obs_browser()` 在 `ENABLE_PLUGINS=ON` 时无条件要求 obs-browser **子模块内容**，而 `dev-native.py` 的 WSL 快速路径用 `git archive` 生成 Linux 存储源码，**archive 不含子模块**，因此必然配置失败。
  4. 按上述修复后 configure 已能依次越过 aja→XCB→obs-browser→FFmpeg(avfilter/avdevice)→Libva→Libpci→MPEGTS(SRT/RIST)→SpeexDSP，最终停在 **`LibDataChannel` 缺失**（`plugins/obs-webrtc/CMakeLists.txt:9`）。obs-webrtc 是 Composite 发布到 MediaMTX 的 WHIP 输出所必需，而 `libdatachannel` **不是 Ubuntu 24.04 的 apt 包**，需要像 Docker 镜像那样单独构建/安装。
  结论（本轮已更新）：源码构建并安装 libdatachannel v0.22.6 后，`cmake` 配置成功生成 `build.ninja`，且 **`obs-ffmpeg.so` / `obs-x264.so` / `obs-webrtc.so` 三个插件全部编译链接成功**（位于 `rundir/Release/lib/obs-plugins/`），启动器的模块校验可通过。上述依赖与开关、子模块复制、libdatachannel 源码构建均已固化进 `dev-native.py`。
  进一步实测：项目 C++ 后端以该 Composite OBS 构建重新配置并编译成功（`core-local-composite`：`webobsd` 与 `webobs-unit-tests` 链接通过），且 **`webobs-unit-tests` 全部通过**（`LD_LIBRARY_PATH` 指向该构建的 libobs）。
  **仍未实测**：真正启动 OBS 合成引擎并把五路来源经 MediaMTX 发布为 Program WHEP（需要真实五路摄像头会话）。
- 真实五路来源 → OBS 合成 → H.264/Opus → MediaMTX → Program WHEP 的发布与浏览器持续解码；`/api/v1/program/status` 的运行时返回未在真实合成会话中抓取。

## F5-05 多音轨 / per-source audio tracks — 界面过滤已实现，真实多音轨通路未实现

已实现：
- 音轨状态三态：只有**真正绑定媒体流且音轨数为 0** 才判定“该源没有音频轨道”（无 capability 不再误报）；已挂载未绑定流、Profile 未探测或探测失败显示“音频轨道待探测”并提供“重新探测”入口；纯色/文字/图片/嵌套来源直接判定无音轨。确认无音轨的来源隐藏电平/阈值/音量控制；有音轨来源可配置方向/位置/大小/透明度、阈值与告警边框。
- 电平表默认 OBS 风格左侧竖放，不遮挡画面标签。
- 验证：`wall-controls.spec.ts` 断言未探测摄像头显示待探测 + 重新探测按钮且不显示电平选项。

未实现 / not implemented（本轮范围外，明确列为后续项）：
- 同源多音轨的真实媒体通路：每条启用音轨独立 audio-only WHEP 通道、原始音轨索引到代理流索引的映射、按“来源+输入音轨”的 Gain/Analyser/Delay、Composite 逐轨混音、Scene v6 `audioInputs` 迁移。
- AudioWorkspace 已按共享三态规则隐藏“确认无音轨”来源的音量/监听/电平控制（未知来源保留控制，不误伤）；仍缺音轨复选框与“合并/独立电平”显示。

## F5-06 五路播放稳定性 / playback stability — 状态机已实现并验证

- `whep.ts`：信令/ICE/媒体轨道/首帧/持续播放分开记录，**只有 `requestVideoFrameCallback` 呈现真实帧才进入 `live`**；20 秒首帧超时、6 秒帧停滞看门狗（后台暂停不误判）、带抖动的有界退避、连接代次校验、迟到响应释放；自动播放被阻止与媒体失败分开处理并提供 `resume()`。
- 探测缓存与并发合并：同一 Camera/Profile 的 ffprobe 结果按“端点哈希+传输方式”缓存（TTL 默认 15 秒，键不保留原始 URL），并发调用等待在途探测并复用结果（一次 ffprobe 服务多个调用者），Camera 保存/目录变更按来源失效。
- 真实拓扑标注：状态区按 `webobs:media-topology` 区分真直连 / 网关转发 / Hybrid 转码 / Composite，不再把全部正常播放标成“直达”（未知时回退“播放中”）。
- 浏览器能力运行时探测：媒体计划只声明本机 `MediaSource.isTypeSupported` 实际支持的编码（H.265/WebCodecs 不再无条件宣称，H.264 为基线兜底），避免规划出客户端无法解码的直连路径。
- 授权失败不再无限重连：WHEP 收到 401/403 时记录 `authorization_rejected`、释放会话、进入重新配对指引并停止退避重试（`getStage().lastError` 可查），避免对未授权来源反复请求。
- 验证：`playback-state.spec.ts` 用脚本化 `RTCPeerConnection` + stub rVFC 断言“ICE 连接不等于 live”，并验证 ICE 失败后的抖动重连；`test_camera_registry.py` 覆盖并发合并、TTL 命中与变更失效（26/26 通过）；`monitor-view.spec.ts` 覆盖拓扑标签映射。

未在本轮实测 / not yet run：
- 真实五路 ≥30 分钟长稳、首帧 ≤20 秒统计、解码帧率 ≥90%、人为断开单路恢复、CPU/GPU 占用与慢读丢包归因。
- 转码/路由创建的引用计数与长期闲置回收、脱敏诊断摘要导出。

## 运行与验证命令 / Commands

```powershell
# 硬件能力（WSL 内）
python3 scripts/hardware-probe.py --json

# 前端相关测试（Chrome）
cd web; node node_modules/@playwright/test/cli.js test -c playwright.local.config.ts --project=chrome -g "monitor-view|playback-state"

# 启动器测试
node --test tests/test-dev-launcher.mjs

# 原生 Composite（首次构建较久；本轮未执行）
.\scripts\dev.ps1 -Setup -Composite
.\scripts\dev.ps1 -Composite
```

## 结论 / Conclusion

F5-01、F5-02、F5-06 状态机与探测缓存已实现并有自动化验证；F5-03 的探测根因已在本机复现并修复，C++/转码路径已编译与实测，但 OBS 侧 NVENC 与 Docker/vGPU 未验收；F5-04 启动与状态链路已实现、端到端合成未实测；F5-05 完成无音轨/待探测/有音轨三态过滤与重探入口，真实多音轨通路与 AudioWorkspace 分组仍未实现。**“画面干净且完整、加速状态真实”已达成；“五路持续出图、本地合成可用、多音轨实际可控”仍需在具备五路来源的环境中按上文命令继续实测。**
