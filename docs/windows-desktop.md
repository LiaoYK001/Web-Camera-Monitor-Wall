# 完整 Windows 桌面客户端（阶段一）

网站/直播源运行包新增锁定的 yt-dlp、Streamlink、Node/EJS；固定 `webobs-online-source.exe` 和解析/转发后代使用 Job Object，文件进入 manifest、许可证和 SBOM，日常运行无需开发 PATH。接入、Cookie 与验证见[网站与直播源](online-sources.md)。Windows x64、容器、Android 按 `vA.B` 更新；后续 Windows ARM/32 位和原生 Linux x86/ARM 通常在 `vA.0` 大版本节点构建、验收和发布。Bundled website tools follow complete package updates; future architectures remain major-milestone targets, not qualified platforms.

`desktop/` 是 Electron 安装版，和 `clients/` 中的 Qt 客户端分别构建。Docker/Podman 仍使用现有镜像。Windows 安装版包含原生 C++ 后端、libobs/D3D11 与来源插件、Python 3.12、go2rtc、MediaMTX、FFmpeg、OpenSSL、Caddy 和 WebUI；日常运行无需 Docker、WSL、系统 Python 或系统 PATH。

## 当前可下载版本

[v3.5 Release](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/releases/tag/v3.5) 已于 2026-10-02 附带 [Windows x64 安装包](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/releases/download/v3.5/WebOBS-3.5.0-windows-x64-UNSIGNED.exe)。版本为 `3.5.0 UNSIGNED`，按维护者选择暂不签名；完整正式自动更新已启用，附带 `latest.yml` 与 blockmap。v3.4 开发版需手动安装 v3.5 一次，此后可使用内置更新。摘要与验证边界见 [v3.5 发布说明](release-notes-v3.5.md)。

## 默认行为

系统设置中的“关于与更新”显示 Electron 实际安装版本、Windows x64 运行方式与 WebUI 构建号，并提供 GitHub 源码、Release、问题反馈、使用说明和 GPL 许可证入口。客户端可手动检查更新，查看最近成功检查时间、下载进度与纯文本发布说明，下载完成后选择“重启更新”。浏览器/PWA 的“检查页面更新”仅检查当前服务器的 Service Worker，服务器镜像仍由部署维护者更新。开发包显示开发通道说明，不连接正式更新源。

The Settings “About and updates” card displays the actual Electron installation version, Windows x64 runtime and WebUI build, with source, Releases, issues, documentation and GPL links. Desktop users can check updates manually, see the last successful check, download progress and plain-text release notes, then explicitly restart to install. The browser/PWA button checks only its current server's Service Worker; maintainers still update the server image. Development packages remain outside the stable updater feed.

- 自动检查正式更新，启动时一次，此后每 6 小时检查；默认自动下载。
- 下载完成后用户选择“重启更新”才安装，退出应用不自动安装。
- 主窗口关闭进入托盘；投影与服务保留。“退出并停止服务”正常停服并收束 Windows Job Object 中的后代。
- 开机启动和局域网共享默认关闭。
- 桌面页面禁用 Service Worker/PWA 更新缓存；浏览器仍保留现有 PWA 流程。
- 声音、场景和弱网设置继续使用同一本机后端中的账号偏好。桌面窗口共用持久会话；局域网浏览器独立登录后使用同账号偏好。

## 构建完整安装包

`pnpm --dir desktop test:runtime` 还检查真实认证代理下的两个签名设备配对、多音轨 schema-v6 保存、重复提交幂等、冲突与正常重启后保留。来源为未激活的合成 Camera，仅验证配置与控制链，不代表真实摄像机音频播放或干净系统安装验收。

`pnpm --dir desktop test:main` also exercises the packaged Settings pairing UI, actual signed/encrypted browser grant, device layout upload/reload and explicit copying to server Preview without changing Program. The subsequent fixed projectors, shared session, tray hide and normal shutdown still run. See [offline workspaces](offline-workspace.md); this is UI/control validation, not physical camera, clean-install or multi-device media qualification.

