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

### 原生宿主崩溃收束烟测 / Crash containment smoke

2026-11-01 在第 20 轮正常退出进程门之外，增加“故意杀死宿主”的收束烟测：`launch-native.ps1` 新增 `-CrashProbe` 模式，使用同一个一次性 portable profile 与进程门，但**不设置**烟测令牌，因此插件不会在写完烟测回执后自行关闭 OBS；运行 8 秒后只终止真实的 obs64 根进程，再检查进程树监听端口与安装根目录残留。回执显式写入 `crashed=true` 与 `crashAfterSeconds`，避免与正常启动烟测混淆。([run 41244917594](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/41244917594)，版本 `4.1.0-dev.49`，提交 `f0042e8`，artifact `13059452295`。)

证据：`native-crash-smoke.json` 为 `status=passed`、`crashAfterSeconds=8`、`exitCode=4294967295`（Windows 强杀返回值）；门回执 `crashed=true`、采样 5 次、`listeners=[]`、`orphans=[]`。此次运行未观察到 obs64 的子进程，因此该回执证明的是“强杀后没有安装根进程存活”，不能扩展为“任何 OBS 子进程都会随根进程退出”。

边界：仍使用五路占位 RTSP 输入而非真实相机；只测试进程级强杀，不模拟插件/驱动崩溃、真实解码压力或长时间运行后的崩溃；不覆盖二实例、安装根之外的分离服务、保留功能启停，也不构成目标机证据或 Electron 默认栈的 P3 结论。

On 2026-11-01, beyond the normal-exit process gate from round 20, a deliberate host-kill containment smoke was added: `launch-native.ps1` gained a `-CrashProbe` mode that reuses the same disposable portable profile and process gate but deliberately **does not** set the smoke token, so the plugin cannot close OBS after writing its receipt; after eight seconds only the real obs64 root process is terminated, then the tree's listeners and install-root survivors are checked. The receipt records `crashed=true` and `crashAfterSeconds` so it can never be confused with a normal startup smoke. ([run 41244917594](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/41244917594), version `4.1.0-dev.49`, commit `f0042e8`, artifact `13059452295`.)

Evidence: `native-crash-smoke.json` reports `status=passed`, `crashAfterSeconds=8`, `exitCode=4294967295` (the Windows hard-kill value); the gate receipt reports `crashed=true`, five samples, `listeners=[]` and `orphans=[]`. This run observed no obs64 child processes, so the receipt proves "no install-root process survived the hard kill", not "every OBS child exits with its root".

Boundaries: still five placeholder RTSP inputs, not real cameras; only a process-level kill, not plugin/driver crashes, real decode pressure or long-run crashes; it does not cover second instance, detached services outside the install root, retained-feature start/stop, and is neither target-machine evidence nor a P3 conclusion for the Electron default stack.

### 原生宿主单实例守卫 / Native host single-instance guard

2026-11-01 为入口 `launch-native.ps1` 增加会话级互斥量 `Local\WebObsNativeHostSingleInstance`：第一次启动持有它并在整个 OBS 生命周期内保持；第二个启动在任何 profile 创建、任何 obs64 进程出现之前直接退出（退出码 0，打印“already running”）。`-AllowMultiple` 保留给明确的多实例开发场景；直接绕过启动器运行 obs64 时仍由上游 OBS 自己的“已在运行”对话框拦截，本测试不自动点击该对话框。([run 41246119235](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/41246119235)，版本 `4.1.0-dev.50`，提交 `9f07eea`，artifact `13059736192`。)

证据：`native-second-instance-smoke.json` 为 `status=passed`、`holdSeconds=30`、`secondExitCode=0`、`secondElapsedMs=547`、`hostsBefore=1`、`hostsAfter=1`、`refused=true`；被持有的第一个宿主随后按计划强杀，进程门 `crashed=true`、`samples=16`、`durationMs=30361`、`listeners=[]`、`orphans=[]`。因此该烟测证明“第二个启动器不会产生第二个 profile 或第二个 obs64”，并同时复验强杀收束。

边界：仅覆盖启动器层；不覆盖直接运行 obs64 时上游对话框的自动化、窗口前置/聚焦转发、不同安装根目录并行运行、真实相机、保留功能启停或目标机；依旧不是 P3 全量结论。

On 2026-11-01 the `launch-native.ps1` entry point gained a session mutex `Local\WebObsNativeHostSingleInstance`: the first launch holds it for the whole OBS lifetime; a second launch exits with code 0 and an "already running" message before creating any profile or obs64 process. `-AllowMultiple` remains the explicit multi-instance escape hatch. Running obs64 directly still reaches upstream OBS's own "already running" dialog, which this test deliberately does not automate. ([run 41246119235](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/41246119235), version `4.1.0-dev.50`, commit `9f07eea`, artifact `13059736192`.)

Evidence: `native-second-instance-smoke.json` reports `status=passed`, `holdSeconds=30`, `secondExitCode=0`, `secondElapsedMs=547`, `hostsBefore=1`, `hostsAfter=1`, `refused=true`; the held first host was then deliberately killed and the process gate reports `crashed=true`, `samples=16`, `durationMs=30361`, `listeners=[]`, `orphans=[]`. The smoke therefore proves "a second launcher creates neither a second profile nor a second obs64" and re-checks kill containment in the same run.

Boundaries: launcher level only; it does not automate upstream OBS's dialog when obs64 is run directly, window activation/focus forwarding, parallel runs from different install roots, real cameras, retained-feature start/stop, or the target machine; it is still not a full P3 conclusion.

### 已发布安装包的跨版本升级 / Cross-version upgrade of a shipped installer

2026-11-01 把跨版本验证从“解压 ZIP 后覆盖”推进到“已在 GitHub 发布的 NSIS 安装包原地升级”：CI 下载固定版本的 `v4.1.0-dev.40` SETUP（固定 SHA-256 `7cc5724c…`），静默安装到一次性 per-user 目录并写入一个私有 profile 文件；随后用当前构建的 SETUP 静默覆盖安装，要求 manifest 版本从 `4.1.0-dev.40` 变为当前版本，而 `config/` 的文件集合与逐文件 SHA-256 完全不变；最后静默卸载，要求私有 profile 逐字节保留、运行时二进制与 manifest 删除、两个 HKCU 键清除。([run 41248500574](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/41248500574)，版本 `4.1.0-dev.52`，提交 `2fbd1b0`，artifact `13060618337`。)

回执 `native-nsis-upgrade.json`：`previousVersion=4.1.0-dev.40`、`version=4.1.0-dev.52`、`previousInstallerSha256=7cc5724c…`、`installerSha256=3ccd92aa…`、`configPreservedAcrossUpgrade=true`、`configPreservedAcrossUninstall=true`、`registryCleanedOnUninstall=true`、`signed=false`。首次运行该步骤时因 YAML 中路径分隔符被吃掉（`Replace('','/')`）失败，等待升级开始前即抛错；修正后通过。

边界：仍是未签名开发安装包；私有 profile 只覆盖本测试写入的标记文件与文件集合/哈希断言，不代表真实用户配置、加密备份或跨机器迁移；不包含自动更新/下载通道、版本回滚、降级拒绝、管理员安装、真实相机或目标机证据。

On 2026-11-01 the cross-version check moved from "extract a ZIP and overwrite" to an in-place upgrade of an NSIS installer already published on GitHub: CI downloads the fixed `v4.1.0-dev.40` SETUP (SHA-256 `7cc5724c…`), silently installs it into a disposable per-user directory and seeds a private profile file; the current SETUP then installs over it, and the manifest must move from `4.1.0-dev.40` to the current version while the `config/` file set and every per-file SHA-256 stay identical; finally a silent uninstall must preserve the private profile byte for byte, remove runtime binaries and the manifest, and clear both HKCU keys. ([run 41248500574](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/41248500574), version `4.1.0-dev.52`, commit `2fbd1b0`, artifact `13060618337`.)

