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

本轮之后五路本地夹具改为 3 路 HEVC + 2 路 H.264（阶段改名 `five-codecs`），[Windows 运行 41202609376](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/41202609376)（`10c3728`）五个阶段全部 passed，两种角色各 8 个样本，回执 artifact `webobs-obs-native-final-pixels-4.1.0-dev.21`（id `13043470707`，2250 字节 zip）；`rtspQualified` / `realCameraQualified` / `mediaHardwareQualified` 仍为 false。

这仍是**合成夹具 + GitHub 托管 Windows Server 2022（Microsoft Basic Render Driver 软件 D3D11）**，不是目标 i9-13900HX/RTX 4090、真实五路 HEVC 摄像机或 OBS 同机对照；BitBlt 读到的是可见窗口像素，不是 GPU/硬解指标。P2–P5 的实机、能力迁移、体积与性能门槛保持未通过，默认包仍为旧 Electron，未发布、未改标签。

The real entry failure was `Add-Type -AssemblyName System.Drawing` in PowerShell 7, which threw at assembly-load before any capture; the old receipt only showed ENOENT. Two later reference-set rewrites produced CS0012 and CS1069, ruling out mixed runtime/reference packs. `ec4485c` replaces capture with core-only GDI: GetDC, compatible DC/bitmap, BitBlt of the client area, deselect, GetDIBits to 24-bit BGR, then a hand-written BMP header, with GetSystemMetrics for bounds and no Drawing/WinForms load. Windows run 41198311598 (`ec4485c`) passed all five phases for both the main Preview and the Program projector, eight samples each, covering known colors, five independent HEVC fixtures, Studio Preview without implicit TAKE, explicit TAKE, and Program reopen (generation 2), with normal exit and unchanged external OBS profile. The receipt artifact is `webobs-obs-native-final-pixels-4.1.0-dev.18` (id 13041537611, 2295-byte zip); the JSON is 30678 bytes, SHA-256 `1a8e877789e2d010486cc6fc9fe3963dbdeb7d83629f7ee61c247266ae01edab`. After this round the five local fixtures are 3 HEVC + 2 H.264 (phase renamed five-codecs). Windows run 41202609376 (`10c3728`) passed all five phases with eight samples per role; the receipt artifact is webobs-obs-native-final-pixels-4.1.0-dev.21 (id 13043470707, 2250-byte zip), while rtspQualified, realCameraQualified and mediaHardwareQualified stay false.

This is still synthetic fixtures on a GitHub-hosted software-D3D11 runner, not the target RTX 4090, real cameras or an OBS comparison; P2–P5 gates, migration, size and performance remain open, the default package is still legacy Electron, and nothing was published or tagged.

### 全屏 Program 投影最终像素（合成夹具）/ Fullscreen Program projector final pixels

最终像素门槛新增第八相位 `program-fullscreen`（`5b4b643`）：在第七相位恢复后打开 monitor 0 的真实全屏 StudioProgram 投影，要求 `isFullScreen()`、五路回环 RTSP 仍为 PLAYING、当前场景仍是五格 RTSP 墙，然后分别捕获主 Preview 与全屏 Program 客户端八帧；全屏角色保留全屏几何，不再套用窗口化 1100×740 的尺寸。`9f49d8f` 把 `program-fullscreen` 加入分析器角色白名单（inset=0）；`20d173e` 修正升级与体积基线步骤的混合 `${{ }}` 条件——拼接后的字符串恒为真，导致像素运行误触升级步骤并因没有原型 ZIP 失败。这两次失败均是测试工程缺陷，不是像素回归。

[Windows 运行 41224874089](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/41224874089)（`20d173e`，dev.37）八个相位全部 passed：第一至第五相位主 Preview 与 Program projector 各 8 样本，第六、七相位主 Preview 各 8 样本，第八相位主 Preview 与全屏 Program 各 8 样本；`programFullscreenPhaseQualified=true`、`syntheticFinalWindowPixelsQualified=true`。回执 artifact `webobs-obs-native-final-pixels-4.1.0-dev.37`（id `13051488872`，2968 字节 zip，JSON 2968 字节）。`rtspQualified` / `realCameraQualified` / `mediaHardwareQualified` / `performanceP2Qualified` / `productMigrationQualified` 仍为 false。

该证据覆盖**单显示器、100% 缩放、软件 D3D11 运行器**上的全屏 Program 投影最终像素；DPI 缩放、多显示器、保存场景重启与真实相机/硬解仍不在其中，不能视为 P1 显示项全部完成或 P5 目标机结论。

An eighth finite phase, `program-fullscreen` (`5b4b643`), opens a real fullscreen StudioProgram projector on monitor 0 after the recovery phase, requires `isFullScreen()`, all five loopback RTSP streams still PLAYING and the current scene to remain the five-tile RTSP wall, then captures eight frames from both the main Preview and the fullscreen Program client, keeping the fullscreen geometry instead of the windowed 1100×740 size. `9f49d8f` added `program-fullscreen` to the analyzer's role allowlist (inset=0), and `20d173e` fixed the mixed `${{ }}` conditions on the upgrade and size-baseline steps, whose joined string was always truthy and made a pixel run execute the upgrade step and fail without a prototype ZIP. Both failures were test-engineering defects, not pixel regressions.

Windows run [41224874089](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/41224874089) (`20d173e`, dev.37) passed all eight phases: eight samples each for the main Preview and Program projector in phases 1–5, eight main-Preview samples in phases 6–7, and eight samples each for the main Preview and the fullscreen Program in phase 8, with `programFullscreenPhaseQualified=true` and `syntheticFinalWindowPixelsQualified=true`. The receipt artifact is `webobs-obs-native-final-pixels-4.1.0-dev.37` (id 13051488872, 2968-byte zip; JSON 2968 bytes). `rtspQualified`, `realCameraQualified`, `mediaHardwareQualified`, `performanceP2Qualified` and `productMigrationQualified` remain false.

This covers fullscreen Program pixels on a **single-monitor, 100%-scale, software-D3D11 runner**; DPI scaling, multiple monitors, saved-scene restart and real cameras/hardware decode are not covered, so it is not a completed P1 display gate or a P5 target conclusion.

### 全屏投影跨断流恢复 / Fullscreen projector across a stream interruption

新增第九相位 `fullscreen-recovery`（`4b5e0e5`）：第八相位完成后保持全屏 StudioProgram 投影打开，驱动在确认第八相位后中断第一路合成 RTSP 发布者 20 秒再重启；宿主必须在全屏投影仍播放时观察到至少一路离开 PLAYING，再等五路恢复 PLAYING、仍在同一五格墙且全屏状态未变，才发布第九相位并分别捕获主 Preview 与全屏 Program 八帧。这样“断流恢复期间全屏投影仍展示恢复后的同一画面”不再是推测。

[Windows 运行 41226901078](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/41226901078)（`602723a`，dev.39）九个相位全部 passed：第八相位主 Preview 与全屏 Program 各 8 样本，第九相位在全屏投影保持打开、断流 20 秒并恢复后同样各 8 样本；`fullscreenRecoveryPhaseQualified=true`、`syntheticFinalWindowPixelsQualified=true`，回执 artifact `webobs-obs-native-final-pixels-4.1.0-dev.39`（id `13051764319`，3185 字节 zip）。首轮 dev.38 在八相位后超时，原因是驱动把相位循环写死为 8 而没有等待第九相位，`602723a` 改为按 `PHASES` 长度迭代并加契约断言。

该证据仍受**单显示器、100% 缩放、软件 D3D11、合成 RTSP 夹具**限制：断流期间的中断画面本身不被采集，只验证恢复后全屏投影仍显示同一五格墙；DPI 缩放、多显示器、保存场景重启、真实相机/硬解不在其中，`rtspQualified` / `realCameraQualified` / `mediaHardwareQualified` / `performanceP2Qualified` / `productMigrationQualified` 仍为 false。

