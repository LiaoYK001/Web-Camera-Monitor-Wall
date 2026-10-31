# OBS 原生前端独立开发原型 / Independent native OBS frontend prototype

此目录是 Windows 架构收敛的 **P2 初始脚手架**，不是新发布产品，也不会替换默认 Electron/NSIS 兼容路径。它直接构建固定上游 OBS Studio **32.1.2** 的完整 Qt 前端、`libobs` 与原生 Media Source/Preview/Projector，再以产品自有插件提供五分屏入口。不引入另一套播放器、渲染器、WebView、Electron、GStreamer 或 `clients/` 产品。

**当前没有产品登录/RBAC、旧数据迁移、服务 supervisor、安装器或产品更新器。请仅在新的、可写、隔离开发目录运行。** 不要导入已有 OBS 用户配置或正式产品私密数据。已有功能仍由兼容产品承担；本原型不能声称 P3/P4 完成或五路 H.265/CPU/GPU 等价验收通过。

## 固定输入与独立构建

上游子模块为 `obs/obs-studio/`，要求 commit `fb4d98bf88fae5fc85cb11fc57f7c5e309282194`，并检查其递归子模块均位于各自固定 commit、无 tracked modifications。构建 helper 只复制 Git tracked 内容，不修改上游；不使用旧产品的 headless patch。固定上游的工具脚本 symlink 仅按 Windows Git `core.symlinks=false` 语义 materialize 链接文本，不跟随外部路径，也不要求 Windows symlink 管理员权限。

依赖直接复用 `desktop/dependencies.lock.json` 中的 `obs-deps`、`obs-qt`（均为 `2025-08-23`）。helper 将 URL、版本、SHA-256 与固定上游 `CMakePresets.json` 交叉核对，再对共享缓存与复制后的归档重新校验。只从固定 HTTPS 地址获取归档；缓存损坏直接失败，不悄悄换包。浏览器/CEF、scripting、WebSocket、VLC、VST、AJA、DeckLink、WebRTC 在这个有限原型中显式关闭，**不代表允许从未来默认产品删除这些能力**。

构建前手工安装并打开 **VS 2022 x64 Developer PowerShell**：PowerShell 7.2+、MSVC x64、Windows SDK `10.0.22621.0`、CMake 3.28+、Python 3、Git。脚本不下载安装任意编译器，也不调用 npm/vcpkg/产品服务。OBS 的 Qt DLL 和 platform plugins 由它自己的固定 CMake 安装规则收集，插件通过明确 `Qt6_DIR` 使用同一份 Qt，不复制系统任意 DLL。

从仓库根目录运行：

```powershell
pwsh -NoProfile -File desktop/scripts/build-obs-native.ps1 -Version 0.1.0-dev.1
# 已存在已校验缓存时可禁止 helper 下载：
pwsh -NoProfile -File desktop/scripts/build-obs-native.ps1 -Version 0.1.0-dev.2 -Offline
# 可显式指定新的、尚不存在的目录（路径内可有空格）：
pwsh -NoProfile -File desktop/scripts/build-obs-native.ps1 -Version 0.1.0-dev.3 -BuildDirectory 'D:\WebOBS Native Test\run-3'
```

默认输出为 `build/obs-native-windows/<dev-version>-<unique-id>/`，内有只读语义的源码快照、OBS build/install、plugin build 和独立 `runtime/`。每次使用 **全新构建树**，只复用已验证归档缓存，避免上游 `.deps` 提取收据掩盖陈旧内容。脚本拒绝已存在的 `BuildDirectory`，不会删除、迁移或覆盖私密 portable 数据。失败后请保留现场，另选新目录重试。`--offline` 对缺失归档直接失败；已复制归档均完整验证后才会启动上游 CMake。

结果中的 `webobs-native-prototype.json` 记录固定版本、禁用可选特性、无服务启动和按 Qt/plugins/other 粗分的实际字节数。

### 原型安装与升级 / Prototype install and upgrade