Receipt `native-nsis-upgrade.json`: `previousVersion=4.1.0-dev.40`, `version=4.1.0-dev.52`, `previousInstallerSha256=7cc5724c…`, `installerSha256=3ccd92aa…`, `configPreservedAcrossUpgrade=true`, `configPreservedAcrossUninstall=true`, `registryCleanedOnUninstall=true`, `signed=false`. The first attempt of this step failed before the upgrade because the YAML edit swallowed a path-separator backslash (`Replace('','/')`); the fixed script passed.

Boundaries: still an unsigned development installer; the private profile is only the marker file seeded by this test plus file-set/hash assertions, not real user data, encrypted backup or cross-machine migration; no auto-update/download channel, version rollback, downgrade refusal, admin install, real cameras or target-machine evidence.

### P4 运行时构建符号剥离 / P4 runtime build-symbol pruning

P4 的第 5 步要求清理“不用的插件、资源、开发文件和构建产物”。先做了其中可归因、可复核的一项：OBS 的 Windows 安装规则把 `*.pdb` 调试符号一起装进运行时，`obs64.exe` 从不加载它们，但 NSIS 会逐字节打包。构建脚本现在在 `stage.py` 生成清单之前调用 `native-host/scripts/prune_runtime.py`：只删除运行时内的 PDB、写出 `native-runtime-prune.json`（删除 34 个文件、144,351,232 B）、断言零残留；NSIS 步骤也拒绝含 PDB 的安装树。清单 `sizeBytesBeforeManifest`/`sizeGroups` 与安装体积因此都不含构建符号。

| 计量（同一构建树，dev.52 → dev.53） | 剥离前 | 剥离后 | 变化 |
| --- | ---: | ---: | ---: |
| 运行时解包字节（zip 内文件总和） | 243,502,095 B | 99,168,288 B | −59.3% |
| 运行时文件数（不含 Uninstall.exe） | 1,578 | 1,544 | −34 |
| 原型 ZIP 下载字节 | 77,986,903 B | 41,484,488 B | −46.8% |
| SETUP.exe 安装包字节 | 45,172,904 B | 27,408,522 B | −39.3% |
| Actions artifact 总字节 | 123,172,732 B | 68,909,368 B | −44.1% |

剥离后的运行时仍通过 10 个合成像素阶段（run 41250018069，`4.1.0-dev.54`，artifact `13060579898`），同一提交的完整原型运行（run 41250011450，`4.1.0-dev.53`，artifact `13060374195`）也通过启动、NSIS 安装/卸载、崩溃收束、单实例与已发布安装包升级烟测。

边界：本项只移除构建符号，未裁剪插件/资源，未移除 Electron 默认运行时，也未改变功能范围；原型与完整 OBS（479,371,662 B，含 CEF/脚本/WebSocket/VST/VLC 等）不是同功能口径，不能据此宣称 P4 体积目标完成。仍缺默认/扩展/实际安装的分组计量、SBOM/许可清单、具体剩余文件解释与目标机证据。

Step 5 of P4 requires cleaning unused plug-ins, resources, development files and build products. The first slice is attributable and reviewable: OBS's Windows install rules stage `*.pdb` debug symbols into the runtime, `obs64.exe` never loads them, yet NSIS packages every byte. Before `stage.py` writes the manifest the build now calls `native-host/scripts/prune_runtime.py`, which removes only runtime PDBs, writes `native-runtime-prune.json` (34 files, 144,351,232 B), and asserts zero survivors; the NSIS step also rejects a PDB-bearing install tree. The manifest's `sizeBytesBeforeManifest`/`sizeGroups` and the installed size therefore exclude build symbols.

| Measurement (same build tree, dev.52 → dev.53) | Before | After | Change |
| --- | ---: | ---: | ---: |
| Runtime unpacked bytes (sum of zip entries) | 243,502,095 B | 99,168,288 B | −59.3% |
| Runtime file count (excluding Uninstall.exe) | 1,578 | 1,544 | −34 |
| Prototype ZIP download bytes | 77,986,903 B | 41,484,488 B | −46.8% |
| SETUP.exe installer bytes | 45,172,904 B | 27,408,522 B | −39.3% |
| Actions artifact total bytes | 123,172,732 B | 68,909,368 B | −44.1% |

The pruned runtime still passed all ten synthetic pixel phases (run 41250018069, `4.1.0-dev.54`, artifact `13060579898`), and the full prototype run at the same commit (run 41250011450, `4.1.0-dev.53`, artifact `13060374195`) passed startup, NSIS install/uninstall, crash containment, single-instance and shipped-installer upgrade smokes.

Boundaries: this slice removes build symbols only; no plug-in/resource trimming, no Electron default removal, no functional-scope change. The prototype and full OBS (479,371,662 B, including CEF/scripting/WebSocket/VST/VLC) are not same-feature measurements, so this is not a P4 size-completion claim. Group accounting for default/extension/actual installs, SBOM/licence inventory, explanations for remaining files and target-machine evidence are still missing.

### P4 运行时清单与体积预算 / P4 runtime inventory and size budget

- 2026-11-01 [run 41253166037](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/41253166037)（`8eabc18`，`4.1.0-dev.56`，artifact `13061902704`，68,930,838 B）在裁剪、冻结之后新增 CI 步骤 “Inventory the runtime and enforce the P4 size budget”。`native-host/scripts/runtime_inventory.py` 拒绝残留的 PDB/lib/exp/obj/CMake 产物，按组汇总字节，统计 locale，并把每个 DLL/EXE 的路径、大小、SHA-256 与厂商/许可提示写入 `native-runtime-inventory.json`；运行时超过 100 MiB（104,857,600 B）即失败。
- 实测：1,544 文件 / 99,168,288 B（与 dev.53 同口径一致）；分组 `bin` 57,188,864 B、`qt` 25,835,008 B、`plugins` 7,354,604 B、`data` 423,075 B、`licenses` 23,001 B、`other` 32,245 B；locale 1,169 文件 / 8,311,491 B / 75 种语言；66 个二进制全部归类（OBS 34、Qt 19、FFmpeg 7、第三方 5、x264 1），无未分类条目。安装器 27,410,022 B（SHA-256 `13b4ffeb664cda5dd58835a56617333a3512576d07ed45de691b168f6bd2e510`，1,545 文件），dev.40 → dev.56 就地升级仍保留私密配置。
- 边界：这是**开发口径**的 100 MiB 预算与厂商/许可提示，不是完整 SBOM 或法律结论，`licenses/` 仍为权威；未裁剪插件/资源，未移除 Electron 默认运行时，未做默认/扩展/实际安装三套口径的分别计量，也没有目标机证据。

On 2026-11-01 [run 41253166037](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/41253166037) (`8eabc18`, `4.1.0-dev.56`, artifact `13061902704`, 68,930,838 B) added the CI step "Inventory the runtime and enforce the P4 size budget" after pruning and freezing. `native-host/scripts/runtime_inventory.py` rejects leftover PDB/lib/exp/obj/CMake products, sums bytes per group, counts locales, and records each DLL/EXE path, size, SHA-256 and vendor/licence hint in `native-runtime-inventory.json`; the runtime fails above the 100 MiB (104,857,600 B) budget.
- Measured: 1,544 files / 99,168,288 B (same scope as dev.53); groups `bin` 57,188,864 B, `qt` 25,835,008 B, `plugins` 7,354,604 B, `data` 423,075 B, `licenses` 23,001 B, `other` 32,245 B; 1,169 locale files / 8,311,491 B across 75 languages; all 66 binaries classified (OBS 34, Qt 19, FFmpeg 7, third-party 5, x264 1) with none unclassified. The installer is 27,410,022 B (SHA-256 `13b4ffeb664cda5dd58835a56617333a3512576d07ed45de691b168f6bd2e510`, 1,545 files), and the dev.40 → dev.56 in-place upgrade still preserves the private profile.
- Boundaries: this is a **development-scope** 100 MiB budget with vendor/licence hints, not a complete SBOM or legal conclusion; `licenses/` stays authoritative. No plug-in/resource trimming, no Electron-default removal, no separate default/extension/actual-install accounting and no target-machine evidence.

### P4 与 stock OBS 的体积差归因 / P4 size-gap attribution against stock OBS