An ninth finite phase, `fullscreen-recovery` (`4b5e0e5`), keeps the real fullscreen StudioProgram projector open after phase 8 while the driver interrupts the first synthetic RTSP publisher for 20 s and restarts it; the host must observe at least one stream leaving PLAYING while the fullscreen projector is still playing, then wait for all five to return PLAYING on the same five-tile wall with the fullscreen state unchanged before publishing the phase and capturing eight frames each from the main Preview and the fullscreen Program. "The fullscreen projector still shows the recovered scene after an interruption" is therefore no longer a guess.

Windows run [41226901078](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/41226901078) (`602723a`, dev.39) passed all nine phases: eight samples each for the main Preview and the fullscreen Program in phase 8, and eight each again in phase 9 after the fullscreen projector stayed open across the 20-second interruption and recovery, with `fullscreenRecoveryPhaseQualified=true` and `syntheticFinalWindowPixelsQualified=true`. The receipt artifact is `webobs-obs-native-final-pixels-4.1.0-dev.39` (id 13051764319, 3185-byte zip). The first dev.38 attempt timed out after eight phases because the driver hard-coded the phase loop to eight and never waited for the ninth; `602723a` iterates over `len(PHASES)` and adds a contract assertion.

This is still limited to **one monitor, 100% scale, software D3D11 and synthetic RTSP fixtures**: the interrupted frames themselves are not captured; only the recovered fullscreen projection of the same five-tile wall is verified. DPI scaling, multiple monitors, saved-scene restart, real cameras and hardware decode remain uncovered, and `rtspQualified`, `realCameraQualified`, `mediaHardwareQualified`, `performanceP2Qualified` and `productMigrationQualified` stay false.

### 回环 RTSP 阶段：测试已扩展，尚未运行 / Loopback RTSP phase

`pixel_test` 有限阶段新增第六阶段 `rtsp-loopback`：测试在启动前先退出 Studio、关闭 Program 投影，再由锁定的 MediaMTX 1.18.2（`desktop/dependencies.lock.json`）在 `127.0.0.1:8554` 上服务五路 `hybrid-<32hex>-1..5` 回环路径，五路 ffmpeg 发布器以 TCP 循环推送同一组本地夹具；harness 只接受五条 `^rtsp://127\.0\.0\.1:[1-9][0-9]{0,4}/hybrid-[0-9a-f]{32}-[1-5]$` URL，以 `is_local_file=false`、`restart_on_activate=true`、`close_when_inactive=false` 创建五个 ffmpeg Media Source 并组成五分屏，等待五路均为 PLAYING/320×180 后由外部仅捕获主 Preview 客户端像素。该阶段全局 ffmpeg 输入为 10，active output/encoder/raw consumer 仍须为零。回环 RTSP 只验证 HTTP 之外的真实解码/播放链路，**不等于**真实摄像机、硬解或 OBS 对照，`rtspQualified` 保持 false。

[Windows 运行 41204913562](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/41204913562)（`d098374`，dev.23）六阶段全部 passed：前五阶段主 Preview 与 Program projector 各 8 样本，回环阶段仅主 Preview 8 样本，五路 RTSP 均 PLAYING/320×180，全局 ffmpeg 输入 10，active output/encoder/raw consumer 均为零，正常退出、外部 OBS profile 未变，MediaMTX 与五个发布器按序停止。回执 34109 字节 / SHA-256 `1114c5a7d4e898d288fb995b6b7eb98560bcd6fd24460c794a72904d6a0d4953`；`loopbackRtspPhaseQualified=true`，`rtspQualified` 仍为 false（本机回环夹具而非真实摄像机、硬解或 OBS 对照）。首次回环运行 [41204036900](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/41204036900) 在前五阶段后因生成数断言错误失败，已由 `d098374` 修正。

断流恢复由 [41215455024](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/41215455024)（`4e02904`，dev.28）验证：第七相位在第六阶段确认后中断第一路发布者 20 秒再重启，宿主先观察到至少一路离开 PLAYING，再在五路恢复 PLAYING、仍在同一五格墙且全局输入仍为十个的前提下取八帧最终像素。通道 1 的时码从 0 重新开始，其余通道继续推进，八帧全部通过颜色、边界标记与时码检查；回执 `rtspRecoveryPhaseQualified=true`、`rtspQualified=false`。该证据只覆盖本机回环合成流与软件 D3D11 运行器，不代表真实相机、硬解或目标机。

A sixth finite phase, `rtsp-loopback`, has been added: the test leaves Studio mode, closes the Program projector, then a locked MediaMTX 1.18.2 serves five `hybrid-<32hex>-1..5` loopback paths on `127.0.0.1:8554` while five ffmpeg publishers loop the same local fixtures over TCP; the harness accepts only five `^rtsp://127\.0\.0\.1:[1-9][0-9]{0,4}/hybrid-[0-9a-f]{32}-[1-5]$` URLs, creates five ffmpeg Media Sources with `is_local_file=false`, `restart_on_activate=true`, `close_when_inactive=false`, builds a five-tile wall and captures only the main Preview client once all five are PLAYING at 320×180. Global ffmpeg inputs must be ten and active outputs/encoders/raw consumers zero. Loopback RTSP exercises the real decode/playback path beyond HTTP but is not a real camera, hardware decode or OBS comparison; `rtspQualified` stays false.

Windows run 41204913562 (`d098374`, dev.23) passed all six phases: the first five with eight samples for both the main Preview and the Program projector, and the loopback phase with eight main-Preview samples, five RTSP streams PLAYING at 320×180, ten global ffmpeg inputs, zero active outputs/encoders/raw consumers, a normal exit, an unchanged external OBS profile, and ordered MediaMTX/publisher shutdown. The receipt is 34109 bytes, SHA-256 `1114c5a7d4e898d288fb995b6b7eb98560bcd6fd24460c794a72904d6a0d4953`; `loopbackRtspPhaseQualified=true` while `rtspQualified` stays false, since this is a local loopback fixture rather than a real camera, hardware decode or OBS comparison. The first loopback run 41204036900 passed five phases and then failed on a wrong generation assertion, fixed by `d098374`.

Interruption recovery is covered by [41215455024](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/41215455024) (`4e02904`, dev.28): phase seven interrupts the first publisher for 20 s and restarts it after phase six is acknowledged; the host first observes at least one source leaving PLAYING, then samples eight final-pixel frames once all five are PLAYING again on the same five-tile wall with ten global inputs. Channel 1's timecode restarts at 0 while the others keep advancing, and all eight frames pass the colour, marker and timecode checks; the receipt records `rtspRecoveryPhaseQualified=true` and `rtspQualified=false`. This covers only local loopback synthetic streams on a software-D3D11 runner, not real cameras, hardware decode or the target machine.

### 五格墙复用与私密墙配置 / Five-tile wall reuse and private wall bootstrap

原生宿主新增 `ensure_five_tile_wall`：按固定名称 “WebOBS Native Wall” 与逐项顺序核对已保存场景，五项 UUID 完全一致才复用并选中；同名但来源不同则报错，绝不覆盖既有场景，也不新建解码器。插件在启动时读取私密 `plugin_config/webobs-native-host/wall.json`（schema 1，仅五个既有 ffmpeg_source UUID），复用或创建五格墙并写 `wall-bootstrap.json` 回执（无 URL、路径或画面）；配置不可读/非法时以固定错误码失败并保留原场景。像素回执从第二相位起记录 `wallReuseVerified`：[Windows 运行 41209084866](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/41209084866)（`95435da`，dev.24）六阶段全部 passed，回执 34119 字节 / SHA-256 `8461ea4934cddbac423f84c080cb0705800cfdc98beae59f5f88b4de4d01d84f`，前五阶段双角色、回环阶段主 Preview 各 8 样本。此前 [41207266353](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/41207266353) 因契约测试缺少场景枚举桩 LNK2019 失败、[41208059481](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/41208059481) 因第一相位即要求复用字段失败，分别由 `546ccf9`、`b7a3af8` 修正。这仍是隔离原型与合成夹具，不是产品默认、真实摄像机或目标机证据。

