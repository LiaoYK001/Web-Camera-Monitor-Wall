# 反馈5 持续执行检查点 / Feedback 5 progress checkpoint

更新 / Updated: 2026-09-19（持续执行第 13 轮 / continuous-execution round 13）

## 当前代码 / Current code

- 上一提交 `573d918`。本轮提交 `140a938`（新增 `tests/verify-video-shift.sh` + 报告第 5 节）。
- 用户场景保持原始 5 路相机（sha256 `87fcca32…`）。
- 未跟踪文件保持原样。

## 本轮完成：负偏移的视频位移已可重复精确验证 / The video delay B is now verified reproducibly

新增 `tests/verify-video-shift.sh`：自建 MediaMTX 与双音轨合成来源，用与转码器**完全相同**的 filter graph 与 `setts=ts=TS+B/(1000*TB)` 各跑一次并输出到**文件**，比较两次的最大 PTS 精确隔离位移。实测（B=2000）：

| 项 | 实测 | 期望 |
|---|---|---|
| 视频最大 PTS 位移 | **2.003 s** | 2.000 s |
| 音频最大 PTS 位移 | −0.017 s | 0.000 s |
| 判据 | **PASS** | — |

之所以必须用文件输出：从 RTSP/WebRTC 客户端读取时接收端会把每条流重新归零到自己的 RTP 时间线（实测两路都从约 0 开始，相差约 −76 ms），看不到该位移——这也解释了此前那条不可信断言。

**仍未测**：客户端侧能否通过 RTCP SR 恢复该相对关系。需要“闪光 + 同步音脉冲”素材，在页面内用同一 `performance.now()` 时基同时检测画面闪光与音频脉冲。

## 下一条具体动作 / Next concrete steps

1. 制作“闪光 + 同步音脉冲”素材，在浏览器内用同一时基检测闪光与脉冲的间隔，闭环客户端侧音视频相对关系。
2. Direct/Hybrid 首帧：让上游 WHEP 调用不再占用唯一 io_context 线程（工作线程 + `net::post` 回投，或按会话加 strand 后多线程跑 io_context）；改完用 `node web/tests/direct-latency-probe.mjs` 复测并重跑验收。
3. 用健康来源复测 Direct/Hybrid 的最大帧间隔与“零来源重启”判据。
4. 受控单路断开/恢复注入。

## 六项状态 / Status

| 项目 | 状态 | 证据 |
|---|---|---|
| F5-01 画面填充 | 已实现并自动化验证 | 聚焦套件 22/22 |
| F5-02 干净画面 | 已实现并自动化验证 | 聚焦套件 22/22 |
| F5-03 硬件加速 | 渲染 D3D12 已验证；NVENC 吞吐低于 x264，已按实测默认回退 | 报告第 2、4.4.2 节 |
| F5-04 本地合成 | 原始规格 30 分钟验收通过 | `tests/artifacts/soak/2026-09-19T12-53-07-152Z-composite-1080p-x264-3d281e4/` |
| F5-05 音频管理 | 批次 A/B/C 已提交并有单测；音频回归驱动三项全绿；视频位移精确验证通过；客户端侧相对关系待测 | 报告第 5 节、`tests/verify-video-shift.sh` |
| F5-06 播放稳定 | 合成模式四项门槛全过；Direct/Hybrid 首帧串行化已减弱（11s→6.5s）但未消除 | 报告 4.2.1、4.3.1、4.3.2 |

## 环境与阻塞 / Environment and blockers

- 后台作业不跨轮次存活；长稳被中断时用 `tests/soak-derive.mjs` 从增量证据重建结论。
- 音频相关工具（`tests/audio-regression.mjs`、`tests/verify-video-shift.sh`）都自建 MediaMTX 占用 8554/9997，运行前需停止开发会话。
- 真实相机首帧本身较慢，Direct/Hybrid 复测时需继续区分“服务端等待”与“来源首帧”。