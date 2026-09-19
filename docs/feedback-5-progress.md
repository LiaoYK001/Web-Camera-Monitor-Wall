# 反馈5 持续执行检查点 / Feedback 5 progress checkpoint

更新 / Updated: 2026-09-19（持续执行第 16 轮 / continuous-execution round 16）

## 当前代码 / Current code

- 上一提交 `2447ca9`。本轮提交 `cb2b25f`（新增 `web/tests/av-sync-probe.mjs` + 报告第 5 节）。
- 用户数据：`cameras.db`（sha256 `ac028d59…`）与场景（`87fcca32…`）均保持还原状态；A/V 测试夹具已全部停止，端口 8554/8889/9997/8654 已关闭。
- 未跟踪文件保持原样。

## 本轮完成：F5-05 负偏移的客户端侧实测 / Client-side verification of the negative offset

用闪光+同步音脉冲素材（黑底 640×360、每 4 秒一次 120 ms 全白闪光、1 kHz 脉冲与之对齐）经**真实转码器**的 audio-mix 发布，再在 Chrome 里用同一 `performance.now()` 时基同时检测画面闪光（canvas 亮度）与音频脉冲（AnalyserNode RMS）：

| mix 规格 | 闪光−脉冲（逐次，ms） | 中位数 |
|---|---|---|
| `0:1.0:0:0`（对照） | −90 / −49 / −16 / 0 / 0 | **−16 ms** |
| `0:1.0:0:-2000`（B=2000） | 1955 / 1992 / 1996 / 2030 / 2033 | **1996 ms** |

即端点浏览器体验到的偏移与 `B` 一致——该位移此前只能由构造保证（客户端 RTP 时间线各自归零，读不到），现在**端到端实测通过**。

复现前提（本轮踩到并写入脚本头部与报告）：① `mix-*` 路由必须先用 MediaMTX API 注册，dev 网关不自动建路径；② 独立启动 MediaMTX 需带 `MTX_WEBRTCLOCALTCPADDRESS` 等 ICE/TCP 设置，否则 Windows 浏览器 ICE 永远连不上（`deadline exceeded while waiting connection`，WHEP 建会话但无媒体）；③ 页面里不要 `await video.play()`——它要等首帧才 resolve，会一直挂住。

## 下一条具体动作 / Next concrete steps

1. 浏览器侧并发上限：改 studio 文档或用 `/api/v1/studio` 做两瓦片对照，判断是单页总量上限还是每路固定降速。
2. 上游 WHEP 调用不再占用唯一 io_context 线程；`/activate` 仍约 2.57 秒/路串行。
3. 在真实相机场景下复测单路故障注入（目前用健康合成源完成）。

## 六项状态 / Status

| 项目 | 状态 | 证据 |
|---|---|---|
| F5-01 画面填充 | 已实现并自动化验证 | 聚焦套件 22/22 |
| F5-02 干净画面 | 已实现并自动化验证 | 聚焦套件 22/22 |
| F5-03 硬件加速 | 渲染 D3D12 已验证；NVENC 吞吐低于 x264，已按实测默认回退 | 报告第 2、4.4.2 节 |
| F5-04 本地合成 | 原始规格 30 分钟验收通过 | `tests/artifacts/soak/2026-09-19T12-53-07-152Z-composite-1080p-x264-3d281e4/` |
| F5-05 音频管理 | 批次 A/B/C 已提交并有单测；音频回归三项全绿；视频位移与**客户端侧相对偏移均实测通过** | 报告第 5 节、`tests/verify-video-shift.sh`、`web/tests/av-sync-probe.mjs` |
| F5-06 播放稳定 | 合成模式四项门槛全过；Direct/Hybrid 首帧与帧间隔在健康来源下达标，帧率缺口归因浏览器侧；单路故障注入已完成 | 报告 4.2.1、4.3.1–4.3.4 |

## 环境与阻塞 / Environment and blockers

- 后台作业不跨轮次存活；从 WSL 调用里 `nohup` 出来的夹具会随该次调用被回收，需要放在持续运行的后台作业里（本轮据此把夹具与测量放在同一次调用内完成）。
- 健康来源对照需临时改 `cameras.db`（先备份、后校验还原）；改场景文件对前端无效——前端以 studio 文档为准。
- 真实相机首帧本身 10–50 秒，是 Direct/Hybrid 首帧门槛的唯一成因。