The native host adds `ensure_five_tile_wall`: it matches a saved scene by the fixed name "WebOBS Native Wall" and exact tile order, reusing and selecting it only when all five UUIDs match; a same-named scene with different sources is an error and is never overwritten, and no decoder is created. At startup the plugin reads a private `plugin_config/webobs-native-host/wall.json` (schema 1, only five existing ffmpeg_source UUIDs), reuses or creates the five-tile wall and writes a `wall-bootstrap.json` receipt (no URLs, paths or pixels); unreadable or invalid configuration fails with fixed codes and leaves existing scenes untouched. The pixel receipt records `wallReuseVerified` from the second phase on: Windows run 41209084866 (`95435da`, dev.24) passed all six phases with a 34119-byte receipt, SHA-256 `8461ea4934cddbac423f84c080cb0705800cfdc98beae59f5f88b4de4d01d84f`, eight samples for both roles in the first five phases and the main Preview in the loopback phase. Run 41207266353 failed on a missing scene-enumeration stub (LNK2019) and run 41208059481 required the reuse field already in the first phase; `546ccf9` and `b7a3af8` fixed them. This remains an isolated prototype with synthetic fixtures, not the product default, real cameras or target-machine evidence.

### 产品相机配置：从私密配置创建五格墙 / Product camera bootstrap

插件在启动时还会读取私密 `plugin_config/webobs-native-host/product.json`（≤16 KiB，schema 1），从五路相机配置创建或复用 OBS Media Source 并生成五格墙，不再要求先由人工建源：

```json
{"schema":1,"canvas":{"width":960,"height":540,"fps":30},
 "cameras":[{"id":"cam-1","name":"Camera 1","url":"rtsp://127.0.0.1:8554/example","hardwareDecode":false},
            {"id":"cam-2","name":"Camera 2","url":"rtsp://127.0.0.1:8554/example-2","hardwareDecode":false},
            {"id":"cam-3","name":"Camera 3","url":"rtsp://127.0.0.1:8554/example-3","hardwareDecode":false},
            {"id":"cam-4","name":"Camera 4","url":"rtsp://127.0.0.1:8554/example-4","hardwareDecode":false},
            {"id":"cam-5","name":"Camera 5","url":"rtsp://127.0.0.1:8554/example-5","hardwareDecode":false}]}
```

`id` 限 1–64 位 `[A-Za-z0-9_.-]`，名称 1–128 位且不含换行，URL 限 1–2048 位且只接受 `rtsp/rtsps/http/https`。可选 `canvas` 在创建源之前写入独立 portable profile 并重置视频；缺省则沿用现有画布。同名既有 `ffmpeg_source` 只有在 `is_local_file=false`、`input` 与期望 URL 相同且 `hw_decode` 一致时才复用，否则报 `camera-name-conflict` 且不覆盖；新建源使用 `looping=false`、`restart_on_activate=true`、`close_when_inactive=false`、`reconnect_delay_sec=10`、`buffering_mb=2`。墙按固定名 “WebOBS Native Wall” 复用或新建；任一步失败会移除本次新建的源并释放全部引用，既有源/场景不变。回执 `product-bootstrap.json` 只含 `created/reused/sceneReused/canvasApplied/items` 与固定错误码，不含 URL、名称或路径。

[Windows 运行 41211230980](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/41211230980)（`ba45f85`，dev.26）六阶段全部 passed：第六相位不再手工建源，而是以回环 RTSP 五路走同一产品创建路径，harness 断言本次新建 5 个源、复用 0 个，主 Preview 8 样本像素与时间码推进；回执 34112 字节 / SHA-256 `869cd667e473803a833979a08f8185b2e2fd014dee3a7f9a8b95af102ffc3e95`，`productBootstrapVerified=true`。前一次 [41210312765](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/41210312765)（`08527a1`，dev.25）也在该路径通过；`ba45f85` 只补失败路径的复用源释放。这仍是隔离原型与合成夹具，不是产品默认启动、真实摄像机、硬解或目标机证据，`rtspQualified` 保持 false。

启动路径同样已覆盖：[保护原型运行 41213367332](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/41213367332)（`cdbab01`，dev.26）把五路占位相机（`rtsp://127.0.0.1:9/...`，只验证创建/启动，不产生媒体成功）交给真实 `launch-native.ps1`。启动器只校验文件大小、schema 与五路数量并把配置写入新建私密 profile；插件在 FINISHED_LOADING 走同一产品创建路径。退出后烟测断言 `productCameraCreated=5`、`productCameraReused=0`、回执文本不含 URL，外部 OBS profile 未变。该运行仍只是启动存在性证据，不证明媒体、像素、硬解或目标机。此前 [41212306887](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/41212306887) 因 FINISHED_LOADING 误调墙引导、产品引导缺省分支递归而未生成回执，由 `cdbab01` 修正。

复用重启由 [41214423256](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/41214423256)（`aaa56cc`，dev.27）验证：同一一次性 portable profile 内连续启动两次，第一次 `created=5, reused=0`，第二次 `created=0, reused=5, sceneReused=true`。这说明同名相机源与五格墙在真实 OBS 存档重开后按名称、UUID 顺序与 URL/硬解设置匹配复用，不新建重复源、不覆盖已有配置；启动器新增的 `-ReuseProfile` 只允许既有的一次性开发配置。该运行仍只证明启动与复用，不证明媒体、像素、硬解或目标机。

The startup path is covered as well: protected prototype run 41213367332 (`cdbab01`, dev.26) hands five placeholder cameras (`rtsp://127.0.0.1:9/...`, creation/startup only, no media success) to the real `launch-native.ps1`. The launcher validates only size, schema and five-camera count and writes the config into the new private profile, then the plugin executes the same product creation path at FINISHED_LOADING. After exit the smoke asserts `productCameraCreated=5`, `productCameraReused=0`, no URL in the receipt text and an unchanged external OBS profile. This run is startup-existence evidence only, not media, pixels, hardware decode or target-machine proof. The earlier run 41212306887 produced no receipt because FINISHED_LOADING called the wall bootstrap and the product bootstrap's fallback branch recursed; `cdbab01` fixes both.

Reuse across restarts is covered by [41214423256](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/41214423256) (`aaa56cc`, dev.27): two consecutive starts inside the same disposable portable profile give `created=5, reused=0` on the first launch and `created=0, reused=5, sceneReused=true` on the second. The same-named camera sources and five-tile wall are reused after a real OBS save/reopen by name, UUID order and URL/hardware-decode settings, without duplicate sources or overwriting existing configuration; the launcher's new `-ReuseProfile` only allows an existing disposable development profile. This is still startup and reuse evidence only, not media, pixels, hardware decode or target-machine proof.

The plugin also reads a private `plugin_config/webobs-native-host/product.json` (at most 16 KiB, schema 1) at startup and creates or reuses the OBS Media Sources for five cameras plus the five-tile wall, so sources no longer have to be prepared by hand. The example above shows the exact shape. Camera ids are 1–64 characters of `[A-Za-z0-9_.-]`, names 1–128 characters without line breaks, and URLs 1–2048 characters restricted to `rtsp/rtsps/http/https`. An optional `canvas` is applied to the isolated portable profile before any source is created; without it the current canvas is kept. An existing same-named `ffmpeg_source` is reused only when `is_local_file` is false, `input` equals the requested URL and `hw_decode` matches; otherwise the bootstrap fails with `camera-name-conflict` and overwrites nothing. New sources use `looping=false`, `restart_on_activate=true`, `close_when_inactive=false`, `reconnect_delay_sec=10` and `buffering_mb=2`. The wall is reused or created under the fixed name "WebOBS Native Wall"; any failure removes the sources created in that attempt and releases every reference, leaving existing sources and scenes untouched. The `product-bootstrap.json` receipt contains only `created/reused/sceneReused/canvasApplied/items` and fixed error codes, never URLs, names or paths.

Windows run 41211230980 (`ba45f85`, dev.26) passed all six phases: phase six no longer creates sources by hand but drives the same product creation path with five loopback RTSP streams, and the harness asserts five newly created sources and zero reused ones with eight main-Preview pixel samples whose timecodes advance. The receipt is 34112 bytes, SHA-256 `869cd667e473803a833979a08f8185b2e2fd014dee3a7f9a8b95af102ffc3e95`, and `productBootstrapVerified=true`. Run 41210312765 (`08527a1`, dev.25) passed the same path; `ba45f85` only fixes reference release on failure. This remains an isolated prototype with synthetic fixtures, not the product default start, real cameras, hardware decode or target-machine evidence, and `rtspQualified` stays false.