`pnpm --dir desktop test:main` 还操作打包后的设置配对界面，验证真实签名加密授权、设备布局上传/刷新及明确复制到服务器 Preview，同时保留 Program；随后继续检查固定投影、共享会话、托盘隐藏和正常退出。详见[离线工作区](offline-workspace.md)，这是 UI/控制链验证，不代替真实摄像机、干净安装或多设备媒体验收。

The native runtime test also covers two signed device enrollments through the real authentication proxy, schema-v6 multi-track persistence, idempotent retries, conflicts and normal service restart. Its synthetic Camera is never activated; this qualifies the configuration/control path, not camera audio playback or clean-system installation.

The main-entry gate also stores a synthetic 1000-source preference workspace, adjusts volume through the actual monitor UI, verifies a small keepalive request, and applies a global telemetry change through the actual authenticated backend. Both operations must retain unrelated source settings. It restores the original fixture preferences before continuing projectors/tray tests. This check requires the current WebUI and cluster service; it does not activate 1000 camera streams.

主入口门槛还保存合成的 1000 路来源偏好，通过真实监控 UI 调整音量并验证小型保活请求，再经真实认证后端全局调整统计叠层；两者均须保留其他逐路设置。随后恢复原夹具偏好再检查投影和托盘。此项需要当前 WebUI 与 cluster 服务，不会启动 1000 路摄像机流。

The main-entry gate also accepts `constructor` and `__proto__` as real Scene source identifiers, renders each color source and verifies account preference save/reload without losing its own decorations. It restores the original Scene and account preferences before continuing desktop lifecycle checks. Linux production validation separately decodes a synthetic H.264 source using those identifiers; neither check qualifies physical cameras.

主入口门槛还通过实际 Scene 接口接受 `constructor` 和 `__proto__` 来源，显示色块并验证账号偏好保存/刷新后保留自己的外观记录；随后恢复原 Scene 和账号偏好继续桌面生命周期检查。Linux 生产验证另行使用这些标识解码合成 H.264；两者均不代表真实摄像机验收。

The same gate also loads 1000 account audio records with the visible source last, checks its saved volume/mute/monitoring, and verifies that master-volume save/reload retains every record. It uses the authenticated Program API and checks that Studio definitions stay unchanged. Color source audio controls remain disabled; this validates preference restoration rather than physical audio playback.

同一门槛还将显示中的来源放在 1000 路账号声音记录末尾，检查其音量、静音与监听，并确认主音量保存/刷新保留全部记录。通过认证的 Program 接口准备画面，同时检查 Studio 定义保持原样。色块声音控件仍禁用；此项验证偏好恢复，不代表实际音频播放。

开发构建机需要 VS 2022 的 MSVC x64、Windows SDK、CMake >= 3.28、Python、Node 24 和 pnpm 11.16.0。使用 PowerShell 7.2+ 的 VS x64 Developer PowerShell：

```powershell
./desktop/scripts/build-windows.ps1 -Version 3.4.0-dev.0
# 正式候选（稳定 X.Y.Z 必须显式 -Release；v4+ 沿用已审查的 v4-M1 门禁）
./desktop/scripts/build-windows.ps1 -Version 4.0.0 -Milestone v4-M1 -Release
```

稳定候选的版本、门禁与已知限制见 [v4.0 发布说明（草案）](release-notes-v4.0.md)；`Release` 与 `-dev.*` 两类互斥，脚本会在任何下载或编译之前拒绝不匹配的组合。

缓存与构建在仓库所在磁盘的 `desktop/.cache` 与 `build/desktop-windows`。固定依赖来自 `desktop/dependencies.lock.json`；vcpkg 固定提交和 baseline。上游 OBS 构建在副本中，原 submodule 不变。构建、C++/桌面测试、完整运行目录校验通过后，NSIS 完整安装包位于 `desktop/out/<版本>`，随包包含所需 VC++ 运行库。不同版本输出分目录保存。

