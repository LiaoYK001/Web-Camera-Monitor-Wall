# WebOBS 4.1.0-dev.18 — 开发测试 / Development test

**Windows x64、未签名、Pre-release；不是稳定版，不进入 stable 更新源，也不替换 Latest。**

Windows x64, unsigned, development prerelease only. This is not a stable release and does not enter the stable update feed or replace Latest.

## 固定构建 / Frozen build

- Source: `24e8eb371582c646c5e4c7059e070d37b4fdfcaa`.
- Successful complete product build: https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/41181595863 . Audit and Windows product jobs passed; the separate historical installed-upgrade job was not requested.
- Immutable build artifact: `13035199490`, `webobs-windows-4.1.0-dev.18`, `1031259327` bytes. ZIP SHA-256: `fb2581a20dd9388c2ed63af2f6b824854bfc765dfbe036bbbe5c7b037907a594`.
- Assets are copied from that existing build without rebuilding or replacing DLLs. Verify the installer against the attached `webobs-windows-4.1.0-dev.18-SHA256SUMS.txt` before use. The ZIP size above is **not** the installer or installed size.

## 改动与实际检查 / Changes and actual checks

修复了 Windows Job 启动时 `STARTF_USESHOWWINDOW/SW_HIDE` 可让首次原生监看窗口继续隐藏的独立缺陷。新窗口使用显式展示并验证可见性；Windows 子进程回归同时验证旧行为和新行为。**这不等于用户“窗口可见但画面黑”的持续黑屏根因已定位。**

Fixed a separate first-window visibility defect inherited from the Windows Job launcher's `SW_HIDE` startup setting. The new window explicitly becomes visible, with a real Windows subprocess regression for both old and new behavior. **This does not establish the cause of a visible-but-black camera window.**

原生状态端点增加受原有账号、权限、Origin 和每次启动 token 保护的低开销绘制快照；界面明确区分“已请求”“绘制回调”和“最终图像成功”。快照仅在请求后的绘制阶段采样，不增加生产 CPU 图像读回，也不以录像/编码器激活画面。

Added guarded on-request draw snapshots and explicit UI wording: a requested window, draw callbacks, texture readiness and final visible media are different facts. No production CPU image readback or dummy recording/encoder activation is added.

完整构建中实际检查了测试自有原生窗口客户区的最终合成像素：五色场景、五路独立 HEVC B 帧输入、倒序 Program 布局、恢复后重开；所有动态样本都核对通道身份、位置、方向和逐路时间进度，新窗口在工具介入前均已可见。既有运行时、Composite、来源 UI、主进程、打包与安装烟测保留并通过。

The complete build checked final visible synthetic client pixels for five scene colors, five distinct HEVC B-frame inputs, reordered Program and recovered reopening. Every dynamic sample checks channel identity, position, orientation and per-channel temporal progress. New windows were visible before the capture tool intervened. Existing runtime, Composite, source UI, main-process, package and installation smoke contracts remained enabled and passed.

## 已知限制 / Known limits

- **仍有重开启动过渡黑帧。** 回执保留全部早期观察样本，不作为验收成功；新候选八张早期样本中六张尚未形成完整五路，随后在相同有界健康/预热条件下做严格恢复检查。旧 dev.17 用同口径恢复门槛也通过，因此不能把恢复成功归因于新核心黑屏修复。
- CI 使用 Microsoft Basic Render Driver 和合成输入，不证明用户五路真实 H.265、RTX 4090 Laptop 硬解、同 GPU、低延迟、持续播放或原版 OBS 同等性能。不能依据 `auto`、D3D11 初始化或回调增长认定逐路硬解。
- 本安装器仍是现有完整兼容宿主，不是独立 OBS/Qt 原型的默认迁移版本。原型的 Windows 编译/隔离配置启动已另行验证，但产品认证、配置迁移、正常退出/升级、许可证交付和完整功能等价门槛尚未完成，故不静默替换用户数据或移除旧能力。
- 真实目标机的同条件 OBS 对照、至少三对交替采样及两小时稳定性、完整所属进程 CPU/GPU、内存/显存/功耗/延迟、默认与完整安装体积均未验收。本开发包发布不代表该目标达成。

Reopening still includes startup-transition black frames; those early samples remain in evidence and are not accepted as successful frames. The unchanged dev.17 runtime also passes the same recovered gate. The software CI renderer and synthetic inputs do not qualify real cameras, target hardware decoding, latency, stability or OBS performance parity. This installer retains the existing full compatibility host; the independent OBS/Qt prototype is not the new default. Authentication, migration, lifecycle, installation and capability-equivalence gates remain open. No real target-machine performance or installed-size acceptance is claimed.

## 测试与反馈 / Testing and feedback

请在保存既有配置的独立 Windows 测试环境中使用，核对摘要与版本；未签名状态应由使用者自行按本机安全策略评估，不建议一律绕过系统安全提示。先确认五路完整可见且时间持续推进，再分别记录首次打开、关闭/重开、TAKE、全屏/DPI/多显示器与断线恢复现象。公开反馈仅提交匿名来源编号、时间和不含私密内容的结果；不公开相机地址、口令、token、配置、完整日志或真实画面。

Use a separate Windows test environment and preserve existing configuration. Verify the checksum and evaluate the unsigned installer under your own security policy rather than blindly bypassing system warnings. Confirm all five channels and temporal progress before collecting startup/reopen/TAKE/display/recovery observations. Public feedback must be anonymized; do not publish camera endpoints, credentials, tokens, configurations, full logs or real camera images.