### 冻结原型压缩包：解压即可运行 / Frozen prototype ZIP runs from a clean extraction

2026-10-31 独立 Windows 运行 [41216669986](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/41216669986)（`8ca6421`，dev.29）把冻结的 `WebOBS-OBS-native-4.1.0-dev.29-windows-x64-PROTOTYPE.zip`（构建树 243,466,645 字节，压缩后附件 77,942,333 字节）解压到全新临时目录，再对解压树执行同一套双启动烟测：OBS 32.1.2 / Qt 6.8.3、产品 dock 与 Media Source 注册、portable 配置、外部 OBS profile 未变、正常退出；首启按私密产品配置新建五路相机与五格墙（created=5，reused=0），第二启复用同一五格墙（created=0，reused=5，sceneReused=true）。压缩包内无 `config/`，解压目录不泄漏用户配置；回执 `native-portable-smoke.json` 记录上述布尔结果，`mediaQualified=false`。该证据只说明**下载到的压缩包本身自包含且能解压运行**，不是安装器、升级、像素、真实相机、硬解或 P5 性能验收。

The independent Windows run [41216669986](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/41216669986) (`8ca6421`, dev.29) extracted the frozen `WebOBS-OBS-native-4.1.0-dev.29-windows-x64-PROTOTYPE.zip` (243,466,645-byte build tree, 77,942,333-byte compressed artifact) into a clean temporary directory and ran the same two-launch smoke on the extracted tree: OBS 32.1.2 / Qt 6.8.3, product dock and Media Source registration, portable profile, unchanged external OBS profile and normal exit; the first launch created five cameras and the five-tile wall from the private product config (created=5, reused=0) and the second reused the same wall (created=0, reused=5, sceneReused=true). The ZIP carries no `config/` and the extraction leaks no user profile; the `native-portable-smoke.json` receipt records those booleans with `mediaQualified=false`. This proves only that the **downloadable ZIP is self-contained and runs**, not an installer, upgrade, pixel, real-camera, hardware-decode or P5 performance qualification.

### 安装目录实际占用：契约通过，NSIS 记录待完整构建 / Installed-tree footprint

新增只读工具 [installed-tree-footprint.ps1](../desktop/tests/installed-tree-footprint.ps1)：在 NSIS 创建隔离安装根**之前**登记 scope，安装后、首次启动前用 `FILE_STANDARD_INFO` 统计逻辑字节、主数据流分配、文件/目录数与分配单元；拒绝 UNC/设备/ADS、非固定盘、reparse、硬链接、重复身份与扫描期间变化，失败不返回部分或填零结果。安装烟测把 `installedTreeFootprint` 写入 `windows-install-smoke.json`，并新增独立 Windows 契约测试（合成临时夹具，junction / 硬链接 / 可选符号链接 / 越界路径负例）。`37fe688` 起回执再带 `sizeGroups` / `sizeGroupsComplete`：按相对目录前两级归集逻辑/分配字节与文件/目录数，根目录直接文件记为 `.`，最多 199 组再加 `__other__`，不写文件名或绝对路径，用于定位安装体积构成。

[Windows 契约运行 41198963353](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/41198963353)（`247b9d9`，job `footprint-contracts`）通过：空树、缺失根、上限、硬链接、junction（根/子/祖先）与 stream 路径拒绝、JSON 无路径等全部 passed。[补充契约运行 41200999641](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/41200999641)（`37fe688`）18 秒通过，新增校验各组合计等于总数、空目录只有根组、组名必须为相对目录。这仅证明 Windows API 契约，**不代表**已测安装包体积或 OBS 同口径比较；实际 NSIS 记录由完整构建的安装烟测产生，目标机复测步骤见[目标机验收运行手册](windows-target-qualification-runbook.md)。

A new read-only tool records the scope before NSIS creates the isolated install root, then measures logical bytes, main-stream allocation, file/directory counts and allocation unit after install and before the first start, rejecting UNC/device/ADS paths, non-fixed volumes, reparse points, hard links, duplicate identities and changes during the scan. The install smoke writes `installedTreeFootprint` into its receipt, and a standalone Windows contract test covers synthetic fixtures. Since `37fe688` the receipt also carries `sizeGroups` / `sizeGroupsComplete`: logical and allocated bytes plus file/directory counts grouped by the first two components of each relative directory, root-level files as `.`, bounded at 199 groups plus `__other__`, with no file names or absolute paths. Contract run 41198963353 (`247b9d9`, job `footprint-contracts`) passed, and supplementary run 41200999641 (`37fe688`) passed in 18 seconds, adding checks that group totals reconcile, an empty tree has only the root group, and names are relative directories; this proves only the API contracts, not the packaged installer size or any OBS comparison. Actual NSIS records come from the full-build install smoke, and target-machine repeat steps are in the [target qualification runbook](windows-target-qualification-runbook.md).

完整构建 [41199031917](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/41199031917)（`247b9d9`，dev.19）的安装烟测首次产出真实安装记录：`logicalBytes=1459568444`、`mainStreamAllocationBytes=1472924328`、7501 文件 / 1108 目录、分配单元 4096 B、扫描 352 ms；安装包 SHA-256 `b702f04f24f0cef78ee94f20c64454963c6ea610bf6770f857abba5782ba1e85`。这是当前 Electron 默认包在 GitHub 托管 Windows Server 2022 上的实装字节，**不是**目标机、也**不是** OBS 同口径；1.46 GB 与同口径 OBS 的体积目标差距明显，P4 的体积收敛尚未开始。之后的构建会单独上传 `webobs-windows-install-smoke-<version>` 小附件；本次记录在加入该步骤之前，通过有界 Range 从未下载的候选 ZIP 中抽取。

[Windows 运行 41201055747](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/41201055747)（`37fe688`，dev.20）的安装烟测经新上传的小附件 `webobs-windows-install-smoke-4.1.0-dev.20`（id `13043052995`，1537 字节）读取：`logicalBytes=1459568403`、`mainStreamAllocationBytes=1472924328`、7501 文件 / 1108 目录、255 ms，10 项安装检查全部 passed；`sizeGroupsComplete=true`，归因为 `resources/runtime` 1071346265 B（7426 文件）、根目录 `.` 335219451 B（17 文件）、`locales` 50643459 B、`resources` 2359228 B。运行时目录约占 73%，根目录的 Electron 可执行与 DLL 约占 23%，因此体积收敛应先处理旧运行时载荷；这仍是 GitHub 托管软件 D3D11 上的默认 Electron 包，不是目标机或 OBS 同口径。

The full-build install smoke at run 41199031917 (`247b9d9`, dev.19) produced the first actual installed-tree record: logicalBytes 1459568444, mainStreamAllocationBytes 1472924328, 7501 files over 1108 directories, 4096-byte allocation unit, 352 ms scan; installer SHA-256 b702f04f24f0cef78ee94f20c64454963c6ea610bf6770f857abba5782ba1e85. This is the current Electron default package on a GitHub-hosted Windows Server 2022 runner, not the target machine and not OBS same-scope; 1.46 GB leaves an obvious gap to the volume target and P4 size convergence has not started. Later builds upload the small webobs-windows-install-smoke-<version> artifact; this run predated that step, so the receipt was read through bounded ranges from the undownloaded candidate ZIP.

Windows run 41201055747 (`37fe688`, dev.20) install smoke, read from the new small artifact webobs-windows-install-smoke-4.1.0-dev.20 (id 13043052995, 1537 bytes), reports logicalBytes 1459568403, mainStreamAllocationBytes 1472924328, 7501 files over 1108 directories, 255 ms, and all ten install checks passed. sizeGroupsComplete is true: resources/runtime 1071346265 B (7426 files), root `.` 335219451 B (17 files), locales 50643459 B and resources 2359228 B. The runtime directory is about 73% and the root Electron executable/DLLs about 23%, so size convergence should start with the legacy runtime payload; this is still the default Electron package on a GitHub-hosted software-D3D11 runner, not the target machine or an OBS same-scope measurement.