固定版本的 obs-browser 在关闭 Qt 面板时仍包含原生 Qt tooltip 调用。`prepare-obs-headless.py` 仅修改隔离的构建副本，移除该原生 tooltip 和对应无条件 Qt 头文件，保留 CEF 浏览器来源与网页自身的交互；上游 submodule 不变。

正式构建默认不签名，生成 `WebOBS-X.Y.Z-windows-x64-UNSIGNED.exe`、blockmap 和 `latest.yml`，启用完整 GitHub Release 自动更新。开发 `-dev.*` 包仍为 `DEVELOPMENT-UNSIGNED`，不连接正式更新源。正式未签名构建：

```powershell
./desktop/scripts/build-windows.ps1 -Version 3.5.0 -Release
```

受信任 CA 与微软 Azure Artifact Signing 的申请区别、地区限制及当前构建入口的凭据配置见 [Windows 代码签名](windows-signing.md)。

开发构建仅生成 `dev.yml`，正式构建生成 `latest.yml`。未签名构建不配置发布者或 Authenticode 更新校验，仍验证完整安装包的 SHA-512 和大小，并在停服、复制与启动安装前再次校验；安装需用户确认。若以后显式选择 `-Sign`，electron-builder 签名主程序与 NSIS 安装包，排除已纳入运行文件摘要的嵌套 `.exe`，并启用发布者验证。保留捆绑组件原有签名，打包后再次验证完整运行目录。

可选签名过滤器明确包含 `WebOBS.exe`、当前版本 NSIS 安装器和卸载器，再排除其他 `.exe`，并通过固定 electron-builder 的实际过滤实现回归。仅显式签名构建强制签名，打包后再次检查主程序发布者。

```powershell
$env:CSC_LINK = '签名证书路径或维护者配置的凭据'
$env:CSC_KEY_PASSWORD = '通过私密环境设置，不写入仓库'
$env:WEBOBS_SIGNING_PUBLISHER = '证书中的正式发布者名称'
./desktop/scripts/build-windows.ps1 -Version 3.5.0 -Release -Sign
```

GitHub `Build full Windows desktop` 是手动候选构建，不发布 Release。也可在现有 `Web runtime public CI` 手动选择 `windows_desktop`，从 dev 分支执行无签名候选。编译机测试不等于 Windows 10/11 实际安装及摄像机验收。

## 服务、端口与数据

桌面主进程按 MediaMTX、go2rtc、账号与设备/事件/NVR 服务、备份服务、C++ 控制端的顺序启动，逐项健康检查。配置了归档才启动 S3 服务。分析与集群节点工具随包提供，仍受现有配置和授权控制。

主控制入口固定 `http://127.0.0.1:18080`，内部端口首次分配后保存在 `ports.json`；冲突报错，不结束其他应用。受认证的 `/api/v1/runtime/info` 返回平台与 go2rtc 建档地址，设备导入使用该地址。服务 URL 的环境映射在根目录 `runtime_support.py` 与 C++ `platform_runtime` 中保持一致。

Windows v4.0 存在 go2rtc 保存配置后未重载的问题，临时处理、`dev` 修复及测试候选状态见[配置重载说明](go2rtc-config-reload.md)。Published Windows v4.0 has a known configuration reload issue; see the linked workaround and development fix status.

go2rtc WebRTC 首次分配先请求系统可用的 UDP 端口，再保留同端口的 TCP；任一协议冲突/受限时关闭本次候选并尝试新端口，最多 16 次。这样避免 TCP 自动端口落入 Windows UDP 保留区。已保存的端口不自动更改；冲突保留原诊断，且不会关闭其他端口占用者。其他失败仍直接报告。

First-use go2rtc WebRTC allocation asks the OS for an available UDP port, then reserves matching TCP. A conflicting/restricted protocol releases the candidate and tries again, at most 16 times, avoiding TCP automatic choices in Windows UDP exclusions. Saved ports never migrate automatically: conflicts retain actionable diagnostics and other owners stay untouched. Other failures are reported immediately.

