# Windows OBS 同等开销执行记录 / OBS parity execution record

## 2026-10-31 / P0 冻结现场（首轮，尚未通过实机基线）

本记录执行 [用户 P0–P5 计划](windows-obs-parity-dsh-plan.md)，不是完成声明。The plan remains open; build/fixture success is not hardware or performance qualification.

### 回退起点与源码身份 / Frozen source identity

- 接手分支 `codex/windows-native-monitor`，HEAD `b6f07f529c131cf407fd484e636b796dded45027`；`origin/dev=5473f9abe389be1f6a166cbd98b2ce3a7b5366c7`。
- [PR #53](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/pull/53) 于本轮核对时仍为 OPEN，目标 `dev`，尚未合入。No ordinary development targets main.
- 已发布 [dev.17](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/releases/tag/v4.1.0-dev.17) 为未签名开发预发布；[成功构建 41062148722](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/41062148722) 的源码为 `4ca94a43290ee93bf20d9083554edc2c892dfda6`。
- Release API 核对安装器 `427435987` 字节，SHA-256 `d52cd3394ee4a8dad0a3029aab3a7cba912d2cb5bb7f1666ef107d65a4466535`。先前 footprint 记录安装载荷 `1459393176` 字节；不把下载大小当安装大小。本轮未重新安装或测量默认/扩展安装空间。
- OBS 固定 `fb4d98bf88fae5fc85cb11fc57f7c5e309282194`（32.1.2）；go2rtc 固定 `b5948cfb25404cc5cb37b166ecaa2dca20b11d4b`。上游子模块不承载产品修改。
- 接手时未跟踪 `.directory`（KDE，保留）与 `docs/windows-obs-parity-dsh-plan.md`（用户计划，纳入开发依据）；无其他已跟踪修改。Preserve unrelated metadata and all private configuration.

### 黑屏与输入基线 / Black-screen reproduction and input baseline

已知反馈：dev.17 原生窗口可见、绘制计数 1445、最终画面全黑。这是用户反馈，不是本机已重现。原临时附件可能过期，不能以日志计数补造截图证据。

复现路径（待目标机复核）：保留原版 OBS 正常的五路配置 → 记录当前已 TAKE Program 场景/来源/音轨 → 打开 Windows 原生监看 → 观察最终画面 → 短时采集脱敏诊断与窗口截图 → 无录像/推流地重开、TAKE、全屏、DPI/显示器切换。不要先覆盖已有 OBS 配置或以虚假录像激活渲染。

接手时的 `desktop/tests/native-program-preview.cjs` 只让五个来源读取同一小型 HEVC 测试片，检查状态、来源健康与绘制计数，不能区分黑屏、旧帧、错路、漏路。首轮已补最终窗口像素、五个独立输入的路号/色彩/空间标记/动态时间码和位置变更回归，下面保留旧实现对照与失败记录。`obs_render_main_texture()` 为合法显示 API，根因仍须由固定源码和实际测试确认，不能把新增测试当用户黑屏已经修复。

| 条件 / Condition | 已知 / Known | 待实机补齐 / Missing |
| --- | --- | --- |
| 目标设备 | i9-13900HX / RTX 4090 Laptop（用户报告） | Windows、驱动、散热/电源、集显/独显 LUID、显示器连接/DPI |
| 输入 1–5 | 五路真实 RTSP / H.265（用户报告） | 每路分辨率、FPS、码率、B 帧、音轨、传输、缓冲/重连；只记录匿名 source-1…source-5 |
| 原版 OBS | 用户报告约 159 MB | 精确版本/来源/组件/插件/文件总字节数、画布/帧率、解码设置、预览/投影尺寸 |
| dev.17 Program | 黑屏反馈、窗口计数增长 | 实际 TAKE 状态、有效帧进度、源 active/showing、渲染/解码适配器 |
| 成本 | 未有合格同机 OBS A/B 数据 | 全进程 CPU、分设备/引擎 GPU、内存/显存、功耗/延迟、画面质量与不确定度 |

Windows 目标机当前不在 Fedora 会话可用环境中。P0 的仓库/候选身份已核对，但五路/声音/显示条件尚未核齐，不能标记 P0 通过。Private camera addresses, secrets, full logs and footage stay outside Git, CI and Releases.

### 数据收集口径 / Measurement protocol

先将原始数据保存在目标机的 Git 外私密目录，每次运行记录 UTC+08 时间、源码/包摘要、来源匿名 ID 和 OBS 设置。OBS 与产品交替单独运行；每次预热 ≥3 分钟、采样 ≥20 分钟，至少三组成对且交替先后；初步满足后稳定性 ≥2 小时。保留原始进程累计 CPU 时间/创建时间、按适配器 LUID/Video Decode/3D/Copy 分类的 GPU 时间及采集工具版本。不要相加异口径百分比或重复计算共享 GPU 时间/内存。

每轮用同一计量办法统计产品全部所属进程，辅助进程不排除；双方合成输入发布器成本一致，或都在外部。画面全程可见，不以黑屏、低帧、静音、隐藏暂停、额外延迟换低读数。截图/CPU 像素分析仅测试或短时诊断，不进入常驻逐帧路径。缺失功耗/延迟/硬解证据明确写“未测”，不填 0。

### 架构与能力迁移账目 / Architecture and capability migration ledger

2026-10-31 决定优先固定 OBS 原生前端 + 产品插件/Qt 扩展；更新旧的 Electron 永久宿主说明。当前完整产品仍为 Electron + supervised services，未静默替换默认包；原生原型要在独立配置和可回退入口中验证。

| 能力/组件 / Capability | 现状 / Current | 目标/退出条件 / Target |
| --- | --- | --- |
| 来源、场景、Program、投影、五路本地媒体 | 现有 libobs + 自制 Win32 试验窗口；黑屏待定位 | 固定 OBS 前端的媒体源/场景/原生显示，兼容配置复用 source，不按 URL 粗暴共享 |
| 配置、来源标识、布局、音轨/过滤器 | 现有产品私有数据格式 | 待迁移；不覆盖 OBS 或既有产品数据、不静默导入 |
| 账号、权限、Origin、loopback、备份恢复 | 现有 C++/Python/主进程边界 | 待迁移/保留远程后端；未等价验证前不替换完整产品 |
| 单实例、托盘/后台、正常退出、崩溃收束 | Electron + Windows Job | 新宿主需等价行为测试，不能仅删除 Electron 测试 |
| 安装、升级、卸载保留数据/失败恢复、更新校验 | 完整 NSIS 路径 | 原生宿主独立验证后再切默认；开发包不进 stable feed |
| Electron | 当前完整兼容路径 | 迁移门槛完成后移出 Windows 默认安装/常驻 |
| MediaMTX / go2rtc | 现有分发/适配服务 | 普通本地 RTSP 不必经；按实际消费者启停 |
| 外置 FFmpeg | 当前转换/导出等任务 | 普通本地媒体用 OBS 内部 obs-ffmpeg，外部任务按需；不同 ABI DLL 不直接替换 |
| Python / 检测 ONNX、NumPy、模型 | 当前默认大包 | 必需本地能力迁入原生/共享库；检测作版本/摘要验证扩展 |
| Node/网站提取 / CEF / Caddy | 当前完整包 | 网站来源/浏览器源/LAN HTTPS 按需组件；许可证、对应源码与离线安装可用 |

所有保留进程还须记录启动者、消费者、退出条件及异常清理者。原型只覆盖明确声明的本地能力，其他能力仍写待迁移，不宣称已完整替代。

### 本轮状态 / Current round

- 修改前路径、进程与依赖：dev.17 完整包身份冻结如上；默认安装仍未切换。
- 五路真实画面/实际 GPU 与逐路硬解：未测；源码策略 `auto` 不作硬解证明。
- 性能/体积目标：未通过；不将 CI、小型合成媒体或候选发布当目标完成。
- 执行中：P1 固定源码定位 + 最终窗口像素回归；P2 最小 OBS 原生宿主和隔离配置构建；测试结果、候选与下一步将在本记录追加。
- 下一轮：先用已知图案显示测试区分窗口绘图、场景/Program 与媒体出帧层；保留原缺陷可失败的回归，再上目标机验证真实五路与可比 OBS 设置。

## 2026-10-31 / 首轮实现与实测记录

### P1：已经证实的独立窗口缺陷，不冒充用户黑屏根因

Job 启动器使用 `STARTF_USESHOWWINDOW/SW_HIDE` 隐藏控制台，原生窗口第一次 `ShowWindow(SW_SHOW)` 会受该启动标记影响。冻结 dev.17 的首次窗口在最终像素工具介入前确为隐藏；这与用户“窗口可见但画面黑”不相同。`bb124c8` 将显式展示改为 `SetWindowPos(...SWP_SHOWWINDOW)` 并检查 `IsWindowVisible`，未猜测更改矩阵、sRGB 或渲染 API。[首轮新核心 Windows 检查](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/41180349503) 中 unit/proxy/新 Win32 子进程回归 3/3 通过，窗口回归 0.12 秒；旧首次 ShowWindow 仍隐藏、新 helper 首次与重开可见。该修复只证明窗口自显，不证明摄像机图像成功。

Draw callback is before swapchain Present. Authenticated diagnostic snapshots now report video/texture/output binding and active/showing state on request, without per-frame CPU readback; neither callback count nor these flags qualify final media pixels or hardware decoding. UI wording in `24e8eb3` reflects that boundary, with compatibility for older backends.

### 冻结旧包、失败与回归范围

- 旧包始终是同一 dev.17 artifact `12981884498`，摘要 `91306c23c876a87fa3648367fa123fe35383b34710bcbd9b72a7bfc5e2f25f81`；新测试代码不重新构建旧运行时。
- [对照 41179250595](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/41179250595)：选择器原先要求已可见窗口，故在读像素前失败，**不是重现黑屏**。改为精确 PID/路径/类名定位测试自有 HWND，明确记录 `initiallyVisible`，仅旧包允许工具强制展示；新包必须自己显示。
- [对照 41179685711](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/41179685711)：已展示的五色 Program 最终像素通过；随后测试发布路径不符合既有网关 ACL，未进入媒体检查。修正为五个独立 `hybrid-<32hex>` 测试路径，未放宽生产权限。
- [对照 41180301808](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/41180301808)：五色 Program、五路独立 HEVC B 帧图案、倒序布局最终像素与各路时间进度通过；重开后第一张截图为黑，原门槛失败。首轮新核心构建也在该阶段失败，未生成安装器，不发布。
- 固定源码显示媒体在 inactive 时关闭、reactivate 时异步重启且清空旧帧，绘制计数增长不表示 decoder 恢复。此前首开等待 healthy=5 + 1500ms，重开只等 callback，测试条件不对称。`a208029` 现在完整保留重开早期 8 张样本的逐帧成功/失败、采样相对时间与绝对时间边界，明确标为 **启动过渡观察，不是验收通过**；再使用与首开相同的有界健康/预热条件做恢复后的严格全样本像素与时间进度检查。不丢弃失败样本、不以等到一次亮图判成功；等待前后的健康及恢复耗时另记。

- [同口径旧包对照 41181886193](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/41181886193)：最终像素回执 `passed=true`，五色、五路 HEVC、倒序、恢复后重开全部通过，**因此不能把新测试的恢复后成功归因于新核心修复**。启动观察 8 张中 7 张仍不满足完整五路；首个完整样本位于重开后约 3859ms，恢复准备记录 5561ms（含 1500ms 预热）。这些是合成输入/软件 D3D11 的短时数据，不是用户真实黑屏已定位或延迟目标已过。整个 job 随后在原有 Composite 合约因诊断工作流未安装 `@playwright/test` 失败；像素回执 `13035217646` / SHA-256 `a691ee0d5165e27f2fadd2463f5024d58b028807d007da1327d4602b0ff63e15` 独立保留，不能写成整个 CI 通过。后续为冻结诊断补装锁定 web/Chromium 工具，保留全部既有合约，不删测试。

The strict gate detects black/missing/swapped/duplicated/flipped/frozen channels and wrong final positions in known synthetic fixtures. Black camera content remains legal. Screenshots stay in the disposable synthetic fixture directory; only bounded counters and non-private synthetic diagnostics are retained. Window occlusion/no interactive desktop fails explicitly.

[新候选完整检查 41181595863](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/41181595863) 已成功，实际产品源码 `24e8eb371582c646c5e4c7059e070d37b4fdfcaa`、版本 `4.1.0-dev.18`，audit 与完整 Windows build/runtime/Composite/source-UI/main/package/NSIS 安装检查保留且通过；历史 installed-upgrade 专项未请求。最终像素回执四个严格阶段通过，新窗口在工具介入前均已可见。重开早期观察 8 张中 6 张不完整，首个完整样本约 4003ms，恢复准备 6930ms（含 1500ms 预热与请求开销）；不将这些过渡帧接受为成功，也不声称用户持续黑屏根因已修复。像素 artifact `13035643128` / SHA-256 `113eec5a2889515671cac8a560aff2b56261803de4d394638021e80d23c7cda0`。Build runner uses Microsoft Basic Render Driver, not the target RTX 4090 Laptop.

完整候选 artifact `13035199490` / `1031259327` 字节 / ZIP SHA-256 `fb2581a20dd9388c2ed63af2f6b824854bfc765dfbe036bbbe5c7b037907a594`，安装器 `427436667` 字节。足迹清单的 `installedBytes=1459397091` / 7500 files 实际来自 `release-assets.mjs` 对 `win-unpacked` 的遍历，不是用户机器重新安装后的磁盘占用；配置、卸载器、分配空间与用户数据边界仍须实测。后续 footprint schema 2 明确记为 `measurementScope=packaged-unpacked-tree / byteMetric=logical-file-length / unpackedPayloadBytes`，实际安装逻辑/分配字节未测时均为 null；旧 installedBytes 仅作为带说明的弃用别名兼容，不回写已发布附件。开发 Pre-release 仅复制该固定构建字节，不重新打包、换 DLL 或替换 stable/Latest。独立 OBS/Qt 原型不混入这个安装器。

### dev.18 开发交付 / Development prerelease delivery

[固定字节发布检查 41185010472](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/41185010472) 已通过：Windows 上先执行离线资产校验正/负例，再核对构建 run/source/artifact 全 ZIP 的字节数与摘要，复制原有八个附件，逐项检查 GitHub 上传摘要后公开 [v4.1.0-dev.18 Pre-release](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/releases/tag/v4.1.0-dev.18)。发布时间 `2026-10-31T08:33:41Z`，Git tag 与 release target 均为已测试的 `24e8eb371582c646c5e4c7059e070d37b4fdfcaa`，不是后续测试 harness 的源码。没有重建产品、覆盖已有资产或发布像素测试专用运行时。

安装器 [直接下载](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/releases/download/v4.1.0-dev.18/WebOBS-4.1.0-dev.18-windows-x64-DEVELOPMENT-UNSIGNED.exe)：`427436667` 字节，SHA-256 `1663e24827de1a9ce41b9e44957bf37bc1b0545c91f7b5cb62b369347d3b8e4f`。`draft=false / prerelease=true`，仅八个白名单附件，无私密校验回执；stable Latest 仍是 release `406670417 / v4.0`。This is unsigned development delivery, not target-camera/performance qualification or an OBS-native default-host migration.

### Linux 实际 libobs 与浏览器边界

Opt-in `WEBOBS_BUILD_OBS_RENDER_TESTS` 对固定 OBS 实际渲染到测试 FBO，并读取已知色块位置，覆盖 activate、prepare 不改 Program、cut、失败 prepare、deactivate/reactivate，确认无 encoder/raw video consumer 也有主纹理。Fedora 44 / RTX 3090 / NVIDIA 615.78.08 / X11 EGL / OpenGL 3.3：CTest 3/3 通过，GPU 测试 0.57 秒，额外重复 10/10 通过。只证明该 Linux/libobs 路径，不证明 Windows D3D11/HWND/Present/摄像机或性能。

dev.18 原始最终像素工作提交的桌面 Node 单测 58/58、公开工作流策略 18/18、受控诊断 UI 的 typecheck + 两项 focused Playwright 通过。后续 unpacked footprint 语义修复及空树未知指标不填零的负例使桌面检查为 59/59；离线发布资产正负例 32/32、策略 18/18 再验通过。它们分别证明 predicate、边界与界面交互，不替代最终像素实测；测试夹具无真实后端时的 WebSocket proxy refusal 不当成产品网络诊断。

### 原生宿主最终像素首轮：编译通过，捕获失败 / First native-host pixel run

默认关闭的 `-PixelTest` 独立测试构建 [41185006193](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/41185006193) 实际 Windows/Qt/MSVC 编译及五个有限阶段均执行，但小型回执 `status=failed / syntheticFinalWindowPixelsQualified=false`。每阶段实际主 Preview 与 Program projector 捕获均失败，读取八个 BMP 为 ENOENT；**未得到最终像素，不能称为截到黑屏、媒体失败或迁移通过**。已能记录阶段零/五个全局 ffmpeg source（包括 private sources）、既有五个 UUID/pointer/settings 不变、active output/encoder/raw consumer 为零、正常退出及外部 OBS profile 未变，但这些不是图像替代证明。

静态复查发现 PowerShell 7 的 `Add-Type -ReferencedAssemblies System.Drawing,System.Windows.Forms` 覆盖默认引用集，而捕获代码使用 Process/Stopwatch 等额外 .NET 类型；原始 subprocess stderr 未保留使首轮具体错误不可还原，不能断言这就是唯一根因。下一检查先做编译预检并只输出固定枚举错误类别，保持 PID/exe/创建时间/HWND/root/可见性/遮挡等守卫以及所有逐样本图像门槛，不公开 token、窗口身份、私密路径、BMP 或测试运行时。普通原型和已发布 dev.18 不随此测试修改。

### 最终像素门槛在 Windows 通过（合成夹具）/ Native final-pixel gate passed on Windows

失败的真正入口是 PowerShell 7 的 `Add-Type -AssemblyName System.Drawing`：它先于任何截图在 assembly-load 阶段抛错，旧回执只留下 ENOENT。随后两次引用集调整分别得到 CS0012 与 CS1069，证明混用运行时/引用包不是修复方向。`ec4485c` 把捕获改为**纯 GDI**：`GetDC` → 兼容 DC/位图 → `BitBlt` 复制客户端区域 → 取消选择 → `GetDIBits` 取 24 位 BGR → 手写 BMP 头；屏幕边界改用 `GetSystemMetrics`，不再加载 Drawing/WinForms。编译预检与有限合约步骤随后通过，捕获回执首次包含完整 stage/code 诊断，8 个样本不再重试。

[Windows 运行 41198311598](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/41198311598)（`ec4485c`）五个阶段全部 `passed`，主 Preview 与 Program projector 各 8 样本全部 `passed/captureFailed=false`，覆盖：五个已知色、五路独立 HEVC、Studio Preview 不隐式 TAKE、显式 TAKE、重开 Program（generation 2）。回执显示主 Preview 客户端 998×578、Program 单独窗口客户端捕获、每阶段时间码/色块参数推进、正常退出、外部 OBS profile 未变、active output/encoder/raw consumer 均为零。回执 artifact `webobs-obs-native-final-pixels-4.1.0-dev.18`（id `13041537611`，2295 字节 zip），JSON 30678 字节 / SHA-256 `1a8e877789e2d010486cc6fc9fe3963dbdeb7d83629f7ee61c247266ae01edab`。

这仍是**合成夹具 + GitHub 托管 Windows Server 2022（Microsoft Basic Render Driver 软件 D3D11）**，不是目标 i9-13900HX/RTX 4090、真实五路 HEVC 摄像机或 OBS 同机对照；BitBlt 读到的是可见窗口像素，不是 GPU/硬解指标。P2–P5 的实机、能力迁移、体积与性能门槛保持未通过，默认包仍为旧 Electron，未发布、未改标签。

The real entry failure was `Add-Type -AssemblyName System.Drawing` in PowerShell 7, which threw at assembly-load before any capture; the old receipt only showed ENOENT. Two later reference-set rewrites produced CS0012 and CS1069, ruling out mixed runtime/reference packs. `ec4485c` replaces capture with core-only GDI: GetDC, compatible DC/bitmap, BitBlt of the client area, deselect, GetDIBits to 24-bit BGR, then a hand-written BMP header, with GetSystemMetrics for bounds and no Drawing/WinForms load. Windows run 41198311598 (`ec4485c`) passed all five phases for both the main Preview and the Program projector, eight samples each, covering known colors, five independent HEVC fixtures, Studio Preview without implicit TAKE, explicit TAKE, and Program reopen (generation 2), with normal exit and unchanged external OBS profile. The receipt artifact is `webobs-obs-native-final-pixels-4.1.0-dev.18` (id 13041537611, 2295-byte zip); the JSON is 30678 bytes, SHA-256 `1a8e877789e2d010486cc6fc9fe3963dbdeb7d83629f7ee61c247266ae01edab`. This is still synthetic fixtures on a GitHub-hosted software-D3D11 runner, not the target RTX 4090, real cameras or an OBS comparison; P2–P5 gates, migration, size and performance remain open, the default package is still legacy Electron, and nothing was published or tagged.

### 安装目录实际占用：契约通过，NSIS 记录待完整构建 / Installed-tree footprint

新增只读工具 [installed-tree-footprint.ps1](../desktop/tests/installed-tree-footprint.ps1)：在 NSIS 创建隔离安装根**之前**登记 scope，安装后、首次启动前用 `FILE_STANDARD_INFO` 统计逻辑字节、主数据流分配、文件/目录数与分配单元；拒绝 UNC/设备/ADS、非固定盘、reparse、硬链接、重复身份与扫描期间变化，失败不返回部分或填零结果。安装烟测把 `installedTreeFootprint` 写入 `windows-install-smoke.json`，并新增独立 Windows 契约测试（合成临时夹具，junction / 硬链接 / 可选符号链接 / 越界路径负例）。`37fe688` 起回执再带 `sizeGroups` / `sizeGroupsComplete`：按相对目录前两级归集逻辑/分配字节与文件/目录数，根目录直接文件记为 `.`，最多 199 组再加 `__other__`，不写文件名或绝对路径，用于定位安装体积构成。

[Windows 契约运行 41198963353](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/41198963353)（`247b9d9`，job `footprint-contracts`）通过：空树、缺失根、上限、硬链接、junction（根/子/祖先）与 stream 路径拒绝、JSON 无路径等全部 passed。[补充契约运行 41200999641](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/41200999641)（`37fe688`）18 秒通过，新增校验各组合计等于总数、空目录只有根组、组名必须为相对目录。这仅证明 Windows API 契约，**不代表**已测安装包体积或 OBS 同口径比较；实际 NSIS 记录由完整构建的安装烟测产生，目标机复测步骤见[目标机验收运行手册](windows-target-qualification-runbook.md)。

A new read-only tool records the scope before NSIS creates the isolated install root, then measures logical bytes, main-stream allocation, file/directory counts and allocation unit after install and before the first start, rejecting UNC/device/ADS paths, non-fixed volumes, reparse points, hard links, duplicate identities and changes during the scan. The install smoke writes `installedTreeFootprint` into its receipt, and a standalone Windows contract test covers synthetic fixtures. Since `37fe688` the receipt also carries `sizeGroups` / `sizeGroupsComplete`: logical and allocated bytes plus file/directory counts grouped by the first two components of each relative directory, root-level files as `.`, bounded at 199 groups plus `__other__`, with no file names or absolute paths. Contract run 41198963353 (`247b9d9`, job `footprint-contracts`) passed, and supplementary run 41200999641 (`37fe688`) passed in 18 seconds, adding checks that group totals reconcile, an empty tree has only the root group, and names are relative directories; this proves only the API contracts, not the packaged installer size or any OBS comparison. Actual NSIS records come from the full-build install smoke, and target-machine repeat steps are in the [target qualification runbook](windows-target-qualification-runbook.md).

完整构建 [41199031917](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/41199031917)（`247b9d9`，dev.19）的安装烟测首次产出真实安装记录：`logicalBytes=1459568444`、`mainStreamAllocationBytes=1472924328`、7501 文件 / 1108 目录、分配单元 4096 B、扫描 352 ms；安装包 SHA-256 `b702f04f24f0cef78ee94f20c64454963c6ea610bf6770f857abba5782ba1e85`。这是当前 Electron 默认包在 GitHub 托管 Windows Server 2022 上的实装字节，**不是**目标机、也**不是** OBS 同口径；1.46 GB 与同口径 OBS 的体积目标差距明显，P4 的体积收敛尚未开始。之后的构建会单独上传 `webobs-windows-install-smoke-<version>` 小附件；本次记录在加入该步骤之前，通过有界 Range 从未下载的候选 ZIP 中抽取。

The full-build install smoke at run 41199031917 (`247b9d9`, dev.19) produced the first actual installed-tree record: logicalBytes 1459568444, mainStreamAllocationBytes 1472924328, 7501 files over 1108 directories, 4096-byte allocation unit, 352 ms scan; installer SHA-256 b702f04f24f0cef78ee94f20c64454963c6ea610bf6770f857abba5782ba1e85. This is the current Electron default package on a GitHub-hosted Windows Server 2022 runner, not the target machine and not OBS same-scope; 1.46 GB leaves an obvious gap to the volume target and P4 size convergence has not started. Later builds upload the small webobs-windows-install-smoke-<version> artifact; this run predated that step, so the receipt was read through bounded ranges from the undownloaded candidate ZIP.

### P2–P5：原型与后续门槛

完整 [能力迁移账本](windows-obs-capability-migration.md) 区分普通 RTSP 直读与控制面/持久任务：现有 cluster/RBAC fail-closed、MTX/NVR 更新工作门、Windows CEF 启动要求、备份/事件/录像任务均不能通过直接删除服务绕过。后续先拆 renderer-free 控制适配、只读数据导入 dry-run 与持久能力状态，再逐项迁移并保留回退。

`37e4f98` 增加独立 `native-host/` 与 `desktop/scripts/build-obs-native.ps1`：固定 OBS 完整 Qt frontend + 产品 dock，按已有 source UUID 复用媒体源，非破坏新建五分屏，Studio Preview 不自动 TAKE，投影使用 OBS 原生接口。全新 portable 配置与原 OBS/产品数据隔离，不启动旧服务。Linux 的七项 Python build contract 与固定真实 OBS headers API contract 1/1 已通过。[Windows 原型检查 41180501363](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/41180501363) 已成功：在 Windows 2022 / VS2022 实际编译 OBS 32.1.2 + Qt 6.8.3 + 产品插件，Qt dock 与媒体源注册、独立 portable 配置、原 OBS profile 未改变、清除继承插件覆盖及正常退出烟测均通过。`mediaQualified=false`，**不证明五路最终像素、摄像机、硬解或性能**。干净归档在烟测产生私密配置前完成，不上传配置和日志。Artifact `13034867787` / `78036418` 字节 / SHA-256 `86cdc83ad3677425fe86dd71a3b46a8b1e6bd6e96c932b0ae92f78810ad59e6a`；prototype manifest 之前文件总字节 `243419789`（Qt `23833088`、plugins `73164953`、other `146421748`），不是安装器大小、完整产品安装空间或同口径原版 OBS 比较，仍未达到体积验收。

本轮不切换默认包、不删除旧能力、不移动已发布标签。原型仍缺产品认证/迁移/安装升级与许可证、源码交付审计；实际五路硬解、同源 decoder 数、真实 Windows GPU/显示拓扑、首轮 OBS A/B 及安装体积同口径目标均未通过。全屏/DPI/多显示器/故障恢复、直接绘图 A 层与本地 H.264 独立测试尚待补齐。P5 只读进程树 CPU/内存采集工具已落地，固定进程 PID+创建时间、原始累计 CPU、保留已观察退出句柄尾数、元数据/原始文件 SHA-256 与三对交替检查；[Windows API 与隔离启动检查 41182986553](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/41182986553) 通过，包含九项合成逻辑及四项真实 Windows times/memory/snapshot、退出尾数、protected 当前用户+SYSTEM DACL、短时采样且 fixture 不被停止合约。没有开展产品 P5 测量；轮询遗漏短命后代、未知中间父进程和树外服务仍使 coverageIncomplete=true / strictTotal=false / qualified=false。GPU、显存、功耗、延迟、最终画面与硬解等未测量项保留 null，不能由不完整下界宣布总体性能等价。