- [run 41254761070](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/41254761070)（`2b48b47`，`4.1.0-dev.58`，artifact `13062880512`，68,939,659 B）在 opt-in 的 OBS 基线步骤里新增 `native-host/scripts/compare_runtime_sizes.py`：分别遍历原型运行时与同机安装的 stock OBS 32.1.2，把字节分为 shared / prototype-only / OBS-only，并将 OBS-only 归类为构建符号、CEF/浏览器、脚本、WebSocket、插件数据/locale、额外插件、卸载器等。
- 实测同一台 Windows Server 2022 runner：原型 1,544 文件 / 99,169,404 B；stock OBS 2,158 文件 / 479,371,662 B；共同路径 1,534 文件 / 98,990,635 B（占 OBS 字节 20.65%）。OBS-only 624 文件 / 379,523,091 B，其中 CEF/浏览器 64 文件 / 287,022,092 B（`libcef.dll` 214,001,712 B 等），构建符号 50 文件 / 76,578,816 B（`obs64.pdb` 41,504,768 B 等），额外插件 6,466,720 B，脚本 4,298,279 B，其他 2,789,120 B，WebSocket 1,240,336 B，插件数据/locale 492 文件 / 979,702 B，卸载器 148,026 B。原型独有仅 10 文件 / 178,769 B（宿主插件 DLL、许可、README、启动脚本、清单、哨兵与一个 locale）。
- 因此「479 MB vs 99 MB」主要不是功能等价下的效率差：去掉构建符号后 OBS 为 402,792,846 B（原型 24.6%）；再去掉 CEF/浏览器（原型不打包 CEF，浏览器源/面板因此不在原型范围，manifest 的 `optionalFeaturesDisabled` 已声明）后 OBS 为 115,770,754 B，原型占 85.7%。剩余约 1,660 万 B 主要是脚本、额外插件、WebSocket、插件数据/locale 与卸载器，另有同名文件的字节差。
- 边界：这是对**功能范围不同**两棵树的字节归因，不是同功能效率结论；Electron 默认包（dev.19 实测 1,459,568,444 B）仍在默认路径，扩展包未定义，原型的真实 NSIS 安装树字节（logical/allocated）尚未单独计量；未裁剪插件/资源，无完整 SBOM/许可结论，也无目标机证据。P4 仍未完成。

On [run 41254761070](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/41254761070) (`2b48b47`, `4.1.0-dev.58`, artifact `13062880512`, 68,939,659 B) the opt-in OBS baseline step gained `native-host/scripts/compare_runtime_sizes.py`: it walks the prototype runtime and the same-OS stock OBS 32.1.2 installation, splits bytes into shared / prototype-only / OBS-only, and classifies the OBS-only side into debug symbols, CEF/browser, scripting, WebSocket, plug-in data/locales, extra plug-ins and uninstaller.
- Same Windows Server 2022 runner: prototype 1,544 files / 99,169,404 B; stock OBS 2,158 files / 479,371,662 B; shared paths 1,534 files / 98,990,635 B (20.65% of OBS bytes). OBS-only 624 files / 379,523,091 B, dominated by CEF/browser 64 files / 287,022,092 B (`libcef.dll` 214,001,712 B and friends) and debug symbols 50 files / 76,578,816 B (`obs64.pdb` 41,504,768 B and friends); extra plug-ins 6,466,720 B, scripting 4,298,279 B, other 2,789,120 B, WebSocket 1,240,336 B, plug-in data/locales 492 files / 979,702 B, uninstaller 148,026 B. Prototype-only is 10 files / 178,769 B (host plug-in DLL, licences, README, launcher, manifest, sentinels and one locale).
- So "479 MB vs 99 MB" is not mainly an equal-feature efficiency gap: without build symbols OBS is 402,792,846 B (prototype 24.6%); without CEF/browser as well (the prototype does not ship CEF, so browser sources/panels are out of its scope, declared in `optionalFeaturesDisabled`) OBS is 115,770,754 B and the prototype is 85.7%. The remaining ~16.6 MB is mostly scripting, extra plug-ins, WebSocket, plug-in data/locales and the uninstaller, plus byte differences in same-path files.
- Boundaries: this is byte attribution across **different feature scopes**, not an equal-feature efficiency claim. The Electron default (1,459,568,444 B measured at dev.19) still ships as the default, no extension scope is defined, and the prototype's real NSIS installed-tree bytes (logical/allocated) are not measured separately yet; no plug-in/resource trimming, no complete SBOM/licence conclusion and no target-machine evidence. P4 remains open.

### P4 实际安装树口径 / P4 actual-install footprint

- [run 41255533864](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/41255533864)（`42af02c`，`4.1.0-dev.59`，artifact `13062922720`，68,931,765 B）在 NSIS 静默安装后、首次启动创建私密 profile 之前，用 `desktop/tests/installed-tree-footprint.ps1`（Win32 `FILE_STANDARD_INFO`，拒绝 reparse 点）测真实安装树，并把结果写入 `native-nsis-installer.json` 的 `installed` 字段。
- 实测：1,545 文件 / 73 个目录（含根）/ logical 99,222,495 B / 主数据流分配 101,550,744 B / 分配单元 4,096 B / 扫描 34 ms。分组：`bin/64bit` 83,023,872 B（42 文件）、`data/obs-studio` 6,366,768 B（264 文件）、`data/obs-plugins` 5,899,417 B（1,191 文件）、`obs-plugins/64bit` 3,716,608 B（18 文件）、`data/libobs` 106,377 B、根目录 86,452 B、许可/README/清单等其余小项。安装器 27,406,889 B，未签名；reinstall/uninstall 仍逐字节保留私密配置。
- 与另两个口径并列：Electron 默认包（dev.19）实测 logical 1,459,568,444 B / allocation 1,472,924,328 B / 7,501 文件 / 1,108 目录；原生原型运行时 99,169,404 B / 1,544 文件；原生实际安装 99,222,495 B logical / 101,550,744 B allocation / 1,545 文件。原生实际安装的 logical 是 Electron 的 6.8%，allocation 是 6.9%。
- 边界：这是**首次启动前**的安装树，不含运行后生成的 `config/`/`backups/`；安装器仍未签名、无自动更新/降级拒绝；Electron 默认迁移、扩展包口径、插件/资源裁剪、完整 SBOM/许可结论与目标机证据仍缺，P4 未完成。

On [run 41255533864](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/41255533864) (`42af02c`, `4.1.0-dev.59`, artifact `13062922720`, 68,931,765 B), right after the silent NSIS install and before the first run creates a private profile, `desktop/tests/installed-tree-footprint.ps1` (Win32 `FILE_STANDARD_INFO`, reparse points rejected) measures the real installed tree and writes it into `native-nsis-installer.json` as `installed`.
- Measured: 1,545 files / 73 directories including the root / logical 99,222,495 B / main-stream allocation 101,550,744 B / 4,096-byte units / 34 ms scan. Groups: `bin/64bit` 83,023,872 B (42 files), `data/obs-studio` 6,366,768 B (264 files), `data/obs-plugins` 5,899,417 B (1,191 files), `obs-plugins/64bit` 3,716,608 B (18 files), `data/libobs` 106,377 B, root 86,452 B, plus licences/README/manifest and other small entries. The installer is 27,406,889 B and unsigned; reinstall/uninstall still preserve the private profile byte for byte.
- Side by side with the other scopes: the Electron default (dev.19) measured logical 1,459,568,444 B / allocation 1,472,924,328 B / 7,501 files / 1,108 directories; the native staged runtime is 99,169,404 B / 1,544 files; the native actual install is 99,222,495 B logical / 101,550,744 B allocation / 1,545 files. The native actual install is 6.8% of Electron logical bytes and 6.9% of allocation.
- Boundaries: this is the **pre-first-run** tree and excludes `config/`/`backups/` created by running; the installer is still unsigned with no auto-update or downgrade refusal; Electron-default migration, extension scope, plug-in/resource trimming, a complete SBOM/licence conclusion and target-machine evidence remain missing, so P4 is not complete.