同步 CommonJS 启动入口在 Electron ready 之前配置用户与会话目录，然后加载桌面模块，避免打包入口等待 ready 时阻塞启动。模块导入失败会保存 `logs/desktop-startup.log` 并显示日志位置；成功启动也保留简短启动记录。

私密启动日志还记录诊断窗口、运行清单校验与服务启动阶段及有界错误。低性能 CPU 启动时，首次建账和密码校验可等待最多 10 秒；账号服务超时/不可用返回 503，不误报密码错误，错误密码和限流仍分别返回 401/429。Private startup diagnostics record initialization stages. Password operations have a bounded 10-second budget; account outages return 503, while invalid credentials/rate limits remain 401/429.

配置、账号数据库、密钥、桌面设置与浏览器会话位于 `%LOCALAPPDATA%\WebOBS`。私密目录仅当前 Windows 用户访问，备份主密钥由 Electron safeStorage/Windows DPAPI 保护；客户端授权签名密钥也使用 DPAPI。运行期间备份进程使用私密 `run` 目录中的临时密钥，停服删除。录像默认位于用户 Videos 下的 WebOBS，可在设置中选择新目录；已有录像不会自动移动。

Windows 写入授权密钥使用二进制文件模式，避免 CRT 把随机密文中的换行字节改写为 CRLF。回归测试同时检查实际文件字节与重新载入后的密钥身份。

私密目录已属于当前用户时，只设置受保护的 DACL，不重复申请更改所有者。这样拥有“修改”权限的 D 盘目录也可正常初始化；需要修复其他所有者时仍要求实际权限，不静默忽略拒绝访问。

OBS 使用 D3D11，外部 FFmpeg 与 OBS 插件能力分别实测。CUDA 设备与驱动通过 Windows CUDA API 检测，NVENC/QSV 编解码以限时样本探测为准；没有通过探测的硬件不会报告为就绪。部分 Linux 专用指标在 Windows 显示不可读取。

Windows 工具保留固定原生入口；需要导入 Python 实现的 S3 备份和分析任务使用包内固定源码路径，避免把 `.exe` 当作 Python 模块读取。运行文件清单、SBOM 与许可证同时覆盖 WebUI、go2rtc 页面依赖和 Electron/Chromium。

## 投影、局域网与备份恢复

Scene 右键菜单可打开不同固定 Scene 的独立投影，选择显示器与全屏，Esc 退出全屏。关闭主窗口不会关闭投影。同 Scene、模式和显示器组合复用其窗口。

系统设置中的 Windows 客户端区提供更新开关、托盘、开机启动、录像目录、局域网设置与服务重启。共享开启后，Caddy 只监听私有 IPv4 地址，生成内部 CA，禁止自动修改系统证书信任。UI 列出 HTTPS 地址、根证书路径与当前用户信任步骤，并列出管理员可自行执行的 Private / LocalSubnet 防火墙命令，涵盖产品和 go2rtc WebRTC 的媒体端口。其他局域网电脑只复制 `root.crt` 公钥证书，按界面步骤导入当前用户的受信任根证书存储；不分发 CA 私钥或整个数据目录。go2rtc 仅在共享开启时提供局域网 ICE 地址；上游管理端口保持 loopback，所有管理请求经过产品认证代理。共享和录像目录设置在重启服务后生效。

Caddy 运行配置由主进程保存，关闭其默认配置 autosave，避免在 `%APPDATA%\Caddy` 额外写入产品配置。

“创建完整配置备份”暂时正常停服，创建一致性快照和加密 `.wobk` 备份，然后恢复运行。录像媒体不复制进配置备份。Docker/WSL 数据通过“从备份恢复”明确选择 `.wobk` 及原始 32 字节密钥导入，先保存当前数据快照，不自动搬移部署。含绝对路径的外部来源、存储卷和 Secret 引用需在恢复后改为本机路径；它们不会被猜测或静默重写。

