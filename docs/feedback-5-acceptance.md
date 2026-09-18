# 反馈5 整改验收报告（当前状态）/ Feedback 5 acceptance report (current state)

日期 / Date：2026-09-19。
被测代码 / Code under test：Commit `93f790a`（渲染器探测与 OBS NVENC）+ `587e329`、`425d5df`、`f09dcaf`（批次 B/C/D）。其上 `367c2ab`、`37f12bb`、`4200576`、`ed70313` 只改验收驱动与文档，不改变被测服务端代码；长稳进程正是这一内容。
Baseline: commit `93f790a` (renderer probe + OBS NVENC) plus `587e329`, `425d5df`, `f09dcaf`. The later commits (`367c2ab`, `37f12bb`, `4200576`, `ed70313`) only touch acceptance drivers and docs, so the long-running services under test are exactly this content.

历史记录（旧结论、被否证的假设、逐步排查过程）见 `docs/feedback-5-acceptance-history.md`。本文件只描述当前状态。
Historical notes (previous conclusions, disproved hypotheses, the step-by-step investigation) moved to `docs/feedback-5-acceptance-history.md`. This file states the current state only.

## 1. 本轮自动化验证 / Automated verification this round

| 套件 | 命令 | 结果 |
|---|---|---|
| 前端类型检查 | `web\node_modules\.bin\tsc.CMD --noEmit`（工作目录 `web`） | 0 错误 / 0 errors |
| 前端运行时（真实 Chrome 153） | `playwright test -c <config> --project=chrome -g "monitor-view\|playback-state\|audio-tracks\|wall-controls"` | **22/22 通过** |
| 转码器与 audio-mix | `node --test tests/test-transcoder-mix.mjs tests/test-transcoder.mjs` | **7/7 通过**（含 ±10000ms 边界、越界拒绝、归一化延迟上报） |
| 启动器 | `node --test tests/test-dev-launcher.mjs` | **9/9 通过**（含 `-Soak`/`--soak`） |
| C++ 核心 | `cmake --build <core-local>` + `ctest` | 编译通过，`webobs-unit-tests` 全过（含新增 11 条混音路由等价断言） |
| OBS Composite 构建 | `python3 scripts/dev-native.py --composite --soak` | `obs-ffmpeg`/`obs-x264`/`obs-webrtc`/`obs-nvenc` 全部产出并通过模块校验 |

## 2. 环境结论（本轮重新探测）/ Environment, re-probed this round

旧报告的“本沙箱没有 WSLg 图形会话、只能用 Xvfb 软件渲染”**不再成立**。

- WSLg 可用：`DISPLAY=:0`、`WAYLAND_DISPLAY=wayland-0`、`XDG_RUNTIME_DIR=/mnt/wslg/runtime-dir`、`/tmp/.X11-unix/X0`（Xwayland 已启动）。
- 硬件 OpenGL 可达：EGL/GL 真实探测在 `GALLIUM_DRIVER=d3d12` 下得到 `GL_RENDERER=D3D12 (NVIDIA GeForce RTX 3090)`；不设置时 Mesa 静默回退 llvmpipe。`scripts/dev-native.py` 现按容器入口的方式做真实探测，只在实际拿到非软件适配器时才上报 hardware。
- OBS 实际渲染器：`[info] Loading up OpenGL on adapter Microsoft Corporation D3D12 (NVIDIA GeForce RTX 3090)`。
- OBS NVENC：Ubuntu 无 `ffnvcodec`/`libmbedtls-dev` 且无 root，已把 `nv-codec-headers n12.1.14.0` 与 MbedTLS 3.6.2 装到用户缓存前缀；OBS 现输出 `NVENC version: 12.1 (compiled) / 13.1 (driver)`、`Loaded OBS module 'obs-nvenc'`，能力接口 `selected=nvenc, encoder=true`，`nvidia-smi` 显示 encoder 利用率约 8%。
- 已知限制：`obs-nvenc` 仍打印 `Failed to get a CUDA device for the current OpenGL context (CUDA_ERROR_OPERATING_SYSTEM)`（WSL 下无法与 OpenGL 上下文共享纹理，编码使用独立 CUDA 上下文）；`obs-nvenc` 偶发加载失败（测试子进程偶发拿不到 NVENC），此时如实回退 x264。
- 真实相机：`rtsp://192.168.31.199:8554/*` 可达。用户原始场景 1920×1080、5 路 camera（sha256 `87fcca32…c9b9`），运行时只读，未改写。

## 3. 六项反馈当前状态 / Status of the six items

