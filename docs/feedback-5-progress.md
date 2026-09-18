# 反馈5 持续执行检查点 / Feedback 5 progress checkpoint

更新 / Updated: 2026-09-19（持续执行轮次 / continuous-execution round）

## 当前代码 / Current code

- HEAD：`f09dcaf`（批次 D 启动器 `-Soak` 转发），其上为 `425d5df`（批次 C 有符号偏移）、`587e329`（批次 B 混音路由复用）、`1896091`（批次 A 空选轨/输出总线）。
- 工作区：批次 D 的验收驱动（`tests/soak-evidence.mjs`、`tests/audio-regression.mjs`、`web/tests/local-runtime/browser-soak.spec.ts`）与渲染器/NVENC 的启动器改动待提交。
- 未跟踪文件（`.github/`、`docs/development*.md`、`scripts/dev*.sh`、`scripts/stop-dev.*`、`compose.dev.yaml`、`web/pnpm-workspace.yaml`、`web/tests/local-runtime/login-gate.spec.ts`、`workspace-shell.spec.ts`）保持原样，不随本轮提交。

## 环境结论（本轮重新探测，取代旧结论）/ Environment, re-probed this round

- **WSLg 存在且可用**：`DISPLAY=:0`、`WAYLAND_DISPLAY=wayland-0`、`XDG_RUNTIME_DIR=/mnt/wslg/runtime-dir`、`/tmp/.X11-unix/X0`（Xwayland 已启动，weston 日志 `created wm, root 1080`）。旧报告“无 WSLg 图形会话”不再成立。
- **硬件渲染可达**：实测 EGL 探针在 `GALLIUM_DRIVER=d3d12` 下得到 `GL_RENDERER=D3D12 (NVIDIA GeForce RTX 3090)`；默认情况下 Mesa 静默回退 `llvmpipe`（软件渲染，1920×1080 五路实测渲染滞后 39–44%）。`dev-native.py` 现按 `docker/entrypoint.sh` 的方式做真实 EGL 探测并据此导出 `WEBOBS_RENDERER_*`。
- **OBS NVENC**：Ubuntu 无 `libmbedtls-dev`/`ffnvcodec` 包且无 root；已把 `nv-codec-headers n12.1.14.0` 安装到用户前缀 `~/.cache/webobs-dev/<hash>/libs`，OBS configure 已 `Found FFnvcodec 12.1.14.0`。同一次 configure 暴露了 `find_package(MbedTLS)` 依赖（旧缓存只是偶然命中了 Windows Anaconda 的 MbedTLS 配置），正在把 MbedTLS 也构建进同一用户前缀。
- 真实相机 `rtsp://192.168.31.199:8554/*` 可达；用户原始场景为 1920×1080、5 路 camera（sha256 `87fcca321c3280089e50b39d84cc9d0aeaf983d61c4f1113750414419ec7c9b9`），已在 `build/scratch/scene.original.json` 备份，运行时不改动。

## 六项状态 / Status

| 项目 | 状态 | 证据 |
|---|---|---|
| F5-01 画面填充 | 已实现并自动化验证 | monitor-view / wall-controls 规格（22/22，本轮在 Windows Chrome 复跑） |
| F5-02 干净画面 | 已实现并自动化验证 | wall-controls 规格 |
| F5-03 硬件加速 | 渲染器改为真实探测（硬件可得）；OBS NVENC 依赖已入用户前缀，构建进行中 | 本检查点“环境结论” |
| F5-04 本地合成 | 真实五路 1920×1080 已发布（tracks=Opus,H264，5/5 来源 healthy） | `/api/v1/program/status`、MediaMTX `program` 路径 |
| F5-05 音频管理 | 批次 A/B/C 已提交；可重复音频回归驱动已写待运行 | `587e329`、`425d5df`、`tests/audio-regression.mjs` |
| F5-06 播放稳定 | 状态机已实现；浏览器 30 分钟与 1080p 长稳本轮执行中 | `tests/soak-evidence.mjs`、`browser-soak.spec.ts` |

## 本轮已完成 / Completed this round

- 批次 B `587e329`：等效音频路由复用（共享 `mix-*` 守卫）、先备后切 + 回读校验、准备失败保留旧节目；新增 `audio_routing_matches` 与 11 条单测。core-local 构建与 `webobs-unit-tests` 全绿。
- 批次 C `425d5df`：`B=max(0,-min(d_i))` 归一化，`adelay=B+d_i` + `setts` 视频后移 B；校验接受 ±10000ms；`node --test` 转码器用例 7/7 通过；setts 在 1/1000 与 1/90000 时间基下均实测精确平移 100ms。
- 批次 D `f09dcaf`：`-Soak`/`--soak` 从 PowerShell/Node 贯通到 Python；`tests/test-dev-launcher.mjs` 9/9 通过。
- 前端 `tsc --noEmit` 0 错误；聚焦运行时套件 **22/22** 通过（Windows Chrome）。
- 真实 1920×1080 五路 Composite 已启动并发布成功（`configuration=ready, engine=ready, publish=publishing`，5 路来源 healthy，lastFrameAgeMs≈110）。

## 下一条命令 / Next

1. 完成 MbedTLS 用户前缀构建 → OBS composite-nv 构建 → 确认 `obs-nvenc` 注册与发布。
2. 短时端到端 + GPU 归因（renderer/encoder 实际值、渲染滞后比例）。
3. 正式 Composite 1920×1080@目标帧率 30 分钟（`tests/soak-evidence.mjs` + `browser-soak.spec.ts`）。
4. Direct/Hybrid 五路 30 分钟。
5. `tests/audio-regression.mjs` 与故障注入（单路断开恢复、切场景、保存重载、声音启停、拓扑切换）。
6. 修订 `docs/feedback-5-acceptance.md`，旧结论移入历史附录。

## 局部阻塞 / Blockers

- 正式 30 分钟浏览器长稳需要稳定的被测进程；构建期间不启动。
- `sudo` 需要密码，无法 `apt-get install`；所有构建依赖改为用户缓存前缀方案。
- Windows `dev.mjs` 依赖的 pnpm 独立安装在 `AppData\Local\pnpm\store` 的链接已损坏，`dev.ps1` 无法启动前端；本轮直接用 `vite` 与 node 入口验证（`corepack pnpm` 本身可用）。