更新安装检查草稿、前端导出和后端证据导出；存在未保存/未完成工作时暂停。录像/媒体仍运行时用户明确选择停止任务并更新。更新前正常停服、创建配置和 NVR 目录数据库快照，记录版本与快照映射。启动失败显示诊断和恢复入口：先安装对应旧版本，再恢复匹配快照。首次手动安装没有缓存旧包时，从相应 Release 下载对应安装包；之后更新保留已安装版本的安装包。恢复包路径与 SHA-256 必须匹配升级记录，只有显式签名发行版额外验证发布者。损坏快照不会激活。

GitHub 检测和下载使用 electron-updater。显式安装等待 Windows 确认已启动经过二次摘要及可选签名校验的完整 NSIS 包后才退出；异步启动失败会删除待升级标记并恢复当前服务。安装向导仍由用户操作，不申请提权回落。

NSIS 自定义初始化仅修改安装器及其子进程的 TEMP/TMP：在现有安装目录所在盘创建私密临时目录，供旧卸载器原子移动旧程序文件，避免跨盘 rename 失败。完成后仅删除该空临时目录，不递归删除未知路径，不修改系统环境变量；账号、录像与快照仍在独立数据目录。

### WebUI 设置细节 / WebUI settings details

首次启动的 go2rtc WebRTC 端口必须同时可绑定 TCP 与 UDP。系统自动选择的 UDP 端口若落入 Windows 的 TCP 保留范围，最多 16 次重试会分散选择 1024–65535 内的候选，并释放失败的占位端口；不会停止其他应用。已保存的端口冲突仍明确报错，不自动迁移。

First-use go2rtc WebRTC allocation reserves both TCP and UDP. After an OS-selected UDP port conflicts with TCP, bounded retries spread candidates across user ports and release failed leases. Saved conflicts remain explicit and never silently replace persisted ports or stop other applications.

客户端开关立即保存，并在执行中锁定输入。局域网 HTTPS 端口先填写，再点击“保存端口”；支持 1024–65535 的整数，错误或未保存的输入不会改变实际端口。未保存端口可以撤销，保存后再点击“应用并重启服务”。状态事件优先于较早发起的读取结果，其他状态变化不会覆盖正在编辑的端口；读取失败提供重试入口。

Client toggles save immediately and lock inputs while running. Edit the LAN HTTPS port and click “保存端口” (Save port); valid integers are 1024–65535. Invalid or unsaved input never changes the actual port. Discard a draft or save before applying a service restart. Push events supersede older IPC reads and unrelated events preserve a port draft. Failed status reads offer retry.

“我的账号”区分读取错误和保存成功，保存时锁定表单，失败保留输入以便重试。昵称或头像未变时不重复提交；密码需要二次确认，并按 UTF-8 字节验证至少 16 字节。密码输入仅在本次页面内保留，成功更新后清空。离开页面会提醒未保存的输入，保存期间阻止切换；Windows 更新草稿检查也包含账号和端口草稿。账号的 WebUI 行为同样适用于普通浏览器及 Android 客户端。

“我的账号” (My account) distinguishes errors from success, locks forms during saves and preserves failed inputs for retry. Unchanged profiles do not submit. Password confirmation must match and the UTF-8 minimum is 16 bytes. Password inputs remain in the current page only and clear after success. Navigation protects drafts and pending saves; Windows update guards also include account and port drafts. Account behavior applies to browser and Android WebUI as well.

## 正式发布与验收

从 v4.0 起正式支持 `vA.B.C` 常规补丁（如 `4.0.1`、`4.0.2`），“关于与更新”显示修复补丁并按数字比较版本，拒绝相同/旧版及开发版；安装仍需确认、正常停服和快照。已有 updater 默认尝试 blockmap 差量，失败回退完整 NSIS 下载，完整包校验不变。小范围修改可减少传输，不保证固定包大小。详见[v4+ 补丁规则](patch-releases-v4.md)。当前重启修复留到 v4.0，不发布 v3.5 热修。

From v4.0, regular patches use A.B.C with numeric comparison and a patch label. Differential downloads retain full-installer fallback and integrity; explicit install/normal shutdown/snapshot safeguards apply equally. Real v4 installed patch upgrades remain a qualification item.