| 反馈 | 状态 | 证据 |
|---|---|---|
| F5-01 画面填充 | 已实现并自动化验证 | `monitor-view.spec.ts` / `wall-controls.spec.ts`（22/22） |
| F5-02 干净画面 | 已实现并自动化验证 | `wall-controls.spec.ts` |
| F5-03 硬件加速 | **OBS 渲染与编码均已在真实运行中启用并取证**；网关 NVENC/CUDA 转码沿用既有实现 | 本文件第 2 节 + `nvidia-smi` |
| F5-04 本地合成 | **真实五路 1920×1080 Composite 30 分钟持续发布**（30/30 采样 ready、track=[Opus,H264]、`inboundFramesInError=0`） | `tests/artifacts/soak/…-composite-1080p-4200576/` |
| F5-05 音频管理 | 批次 A/B/C 已提交并有自动化验证；路由复用/先备后切有单测；有符号偏移有转码器用例；端到端音频驱动部分通过 | 见第 5 节 |
| F5-06 播放稳定 | 合成模式 30 分钟浏览器验收**已完成**：首帧 4.55s、最大帧间隔 1.77s、媒体时间推进 1807s；**帧率 21.95/30 = 73.2%，未达 90% 门槛**，瓶颈已归因到来源 | `tests/artifacts/browser-soak/2026-09-18T18-04-45-516Z-composite/` |

## 4. 长稳实测数据 / Measured soak data

### 4.1 服务端（sampler，`tests/soak-evidence.mjs`）

- 运行：`2026-09-18T18-02-32-770Z-composite-1080p-4200576`，30 次每分钟采样，覆盖 29.0 分钟。
- renderer=hardware、encoder=nvenc。
- **通过**：`program` 路由 30/30 ready、tracks `[H264,Opus]`、字节 387 MB → 1451 MB、`inboundFramesInError=0`；每个采样都是 `publish=publishing`。
- **未通过**：逐来源帧推进与“无重启”。5 路中 2 路全程稳定（`camera-mu2ux4qk`、`camera-mu2ux99i`：最大帧龄 501ms、重启 2 次），另外 3 路反复 stalled/recovering：

| 来源 | 最大帧龄 | 重启次数 |
|---|---|---|
| camera-mu2uub8u | 113 s | 69 |
| camera-mu2uuez4 | 582 s | 41 |
| camera-mu2ux73u | 29 s | 25 |

### 4.2 浏览器（`web/tests/local-runtime/browser-soak.spec.ts`，真实产品页面 + Chrome）

- 运行：30.1 分钟（1812s），播放的是页面内的 `video[aria-label="实时合成节目画面"]`（服务端 Program）。
- 首帧 4551 ms（≤20s 通过）、最大帧间隔 1772 ms（≤3s 通过）、媒体时间推进到 1807.5s（持续出图通过）。
- **39768 帧 / 1812s = 21.95 fps，为目标 30 fps 的 73.2%，未达 90% 门槛。**

### 4.3 瓶颈归因 / Bottleneck attribution

渲染与编码不是瓶颈：OBS 日志的渲染滞后为 **1/8247（0.0%）**、编码滞后 **59/8247（0.7%）**，`nvidia-smi` GPU 15%、encoder 8%。

瓶颈在**真实相机来源**。12 秒直接读取各相机（`ffprobe -count_frames`）：

| 来源 | 名义帧率 | 实测帧数/12s | 说明 |
|---|---|---|---|
| back_3 | 20 | 94（≈7.8 fps） | `Could not find ref with POC`（丢包） |
| front_3 | 20 | 185（≈15.4 fps） | 同上 |
| overview_c4 | 15 | 216（≈18 fps） | 同上 |
| hik_ch1_main / hik_ch2_main | 25 | 大量 `PPS id out of range` | 解码告警持续 |

因此“≥目标帧率 90%”在本轮无法达成，属于来源侧限速，不是合成/编码/传输回归——同一 30 分钟内 program 路由始终 ready 且 0 帧错误。

## 5. F5-05 音频现状与证据 / Audio state and evidence

已提交：

- `587e329` 批次 B：等效音频路由复用（共享 `mix-*` 守卫）、先备后切 + 回读校验、准备失败返回来源级错误并保留旧节目；`audio_routing_matches` 有 11 条单测。
- `425d5df` 批次 C：`B=max(0,-min(d_i))`，逐轨 `adelay=B+d_i`，视频用 `setts` 后移 B；校验接受 ±10000ms；`setts` 在 1/1000 与 1/90000 时间基下实测均精确平移 100ms。
- `f09dcaf` 批次 D：`-Soak`/`--soak` 贯通 PowerShell/Node/Python。

`tests/audio-regression.mjs`（自建 MediaMTX + 440/880Hz 双音轨来源 + 真实 `transcode-on-demand.sh` audio-mix）本轮实测：

