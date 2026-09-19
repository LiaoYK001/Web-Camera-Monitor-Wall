# 反馈5 持续执行检查点 / Feedback 5 progress checkpoint

更新 / Updated: 2026-09-19（持续执行第 11 轮 / continuous-execution round 11）

## 当前代码 / Current code

- 上一提交 `85d8a89`。本轮提交 `241e8ea`（播放路由优先使用注册表已存编解码器；`core/src/control_server.cpp`、`camera/camera_registry.py`、报告 4.3.2）。
- 用户场景保持原始 5 路相机（sha256 `87fcca32…`）。
- 未跟踪文件保持原样。

## 本轮进展：Direct/Hybrid 首帧串行化的第一步修复 / First fix for the serialized Direct/Hybrid first frame

**做了什么**：`ensure_playback_route()` 原先对每条新路由跑两次 ffprobe（各 12 秒超时）来发现编解码器；相机注册表其实早已把 `video_codec`/`audio_codec` 存在 `stream_profiles` 里。现在 `/resolve/<camera>/<profile>` 一并返回这两个字段（`resolve_profile()` 增加 `videoCodec`/`audioCodec`），`ResolvedCameraEndpoint` 与解析逻辑相应扩展，控制面优先使用注册表值，仅在缺失或 `unknown` 时回落实测。

**效果**（同一探针、真实五路相机）：

| 指标 | 修复前 | 修复后 |
|---|---|---|
| 五个 WHEP 服务端耗时 | 14.99 / 25.13 / 32.89 / 45.41 / 54.40 s | 约 10 / 17 / 22 / 29 / 35 s |
| 串行间隔 | 约 11 s | 约 6.5 s |
| 末路 live | 52.8 s | 31.8 s |

**残余等待（已定位）**：`create_validated()`（`control_server.cpp:1087`）在 1103 行对 MediaMTX 发起阻塞的 WHEP 信令请求；按需路由要等相机出帧后 MediaMTX 才应答（约 6 秒/路），而 handler 跑在唯一的 io_context 线程上，五路因此仍串成约 5×6.5 秒。

## 下一条具体动作 / Next concrete steps

1. 让上游 WHEP 调用不再占用唯一 io_context 线程（工作线程 + `net::post` 回投，或按会话加 strand 后多线程跑 io_context）；改完用 `node web/tests/direct-latency-probe.mjs` 复测并重跑 Direct/Hybrid 验收。
2. 用健康来源复测 Direct/Hybrid 的最大帧间隔。
3. “零来源重启”判据：用健康来源复测确认产品在来源健康时零重启。
4. 受控单路断开/恢复注入。
5. 修正 `tests/audio-regression.mjs` 的启动空档与负偏移 PTS 测量。

## 六项状态 / Status

| 项目 | 状态 | 证据 |
|---|---|---|
| F5-01 画面填充 | 已实现并自动化验证 | 聚焦套件 22/22 |
| F5-02 干净画面 | 已实现并自动化验证 | 聚焦套件 22/22 |
| F5-03 硬件加速 | 渲染 D3D12 已验证；NVENC 吞吐低于 x264，已按实测默认回退 | 报告第 2、4.4.2 节 |
| F5-04 本地合成 | 原始规格 30 分钟验收通过 | `tests/artifacts/soak/2026-09-19T12-53-07-152Z-composite-1080p-x264-3d281e4/` |
| F5-05 音频管理 | 批次 A/B/C 已提交并有单测；端到端音频驱动部分通过 | 报告第 5 节 |
| F5-06 播放稳定 | 合成模式四项门槛全过；Direct/Hybrid 首帧串行化已减弱但未消除 | 报告 4.2.1、4.3.1、4.3.2 |

## 环境与阻塞 / Environment and blockers

- 后台作业不跨轮次存活；长稳被中断时用 `tests/soak-derive.mjs` 从增量证据重建结论。
- 探针 `web/tests/direct-latency-probe.mjs` 需要后端与 Vite 在跑；未配对时会先走产品自身配对流程。
- 真实相机首帧本身较慢，修改后需继续区分“服务端等待”与“来源首帧”。
