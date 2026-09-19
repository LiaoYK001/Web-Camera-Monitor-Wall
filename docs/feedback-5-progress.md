# 反馈5 持续执行检查点 / Feedback 5 progress checkpoint

更新 / Updated: 2026-09-19（持续执行第 8 轮 / continuous-execution round 8）

## 当前代码 / Current code

- 上一提交：`59b6eb8`。本轮待提交：`web/tests/local-runtime/browser-soak.spec.ts`（WebRTC inbound 统计）、`scripts/dev-native.py`（D3D12 下默认 x264）、本次报告与检查点。
- 用户场景保持原始 5 路相机（sha256 `87fcca32…`，与 `build/scratch/scene.original.json` 一致）。
- 未跟踪文件保持原样。

## 本轮关键结论 / Key finding this round

**帧率未达标的主因是 WSL 下 OBS 的 NVENC，不是来源，也不是浏览器。**

| 编码器 | program 服务端 fps | 浏览器 framesReceived | framesDecoded | framesDropped | packetsLost | nackCount | 元素解码 fps | 元素呈现 fps |
|---|---|---|---|---|---|---|---|---|
| NVENC（auto） | 24.5（1473/60s） | 24.41 | 24.35 | 2 | 0 | 0 | 24.3 | 23.4 |
| x264 | **29.6–29.8**（1779/1789 每 60s） | **30.07** | **30.03** | 0 | 0 | 0 | **30.0** | **28.7** |

- 两条链路都是 `packetsLost=0`、`nackCount=0`：浏览器如实接收并解码发送端给出的帧，所以缺口完全在发送端。
- **改用 x264 后，合成模式（1920×1080、真实五路相机）的“≥目标 90%”在服务端与浏览器两侧都达成**（呈现 28.7 fps ≥ 27）。
- 原因：`Failed to get a CUDA device for the current OpenGL context (CUDA_ERROR_OPERATING_SYSTEM)`——D3D12 后端 OpenGL 下 NVENC 无法共享纹理，退化为拷贝路径。
- 已据此修改启动器：D3D12 后端 OpenGL 且未显式设置 `WEBOBS_VIDEO_ENCODER` 时默认 x264 并打印实测理由；显式 nvenc 仍可强制。

## 六项状态 / Status

| 项目 | 状态 | 证据 |
|---|---|---|
| F5-01 画面填充 | 已实现并自动化验证 | 聚焦套件 22/22 |
| F5-02 干净画面 | 已实现并自动化验证 | 聚焦套件 22/22 |
| F5-03 硬件加速 | OBS 渲染 D3D12 且 NVENC 已注册；但实测其吞吐低于 x264，默认已回退并有明确理由 | 报告第 2、4.4.2 节 |
| F5-04 本地合成 | 真实五路 1920×1080 Composite 持续发布；x264 下达到原始帧率 | `tests/artifacts/soak/…composite-1080p-4200576/` |
| F5-05 音频管理 | 批次 A/B/C 已提交并有单测；端到端音频驱动部分通过 | 报告第 5 节 |
| F5-06 播放稳定 | 合成模式在 x264 下达标（呈现 28.7 fps）；Direct/Hybrid 五路 1787.8s 但首帧/帧间隔仍超门槛 | `tests/artifacts/browser-soak/2026-09-19T12-44-34-450Z-composite/`、`…/2026-09-19T09-49-57-510Z-direct/` |

## 下一条具体动作 / Next concrete steps

1. 用 x264 重跑**正式 30 分钟合成长稳**，产出完整的 summary（本轮只做了 3 分钟对照）。
2. Direct/Hybrid 的首帧与帧间隔缺口：该模式不经 OBS 编码，需单独定位（候选：逐路网关计划建立耗时、来源首帧慢、瓦片并发连接）。
3. 受控单路断开/恢复注入。
4. 修正 `tests/audio-regression.mjs` 的启动空档与负偏移 PTS 测量；让长稳周期写 summary。

## 环境与阻塞 / Environment and blockers

- 后台作业不跨轮次存活；跨轮次长稳会在边界中止（已有增量证据与事后推导缓解）。
- WSL 下 OBS NVENC 无 GL 纹理共享：功能可用但吞吐不足，已按实测回退。
- 对照组临时替换场景后必须还原（备份 `build/scratch/scene.original.json`，本轮已还原并校验）。