### 开发候选发布 v4.1.0-dev.53 / Development candidate publication v4.1.0-dev.53

- 2026-11-01 发布 Pre-release [v4.1.0-dev.53](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/releases/tag/v4.1.0-dev.53)，`--prerelease`、`--latest=false`；stable Latest 仍为 v4.0，tag 指向已测试提交 `b77f9160385ad6370a0587ea448942c0250f1dcc`。
- 构建 artifact `13060374195`（68,909,368 B，`sha256:08ee3b052b0a8abfb851d2d4db5cee7b162b40d719f128f93cd4608788c4f806`，run 41250011450）。发布前用 `verify_native_dev_assets.py` 校验 NSIS 回执、ZIP 清单、版本/上游 pin、无私有 `config/` 与路径穿越，暂存 `SETUP.exe` + `PROTOTYPE.zip` + `SHA256SUMS.txt`。
- 附件为冻结字节、未重新打包：SETUP 27,408,522 B `3c7f58466600982ae13bbab98d67ef2dd8edc9f2623bbf1b0f8eedbf7694caab`，PROTOTYPE.zip 41,484,488 B `2d065e4671357d54e7d29983918baf8040260a5c5f65b276181bf79b5df9c3e8`，SHA256SUMS 242 B。上传后 GitHub 摘要与本地哈希一致；发布后重新下载 SETUP 并 `sha256sum -c` 通过。
- 同提交的 dev.53 原型运行（启动、NSIS 安装/卸载、崩溃收束、单实例、已发布 dev.40 安装包就地升级）与 dev.54 十阶段像素运行全部通过；发布不改变这些边界。

- 2026-11-01 published Pre-release [v4.1.0-dev.53](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/releases/tag/v4.1.0-dev.53) with `--prerelease --latest=false`; the stable Latest remains v4.0 and the tag points at the tested commit `b77f9160385ad6370a0587ea448942c0250f1dcc`.
- Build artifact `13060374195` (68,909,368 B, `sha256:08ee3b052b0a8abfb851d2d4db5cee7b162b40d719f128f93cd4608788c4f806`, run 41250011450). Before publication `verify_native_dev_assets.py` checked the NSIS receipt, ZIP manifest, version/upstream pins, absence of a private `config/` and traversal entries, then staged `SETUP.exe`, `PROTOTYPE.zip` and `SHA256SUMS.txt`.
- The attached bytes are frozen and unrepacked: SETUP 27,408,522 B `3c7f5846…`, PROTOTYPE.zip 41,484,488 B `2d065e46…`, SHA256SUMS 242 B. GitHub asset digests matched the local hashes after upload; the published SETUP was downloaded again and passed `sha256sum -c`.
- At the same commit the dev.53 prototype run (startup, NSIS install/uninstall, crash containment, single instance, in-place upgrade of the published dev.40 installer) and the dev.54 ten-phase pixel run passed; publication does not change those boundaries.
### P5 目标机预检工具与 Windows 诊断回执 / P5 target preflight and hosted diagnostic

- 2026-11-01 新增 `native-host/qualification/preflight.py`：在正式采样前核对 Windows 版本、CPU、物理内存、显示适配器/驱动、显示器数量、两个 `obs64.exe` 的 SHA-256/字节数（必须不同）与元数据契约（五路输入全部 `h265`、`workload=five-real-h265`、七项声明全部确认）。回执 schema 1、kind `native-p5-preflight`，永远 `qualified=false` / `coverageIncomplete=true`；不启动 OBS、不读取摄像机、不测 GPU。`--diagnostic` 只供 CI 用公开占位元数据自检。
- 诊断回执：run 41257481405（提交 75a2992，dev.61），Windows Server 2022 build 20348 / EPYC 9V74 / 17,174,360,064 B 内存 / Microsoft Hyper-V Video / 1 显示器；10/10 检查通过，`diagnostic=true`、`qualified=false`，两个 EXE 的 SHA-256 不同。dev.60 首次诊断在占位声明与 16 GiB 阈值上按预期失败，随后把“诊断模式允许占位声明”和 CI 阈值写清，并非目标机结果。
- 边界：这是工具自检与机器身份回执，不是五路真实相机、硬件解码、GPU、延迟或同机 OBS 对照证据；托管运行器的 Hyper-V 适配器不是 RTX 4090，目标机仍须由操作者按运行手册执行并保管私密回执。

### P5 三对交替排期生成器 / P5 alternating campaign scheduler

- 2026-11-01 新增 `native-host/qualification/plan.py`：从一份已确认的 pair-1/position-1 元数据展开三对交替（产品→OBS→产品→OBS→产品→OBS）的六个 `run-NN-*.json` 与 `plan.json`，可绑定一份 `status=pass`、`diagnostic=false` 的预检回执；`status=planned`、`qualified=false`，不启动 OBS、不采集、不判定。
- 契约：模板必须五路全 `h265`、`five-real-h265`、七项声明全部确认；派生 `runId` 必须唯一且 ≤64 字符；输出必须是仓库外的新私密目录；诊断预检回执会被拒绝。
- 边界：这是排期与元数据一致性工具，不是测量；每轮仍须独立私密目录、`collect.py` 采样与操作者手工核对窗口/相机，P5 未因此推进。

### P3 无媒体控制授权基础 / P3 renderer-free control authorization foundation

- 2026-11-01 按用户优先推进控制/认证与旧配置迁移的决定，新增 [NativeControlAuth](../core/include/webobs/native_control_auth.hpp) 与 [接入边界说明](native-control-auth.md)。直接复用既有 SQLite SessionStore，固定 `scene.read` / `scene.write` / `live.view`，每次操作重新查询可信账号回调；检查精确 loopback peer、Origin、authority 与单个 camera scope，不使用 Basic 或 session-only 管理员回退。
- 账号不存在/禁用时成功撤销该用户会话才返回 401；拒绝 403、后端异常/无回调/无配置 503。独立审查发现原实现忽略 `revoke_user` 返回值，已加入实际 SQLite `BEFORE DELETE ... RAISE(ABORT)` 故障回归：删除未确认时保守 503，不报告撤销成功。structural rejection 不滑动会话或调用后端；后台授权结束后再次验证会话，拒绝途中 logout。
- 本地 Fedora：独立 Release CTest（真实 SessionStore 回归、静态库无媒体符号）通过；根 CTest 的 common / native auth / go2rtc proxy 同时通过。CI 增加独立 Linux/MSVC 构建，Windows 只从既有固定 vcpkg baseline 使用 OpenSSL/SQLite 测试依赖，不改原生包的依赖或媒体链路。
- 边界：这是库和回归，不是完整原生登录。真实账号 HTTP adapter、私密凭据/ACL、listener 有界解析、全部 graph-derived scope 与 OBS 菜单/快捷键等绕过入口控制尚未接入；未开启任何新服务、未切换 Electron 默认产品，未发布新安装器。回执/单测不能替代目标机像素、硬解和性能验收。

The new renderer-free boundary reuses persistent sessions and performs fresh allowlisted permission/scope checks per operation. A real SQLite deletion-failure regression now prevents an unconfirmed revoke-all operation from being reported as a normal 401. Fedora standalone and existing shared regressions pass; Linux/MSVC CI coverage is added independently of the OBS runtime. This does **not** implement native product login, account-service transport, OBS execution or complete UI isolation, and does not change the default product or qualify target-machine media/performance.

### P3 旧配置只读规划 / P3 read-only legacy configuration planning