### P2–P5：原型与后续门槛

完整 [能力迁移账本](windows-obs-capability-migration.md) 区分普通 RTSP 直读与控制面/持久任务：现有 cluster/RBAC fail-closed、MTX/NVR 更新工作门、Windows CEF 启动要求、备份/事件/录像任务均不能通过直接删除服务绕过。后续先拆 renderer-free 控制适配、只读数据导入 dry-run 与持久能力状态，再逐项迁移并保留回退。

`37e4f98` 增加独立 `native-host/` 与 `desktop/scripts/build-obs-native.ps1`：固定 OBS 完整 Qt frontend + 产品 dock，按已有 source UUID 复用媒体源，非破坏新建五分屏，Studio Preview 不自动 TAKE，投影使用 OBS 原生接口。全新 portable 配置与原 OBS/产品数据隔离，不启动旧服务。Linux 的七项 Python build contract 与固定真实 OBS headers API contract 1/1 已通过。[Windows 原型检查 41180501363](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/41180501363) 已成功：在 Windows 2022 / VS2022 实际编译 OBS 32.1.2 + Qt 6.8.3 + 产品插件，Qt dock 与媒体源注册、独立 portable 配置、原 OBS profile 未改变、清除继承插件覆盖及正常退出烟测均通过。`mediaQualified=false`，**不证明五路最终像素、摄像机、硬解或性能**。干净归档在烟测产生私密配置前完成，不上传配置和日志。Artifact `13034867787` / `78036418` 字节 / SHA-256 `86cdc83ad3677425fe86dd71a3b46a8b1e6bd6e96c932b0ae92f78810ad59e6a`；prototype manifest 之前文件总字节 `243419789`（Qt `23833088`、plugins `73164953`、other `146421748`），不是安装器大小、完整产品安装空间或同口径原版 OBS 比较，仍未达到体积验收。

本轮不切换默认包、不删除旧能力、不移动已发布标签。原型仍缺产品认证/迁移/安装升级与许可证、源码交付审计；实际五路硬解、同源 decoder 数、真实 Windows GPU/显示拓扑、首轮 OBS A/B 及安装体积同口径目标均未通过。全屏/DPI/多显示器/故障恢复与直接绘图 A 层尚待补齐；本地混合 H.264 夹具已加入并通过 Windows 像素运行。P5 只读进程树 CPU/内存采集工具已落地，固定进程 PID+创建时间、原始累计 CPU、保留已观察退出句柄尾数、元数据/原始文件 SHA-256 与三对交替检查；[Windows API 与隔离启动检查 41182986553](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/41182986553) 通过，包含九项合成逻辑及四项真实 Windows times/memory/snapshot、退出尾数、protected 当前用户+SYSTEM DACL、短时采样且 fixture 不被停止合约。没有开展产品 P5 测量；轮询遗漏短命后代、未知中间父进程和树外服务仍使 coverageIncomplete=true / strictTotal=false / qualified=false。GPU、显存、功耗、延迟、最终画面与硬解等未测量项保留 null，不能由不完整下界宣布总体性能等价。

### 原型安装器：重装保留私密配置 / Prototype installer preserves the private profile

`a6015d5` 新增 `native-host/scripts/install_native.py`：只接受带 `webobs-native-prototype.json`、`launch-native.ps1` 与固定 OBS 文件的冻结 ZIP，拒绝绝对/`..`/盘符段与顶层 `config/`，替换前把现有 `config` 复制进 staging（`configPreserved`），把旧根移到备份、失败则回滚；卸载同样要求 manifest。安装回执只含版本、包字节/SHA-256、文件数与布尔值，不写路径或 URL。

[Windows 运行 41220134972](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/41220134972)（`841b6fe`，dev.32）的安装步骤全部通过：新装回执 `configPreserved=false`、1578 文件、包 78,000,435 字节（SHA-256 `1f85d9fb939efe0164b5d0baafd4667c920933e5f506c90a9bf0a33bb048e7cd`）；对同一包重装回执 `configPreserved=true`、`previousVersion=4.1.0-dev.32`、1598 文件。新装双启动烟测通过（首启 created=5/reused=0，次启 created=0/reused=5、sceneReused=true），重装后对保留配置的单启动烟测也通过（created=0/reused=5、sceneReused=true，正常退出，外部 OBS profile 未变）。首个 dev.30 尝试曾因保留配置里已有旧 `native-smoke.json`、插件 `NewOnly` 写入失败而超时；`841b6fe` 改为插件读取受限的 `WEBOBS_NATIVE_SMOKE_RECEIPT`，每次启动使用带随机前缀的唯一回执名。

### 每用户安装包原型：安装、重装与卸载保留私密配置 / Per-user installer prototype: install, reinstall and uninstall keep the private profile

`native-host/installer/WebOBSNative.nsi` 把同一份冻结 runtime 打成未签名的每用户安装器，安装到 `%LOCALAPPDATA%\WebOBS Native Prototype`，只写 HKCU 卸载信息、不注册服务；安装包本身不含 `config/`，重装覆盖程序文件但不触碰现有 `config/`，静默卸载删除程序文件而逐字节保留 `config/`（含 RTSP 凭据与五格墙），并清理注册表。

[Windows 运行 41228010208](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/41228010208)（`3c916db`，dev.40）通过：安装器 45,250,255 字节、SHA-256 `7cc5724c0aee941802bdc9f8ed71b7547d1b3d73631170e003c5a03d7bb2a54d`，静默安装 1579 个文件后首次双启动烟测通过；重装前后 `config/obs-studio` 逐文件哈希一致；静默卸载后程序文件与 manifest 消失、`config/obs-studio` 逐字节保留、两个 HKCU 键均被清理。回执 `native-nsis-installer.json`。安装包未签名，不覆盖跨版本安装器升级、自动更新、数据迁移、认证、真实相机或 P5 性能。

A per-user installer prototype packages the same frozen runtime under `%LOCALAPPDATA%\WebOBS Native Prototype`, writes only HKCU uninstall metadata and registers no service; the package itself carries no `config/`, reinstall replaces program files without touching the existing `config/`, and silent uninstall removes program files while preserving `config/` byte for byte (RTSP credentials and the five-tile wall) and cleaning the registry.

Windows run [41228010208](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/41228010208) (`3c916db`, dev.40) passed: the installer is 45,250,255 bytes with SHA-256 `7cc5724c0aee941802bdc9f8ed71b7547d1b3d73631170e003c5a03d7bb2a54d`; the silent install of 1,579 files passed the two-launch smoke; the per-file hashes of `config/obs-studio` were identical across a reinstall; and after silent uninstall the program files and manifest were gone while `config/obs-studio` was preserved byte for byte and both HKCU keys were removed. The receipt is `native-nsis-installer.json`. The installer is unsigned and does not cover cross-version installer upgrades, auto-update, data migration, authentication, real cameras or P5 performance.

该证据仅覆盖**同一包的安装/重装与保留配置复用**：安装器是未签名的 portable 原型，不写注册表/服务；跨一个 dev 版本的原型树替换另见下节，它不覆盖真实安装器、数据迁移、认证、像素或 P5 性能验收，仍不能作为产品安装包或体积目标结论。

Commit `a6015d5` added `native-host/scripts/install_native.py`: it accepts only a frozen ZIP carrying `webobs-native-prototype.json`, `launch-native.ps1` and the fixed OBS files, rejects absolute/`..`/drive-letter segments and a top-level `config/`, copies any existing `config` into the staging tree (`configPreserved`) before replacing the tree, moves the old root to a backup and restores it on failure; uninstall likewise requires the manifest. Its receipt carries only version, package bytes/SHA-256, file count and booleans, never paths or URLs.