`native-host/scripts/install_native.py` 把冻结 ZIP 安装到用户指定的私密目录：校验条目路径与 manifest（开发版、`defaultProduct=false`、不启动服务）、拒绝包内 `config/`、当前安装目录没有 manifest 时拒绝覆盖无关目录、替换前备份并在失败时回滚；已存在的 `config/obs-studio` portable profile 会复制进新树，因此重装/升级保留五格墙、source settings 与账号登录。安装器写入小型 JSON 回执（版本、SHA-256、是否保留配置、文件数），不含路径、URL 或日志。这是原型安装器，不注册系统服务、不写注册表、未签名，也不是产品安装包。

`native-host/scripts/install_native.py` installs a frozen ZIP into a private caller-chosen directory: it validates entry paths and the manifest (development version, `defaultProduct=false`, no services), rejects a bundled `config/`, refuses to overwrite an unrelated directory without a manifest, backs up the old tree and rolls back on failure; an existing `config/obs-studio` portable profile is copied into the new tree so reinstall or upgrade keeps the five-tile wall, source settings and account login. It writes a small JSON receipt (version, SHA-256, whether config was preserved, file count) without paths, URLs or logs. This is a prototype installer: no service registration, no registry writes, unsigned, and not a product installer.

独立开发安装包（原型）：`native-host/installer/WebOBSNative.nsi` 用 NSIS 把同一份冻结 runtime 打包成未签名的每用户安装器 `WebOBS-OBS-native-<dev>-windows-x64-SETUP.exe`。静默安装到 `%LOCALAPPDATA%\WebOBS Native Prototype`，只写 HKCU 的卸载信息，不注册服务；重装会覆盖程序文件而不触碰 `config\`，静默卸载删除程序文件但逐字节保留 `config\`（内含 RTSP 凭据与五格墙）。CI 会在同一运行中验证安装→双启动烟测→重装保留配置→卸载保留配置与清理注册表，并记录安装包字节数/SHA-256。它仍是开发包：未签名、无自动更新、无自动数据迁移或自动回滚，不是产品安装器。

版本升级快照：每次以一个安装目录中**首次出现的新版本**启动时，插件在 `FINISHED_LOADING` 处理前把 `config/obs-studio`（跳过 `obs-studio/logs`）复制到 `backups/config-<version>-<UTC 时间>/`，并写 `backup.json`（逐文件 SHA-256、字节数、版本）；最多保留 3 份，失败时删除半成品，绝不阻塞启动。`backups/` 与 `config/` 一样不随卸载删除。恢复前先查看并校验：

```powershell
python -B native-host/scripts/restore_native_backup.py --install-root '<安装根>' --list
python -B native-host/scripts/restore_native_backup.py --install-root '<安装根>' --backup config-<version>-<时间> --apply
```

`--apply` 会先把当前 `config/` 快照到 `backups/pre-restore-<UTC>/`，再以临时目录原子替换并写恢复回执；拒绝路径穿越、绝对路径、未列入清单的文件、重复条目和哈希/字节数不匹配。边界：这是同一安装目录内的文件级开发快照，不是加密凭据备份、跨机器迁移、自动回滚或产品数据保留策略。

Standalone development installer (prototype): `native-host/installer/WebOBSNative.nsi` packages the same frozen runtime with NSIS into an unsigned per-user `WebOBS-OBS-native-<dev>-windows-x64-SETUP.exe`. It installs silently under `%LOCALAPPDATA%\WebOBS Native Prototype`, writes only HKCU uninstall metadata and registers no service; reinstalling replaces program files without touching `config\`, and silent uninstall removes program files while preserving `config\` byte for byte (including RTSP credentials and the five-tile wall). CI verifies install → two-launch smoke → reinstall preserving the profile → uninstall preserving the profile and cleaning the registry, and records the installer byte count/SHA-256. It remains a development package: unsigned, no auto-update, no automatic data migration or rollback, not the product installer.

Version upgrade snapshots: on the first launch of a **new version** in an install root, the plugin copies `config/obs-studio` (excluding `obs-studio/logs`) to `backups/config-<version>-<UTC>/` before `FINISHED_LOADING` handling and writes `backup.json` (per-file SHA-256, byte counts, version); at most three snapshots are kept, a partial directory is removed on failure, and startup is never blocked. Like `config/`, `backups/` survives uninstall. Inspect and restore with:

```powershell
python -B native-host/scripts/restore_native_backup.py --install-root '<install root>' --list
python -B native-host/scripts/restore_native_backup.py --install-root '<install root>' --backup config-<version>-<time> --apply
```

`--apply` first snapshots the current `config/` to `backups/pre-restore-<UTC>/`, then atomically replaces it from a staging directory and writes a restore receipt; it rejects path traversal, absolute paths, unlisted files, duplicate entries and size/hash mismatches. Boundary: this is a file-level development snapshot inside one install root, not encrypted credential backup, cross-machine migration, automatic rollback or a product data-retention policy.
这是原型体积基线，不是发布包/压缩率或性能结论。保留 OBS 自身的 license/data 安装内容，并复制 GPL、产品插件许可、依赖锁；公开分发前仍须完整许可证/源码包审计。

## 运行与配置隔离

构建脚本打印实际 `runtime/` 路径。显式运行该目录中的启动器：

```powershell
pwsh -NoProfile -File '<实际 runtime 路径>\launch-native.ps1' -AllowPrototype
```

`-AllowPrototype` 是刻意的开发门槛，不是产品认证。没有此开关就拒绝启动。启动器验证身份清单、`obs64.exe`、Media Source、产品插件、Qt platform plugin、portable/updater sentinel；检查配置目录可写后，用固定 `runtime/bin/64bit` 工作目录和 `--portable --disable-updater` 启动 OBS，并移除继承的外部 OBS/Qt plugin 与 config 环境覆盖。

OBS 32.1.2 Windows portable 配置实际位于 **`runtime/config/obs-studio/`**，不是 `OBS_CONFIG_PATH`。`portable_mode.txt` 与 `disable_updater.txt` 同时保存在 bundle 根。portable 模式跳过用户/系统 OBS plugin 搜索路径，且不会读取或写入 `%APPDATA%\obs-studio`。本阶段不适合只读 Program Files 安装。OBS 可以在此目录持久化含 RTSP 凭据的 source settings、日志、记录等；请将整个构建/runtime 树按私密数据处理，不提交或公开上传。不能把 portable 隔离当成产品用户认证。

不运行任何 core/Python/go2rtc/MediaMTX/转码服务，不监听产品管理端口，不访问旧 Electron 数据，不自动迁移，不执行自动更新，也不绕过 OBS 自身实例互斥。

## 最小原生功能

1. 在独立 OBS 内用其原生 **Media Source** 属性创建摄像头输入；取消 Local File 并输入自己的 RTSP 地址。缓存、硬件解码、重连、音频、色彩等仍由固定 OBS 原生属性控制，本插件不解析/另存 URL、不新建 media source、不更改这些参数。
2. 在 **Docks → WebOBS Native Prototype** 中刷新既有 Media Sources，并选择五个槽位。插件使用 source **UUID** 获取相同源对象，添加 scene item 时复用对象及其现有解码器。跨场景/投影不主动另开解码器；同一源可以选入多个槽位，这不代表五路独立输入验收。
3. 点击创建五分屏会新建唯一名称的场景，不覆盖既有场景。按当前 OBS canvas base size 布局为 3×2 网格、末格留空，画面保持比例并居中在每格内。先验证全部输入再变更；scene item 创建失败会移除新建的半成品场景。Studio Mode 只选到 **Preview**，TAKE 仍由用户决定；非 Studio Mode 选择当前 Scene。
4. Program 按钮调用 OBS 原生 `StudioProgram` projector；可在 OBS 原生窗口菜单中选择屏幕/管理投影。它既不 capture/canvas 回读画面，也不借用浏览器播放。多投影的源/解码器稳定性仍需实际 Windows 观测，不能由此代码结构替代验收。

原生 OBS UI 有英文开发提示。当前 dock 没有 PTZ、收藏/锁定、告警、摄像头目录、分享、录像迁移、审核/权限或后端管理能力；请参照主计划和执行台账逐项迁移，不静默删功能。

## 跨平台可验证范围

在有 C++17 编译器、CMake/Ninja 和 SIMDe headers 的 Linux 环境可运行：

```sh
python -B native-host/tests/test_build_contract.py
cmake -S native-host -B build/native-host-contract -G Ninja \
  -DWEBOBS_NATIVE_BUILD_PLUGIN=OFF -DWEBOBS_NATIVE_BUILD_TESTS=ON
