# 反馈5 持续执行检查点 / Feedback 5 progress checkpoint

更新 / Updated: 2026-09-19（持续执行第 17 轮 / continuous-execution round 17）

## 当前代码 / Current code

- 上一提交 `d039840`。本轮只改文档（报告 4.3.5、仍未完成、本检查点），无产品代码改动。
- 用户数据：`cameras.db`（sha256 `ac028d59…`）、`studio.json`（节目场景 5 路）与场景（`87fcca32…`）均已还原校验；合成源与栈已停止，端口全部关闭。
- 未跟踪文件保持原样。

## 本轮完成：并发上限对照 / Concurrency-ceiling control

通过产品自身的 `PUT /api/v1/studio` 把节目场景临时改成只引用 2 路来源（前端以 studio 文档为准，改 scene 文件无效），健康合成源与目标 25 fps 不变：

| 瓦片数 | 每路解码帧率 |
|---|---|
| 5 | 14.0–14.6 fps |
| 2 | **15.2–15.6 fps** |

瓦片数减到 2/5，每路只从约 14.4 升到约 15.4 fps——**几乎不变**。因此不是单页并发总量上限，而是**每条直连流自身的速率上限（约 15 fps）**。

已知边界：服务端对 5 个并发 RTSP 读取者能给满 25 fps；合成模式单条 1080p30 program 流在浏览器能到 30 fps。所以缺口在“每来源 WHEP 直连”这条链路上，下一步需要浏览器播放时读取 MediaMTX 逐 reader 发送统计，区分 MediaMTX WebRTC 输出限速与浏览器接收/解码节奏。

## 下一条具体动作 / Next concrete steps

1. 浏览器播放时读取 MediaMTX 逐 reader 发送统计（或 `/v3/paths/list` 的 bytesSent 增量），区分 WHEP 直连约 15 fps 的上限来自服务端还是浏览器。
2. 上游 WHEP 调用不再占用唯一 io_context 线程；`/activate` 仍约 2.57 秒/路串行（来源慢时会放大首帧）。
3. 在真实相机场景下复测单路故障注入。

## 六项状态 / Status

| 项目 | 状态 | 证据 |
|---|---|---|
| F5-01 画面填充 | 已实现并自动化验证 | 聚焦套件 22/22 |
| F5-02 干净画面 | 已实现并自动化验证 | 聚焦套件 22/22 |
| F5-03 硬件加速 | 渲染 D3D12 已验证；NVENC 吞吐低于 x264，已按实测默认回退 | 报告第 2、4.4.2 节 |
| F5-04 本地合成 | 原始规格 30 分钟验收通过 | `tests/artifacts/soak/2026-09-19T12-53-07-152Z-composite-1080p-x264-3d281e4/` |
| F5-05 音频管理 | 批次 A/B/C 已提交并有单测；音频回归三项全绿；视频位移与客户端侧相对偏移均实测通过 | 报告第 5 节、`tests/verify-video-shift.sh`、`web/tests/av-sync-probe.mjs` |
| F5-06 播放稳定 | 合成模式四项门槛全过；Direct/Hybrid 首帧与帧间隔在健康来源下达标；帧率缺口收敛到“每条直连流约 15 fps”；单路故障注入已完成 | 报告 4.2.1、4.3.1–4.3.5 |

## 环境与阻塞 / Environment and blockers

- 后台作业不跨轮次存活，且从 WSL 调用里 `nohup` 出来的夹具会随该次调用被回收；夹具必须放在持续运行的后台作业里（本轮用 `synth-hold.sh`）。
- 改 `scene.json` 对前端无效（前端以 studio 文档为准）；studio 的 `PUT` 会因 revision 竞争失败，直接改写 `studio.json` 需先停止栈。
- 真实相机首帧本身 10–50 秒，是 Direct/Hybrid 首帧门槛的唯一成因。