Windows run [41220134972](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/41220134972) (`841b6fe`, dev.32) passed the whole install step: the fresh receipt reports `configPreserved=false`, 1578 files and a 78,000,435-byte package (SHA-256 `1f85d9fb939efe0164b5d0baafd4667c920933e5f506c90a9bf0a33bb048e7cd`), while reinstalling the same package reports `configPreserved=true`, `previousVersion=4.1.0-dev.32` and 1598 files. The fresh two-launch smoke passed (first launch created=5/reused=0, second created=0/reused=5 with sceneReused=true), and the post-reinstall single-launch smoke over the preserved profile also passed (created=0/reused=5, sceneReused=true, normal exit, external OBS profile unchanged). The first dev.30 attempt timed out because the preserved profile still held the previous `native-smoke.json` and the plugin's `NewOnly` write failed; `841b6fe` makes the plugin read a restricted `WEBOBS_NATIVE_SMOKE_RECEIPT` and gives every launch a unique token-prefixed receipt name.

This evidence covers only **same-package install/reinstall and private-profile reuse**: the installer is an unsigned portable prototype and writes no registry entries or services. Replacing a portable tree across one dev version is covered separately below; it still does not cover a real installer, data migration, authentication, pixel or P5 performance qualification, and cannot be treated as the product installer or a size-target conclusion.

### 跨版本升级保留私密配置 / Cross-version upgrade preserves the private profile

2026-11-01 [Windows 运行 41221997187](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/41221997187)（`a9dbc2a`，dev.34，`upgrade_previous=true`）先下载固定 [dev.32 原型产物](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/41220134972) 安装到全新临时根（回执 `native-upgrade-first.json`：`configPreserved=false`、1578 文件、包 78,000,435 字节、SHA-256 `1f85d9fb939efe0164b5d0baafd4667c920933e5f506c90a9bf0a33bb048e7cd`），双启动烟测通过后记录 `config/obs-studio` 逐文件哈希清单，再用本次构建原地升级：回执 `native-upgrade-second.json` 报 `previousVersion=4.1.0-dev.32`、`version=4.1.0-dev.34`、`configPreserved=true`、1598 文件，升级后配置目录哈希清单与升级前逐字节一致，最后 `--existing-wall` 烟测通过（created=0/reused=5、sceneReused=true、正常退出、外部 OBS profile 未变）。

该验证仍只覆盖 **portable 原型安装树在跨一个 dev 版本时的替换与私密配置保留**：固定旧产物依赖 Actions artifact 7 天保留期，升级步骤默认关闭；不覆盖真实安装器/注册表/服务、数据迁移、像素、真实相机或 P5 性能，也不能代替产品升级路径。跨版本证据不改变“未测不宣称”的结论。

Windows run [41221997187](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/41221997187) (`a9dbc2a`, dev.34, `upgrade_previous=true`) downloads the pinned [dev.32 prototype artifact](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/41220134972) into a fresh temporary root (receipt `native-upgrade-first.json`: `configPreserved=false`, 1578 files, 78,000,435-byte package, SHA-256 `1f85d9fb939efe0164b5d0baafd4667c920933e5f506c90a9bf0a33bb048e7cd`), runs the two-launch smoke, records a per-file hash manifest of `config/obs-studio`, then upgrades in place with the current build: `native-upgrade-second.json` reports `previousVersion=4.1.0-dev.32`, `version=4.1.0-dev.34`, `configPreserved=true` and 1598 files, the post-upgrade config manifest is byte-identical to the pre-upgrade one, and the final `--existing-wall` smoke passes (created=0/reused=5, sceneReused=true, normal exit, external OBS profile unchanged).

This still covers only **replacing a portable prototype tree across one dev version while preserving the private profile**: the pinned old artifact depends on the 7-day Actions retention and the step is opt-in; it does not cover a real installer, registry/services, data migration, pixels, real cameras or P5 performance, and is not the product upgrade path. Cross-version evidence does not change the “unmeasured means unclaimed” conclusion.

### 原版 OBS 安装体积参考 / Stock OBS installed-size reference

2026-11-01 [Windows 运行 41221199820](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/41221199820)（`d6e9c44`，dev.33，输入 `obs_size_baseline=true`）在 GitHub 托管 Windows Server 2022 上静默安装固定版 OBS 32.1.2 安装包（157,809,480 字节，SHA-256 `94d180c1fc481ccc307b95513f795d088d63ac4f61ad3253c2ac0d94d0844110`，该哈希为本次下载记录，不是独立发布的校验值），再用同一安装树工具在首次启动前测量：逻辑字节 479,371,662、主数据流分配 482,421,648、2158 文件 / 88 目录、分配单元 4096 B。分组以 `obs-plugins/64bit` 317,367,244 B（120 文件，含 CEF/obs-browser 等）和 `bin/64bit` 137,144,384 B 为主，其余 `data/obs-plugins` 11,402,872 B、`data/obs-scripting` 6,835,991 B、`data/obs-studio` 6,366,768 B、`data/libobs` 106,377 B。

该数字是**同 OS 的参考基线**，不是目标机、不是等能力范围：原版包含 CEF 浏览器、脚本、WebSocket、VLC、AJA/DeckLink 等本原型已关闭的组件；原生原型 manifest 之前文件总字节 243,466,645，小于原版安装，但缺少这些能力，不能据此宣布体积达标。当前默认 Electron 包 1.46 GB 的收敛仍以 P3 能力迁移与等能力对照为前提。

Windows run [41221199820](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/41221199820) (`d6e9c44`, dev.33, input `obs_size_baseline=true`) silently installed the pinned OBS 32.1.2 installer (157,809,480 bytes, SHA-256 `94d180c1fc481ccc307b95513f795d088d63ac4f61ad3253c2ac0d94d0844110`, recorded for this download rather than an independently published checksum) on a GitHub-hosted Windows Server 2022 runner and measured it before first start with the same installed-tree tool: 479,371,662 logical bytes, 482,421,648 main-stream allocation bytes, 2158 files over 88 directories and a 4096-byte allocation unit. `obs-plugins/64bit` accounts for 317,367,244 B (120 files, including CEF/obs-browser) and `bin/64bit` for 137,144,384 B; the rest is `data/obs-plugins` 11,402,872 B, `data/obs-scripting` 6,835,991 B, `data/obs-studio` 6,366,768 B and `data/libobs` 106,377 B.

This is a **same-OS reference baseline**, not the target machine and not an equal-feature scope: stock OBS includes the CEF browser, scripting, WebSocket, VLC, AJA/DeckLink and other components this prototype disables. The native prototype's 243,466,645 bytes before its manifest are smaller than the stock installation but lack those capabilities, so this cannot be presented as meeting the size target. Convergence of the current 1.46 GB Electron default still depends on P3 capability migration and an equal-feature comparison.

### 开发候选发布 v4.1.0-dev.40 / Development candidate publication v4.1.0-dev.40

2026-11-01 将 dev.40 原生监看原型作为**未签名开发 Pre-release** 发布：[v4.1.0-dev.40](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/releases/tag/v4.1.0-dev.40)，源码 `3c916db18de59e86dfbd14f39ea53cef1f564005`（[Windows 运行 41228010208](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/41228010208)），标签与 release target 均为该已测试提交，stable Latest 仍为 `v4.0`。

发布前重新下载不可变 artifact `13052358847`（123,286,064 字节，摘要 `sha256:0f338160fc3ef8fcd64a2d02977884513440029467dfbcd4277c168fc60fdd3d`），本机运行 `native-host/scripts/verify_native_dev_assets.py` 核对安装器回执、原型 ZIP 清单、sidecar 与私有配置排除；上传后 GitHub 记录的三个附件摘要与本地哈希一致，再下载发布后的 SETUP.exe 复核 `sha256sum` 通过。附件字节未重新打包：

| 附件 / Asset | 字节 / Bytes | SHA-256 |
| --- | ---: | --- |
| `WebOBS-OBS-native-4.1.0-dev.40-windows-x64-PROTOTYPE.zip` | 78,029,241 | `634af4be2fd9b7a0709a29a87ad67e8b3a0662fcaf54043205c1cdf21402ab18` |
| `WebOBS-OBS-native-4.1.0-dev.40-windows-x64-SETUP.exe` | 45,250,255 | `7cc5724c0aee941802bdc9f8ed71b7547d1b3d73631170e003c5a03d7bb2a54d` |
| `SHA256SUMS.txt` | 242 | `04abb74831aa3d13e93cacbb7b7e92f928bc618b6052ade21d6738f088b3fab1` |