- **单次增益**：`0:0.25:0,1:1.0:0` 实测 440/880 比值 **12.06 dB**，与理论 −12.04 dB 相符 → 增益只应用一次（通过）。
- **首轨静音**：对真实抓取做直接 DFT，440Hz 幅度 **0.0000**、880Hz **0.0623** → 静音首轨不会静音整个来源（通过；驱动自身的窗口统计此次抓到了启动空档，报告为 FAIL 属驱动缺陷，见下）。
- **负偏移**：转码器 stderr 实测输出 `新增端到端延迟: 2000ms (video and every track)`，流内视频/音频轨道均存在（通过）；“视频后移 2 秒”的 PTS 断言因录制未加 `-copyts`、复用器把两条流各自归零而**不可信**，需要在后续修正测量方法。

驱动当前缺陷（已在脚本头部注明）：录制进程与转码器首帧存在竞争，个别用例会抓到启动空档而得到全零窗口；本次已因此产生一次误报。该驱动**尚不能单独作为验收判据**。

## 6. 仍未完成 / Still open

1. **Direct/Hybrid 五路浏览器 30 分钟验收**：真实页面的五路瓦片全部显示“离线”，且经 Playwright 跟踪，瓦片**没有发出任何 API 请求**（无 `browserGrantProfile`/`requestBrowserPlan`），因此浏览器媒体路径根本没有启动。已在 HEAD `ed70313` 上复现两次（登录成功、`data-playback-suspended="false"`、能力接口对 5 路均返回 `preferred=direct`）。这是需要继续定位的产品级问题，不是环境问题。
2. **单路断开/恢复的受控故障注入**：本轮只有真实来源的自发 stall/recover 观测，没有受控注入，因此“其余四路不被一起重建、15 秒内出图”尚无证据。
3. **音频回归驱动**的启动空档缺陷与负偏移 PTS 测量方法。
4. **Docker / vGPU** 与跨设备音视频组合（按用户已确认范围留待后续）。

## 7. 命令 / Commands

```powershell
# 标准 Windows 入口（本轮已实测可启动到 WEBOBS_DEV_READY，并转发 --soak）
.\scripts\dev.ps1 -Composite -Soak

# 前端与启动器
web\node_modules\.bin\tsc.CMD --noEmit    # 工作目录 web
node --test tests/test-dev-launcher.mjs
node --test tests/test-transcoder-mix.mjs tests/test-transcoder.mjs

# 长稳采样（Windows 侧，读取 WSL 里的后端）
$env:WEBOBS_SCENE_FILE='build\scratch\scene.original.json'
node tests/soak-evidence.mjs --label composite-1080p --mode composite --target-fps 30 --minutes 30

# 浏览器长稳（真实产品页面）
$env:WEBOBS_SOAK='1'; $env:WEBOBS_SOAK_MODE='composite'; $env:WEBOBS_SOAK_MINUTES='30'
node node_modules/@playwright/test/cli.js test -c <config> --project=chrome -g "feedback-5 soak"

# 音频回归（需先停止开发会话，占用 8554/9997）
node tests/audio-regression.mjs
```

## 8. 结论 / Conclusion

渲染与编码侧已从“软件渲染 + x264”推进到**真实硬件路径**（OBS 渲染滞后 0.0%、编码滞后 0.7%、NVENC 已注册并被选用），并且**原始 1920×1080 五路 Composite 在真实产品页面上连续播放了 30 分钟**，首帧与帧间隔门槛通过。帧率门槛未达标，原因经逐项测量定位到**真实相机来源本身**（7.8–18 fps、HEVC 丢包），不是合成/编码/传输回归。

F5-01/F5-02 保持既有自动化验证；F5-05 的批次 A/B/C 代码与单测已完成，端到端音频驱动部分通过；F5-06 的合成模式 30 分钟验收已完成而 Direct/Hybrid 一项被“瓦片不发请求”的未定位问题阻塞，故障注入与音频驱动缺陷仍需继续。

The rendering and encoding side moved from software-only to a real hardware path (0.0% rendering lag, 0.7% encoding lag, NVENC registered and selected), and the original 1920x1080 five-source Composite played for a full 30 minutes inside the real product page with the first-frame and stall thresholds met. The frame-rate threshold is not met, and per-item measurement attributes that to the real camera feeds themselves (7.8-18 fps with HEVC packet loss) rather than to compositing, encoding or transport. F5-01/F5-02 keep their existing automated verification, F5-05 has batches A/B/C implemented with unit tests and a partially passing end-to-end audio driver, and F5-06 has the composite 30-minute acceptance while Direct/Hybrid is blocked by the undiagnosed "tiles issue no request" defect; fault injection and the audio driver defect remain open.