产品标签 `vX.Y` 对应客户端 `X.Y.0`，`vX.Y.Z` 对应 `X.Y.Z`。容器与 Windows 共用已审计的产品 Release。候选附件包含安装包、blockmap、`latest.yml`（仅正式包）、SHA-256 摘要、运行文件清单、CycloneDX SBOM 与许可证归档。Electron updater 校验 SHA-512 与大小，准备安装时再次校验；可选签名构建额外验证 Authenticode 发布者。客户端不包含 GitHub Token。

Windows 10、11 各自记录实际安装、媒体、LAN 与两版更新结果。`desktop/qualification.example.json` 只是格式示例，不能作为通过证明；完整检查名见 `desktop/scripts/qualification.mjs`。维护者还需收集匹配第三方二进制的完整对应源码（包括 FFmpeg 及其启用的 GPL 组件），提供已审核 `SOURCE-MANIFEST.json`，其字段为 `revision`、`version`、`reviewed: true`、`files: [{name, sha256}]`。

```powershell
./desktop/scripts/publish-release.ps1 -Tag v4.0 `
  -ArtifactDirectory 'D:/release/webobs-windows' `
  -QualificationReceipts 'D:/private/windows-qualification.json' `
  -CorrespondingThirdPartySourceDirectory 'D:/release/matching-third-party-sources'