边界：未签名、无自动更新、无跨版本安装器升级/数据迁移；原型 ZIP 不是产品默认包，不替换 Electron 产品；像素门槛仍为软件 D3D11 + 合成 RTSP（九阶段），不证明目标机、真实五路 H.265、硬解、延迟、功耗或 OBS 同机对照；P1 显示缺口、P3 能力迁移与 P5 性能/体积门槛保持未通过。发布说明见 `docs/release-notes-dev40.md`。

On 2026-11-01 the dev.40 native monitor prototype was published as an **unsigned development Pre-release**: [v4.1.0-dev.40](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/releases/tag/v4.1.0-dev.40), source `3c916db18de59e86dfbd14f39ea53cef1f564005` ([Windows run 41228010208](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/41228010208)); both the tag and the release target are that tested commit, and stable Latest remains `v4.0`.

Before publication the immutable artifact `13052358847` (123,286,064 bytes, digest `sha256:0f338160fc3ef8fcd64a2d02977884513440029467dfbcd4277c168fc60fdd3d`) was downloaded again and `native-host/scripts/verify_native_dev_assets.py` checked the installer receipt, prototype ZIP manifest, sidecar digests and private-config exclusion locally; after upload GitHub's recorded digests for all three assets matched the local hashes, and the published SETUP.exe was downloaded again and passed `sha256sum`. No asset was repacked:

| Asset | Bytes | SHA-256 |
| --- | ---: | --- |
| `WebOBS-OBS-native-4.1.0-dev.40-windows-x64-PROTOTYPE.zip` | 78,029,241 | `634af4be2fd9b7a0709a29a87ad67e8b3a0662fcaf54043205c1cdf21402ab18` |
| `WebOBS-OBS-native-4.1.0-dev.40-windows-x64-SETUP.exe` | 45,250,255 | `7cc5724c0aee941802bdc9f8ed71b7547d1b3d73631170e003c5a03d7bb2a54d` |
| `SHA256SUMS.txt` | 242 | `04abb74831aa3d13e93cacbb7b7e92f928bc618b6052ade21d6738f088b3fab1` |

Boundaries: unsigned, no auto-update, no cross-version installer upgrade or data migration; the prototype ZIP is not the product default and does not replace the Electron product; the pixel gate is still software D3D11 plus synthetic RTSP (nine phases) and does not qualify the target machine, five real H.265 cameras, hardware decoding, latency, power or same-machine OBS comparison; P1 display gaps, P3 capability migration and P5 performance/size gates remain open. Release notes: `docs/release-notes-dev40.md`.

### 版本升级私密配置快照与校验恢复 / Version-upgrade private-profile snapshots and verified restore

2026-11-01 原生原型增加每版本私密配置快照与可校验恢复（[run 41236346267](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/41236346267)，提交 `011e879`，artifact `13055697896`，123,339,661 B）。这是 P3/P4 数据保留与升级生命周期的一个有界步骤，不等于完整能力迁移或产品数据保留政策。

机制：插件在 `OBS_FRONTEND_EVENT_FINISHED_LOADING`、产品五分屏 bootstrap 之前读取 `<install>/webobs-native-prototype.json` 的版本；若 `backups/config-<version>-*` 尚无同版本 `backup.json`，就把 `<install>/config/` 逐文件快照到 `backups/config-<version>-<UTC>/`，记录相对路径、字节数和 SHA-256，跳过 `obs-studio/logs/`、运行时 `.sentinel/` 与 `crashes/`；`backup.json` 用 `QSaveFile` 原子写入，最多保留 3 份，任何失败都删除半成品且不阻塞启动；pixel-test 构建运行时不快照。NSIS 卸载保留 `config/` 与 `backups/`。恢复由 `native-host/scripts/restore_native_backup.py --backup <name> --apply` 执行：先校验清单（schema/kind/version、路径安全、重复、大小/哈希、多余或缺失文件），把当前 `config/` 另存为 `backups/pre-restore-<UTC>`，再在安装根下的临时目录内替换 `config/` 并写回执。

CI 证据（安装器 + 固定 dev.32 升级 + 恢复）：

- 安装器：`SETUP.exe` 45,235,341 B，SHA-256 `601eff0989aed2e9cfe564fcab9ca07b78056d36e01f2fd45400936779c94675`，1,579 文件；重装与卸载都保留配置；首次启动生成 1 份版本快照，卸载后快照与回执保留；未签名。
- 升级：固定 dev.32（78,000,435 B）安装并双启动后覆盖安装 dev.42（`packageBytes` 78,093,814，`sha256` `e3cd8eb2fd212c30295d98b00705f0e4758732d2e033d42b505e7501ef873b44`），`previousVersion=4.1.0-dev.32`、`configPreserved=true`、`fileCount=1598`；新版本启动后快照的稳定文件集合与升级前一致、逐文件哈希相同（没有缺失，也没有额外配置外文件），`--existing-wall` 启动复用 5 路（created=0/reused=5，`sceneReusedSecond=true`）。
- 恢复：从快照 `config-4.1.0-dev.42-20261031T200201Z` 恢复到临时安装根，恢复 18 个文件 / 126,204 B，先生成 `pre-restore-20261031T200201Z`；恢复后每个稳定文件哈希与升级前一致；回执随 artifact 归档。

边界：快照是文件级且未加密（依赖用户目录 ACL），不含 DPAPI 封装、跨机器迁移、自动回滚、自动调度、Electron 数据/账号迁移或跨大版本兼容承诺；安装器仍不会自动迁移，只有 CI 的显式 `upgrade_previous` 路径被验证；未在目标机验证，不构成 P5 或产品数据保留政策证据。

On 2026-11-01 the native prototype gained per-version private-profile snapshots and verified restore ([run 41236346267](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/41236346267), commit `011e879`, artifact `13055697896`, 123,339,661 B). This is one bounded P3/P4 data-retention and upgrade-lifecycle step, not a complete capability migration or a product retention policy.

Mechanism: before the product five-tile bootstrap at `OBS_FRONTEND_EVENT_FINISHED_LOADING`, the plugin reads the version in `<install>/webobs-native-prototype.json`; if no `backups/config-<version>-*` directory already holds a `backup.json` for that version, it snapshots `<install>/config/` file by file into `backups/config-<version>-<UTC>/`, recording relative path, bytes and SHA-256 while skipping `obs-studio/logs/`, runtime `.sentinel/` files and `crashes/`. `backup.json` is written atomically with `QSaveFile`, at most three snapshots are kept, failures remove partial data and never block startup, and pixel-test runs do not snapshot. NSIS uninstall keeps `config/` and `backups/`. Restore runs through `native-host/scripts/restore_native_backup.py --backup <name> --apply`: it validates the manifest (schema/kind/version, path safety, duplicates, sizes/hashes, extra or missing files), saves the current `config/` as `backups/pre-restore-<UTC>`, then replaces `config/` from a staging directory under the install root and writes a receipt.

CI evidence (installer + pinned dev.32 upgrade + restore):

- Installer: `SETUP.exe` 45,235,341 B, SHA-256 `601eff0989aed2e9cfe564fcab9ca07b78056d36e01f2fd45400936779c94675`, 1,579 files; reinstall and uninstall preserve configuration; the first run creates one version snapshot and uninstall keeps the snapshot and receipt; unsigned.
- Upgrade: after installing and double-launching pinned dev.32 (78,000,435 B), dev.42 is installed over it (`packageBytes` 78,093,814, `sha256` `e3cd8eb2fd212c30295d98b00705f0e4758732d2e033d42b505e7501ef873b44`) with `previousVersion=4.1.0-dev.32`, `configPreserved=true`, `fileCount=1598`; the new version's snapshot has the same stable file set and per-file hashes as before the upgrade (nothing missing, no extra non-configuration file), and the `--existing-wall` launch reuses five cameras (created=0/reused=5, `sceneReusedSecond=true`).
- Restore: from snapshot `config-4.1.0-dev.42-20261031T200201Z` into a temporary install root, restoring 18 files / 126,204 B after creating `pre-restore-20261031T200201Z`; every stable file hash matches the pre-upgrade value and the receipt is archived with the artifact.