- 新增 [显式导出预检](../native-host/scripts/legacy_import.py) 与 [契约说明](native-legacy-import.md)，接受 scene schema 5/6 或 studio schema 1。只读一个显式 JSON，不发现/打开账号及 camera 数据库、不解密、不访问网络或实际相机、不提供 apply。报告仅含白名单属性和稳定 ID 映射，去除名称、原始 ID、URL、路径及秘密；Program/Preview 分开映射，不隐式 TAKE。
- 普通 RTSP 是保守候选；硬解与超时必须显式确认。非 RTSP、filter（含 disabled）、非黑背景、高级 item、显式非空 audioInputs 都阻断，不能静默舍弃；空 audioInputs 与缺省语义分开，audioTrack 仍为输出总线。候选不是原生 product 配置，当前 bootstrap 未因此获得超时设置或导入能力。
- POSIX 逐级目录 fd + O_NOFOLLOW；Windows 持有 ancestor handle 并以 OPEN_REPARSE_POINT 打开最终输入，读取前验证 handle 类型/属性/链接/大小，防止先跟随后拒绝。审查发现并修正原 lstat→CRT-open 竞态；加入最终分量替换和 Windows kernel API 契约测试。报告位于导出目录树外，exclusive-create 不覆盖原文件。Windows ACL 继承、不声称自动建立私密 ACL。
- 本地 Python 回归使用临时合成文档，不读取真实私密配置；CI 在 Linux 和 Windows 同跑。所有结果 dryRun=true、applied=false、qualified=false；尚无经授权的 copy-on-write 应用、逐字段 OBS graph 比对与回滚，P3 仍未完成。

The new preflight plans only explicitly exported scene/studio JSON, reconstructs a safe public report and stable scoped IDs, and blocks unsupported semantics instead of dropping them. It does not open databases, decrypt secrets, connect to cameras, or apply a migration. A reviewed Windows final-component race is fixed with a native no-follow handle; race and API-contract regressions accompany the privacy/read-only tests. Reversible application and native product authentication remain future work; no default-product or target-machine qualification claim is made.

### P3 跨平台基础回归回执 / P3 cross-platform foundation regression receipt

