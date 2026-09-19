# 反馈5 持续执行检查点 / Feedback 5 progress checkpoint

更新 / Updated: 2026-09-19（持续执行第 7 轮 / continuous-execution round 7）

## 当前代码 / Current code

- HEAD：`8d36ae1`，本轮新增未提交改动：`web/tests/local-runtime/browser-soak.spec.ts`（增加解码帧计数）。
- 用户场景：`~/.cache/webobs-dev/<hash>/data/scene.json` 已还原为原始 5 路相机场景，sha256 `87fcca32…` 与备份 `build/scratch/scene.original.json` 一致；对照实验用的 `assets/control-clip.mp4` 已删除。
- 未跟踪文件保持原样，不随本轮提交。

## 本轮关键结论 / Key finding this round

健康来源对照（5 路本地 1920×1080@30 `media` 源替换真实相机，其余不变）：

| 场景 | 服务端 program fps | 对 30 fps | 浏览器呈现 fps | 浏览器解码 fps |
|---|---|---|---|---|
| 真实 5 路相机 | 24.5（1473/60s） | 81.7% | 23.4 | 未记录 |
| 健康 5 路合成来源 | **27.2（1630/60s）** | **90.7%** | 24.6 | 24.6（4409 帧） |

- **服务端在健康来源下达到 ≥90% 门槛**；真实相机把它压低约 2.7 fps。
- 浏览器侧无论来源都停在 24–25 fps，且**呈现帧与解码帧几乎相等**（4401 对 4409）→ 瓶颈不在呈现，而在 WebRTC 接收/解码节奏，剩余约 2.6 fps 缺口待定位。

## 六项状态 / Status

| 项目 | 状态 | 证据 |
|---|---|---|
| F5-01 画面填充 | 已实现并自动化验证 | 聚焦套件 22/22 |
| F5-02 干净画面 | 已实现并自动化验证 | 聚焦套件 22/22 |
| F5-03 硬件加速 | OBS 渲染 D3D12 + NVENC 已注册并被选用 | 报告第 2 节 |
| F5-04 本地合成 | 真实五路 1920×1080 Composite 30 分钟持续发布 | `tests/artifacts/soak/…composite-1080p-4200576/` |
| F5-05 音频管理 | 批次 A/B/C 已提交并有单测；端到端音频驱动部分通过 | 报告第 5 节 |
| F5-06 播放稳定 | 两种模式各 30 分钟验收均已执行；门槛未全达标，瓶颈已分解为来源 ~2.7 fps + 浏览器接收 ~2.6 fps | 报告第 4 节 |

## 下一条具体动作 / Next concrete steps

1. 定位浏览器接收侧约 2.6 fps 缺口：对比 WHIP 输出统计（`framesEncoded`/`framesSent`）与浏览器 `inbound-rtp.framesDecoded`/`framesDropped`/`nackCount`，区分拥塞控制降帧与抖动缓冲丢帧；必要时对比 `program` 的 RTSP 读取与 WHEP 读取。
2. 用相同健康来源复测 Direct/Hybrid 的首帧与帧间隔门槛（本轮只测了 Composite）。
3. 受控单路断开/恢复注入。
4. 修正 `tests/audio-regression.mjs` 的启动空档与负偏移 PTS 测量；让长稳周期写 summary。

## 环境与阻塞 / Environment and blockers

- 后台作业不跨轮次存活：跨轮次的长稳会在边界被中止（已通过增量时间线与事后推导缓解）。
- 对照组需要临时替换场景；本轮已还原并校验，后续实验务必同样还原（备份在 `build/scratch/scene.original.json`）。
- `media` 源的文件路径必须是 `/assets/...` 或 `/recordings/...`（否则 `scene storage error`）。