Boundaries: the snapshot is file level and unencrypted (it relies on the user directory ACL); there is no DPAPI wrapping, cross-machine migration, automatic rollback, scheduling, Electron data/account migration or cross-major-version compatibility promise. The installer still does not migrate automatically — only the explicit CI `upgrade_previous` path is verified — and nothing here was checked on the target machine or counts as P5 or product retention evidence.

### 保存场景重启后最终像素 / Final pixels after a saved-scene restart

2026-11-01 原生像素门新增第 10 阶段：第一个 OBS 进程创建合成五路 RTSP 墙并通过 `obs_frontend_save()` 保存场景集合后正常退出；另一个全新的 obs64 进程使用同一私密 profile 重新启动，不创建、不选择任何场景或源，只等待保存的 `WebOBS Native RTSP Wall` 自动恢复、五路源进入 PLAYING，然后捕获八帧真实主 Preview 窗口像素。([run 41240282257](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/41240282257)，版本 `4.1.0-dev.45`，提交 `1fdd1f8`，artifact `13057621643`，3,427 B；回执十阶段全部通过，`savedSceneRestartPhaseQualified=true`。)

机制：第二进程只接受 `WEBOBS_NATIVE_RESTART_TOKEN` 对应的私密 `native-restart-test/request.json`（schema 1、token），校验安装根、私密 profile 与插件配置目录后认领；窗口打开时把测试画布固定回文档化的 960×540，要求墙场景是当前场景、五路 `Synthetic loopback RTSP 1..5` 均为 320×180 PLAYING，且场景项正好五个、全部可见、位置为 (0,0)、(320,0)、(640,0)、(0,270)、(320,270)。状态文件发布这些几何与画布字段后，外部脚本捕获主 Preview 的八帧，按五格颜色/时间码与时间推进判定，再确认正常退出。

迭代记录：dev.43 首次执行到第 10 阶段，但保存的 profile 没有带回测试画布（重启后为 1024×768），分析的 960×540 几何不再匹配，样本报 `Wrong channel 1 in tile 0: 19,20,26`；dev.44 仅在安全回执中加入位图尺寸（998×578）与画布/墙项字段完成定位；`1fdd1f8` 在见证进程固定 960×540 画布并显式发布、校验五个可见墙项后，dev.45 通过。这是测试见证器的画布契约，不是产品默认行为。

边界：仍是软件 D3D11 上的合成回环 RTSP；只捕获主 Preview，不覆盖断流期间的丢帧、真实相机/硬件解码、物理 GPU、DPI 缩放、多显示器、产品默认安装或目标机；保存场景的自动恢复只在像素测试构建中验证，不等于产品生命周期或 P5 证据。

On 2026-11-01 the native pixel gate gained a tenth phase: one OBS process creates the synthetic five-source RTSP wall and saves the scene collection through `obs_frontend_save()`, then exits normally; a brand-new obs64 process reopens the same private profile without creating or selecting any scene or source, waits for the saved `WebOBS Native RTSP Wall` to return by itself with all five sources PLAYING, and captures eight real main-Preview samples. ([run 41240282257](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/41240282257), version `4.1.0-dev.45`, commit `1fdd1f8`, artifact `13057621643`, 3,427 B; all ten phases passed, `savedSceneRestartPhaseQualified=true`.)

Mechanism: the second process only accepts the private `native-restart-test/request.json` (schema 1, token) matching `WEBOBS_NATIVE_RESTART_TOKEN`, after checking the install root, private profile and plugin config directory; on window open it pins the documented 960×540 test canvas, requires the wall scene to be current, the five `Synthetic loopback RTSP 1..5` sources to be 320×180 and PLAYING, and exactly five visible scene items at (0,0), (320,0), (640,0), (0,270) and (320,270). After publishing those geometry/canvas fields, the external script captures eight main-Preview samples, verifies five-tile colours/timecode and temporal progress, and confirms a normal exit.

Iteration record: dev.43 reached phase 10, but the saved profile did not carry the test canvas (1024×768 after restart), so the 960×540 analysis geometry no longer matched and samples reported `Wrong channel 1 in tile 0: 19,20,26`; dev.44 added only bitmap dimensions (998×578) and canvas/wall-item fields to the safe receipt to locate it; `1fdd1f8` pinned 960×540 in the witness and published/validated the five visible wall items, after which dev.45 passed. This is a witness canvas contract, not product default behaviour.

Boundaries: still synthetic loopback RTSP on software D3D11; only the main Preview is captured; interrupted-frame loss, real cameras/hardware decoding, physical GPU, DPI scaling, multiple monitors, the product default install and the target machine are not covered; automatic saved-scene recovery is verified only in the pixel-test build and is not product-lifecycle or P5 evidence.

### 原生宿主进程门 / Native host process gate

2026-11-01 启动烟测新增进程门，作为 P3“普通本地监看不启动无关服务、正常退出无残留”的部分实证：`launch-native.ps1` 在等待真实 obs64 退出期间按约 2 秒间隔枚举其完整后代进程树，记录可执行文件名与路径；首个样本同时记录该树拥有的监听端口；正常退出后再扫描安装根目录下仍存活的可执行文件（至多重试三次）。烟测收到门回执后拒绝以下任一情况：出现 MediaMTX、go2rtc、FFmpeg、Python、Node、Caddy、Electron 等网关/转换/检测/网站辅助进程；进程树监听 80/443/1984/8554/8555/8888/9000/8080 等已知服务端口；安装根目录下有任何进程在正常退出后存活。([run 41241580939](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/41241580939)，版本 `4.1.0-dev.46`，提交 `9dd766b`，artifact `13058022418`。)

证据：五个烟测回执全部 `status=passed` 且 `processGate` 通过。双启动 portable 烟测采样 4 次，只观察到 OBS 自身的 `get-graphics-offsets32.exe` 与 `conhost.exe`（均为 OBS 内部 GPU/控制台辅助，不在禁止集合），服务端口为空、残留为 0；四个更短的启动/安装/卸载烟测各采样 1 次、未观察到子进程，服务端口与残留同样为空。门回执随产物上传为 `native-*-process-gate.json`。

边界：烟测使用五路占位 RTSP 地址，不是真实相机或媒体流；进程门只审查 obs64 后代与安装根目录内的残留，安装根之外的分离式服务不会被发现；它证明的是“该原生宿主没有拉起已知辅助进程且正常退出无残留”，不证明保留功能的启停、崩溃收束、二实例、真实相机/硬解，也不能替 Electron 默认栈的 P3 迁移结论。

On 2026-11-01 the startup smoke gained a process gate as partial P3 evidence for "plain local monitoring starts no unrelated services and a normal exit leaves nothing behind": while waiting for the real obs64 to exit, `launch-native.ps1` enumerates its full descendant tree about every two seconds and records executable names and paths; the first sample also records listening ports owned by that tree; after a normal exit it re-scans the install root for surviving executables (up to three attempts). The smoke then rejects any receipt with MediaMTX, go2rtc, FFmpeg, Python, Node, Caddy or Electron-style gateway/conversion/detection/website helpers, with listeners on known service ports (80/443/1984/8554/8555/8888/9000/8080), or with any process from the install root surviving a normal exit. ([run 41241580939](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/41241580939), version `4.1.0-dev.46`, commit `9dd766b`, artifact `13058022418`.)

Evidence: all five smoke receipts report `status=passed` with a passing `processGate`. The two-launch portable smoke sampled four times and observed only OBS's own `get-graphics-offsets32.exe` and `conhost.exe` (internal GPU/console helpers, not in the forbidden set), with no service ports and zero survivors; the four shorter startup/install/uninstall smokes sampled once each, observed no children, and likewise reported no service ports or survivors. Gate receipts upload as `native-*-process-gate.json`.

Boundaries: the smoke uses five placeholder RTSP URLs, not real cameras or media; the gate inspects only obs64 descendants and survivors inside the install root, so a detached service outside that root would be missed; it proves this native host starts no known helper processes and leaves nothing behind on normal exit, not retained-feature start/stop, crash containment, second-instance behaviour, real cameras/hardware decode, or Electron-default P3 migration.
