# 反馈5 持续执行检查点 / Feedback 5 progress checkpoint

更新 / Updated: 2026-09-19（持续执行轮次结束状态 / end of the continuous-execution round）

## 当前代码 / Current code

- HEAD：`ed70313`（长稳驱动匹配真实页面）。被测服务端内容等价于 `93f790a`：其上 `367c2ab`、`37f12bb`、`4200576`、`ed70313` 只改验收驱动与文档。
- 本轮提交顺序：`587e329`（批次 B）→ `425d5df`（批次 C）→ `f09dcaf`（批次 D 启动器）→ `93f790a`（渲染器真实探测 + OBS NVENC）→ `367c2ab`、`37f12bb`、`4200576`、`ed70313`（验收驱动）。
- 未跟踪文件保持原样，不随本轮提交：`.github/`、`docs/development*.md`、`scripts/dev*.sh`、`scripts/stop-dev.*`、`compose.dev.yaml`、`web/pnpm-workspace.yaml`、`web/tests/local-runtime/login-gate.spec.ts`、`web/tests/local-runtime/workspace-shell.spec.ts`。

## 六项状态 / Status

| 项目 | 状态 | 证据 |
|---|---|---|
| F5-01 画面填充 | 已实现并自动化验证 | 聚焦套件 22/22 |
| F5-02 干净画面 | 已实现并自动化验证 | 聚焦套件 22/22 |
| F5-03 硬件加速 | OBS 渲染 D3D12 + NVENC 已注册并实测使用 | 报告第 2 节 |
| F5-04 本地合成 | 真实五路 1920×1080 30 分钟持续发布（30/30 采样） | `tests/artifacts/soak/…composite-1080p-4200576/` |
| F5-05 音频管理 | 批次 A/B/C 已提交；音频回归驱动部分通过 | 报告第 5 节 |
| F5-06 播放稳定 | 合成模式 30 分钟浏览器验收完成；帧率 73.2% 未达标（来源限速）；Direct/Hybrid 被阻塞 | `tests/artifacts/browser-soak/…composite/` |

## 本轮已完成 / Completed this round

- 批次 B `587e329`：等效混音路由复用（共享守卫）、先备后切 + 回读校验、失败保留旧节目；11 条新单测，core 构建与单测全绿。
- 批次 C `425d5df`：`B=max(0,-min(d_i))` 归一化、`setts` 视频后移；±10000ms 校验；转码器用例 7/7。
- 批次 D `f09dcaf` + `367c2ab`：`-Soak` 贯通到 Python；`tests/soak-evidence.mjs`、`tests/audio-regression.mjs`、`web/tests/local-runtime/browser-soak.spec.ts`；启动器用例 9/9。
- `93f790a`：真实 EGL 渲染器探测（WSLg + d3d12）、用户前缀 ffnvcodec/MbedTLS、构建并放置 `obs-nvenc` 及其 `obs-nvenc-test` 辅助程序、core 加载 obs-nvenc；渲染滞后 39–84% → 0.0%。
- 真实 1920×1080 五路 Composite 30 分钟服务端采样 + 30 分钟真实页面浏览器长稳。
- 帧率未达标的归因测量（来源 7.8–18 fps、HEVC 丢包；渲染 0.0%、编码 0.7%）。

## 下一条具体动作 / Next concrete steps

1. 定位 Direct/Hybrid 瓦片“离线且不发任何请求”：从 `web/src/DirectPreview.tsx` 的 `CameraDirectTile` effect 入口（`loadBrowserIdentity`/IndexedDB）与 `web/src/localRuntime.ts` 的本地运行时状态入手，确认 effect 是否执行、Promise 是否悬挂。
2. 修正 `tests/audio-regression.mjs`：录制与转码器首帧的竞争（等待首个非静音窗口后再计时）与负偏移测量改用相对 PTS。
3. 受控故障注入（代理/测试路由断开一路），验收“其余四路不重建、15 秒内出图”。
4. 修订报告与证据；仍未达成的门槛按来源限速如实记录。

## 环境与阻塞 / Environment and blockers

- WSLg 可用、`GALLIUM_DRIVER=d3d12` 下 OBS 使用 D3D12 硬件渲染；OBS NVENC 偶发加载失败（测试子进程偶发拿不到 NVENC），此时回退 x264。
- `sudo` 需要密码，无法 apt 安装；`ffnvcodec`、MbedTLS、libdatachannel 均构建在 `~/.cache/webobs-dev/<hash>/libs`。
- Windows `dev.mjs` 经 corepack 使用 pnpm 11.16.0，`node scripts/dev.mjs --check` 通过；Playwright 的 `webServer` 里那条裸 `pnpm` 命令在本机独立安装损坏，改由 `node node_modules/vite/bin/vite.js` 启动前端。
- 真实相机 `camera-mu2uub8u`、`camera-mu2uuez4`、`camera-mu2ux73u` 在 30 分钟内反复 stall（7.8–18 fps、HEVC 丢包），是本轮帧率门槛未达成的直接原因。
