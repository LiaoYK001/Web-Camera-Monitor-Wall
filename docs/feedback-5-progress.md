# 反馈5 持续执行检查点 / Feedback 5 progress checkpoint

更新 / Updated: 2026-09-20（持续执行第 20 轮 / continuous-execution round 20）

## 当前代码 / Current code

- 上一提交 `3563780`。本轮修复 `gateway/transcode-on-demand.sh`（Direct/Hybrid 帧率缺口的根因）并新增回归测试与速率探针；报告 4.5 节记录了完整证据链。
- 用户数据未改动：本轮只在自建 MediaMTX（8554/8889/9997）与 `/tmp` 合成源上做隔离实验，未启动开发栈、未触碰 `cameras.db`/`scene.json`/`studio.json`。
- 未跟踪文件保持原样（`.github/`、`docs/development*.md`、`docs/feedback-5-*.md`、`scripts/dev*.sh`、`web/pnpm-workspace.yaml` 等）。

## 本轮完成：Direct/Hybrid 帧率缺口的根因与修复 / Root cause and fix

**根因**：x264 的 `sliced-threads`（由 `-tune zerolatency` 自动开启）会把一帧切成多个 slice，MediaMTX 在这些流上的 H264 access unit 组装随之只把约 60% 的帧交给 WebRTC 输出。整个 Direct/Hybrid 帧率缺口由此产生，与本项目代码、浏览器、传输都无关。

隔离实验（`web/tests/whep-rate-probe.mjs` 直接对 MediaMTX 发 WHEP，应用不参与）：

| 编码参数 | 浏览器接收 / 解码 / 呈现 fps |
|---|---|
| `ultrafast -tune zerolatency` | 15.99 / 15.99 / 15.99 |
| 同上 + `-x264-params sliced-threads=0` | **24.99 / 24.99 / 24.99** |
| `ultrafast -x264-params sliced-threads=1` | 14.95 / 14.95 / 14.95 |
| 离线编码后 `-c copy` 发布 | 25.02 / 24.99 / 24.99 |

已排除的变量：码率（700k 与 2500k 相同）、并发（1 路与 5 路每路约 15 fps）、传输（WSL 内 ICE/UDP 与 Windows Chrome ICE/TCP 相同）、浏览器解码（本地 720p25 = 25.00 fps、1080p30 = 30.13 fps）。

**修复**：`gateway/transcode-on-demand.sh` 的 libx264 分支保留 `-tune zerolatency`，加 `-x264-params sliced-threads=0`。

**端到端验证**（真实脚本 + 真实 MediaMTX `runOnDemand`，同一条 25 fps 来源）：修复前 17.00 fps、修复后 **24.99 fps**。

**回归测试**：新增 `tests/test-transcoder-encoder.mjs`；`node --test tests/test-transcoder-encoder.mjs tests/test-transcoder-mix.mjs` → **6/6 通过**。

**纠正**：报告 4.3.3/4.3.5 曾把缺口归因于“浏览器侧并发接收能力 / 每条流自身约 15 fps”，该结论已被推翻，并在原处标注修正。

## 下一条具体动作 / Next concrete steps

1. 让健康合成源不再使用 `-tune zerolatency`（或改为离线 copy/x265），在修复后的代码上重跑 **Direct/Hybrid 30 分钟浏览器验收**，判定 F5-06 帧率门槛。
2. 上游 WHEP 调用不再占用唯一 io_context 线程；`/activate` 仍约 2.57 秒/路串行。
3. 在真实相机场景下复测单路故障注入。
4. 判断 NVENC/VA-API 两条转码分支是否存在同类 slice 行为（本环境未触发）。

## 六项状态 / Status

| 项目 | 状态 | 证据 |
|---|---|---|
| F5-01 画面填充 | 已实现并自动化验证 | 聚焦套件 22/22 |
| F5-02 干净画面 | 已实现并自动化验证 | 聚焦套件 22/22 |
| F5-03 硬件加速 | 渲染 D3D12 已验证；NVENC 吞吐低于 x264，已按实测默认回退 | 报告第 2、4.4.2 节 |
| F5-04 本地合成 | 原始规格 30 分钟验收通过 | `tests/artifacts/soak/2026-09-19T12-53-07-152Z-composite-1080p-x264-3d281e4/` |
| F5-05 音频管理 | 批次 A/B/C 已提交并有单测；音频回归三项全绿；视频位移与客户端侧相对偏移均实测通过 | 报告第 5 节 |
| F5-06 播放稳定 | 合成模式四项门槛全过；**Direct/Hybrid 帧率缺口的根因已定位并修复（4.5 节）**，修复后端到端 24.99 fps，尚待在修复后的代码上重跑 30 分钟 | 报告 4.2.1、4.3.1–4.3.5、4.5 |

## 环境与阻塞 / Environment and blockers

- 本轮新增可用工具：`web/tests/whep-rate-probe.mjs`（WHEP 速率探针，`WHEP_PROBE_CHANNEL=chrome` 可切 Windows Chrome）、`web/tests/local-play-probe.mjs`（本地文件播放速率，用于排除浏览器解码能力）。
- 复现隔离实验的要点：自建 MediaMTX 必须设 `webrtcLocalTCPAddress`（Windows 浏览器 ICE/TCP）与 `webrtcLocalUDPAddress`；`pkill` 必须写在脚本文件里，否则会匹配到调用它的 shell 自身。
- 报告纠正记录：4.3.3 的“瓶颈在浏览器侧”、4.3.5 的“每条流自身约 15 fps”均已在原处标注为**错误**，正确根因见 4.5 节。