- run [41284616387](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/41284616387)，源码 `8480ba5`：`native-control-contracts`（Ubuntu）与 `windows-native-control-contracts`（Windows Server 2022）均成功。Linux 独立 CTest 2/2（授权 + 无媒体符号）、迁移 13 通过 / 1 Windows 专属跳过；Windows MSVC 19.44.35229.0 Release CTest 1/1、迁移 14/14，通过真实 Windows junction/最终分量替换及 no-follow API 契约。Windows 不运行 Unix `nm` 符号门，不把两边计数混同。
- 总 workflow **未通过**：旧 updater job 的未修改 desktop 依赖审计发现 `minimatch` / [GHSA-g3hv-75wg-m249](https://github.com/advisories/GHSA-g3hv-75wg-m249)，在执行 updater 测试前停止，未忽略或降级审计。公开仓库审计另拒绝了新增测试中的合成 RTSP 凭据；已统一为既有 `fixture-user:fixture-password` 占位约定并仅增加“该测试路径 + 该精确占位对”的 allowlist，修正后本地索引审计与迁移回归通过，不放行任意凭据。此修正尚不是一次全 workflow 绿色回执。
- 首次 run 41284146292 在 job 创建前 startup_failure：原 optional reusable caller 的 `contents:read` 上限无法容纳其静态嵌套 publisher 的 `contents:write`。修正仅限原 opt-in caller，上层及两个新安全 job 仍 `contents:read`；本轮 `windows_desktop=false`，没有构建/发布候选。

At tested source `8480ba5`, the independent Ubuntu and MSVC foundation jobs both passed. Windows completed the real session-store authorization suite and all fourteen importer regressions, including junction/race and native no-follow API checks. The overall workflow remained red: an unchanged desktop dependency audit blocked the updater tests, and the public audit rejected a newly introduced synthetic credential fixture. The fixture is now covered only by the existing exact path-and-placeholder policy and passes the local indexed-content audit; this is not a claim of a green full-workflow rerun. No advisory was ignored, no new installer was published, and native login/apply/default-product/media acceptance remain open.

### P3 有界真实账号授权后端 / P3 bounded authoritative account backend

- 新增 [NativeClusterAuthorizationBackend](../core/include/webobs/native_cluster_authorization.hpp)，为已有 NativeControlAuth 接入真实 cluster `POST /auth/authorize` 协议，而非复制旧 core 的 status-only 200 许可。固定 loopback IPv4/port、64 hex 内部凭据、connect≤500 ms / total≤2000 ms、4 KiB body / 16 KiB headers / 128 callbacks；禁用环境代理、重定向、netrc/Basic，不转发 session cookie，不发送可覆盖 registry 解析的 groupId。
- 严格核对成功 JSON 的 allowed/userId/permission 与错误状态/code/message，拒绝重复键、NUL、尾随数据、未知形状和超限；错误内部 token 等故障为 503，不误当普通拒绝或账号失效。每命令真实查询，不缓存许可。
- Fedora 独立项目与根 CTest 已通过真实 SessionStore + cluster Handler/ClusterStore + 临时 camera registry 集成：同会话角色与 camera scope 更新、registry 组变更、禁用撤销全部同用户会话、错误服务凭据后恢复。独立 hostile HTTP 证明非 status-only 许可、超时/超限、代理/重定向 trap 无凭据泄漏；无效 direct 请求针对活跃 observer 断言零请求并设正常正对照。审查指出的“关闭端口不能证明零请求”假阳性已修正，probe 增加每次响应 deadline 与 owned reader 回收。
- 测试 hasher 为 fixture，不是登录/Argon2 验收；没有访问真实私密数据库或相机，没有启动完整 Supervisor、listener 或第二媒体引擎。Linux/MSVC 独立 CI 已纳入真实后端测试；首轮 Windows run [41287546346](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/41287546346) 在编译阶段发现 SDK `max` 宏冲突（C2589/C2059），尚未执行该后端测试；修正后 run [41288546248](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/41288546248) 已完成 MSVC 编译且不再出现静态 CRT 冲突，但后端测试暴露 Python fixture 未显式 close SQLite 引起的 WinError 32 清理失败，另有禁用账号一次 503≠401；未记为通过。现已显式关闭所有 fixture 连接，并加入持有强引用（防 GC 掩盖）的红→绿所有权回归，再复验 Windows，不放宽授权或 deadline。原生登录、私密 ACL/服务生命周期、全 graph-derived scope、UI 防绕过、用户名重用/密码 epoch 和可回滚迁移仍未完成；无新安装器或默认切换。

The renderer-free adapter now speaks the actual cluster authorization protocol with bounded requests and strict body/status correlation. Real Handler/ClusterStore/registry tests are separate from hostile HTTP fixtures; they cover fresh roles/scopes, account disabling, session revocation and service-credential recovery without a real profile or media process. Reviewed test gaps were closed with a live no-contact observer and a bounded owned probe reader. Linux/root regressions pass locally. The first MSVC attempt (run 41287546346) stopped at an SDK `max` macro collision before the new tests ran; run 41288546248 then compiled without the CRT warning but failed backend fixtures with unclosed Python SQLite handles (WinError 32), plus a disabled-account 503≠401. All fixture connections now close explicitly; a strong-reference ownership regression is red under the former lifetime and green with the correction. Windows is being rerun without relaxing authorization or deadlines. Both unrelated public-PWA/updater jobs also stopped on unchanged dependency audit gates (minimatch GHSA-g3hv-75wg-m249, plus web glob GHSA-3g3m-2fjr-6pw4); the indexed-content privacy audit itself passed. This is not native login, UI isolation, reversible migration, product-default convergence or target-machine qualification.

### P3 真实账号后端跨平台回执 / P3 real-account backend platform receipt

- 修复测试源码 `b23420d` 的 [run 41289560072](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/41289560072)：Ubuntu `native-control-contracts` 与 Windows `windows-native-control-contracts` 均成功：Ubuntu CTest 4/4；Windows MSVC 19.44.35229.0 CTest 2/2（真实后端集成 + 本地会话门）、旧配置预检 14/14，含 Windows native handle/junction 路径用例。Windows 已真正运行后端集成，而非仅编译；原 SDK max 宏、CRT 选择和 Python SQLite fixture 资源回收问题分别保留前两轮失败记录，不将其改写为通过。
- SQLite 资源回归持有全部连接的强引用，避免 POSIX unlink/GC 掩盖泄漏：旧 transaction-only lifetime 必须红，显式 closing 后绿；不依赖 sleep、放宽 401/503 或删除 Windows 清理断言。没有改生产账号服务、权限决策或请求时限。
- Fedora 最终独立 CTest 4/4、根 CTest 4/4、构建契约 18/18，旧配置预检 13 通过 + 1 Windows 专用跳过；本地索引隐私审计 838 paths 通过。
- **整条 workflow 仍失败**：PWA/updater 的既有依赖审计门仍报告 minimatch GHSA-g3hv-75wg-m249，web 另有 glob GHSA-3g3m-2fjr-6pw4。后续 PWA/browser/updater 测试未执行，未豁免审计或跨 major 强换依赖。本轮没有创建安装器、发布版本、切换 Electron 默认入口或做目标机器媒体验收。
- 接入前的独立审查见 [认证契约后续](native-control-auth.md#后续--next)：先可信 graph/camera 身份与全 scope 预检；旧 product bootstrap 混合 reuse/create 回滚的静态风险须另做可执行回归，不能直接对现有 dock 加登录后宣称完成。

Run 41289560072 at tested commit `b23420d` passed both native Linux and real MSVC jobs after fixing macro/CRT portability and deterministic fixture SQLite ownership; the earlier failed attempts remain documented. Fedora standalone/root CTest passed 4/4 each, build contracts 18/18, read-only import 13 passed plus one Windows-only skip. The whole workflow is still red on unchanged PWA/updater dependency audits, with downstream tests unexecuted. No audit bypass, new package/release, default-host switch, secured native login, reversible import or target-machine media/performance qualification is claimed.

### P3 bootstrap 混合所有权回滚 / P3 bootstrap mixed-ownership rollback

- 将先前静态发现转为可执行红→绿回归：直接编译实际 `product_bootstrap.cpp` 与固定 OBS 32.1.2 headers、API doubles，旧代码 181 用例中 113 通过/68 失败；最小复现为 reuse 槽 0 → create 槽 1 → 槽 2 名称冲突，按 created=1 删除前缀会误删复用源、遗留新建源。源创建失败和 wall 失败的混合排列也覆盖。
- 修复仅用函数内部逐槽 `created_here` 标记本次成功创建的源；所有失败出口只 remove 标记项，随后由既有 `ProductWallResult::release` 统一释放所有取得的引用。公共 result/counters、媒体 settings、源复用规则、Studio/Program 语义均未改变。
- 本地 Release CTest 2/2（既有 wall + 新 bootstrap）、bootstrap 181/181、Python 构建契约 19/19；检查全部五槽 mask、每个早退位置、失败引用平衡/精确删除、成功不删除、release 幂等、无效最后槽在 OBS 调用前拒绝。新增轻量 Linux/MSVC 矩阵 `native-graph-api-contracts`，只取固定 headers、不构建或启动 OBS；[run 41292051971](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/41292051971) 在源码 `2860666` 实际通过 Linux GNU 13.3.0 与 Windows MSVC 19.44.35229.0 的两组 graph CTest 2/2，原 Linux/MSVC control-auth jobs 也成功。索引隐私审计 839 paths 通过；整条 CI 仍被未修改的 PWA/updater minimatch/glob 依赖审计门阻断，后续相关测试未运行。
- 替身 wall 只模拟返回 scene 引用，不证明真实 scene lookup/item 引用/选择/保存、Qt、媒体或像素。修复不建立 camera registry 身份、授权 UI、copy-on-write 迁移或目标机验收；未发布安装器或切换默认产品，既有 PWA/updater 审计门保持。

The static concern is now executable: 68 of 181 bootstrap cases fail under the old prefix cleanup, including reuse0/create1/conflict2. A private per-slot creation mask limits removal to objects created by this attempt, followed by the unchanged reference-release path; local bootstrap 181/181, CTest 2/2 and build contracts 19/19 pass. Run 41292051971 at `2860666` passed the lightweight graph CTest 2/2 on both Linux GNU 13.3.0 and real Windows MSVC 19.44.35229.0; both existing control-auth jobs also passed. The whole workflow remains red on unchanged PWA/updater dependency audits, with downstream tests unexecuted. Their wall seam is not frontend/media qualification; trusted graph identity, live authorization and reversible migration remain separate open gates.

### P3 未暴露的只读 scene 观察 / P3 unexposed read-only scene observation

- 新增 [wall snapshot](../native-host/src/wall_snapshot.hpp) 与实际只读实现：严格 scene UUID 查询已有 scene，在 OBS scene locks 内枚举包含隐藏项的五个平面 Media Source item，复制 UUID/item ID/用户可见标记。重复 source 允许，错误/缺失结构返回无部分 DTO；拒绝 group、嵌套、任意 scene/source filter（含禁用项）、错误类型/UUID/重复 item ID，第六项在读取 source 前拒绝。
- 不读名称、settings、URL，不创建/删除/选择/保存，不启动 renderer 或服务；callback 异常包含在 C++ 内，取得的 source 引用用 RAII 释放，DTO 在离开锁后分配。源码仅加入单独 API test target，未接入产品插件、认证库、路由或 live 命令。
- Fedora Release 的 graph CTest 3/3、独立 snapshot 84/84 情形、构建契约 19/19 已通过。测试使用真实固定 OBS 32.1.2 headers、15 个只读/引用/加锁 API doubles；无 mutation/frontend doubles。现有矩阵会在 Linux/MSVC 复验新增第三个 graph CTest；本节此时尚无新 MSVC 结果，不以本地编译替代。
- 边界：这是观察，不是可信 registry camera/profile 绑定、全 scope 授权或可供执行的 graph revision。可见标记不是像素；transform/audio/transitions 等依赖未审计，锁和 filter 遍历无硬时限。下一步仍需可信 owner mapping、身份/权限 epoch 一致性、UI bypass/服务所有权与经授权可回退应用；不切换默认产品、不发布安装器、不宣称目标机验收。

A separate unexposed inspector now observes existing flat five-item scenes, including hidden entries, using actual pinned OBS headers and read/ref/lock doubles. Fedora graph CTest 3/3, the 84-scenario inspector and build contracts 19/19 pass; the existing Linux/MSVC matrix will exercise the new third graph test, with the new Windows result still pending here. No plugin/auth-library/live-action wiring, media or final-pixel qualification is added. UUID tuples and user-visible flags are observations, not trusted camera bindings, a complete dependency audit, an authorization grant, or a hard-deadline snapshot; identity/policy consistency and reversible migration remain open.

首次实际 run [41301431730](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/41301431730)（`55465d5`）中 Linux graph 3/3 通过，但 MSVC 19.44.35229.0 的 snapshot 测试报 `root_ref_balance`，不能记为双平台成功。Windows 编译同时报告 C4297：测试故意从 `extern "C"` OBS doubles 抛出异常，而默认 `/EHsc` 内含 `/EHc`（假定 C 调用不抛异常），使这种人工场景的展开/RAII 释放假设不成立。仅在 `native-wall-snapshot-test` 的两个 translation unit 后置 `/EHs /EHc-`，保留全部异常、引用和无修改断言，增加固定 case 序号及 verbose 编译日志；真实插件和 observer 源码行为未改。这不是已证实的真实 libobs 引用泄漏；需要实际 MSVC 复验，不能以 Fedora 通过推定修正有效。

The first hosted run (`55465d5`) passed Linux graph 3/3 but failed the Windows snapshot fixture with `root_ref_balance`. MSVC C4297 identified deliberately throwing extern-C API doubles under `/EHsc`'s C-nothrow assumption. A test-target-only `/EHs /EHc-` override now models those synthetic exceptions in both translation units; all assertions remain, diagnostics include a fixed case ordinal, and verbose build logs expose option order. No production plugin flags or observer behavior changed. This is not evidence of a real libobs leak, and actual MSVC revalidation was required before calling the correction effective.

复验 run [41302282797](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/41302282797)（源码 `3df73963fe2742daaaf341108038145b469a0b61`）的 Linux graph job `124835561407`（GNU 13.3.0）与 Windows graph job `124835561423`（MSVC 19.44.35229.0）均为 **3/3 CTest 通过**。Windows verbose 编译日志实际显示 snapshot target 使用 `/EHs /EHc-`，其他两个 graph target 保持 `/EHsc`；新日志无 C4297。84 个 snapshot 情形与所有异常/引用断言保留，这只是 pinned-header/API-double 的只读、引用和结构契约，不是实际 libobs 媒体、可信身份或产品登录验收。同一 run 的无渲染认证 job 也通过：Linux `124835561468` 为 CTest 4/4（含两个 no-media symbol gate），只读迁移 13 通过加 1 Windows 专属跳过；Windows `124835561228` 为实际 MSVC CTest 2/2、迁移 14/14。本机追加复验 core/session/真实 cluster backend/proxy CTest 4/4、只读迁移 13 通过加 1 Windows 专属跳过、备份恢复 8/8。该 run 的索引隐私检查通过 842 paths，但独立 updater 的 minimatch 审计（GHSA-g3hv-75wg-m249）与 web 的 minimatch/glob 审计（另有 GHSA-3g3m-2fjr-6pw4）仍失败，下游相应测试未执行；无 ignore、降级阈值或泛化跨 major override。未构建或发布安装器，未接入 live 操作，未切换默认产品。

Revalidation run 41302282797 at `3df7396` passed graph CTest **3/3 on both Linux and actual MSVC**. Verbose Windows logs confirm `/EHs /EHc-` only for the snapshot target while the other two targets retain `/EHsc`, without C4297. All 84 snapshot scenarios and exception/reference assertions remain; this proves the isolated pinned-header API contract, not real media, trusted identity or secured native UI. The same run also passes renderer-free authorization CTest 4/4 on Linux (including two no-media symbol gates) and 2/2 on MSVC, with migration 13 passes/one Windows-only skip on Linux and 14/14 on Windows. Local preserved core/auth/backend/proxy CTest 4/4, migration 13 passes plus one Windows-only skip, and restore 8/8 also pass. The same run passes indexed privacy checks but still fails the separate unchanged minimatch/web-glob advisory gates, leaving downstream tests unexecuted; the workflow is not green. No installer, live action, product-default switch or target-machine qualification is added. At the time of that run, the reviewed offline private-staging proposal in [legacy migration](native-legacy-import.md#下一阶段候选离线私密暂存--next-candidate-offline-private-staging) was unimplemented and unverified, not a usable import format. The subsequent bounded offline-copy increment is recorded below.

### P3 受限离线私密候选 / P3 bounded offline private candidate

新增 [离线 CLI](../native-host/scripts/legacy_stage.py)、[纯转换及独立语义验证](../native-host/scripts/legacy_stage_document.py) 和 [新目录私密事务](../native-host/scripts/private_stage.py)。只接受单 scene schema 5/6、平面 RTSP、contain/零 crop/普通 blend、显式 `audioInputs=[]` 且监听 off；不支持字段整单拒绝。scene/source UUID、独立正 int64 item ID、层序、隐藏/锁定、复用、名称/URL/transport/音量/静音/同步与布局从原输入逐字段比较，篡改后重算集合哈希也不能代替语义校验。global profile/output/FPS 和 timeout 保留为未应用要求；真实固定 libobs JSON loader roundtrip 仍未验证。

操作者必须提供原始导出、全新目标目录和完整的现有配置排除根；不自动发现配置。路径排除在安全父目录句柄保持至清理结束期间比较目录卷/文件身份，避免短名、DOS 盘符或 bind 别名仅凭拼写绕过。两个强制别名回归在恢复旧 lexical-only guard 后均按预期失败，新 guard 本地通过。新目录/文件为 exclusive create；POSIX 0700/0600 与 file/directory fsync，Windows 创建时即传入 protected current-user DACL、通过 handle 验证后才写秘密，持有 no-reparse/deny-write-delete handles。成员独立读回比较、回调后再检查、completion 最后创建并读回；Windows 文件 flush 必须成功，但目录持久性明确未确认。失败只清理本次身份仍匹配的路径，外来内容/清理失败可留下不完整私密现场；不是跨文件原子导入、断电保证或认证。全部三个输出成员私密，不上传 CI。

本地已有 converter 12/12、CLI 10 通过加 1 Windows 专属跳过、私密文件测试 18 通过加 8 Windows 专属跳过、构建契约 20/20；保留 graph CTest 3/3、renderer-free auth CTest 4/4、只读预检 13 通过加 1 Windows 专属跳过、恢复 8/8。新增独立 Linux/Windows Python CI 矩阵，不获取 OBS/媒体依赖、不上传输出；新增 Win32 实例 API 边界测试覆盖 ACL 验证先于写入、WriteFile 失败/零进度/真实短写、ReadFile 失败/提前 EOF、成员/marker flush 必须成功、目录预期 flush 错误与其他错误区分，以及清理失败只留下受限私密片段。实际 Windows/Ubuntu 结果已记录在下方平台回执中，未以 Fedora 跳过替代。

This increment creates only a new private offline candidate, never a live-host import. A strict single-scene, flat RTSP, contain-only, explicitly silent subset is independently decoded against the original export, including identities, positive bounded item IDs, names/URLs/settings, order and transforms; forged updated hashes do not bypass semantic verification. Explicit configuration exclusions use held directory identities, not just lexical paths. Exclusive private creation, permissions-before-secret-write, verified readback, a final private completion index and identity-limited cleanup are separate from the converter. Windows file flush is required but directory durability remains unconfirmed; partial private data can remain on cleanup failure. The Linux/Windows Python matrix neither starts OBS/media nor uploads generated members. Local preserved regressions pass; the new Win32 fault coverage is implemented, and the actual platform receipt is recorded below. Pinned real-loader compatibility, immutable account/policy identity, trusted camera binding, full-scope authorization and reversible live apply remain open. No current profile, product default, installer, release or target-machine qualification is changed.

#### 私密离线候选平台回执 / Private offline candidate platform receipt

[run 41306040713](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/41306040713) 测试源码 `00c19a16c7ad8d86461294a7360d062a7d43b6a5`。独立 Ubuntu job `124846501293` 和 Windows Server 2022 job `124846501334` 均成功：两端 converter 都是 12/12；Ubuntu 私密文件 18 通过、8 Win32 专属跳过，CLI 10 通过、1 Win32 专属跳过；Windows 私密文件 22 通过、4 POSIX 专属跳过，CLI 11/11，实际 DOS drive alias 回归明确 `ok`。Windows 执行了 6 个新增 API 边界测试及既有 protected owner DACL/deny-write-delete、junction 测试；未以 POSIX 替身通过冒充 Win32。失败注入验证拒绝而不是降低权限或放宽文件 flush；目录预期错误仍只表示 directory-unconfirmed。测试仅使用本次临时合成数据，不加载 OBS、不读取真实用户配置、不上传生成文件。

The independent Ubuntu (`124846501293`) and Windows Server 2022 (`124846501334`) staging jobs passed on the exact source above: converter 12/12 on both; private filesystem 18 passed/8 Win32-only skipped on Ubuntu and 22 passed/4 POSIX-only skipped on Windows; CLI 10 passed/1 Win32-only skipped on Ubuntu and 11/11 on Windows, including the actual DOS-drive directory-alias test. All six new Win32 API-boundary tests ran, alongside protected-owner DACL/sharing and junction checks. These are disposable synthetic filesystem/conversion tests, not pinned-libobs loader, live authentication/import, cameras, pixels or target-machine qualification. The full workflow status and preserved native graph/auth jobs are separate and must not be inferred from these two successful jobs.

同 run 保留的 graph jobs `124846501279` / `124846501302` 均成功；Linux renderer-free auth job `124846501348` 成功，Windows auth job `124846501102` 成功，实际日志为 MSVC CTest 2/2、只读 importer 14/14。整条 workflow **仍失败**：updater job `124846501258` 因未改动的 minimatch `GHSA-g3hv-75wg-m249` 审计终止，public-audit job `124846501290` 因同项及 glob `GHSA-3g3m-2fjr-6pw4` 两项依赖告警终止；后续浏览器/管理等步骤未执行，Windows 完整安装器 job 按输入跳过。没有忽略告警、放宽门槛或以局部通过替代总 CI 状态。

The retained graph jobs passed on both platforms; renderer-free authorization passed on Linux and Windows, with the actual Windows log reporting MSVC CTest 2/2 and read-only importer 14/14. The overall workflow **failed** at unchanged dependency audits: minimatch `GHSA-g3hv-75wg-m249` in the updater, and that advisory plus glob `GHSA-3g3m-2fjr-6pw4` in the public audit. Downstream browser/management steps did not run and the full installer job was explicitly skipped. No audit ignore or threshold weakening was introduced.

下一 loader 门槛尚未实现：必须在独立固定 libobs 测试进程中仅注册无 I/O 的惰性测试 source，真实 load/query/save/reload，显式设置 `AbsoluteCoordinates=true`，并让 base size 与 scene canvas 不同以暴露坐标解释错误。不能加载真实 obs-ffmpeg 验证“离线”候选：当前 `close_when_inactive=False` 在固定上游 `obs-ffmpeg-source.c:488–489` 即使未激活也可能 open。当前显式静音契约不承诺未来启音后的原 bus 路由等价。真实 loader、授权提交与可逆应用仍未通过。

The next, unimplemented gate must use a separate pinned-libobs process with an inert, no-I/O test source, actual load/query/save/reload, explicit `AbsoluteCoordinates=true`, and a base size different from the scene canvas. Do not load the real FFmpeg media plugin to validate an “offline” candidate: `close_when_inactive=False` can open media even while inactive in the pinned source at lines 488–489. The explicit-silence subset does not qualify future enabled-audio bus routing. Real-loader compatibility, authorized commit and reversible apply remain open.

### P3：惰性源真实 libobs loader 回归 / Inert-source real-libobs loader regression

新增独立 [CMake target](../native-host/tests/real-loader/CMakeLists.txt)、[C++ 探针](../native-host/tests/real-loader/loader_probe.cpp) 与 [合成 stdin 驱动](../native-host/tests/test_real_legacy_loader.py)。固定 32.1.2 SDK，实际 libobs load/query/save/销毁/reload/后续加项；仅注册自身固定 800×600 无媒体 I/O 源，不加载模块/frontend、不 reset audio/video、不渲染、不读取真实 profile/export。原始输入与映射独立推导实时查询期望，纯 decoder 继续验证确定性映射与完整 manifest；不是只验证自生成哈希。

首轮本机运行因探针漏释放 main canvas 的 SCENE_REF，在 `reload_cleanup` 明确失败，未记通过；修正为持有本次场景引用时 `obs_canvas_scene_remove` 再释放，逐轮验证精确非零 create/destroy 次数与 UUID/name 消失。另修正无 video mix 时不能使用 `obs_get_video()`，改为安全的 `obs_get_video_info`。增加 scene 中性状态、负/零/极小/超大数值与极端枚举预启动拒绝、1 MiB 原始字节边界/CRLF/Ctrl-Z/NUL、固定失败/超时诊断不回显测试。没有改 converter 或生产产品行为。

本机 Fedora 已实际通过真实 loader CTest 1/1（Python 12 个测试家族）、构建契约 21/21；Linux CI 与 Windows MSVC 结果在提交后单独记录，不能以本机通过代替。Windows builder 在 SDK 安装后、plugin 构建前运行独立测试，临时设置 DLL PATH 并 finally 恢复；探针不安装/打包。新增 Ubuntu CI 只构建固定 libobs、仅安装其 SDK，不上传输出。

边界：显式临时恢复 AbsoluteCoordinates；无非零全局 base canvas，尚未验证两个不同非零 base/scene 尺寸或默认相对坐标。只查询 custom dimensions/CPU transforms，不证明像素或媒体；原生探针信任映射意图，版本检查不证明二进制来源。absolute 模式的 scale_ref 与已解析 UUID 的 item.name fallback 可被上游忽略，不宣称每个存储字段篡改都被实时语义拒绝。授权、不可变账号/策略 epoch、可信 camera 绑定与可逆 live apply 仍未实现；默认产品/稳定发布/目标硬件验收均不改变。

English: a separate exact-version libobs target and synthetic-only stdin driver now exercise real load/query/save/destruction/reload and item-counter allocation using only an inert fixed-size source. No modules, frontend, media, audio/video reset, rendering or real profile/export is used. Original/mapping-derived live expectations are layered with the independent pure decoder, not replaced by collection hashes. The first local run failed honestly at reload cleanup because the probe missed the main-canvas scene reference; detaching its own retained scene fixed probe ownership. Exact nonzero callback counts, neutral scene state, pre-start numeric/enum safety, raw byte limits and non-echoing failure/timeout diagnostics are covered. Fedora passed one CTest containing 12 Python test families and 21 build contracts; Linux CI and MSVC receipts remain separate until actually observed. The Windows builder runs but never installs/packages this target and restores its temporary DLL PATH. No nonzero global/base canvas, relative-coordinate mode, pixels, media behavior, binary provenance, native product authorization or reversible live import is qualified. No default product, stable publication or target-camera claim changed.

首轮平台 CI：run `41309421880`，source `e61b361` 的 Ubuntu real-loader job `124856493901` 在 SDK configure 阶段失败：`Could not find a package configuration file provided by "ECM"`；探针尚未运行，不能记通过。补齐 `extra-cmake-modules`。另已在本机移除 DISPLAY 的独立进程复现有效合成输入在 `startup` 固定失败；固定 OBS 的启动流程会初始化 X11 热键，即使不 reset video/audio，因此 CI 使用 Xvfb 提供该 OS 服务，仍不创建 OBS video context。新增契约锁定两项 CI 依赖，重跑结果另记。Windows run `41309424968` 仍需实际结果。

English: the first platform run `41309421880` at `e61b361` failed in Ubuntu job `124856493901` while configuring the SDK because ECM was missing; no real-loader test ran. Add `extra-cmake-modules`, not a relaxed loader assertion. A separate local subprocess without DISPLAY also reproduced a fixed startup rejection for valid synthetic input: pinned OBS initializes X11 hotkeys even without audio/video reset. Xvfb supplies that OS service in CI, not an OBS video context. Build contracts now retain both dependencies. The second Ubuntu run `41310063270` at `860dc1e` passed ECM discovery but stopped during SDK configuration at `Could NOT find OpenGL (missing: OPENGL_opengl_LIBRARY OPENGL_glx_LIBRARY OPENGL_INCLUDE_DIR)` in upstream `deps/glad/CMakeLists.txt`; the probe again did not run. Add `libglvnd-dev` for upstream configure-time headers/libraries even though only libobs is built and no renderer is loaded. 第一次缺 ECM、第二次缺 upstream glad 所需 OpenGL 开发包均为实际配置失败，不计 loader 通过；不通过放宽断言绕过。重跑和 Windows 证据另记。

Windows 首轮 run `41309424968`（`e61b361`），job `124856502106` 实际 MSVC 编译探针成功，真实 loader CTest **1/1 passed，2.72 s**，随后 graph CTest **3/3**。整项仍失败：后续 Python 3.12 的 build-contract 源文件读取使用默认 cp1252，5 个测试在 UTF-8 workflow/中文文档解码时报错；不是 loader 失败，也不能把该 job 记全绿。现在对该测试文件的所有 `Path.read_text` 显式指定 UTF-8，并增加 AST 契约防回归；不更换系统代码页、不跳过断言。Windows loader CTest 增加 verbose 输出，后续重跑保留 Python 家族级结果。

English: Windows run `41309424968` at `e61b361`, job `124856502106`, actually compiled the probe with MSVC and passed real-loader CTest **1/1 in 2.72 s**, then graph CTest **3/3**. The overall job nevertheless failed later: Python 3.12 build-contract tests implicitly decoded UTF-8 workflows/bilingual documentation using cp1252, causing five decode errors. Explicit UTF-8 source reads and an AST regression guard fix test portability without changing the OS code page or skipping assertions. Subsequent Windows loader CTest output is verbose so individual Python families are visible; the rerun is not yet claimed successful.