cmake --build build/native-host-contract
ctest --test-dir build/native-host-contract --output-on-failure
```

C++ 测试包含实际固定 OBS 32.1.2 headers，只用记录操作的 API doubles 执行验证，不链接其他版本的 system libobs，也不模拟媒体验收。覆盖源身份/引用释放、重复槽位复用、缺失/删除/错误类型输入、canvas 校验、唯一场景名、奇数 canvas 网格、部分失败回滚和 Studio Preview/Program 语义。Python 覆盖共享缓存 SHA-256/离线拒绝、真实 dependency lock 对齐、Git tracked 快照与篡改拒绝、缺失 Qt/插件运行时拒绝、portable 数据保护和脚本架构边界。

本地合同测试本身不能证明 Qt DLL/MSVC 链接或 UI 加载；Fedora 实现环境没有 PowerShell/Windows/Qt SDK。后续独立 Windows CI 已实际完成固定 OBS/frontend/plugin 编译和隔离启动烟测： [41180501363](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/41180501363)、[41182986553](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/41182986553)。这些运行验证 Qt 6.8.3、产品 dock/Media Source 注册、portable 配置、原 OBS profile 未变与正常退出，**不是最终媒体像素、实机硬解或 P5 性能验收**。

独立 Windows 工作流现在还会把冻结的 `WebOBS-OBS-native-<dev>-windows-x64-PROTOTYPE.zip` 解压到干净临时目录，再对解压树执行同一套“全新创建 + 复用”双启动烟测，并拒绝任何 `config/` 目录泄漏。这验证的是可下载压缩包自包含且能解压运行，仍不是安装器、升级、最终像素、实机硬解或 P5 性能验收。

### Windows 实际启动烟测（需图形桌面）

构建完成后、尚未运行过的新 `runtime` 可执行：

```powershell
python -B native-host/tests/smoke_windows.py --runtime '<buildroot>/runtime' --result '<buildroot>/native-startup-smoke.json'
# 或构建时显式要求烟测（不会打包/发布）：
pwsh -NoProfile -File desktop/scripts/build-obs-native.ps1 -Version 0.1.0-dev.4 -SmokeTest
```

烟测调用真正的启动器，故意注入错误 OBS/Qt plugin 路径以验证子进程清除环境；仅在全新 profile 中设置跳过 OBS 首启向导，不创建任何摄像头或默认音频输入。实际产品插件收到 `FINISHED_LOADING` 后，确认从 `obs_module_config_path` 取得的配置根严格位于 bundle portable 目录，再写固定回执并排队关闭原生主窗口，走 OBS 正常保存/退出。启动器仅在显式烟测参数下设定 90 秒截止时间，超时只结束它刚创建的子进程。正常开发启动会删除继承的烟测环境开关，不会自动关闭窗口。

脚本对 `%APPDATA%/obs-studio` 做有界私密哈希前后比较（不导出内容）；若有并发 OBS 写入会安全失败，请在独立测试账号运行。公开的 summary 仅包含版本与布尔结果，不含 token、完整路径或日志。这个回执证明的上限是 Qt/plugin 实际加载、Media Source 类型注册、一次 portable 配置与正常退出，**不是五分屏/摄像头/解码/像素/性能或迁移验收**。

烟测后 `runtime/config` 是可丢弃私密测试数据。若需上传 CI 原型，必须在烟测前归档干净 runtime，之后只上传先前归档、构建身份清单和脱敏 summary；不要上传生成的配置目录或 OBS 日志，也不自动删除已有配置来重跑烟测。

## 有限最终像素测试构建（不可发布）

`-PixelTest` 与 `-SmokeTest` 互斥，默认关闭。仅在新的独立构建目录使用：

```powershell
pwsh -NoProfile -File desktop/scripts/build-obs-native.ps1 -Version 0.1.0-dev.5 -BuildDirectory 'D:\\WebOBS Pixel Test\\run-5' -PixelTest
```

该开关编译仅测试专用的有限 harness，标记运行时 `pixelTestBuild=true` / `redistributable=false`，随后**自动运行一次**真实 Windows 图形测试，不能再次复用生成的私密配置。不得公开归档或发布此运行时、配置、日志、句柄或截图；CI 仅保留 `<BuildDirectory>/native-final-pixels.json` 脱敏合成回执。正常原型仍不编译这个入口，未增加生产截图/HTTP/任意媒体路径接口。

在全新 portable profile 中，以一次性 token 和固定阶段协议检查：五色场景、五个独立本地 HEVC 图案、真实产品五分屏 A/B、Studio Preview 不隐式 TAKE、显式 TAKE、Program 投影确实销毁后重开与正常退出。每阶段分别识别**真实主 UI Preview**与原生 **StudioProgram projector** 的所属 HWND，校验 PID/可执行路径/创建时间/遮挡后，仅采集测试自有客户区。每角色保留并检查全部八张样本的五路身份、位置、方向与时间码，不以回调、PLAYING 或一次亮图接受黑帧；全局包含 private sources 的媒体计数仍为五，原 UUID/对象/settings 不变，活动 encoder/output 与 raw-video consumer 为零。

本地 `python -B native-host/tests/test_pixels.py` 仅验证协议/图案 predicate/负例；不代表 Windows Qt/Win32 执行成功。新增 harness 的首轮 Windows 编译/像素结果须另行记录。此固定夹具为 320×180、无 B 帧、软件解码的本地 HEVC，主 Preview inset 只覆盖固定源码的 100% DPI；**不资格化真实摄像机、RTSP、逐路硬解、DPI/多显示器、P2 性能、P3 迁移或完整产品**。不能把测试代码存在或合成 PASS 扩大为这些结论。

## 必须完成的 Windows 验证

- 用上面的独立脚本在 Windows x64 完成固定 OBS/frontend/plugin build、CMake/CTest、PowerShell 执行、Qt platform plugin 和产品 dock 加载；保留完整 dependency/体积 receipt。检查上游与现有构建工作流未变。
- 在已有用户 OBS 和已有 Electron 用户数据的机器验证 portable 启动/退出/再启动，仅改独立 profile；改变工作目录及外部 OBS/Qt 环境变量不能越界。只读目录、异常退出、并发实例和非 ASCII 路径应给出安全失败，不丢私密数据。
- 用真实五路固定 H.265 摄像头验证 Media Source 本身的 native 解码配置、五分屏、布局切换、Preview/Program TAKE、两个固定显示器的 native projectors、重连/休眠/恢复，并观察输入/source/decoder 数量不因布局/投影而增长；记录 main/投影 UI resize、快切和异常退出。
- 使用独立固定编码图案/像素采样和实际 native projector 截图，做与同版本纯 OBS 一致条件的渲染/色彩/画幅检查；在 main+projectors 均打开的真实本地监控场景做 CPU/GPU A/B。API doubles 和静态配置都不算摄像头、像素或硬件证据。
- P3 的认证/Origin/RBAC、私密配置、按需服务/Job Object、旧功能等价、迁移备份/回滚和 P4 的 NSIS 安装/升级/稳定 feed 门槛全部达成前，保持此入口为 non-default development-only，不能替换兼容产品或公开发布。

## 文件与许可

产品源码/构建帮助器全在本目录与独立 `desktop/scripts/build-obs-native.ps1`，遵循仓库 GPL-2.0-or-later。OBS 上游及嵌套依赖保留各自原始许可；未对 upstream checkout 打补丁。参见 `LICENSE`、`obs/obs-studio/COPYING` 与 `desktop/dependencies.lock.json`。