```

发布器验证实际安装包摘要、版本、`latest.yml` 与源码身份，复用 `scripts/create-source-bundle.sh` 和 `scripts/upload-release-assets-immutable.sh`。默认允许明确标记 `UNSIGNED` 的正式包；显式签名包仍需匹配发布者。没有完整平台验收回执时，必须提供绑定安装包摘要的实际 `windows-install-smoke.json`，并在 Release 如实披露干净系统/摄像机等待验收项；主机冒烟检查不等于全平台验收。对应源码仍需审核。维护者发布机需要 Git Bash/gh；Token 仅用于附件上传。不要把开发包的元数据上传到正式更新源。

多端共用 Draft 时，发布器通过 `gh release view` 核对标签并取得数字 Release ID，再调用既有不可变上传接口；GitHub REST 按标签查询草稿可能返回 404，不能因此新建第二个 Release 或提前发布。已有不同内容的同名附件仍拒绝覆盖。For a shared Draft, the publisher resolves its numeric ID through `gh`, verifies the tag and uses the existing immutable ID-based uploader. A REST tag lookup returning 404 does not authorize a duplicate Release or early publication; conflicting attachment bytes remain rejected.

## 当前验证边界

已通过 Windows 原生 C++/OBS 编译与 CTest、完整 NSIS 开发包构建、桌面逻辑与真实 Electron 检查。本机 Windows 11 的捆绑服务已通过首个账号、认证 go2rtc、快照和重启后会话恢复；RTX 3060 Ti 实际通过 NVENC 样本探测及 OBS Program 编码。完整构建必须通过 `pnpm --dir desktop test:runtime` 和 `pnpm --dir desktop test:main`，后者使用真实桌面入口检查两个固定 Scene 投影、共享登录、关闭主窗口保留服务及正常退出。均使用临时数据目录，不覆盖真实摄像机。Windows 10/11 干净安装、真实摄像机播放与跨设备 LAN 仍须分别记录。v3.5 已验证本机两版真实未签名 NSIS 升级和公开 GitHub 下载；后续公开源两版安装及更新故障验收仍须记录；没有完成这些实际检查前，不宣称阶段一达到生产验收。

打包后还必须通过 `pnpm --dir desktop test:package`：启动真正的 `win-unpacked/WebOBS.exe`，验证 ASAR、生产依赖、独立账号和 go2rtc，并检查主进程异常退出后 Job 收束所有后代。本机另已验证真实 Caddy 的 HTTPS、显式 CA、认证与 go2rtc 代理；未修改系统信任和防火墙，不等于其他设备的浏览器及媒体验收。

完整构建还运行 `pnpm --dir desktop test:install`，实际执行当前版本的 NSIS 安装与卸载：使用包含中文及空格的独立安装目录、私密测试账号和独立录像目录，检查运行文件摘要、清空 PATH 后启动、认证 go2rtc、Job 清理、默认卸载保留数据，以及注册项和快捷方式清理。已有 WebOBS 注册项或快捷方式时拒绝运行，避免覆盖用户安装。通过后将系统版本、已测运行清单提交和安装包摘要写入 `desktop/out/<版本>/windows-install-smoke.json`；该检查不会更新正式验收记录，也不代替干净系统和两个签名版本的升级测试。本机 Windows 11 已通过该安装与卸载流程。

`pnpm --dir desktop test:updates` 使用真实 electron-updater 和本机小型协议夹具验证检测、下载、损坏摘要拒绝、重新校验和断网状态；不安装夹具。两版实际未签名 NSIS 包可通过 `pwsh desktop/tests/installed-update-smoke.ps1 -PreviousVersion <旧稳定版本> -Version <新稳定版本>` 进行隔离安装、真实完整包下载、确认调用、正常停服/快照、升级启动与账号数据保留检查。该检查使用本机更新源及静默测试安装器，不能冒充 GitHub 下载、交互向导或全平台验收；已有安装或快捷方式时拒绝运行。

跨版本检查使用旧安装包自身的完整性、服务和更新模块，在独立 Node 进程中提取后再启动测试，避免持有待替换的 ASAR。升级后执行当前完整校验并验证实际健康里程碑。下载三分钟、安装五分钟预算保持原值；`windows-upgrade-trace.json` 只记录阶段、时间和退出码，不包含账号、Cookie、配置或原始服务日志。手动 Windows 工作流的 `installed_upgrade` 路径只验证冻结的 v4.0 候选与已发布 v3.5，不重建或发布包；测试提交与安装包的源码提交分别记录。

Cross-version checks use the previous installed package's own integrity, supervisor and update modules, extracted in a separate Node process before testing so the harness does not keep the replaced ASAR open. The upgraded runtime receives the current full verification and actual health-milestone check. The three-minute download and five-minute install budgets stay unchanged. The bounded trace records only phases, timestamps and exit codes. The manual Windows workflow's `installed_upgrade` path qualifies the frozen v4.0 artifact against published v3.5 without rebuilding or publishing; tester and artifact revisions are recorded separately.

v4 adds the private `services/nvr/evidence.py` runtime contract. Export jobs and their owner remain in the recording catalog, so data snapshots preserve job history. Queued and active exports block update installation even after the archive page closes. `test:runtime` now uses bundled Python/FFmpeg to create synthetic H.264/AAC evidence, submit through the authenticated core and verify hashes and result restoration after restart. A newly compiled core is required for principal injection; host Python tests or an earlier EXE do not establish this Windows gate.

v4 新增私有 `services/nvr/evidence.py` 运行时契约。导出任务与账号归属保存在录像数据库中，数据快照包含任务历史；离开归档页后，排队和活动导出仍阻止更新安装。`test:runtime` 新增使用捆绑 Python/FFmpeg 生成合成 H.264/AAC 证据，通过认证核心提交，并检查摘要与重启后的结果恢复。身份注入需要重新编译核心，主机 Python 测试或旧 EXE 不代替这项 Windows 门禁。

The native evidence gate also streams a valid H.264/AAC MP4 larger than 64 MiB through the core with a bounded client hash reader, HEAD, Range, If-Range and ETag validation. A synthetic MP4 free box provides the file-size stress; it is not camera bitrate or decoder qualification. Large media uses a bounded asynchronous proxy rather than the control request pool, retaining the same account identity, permission checks and reader protection.

原生证据门禁另通过核心传输大于 64 MiB 的有效 H.264/AAC MP4，客户端按块计算摘要，并验证 HEAD、Range、If-Range 和 ETag。使用合成 MP4 free box 扩展文件大小，不冒充摄像机码率或解码器验收。大媒体采用有界异步代理，保留账号身份、权限与读保护，并与控制请求 worker 分离。
