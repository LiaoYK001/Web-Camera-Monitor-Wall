# 反馈5 持续执行检查点 / Feedback 5 progress checkpoint

更新 / Updated: 2026-09-19（持续执行第 5 轮 / continuous-execution round 5）

## 当前代码 / Current code

- HEAD：`fa84b2f`（长稳驱动：配对重试 + 采样器模式感知）。本轮新增 `185197b`（Direct-only 启动崩溃修复）、`0a1026b`（未配对误报修复）、`4ab704f`（真实配对流程 + 中途证据）、`fa84b2f`。
- 未跟踪文件保持原样，不随本轮提交。

## 六项状态 / Status

| 项目 | 状态 | 证据 |
|---|---|---|
| F5-01 画面填充 | 已实现并自动化验证 | 聚焦套件 22/22 |
| F5-02 干净画面 | 已实现并自动化验证 | 聚焦套件 22/22 |
| F5-03 硬件加速 | OBS 渲染 D3D12（滞后 0.0%）+ NVENC 已注册并被选用 | 报告第 2 节 |
| F5-04 本地合成 | 真实五路 1920×1080 Composite 30 分钟持续发布（30/30 采样） | `tests/artifacts/soak/…composite-1080p-4200576/` |
| F5-05 音频管理 | 批次 A/B/C 已提交并有单测；端到端音频驱动部分通过 | 报告第 5 节 |
| F5-06 播放稳定 | 两种模式各 30 分钟浏览器验收均**已执行**：合成 73.2% 帧率；Direct/Hybrid 1787.8s、五路持续出图、帧率 0.671–1.093、首帧与帧间隔超门槛 | `tests/artifacts/browser-soak/2026-09-18T18-04-45-516Z-composite/`、`…/2026-09-19T09-49-57-510Z-direct/` |

## 本轮完成 / Completed this round

- **修复 Direct-only 网关启动即崩溃**（`361cada` 引入）：`encoder_registered()` 在 `!obs_initialized()` 时返回 false，NVENC 调用按 `modules_loaded` 短路。修复前 `core-local/webobsd` 直接 SIGSEGV（栈顶 `obs_enum_encoder_types+0xd`），修复后正常启动并返回 `configuration=disabled`。这是 Direct/Hybrid 验收长期缺失的直接原因。
- **修复未配对被误报为控制面不可达**：`requestBrowserPlan()` 先单独解析设备头，未配对时抛「此浏览器尚未完成配对」，走 needsPairing 分支。
- **打通 Direct/Hybrid 浏览器验收**：`WEBOBS_SOAK_PAIR=1` 走产品自身配对流程（创建 → 管理会话批准 5 路授权 → 完成），实测五路瓦片全部出图；并修掉登录竞态、增加配对重试与中途证据写入。
- **完成 Direct/Hybrid 30 分钟验收**（1787.8s，因轮次边界未写自身汇总，由增量时间线重新计算并生成 `derived-browser-summary.md`）。
- 采样器改为模式感知：Direct/Hybrid 无 libobs 时不再把逐来源检查判为失败。

## 下一条具体动作 / Next concrete steps

1. 用**健康的合成来源**（例如测试 RTSP 发布）重跑一次 30 分钟，验证“来源健康时”首帧/帧间隔/帧率能否达标——用以区分“产品管线上限”与“本轮来源欠佳”。现有失败的归因已很明确，但缺少健康来源的对照。
2. 受控故障注入（代理/测试路由断开一路），验收“其余四路不重建、15 秒内出图”。
3. 修正 `tests/audio-regression.mjs` 的启动空档与负偏移 PTS 测量。
4. 让长稳驱动在结束时也能从中断中恢复：把 `summary` 也按周期写入，而不是只在末尾写一次。

## 环境与阻塞 / Environment and blockers

- 后台作业不跨轮次存活：30 分钟长稳若跨越轮次边界会在末尾被中止（本轮 Direct/Hybrid 运行正是如此）；浏览器长稳已改为增量写入时间线，采样器本身也逐条写 `samples.jsonl`，因此证据可恢复。
- 真实相机 `camera-mu2uub8u`、`camera-mu2ux73u`、`camera-mu2ux4qk` 稳定性差（12 秒直读 7.8–18 fps、HEVC 丢包；Direct 模式 21 条路由中 11 条从未 ready）。
- `sudo` 需要密码；`ffnvcodec`/MbedTLS/libdatachannel 均构建在用户缓存前缀。
- Windows 侧 Vite 由 `node node_modules/vite/bin/vite.js` 启动（Playwright 的 `webServer` 里那条裸 `pnpm` 在本机独立安装损坏）。
