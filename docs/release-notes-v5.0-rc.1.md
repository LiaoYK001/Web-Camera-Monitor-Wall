# WebOBS Wall v5.0.0-rc.1 完整融合候选 / Complete Windows fusion candidate

状态：**预发布完整候选，等待目标机集中验收**。不是稳定版，不进入 Latest，不打开稳定更新 feed，不改变 v4.5 已发布预览及其附件。
Status: **pre-release complete candidate pending concentrated target-machine acceptance**. It is not a stable release, is not marked Latest, does not open the stable updater feed, and does not change the published v4.5 preview or its assets.

## 下载 / Download

- 安装包 / Installer: [WebOBS-Wall-5.0.0-rc.1-windows-x64-SETUP.exe](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/releases/download/v5.0.0-rc.1/WebOBS-Wall-5.0.0-rc.1-windows-x64-SETUP.exe)
- 更新元数据 / Update metadata: [latest.yml](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/releases/download/v5.0.0-rc.1/latest.yml)
- 校验和 / Checksums: [SHA256SUMS.txt](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/releases/download/v5.0.0-rc.1/SHA256SUMS.txt)
- 验收摘要 / Verification summary: [webobs-v5.0.0-rc.1-verification.json](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/releases/download/v5.0.0-rc.1/webobs-v5.0.0-rc.1-verification.json)
- 来源清单 / Source manifest: [webobs-v5.0.0-rc.1-source-manifest.json](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/releases/download/v5.0.0-rc.1/webobs-v5.0.0-rc.1-source-manifest.json)
- 候选 SBOM: [webobs-wall-5.0.0-rc.1-sbom.cdx.json](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/releases/download/v5.0.0-rc.1/webobs-wall-5.0.0-rc.1-sbom.cdx.json)
- 安装后数据目录 / Installed data root: `%LOCALAPPDATA%\WebOBS\Native`
- 安装目录 / Install root: `%LOCALAPPDATA%\Programs\WebOBS Wall`

## 交付内容 / What is included

- 单一 `WebOBS Wall` Windows x64 未签名 NSIS 安装入口，独立于 v4.5 `NativePreview` 和旧 WebOBS。
- 原生 OBS/Qt 媒体宿主：认证账号、可变 1–64 路有界快捷墙、保存的 Studio 场景、Preview/Program、真实 cut/fade TAKE、Program 回执和固定/Program 投影。
- 同机完整服务：events、NVR、v2 客户端、go2rtc、backup 和产品控制面；MediaMTX/转码不会因普通本地监看而无需求启动。
- 录像与存储管理页：从现有摄像机目录选择连续/事件录制，设置分段、保留和容量，查看实际录制状态；NVR 实际录制、时间线、鉴权 MP4 播放和导出入口。
- 事件中心：持久事件、去重、移动区/规则和持久通知 outbox；真实服务回归覆盖事件创建、规则路由和 outbox 持久化。
- 网站与直播源：完整包内置锁定 yt-dlp、Streamlink、Node/EJS 和 FFmpeg，启动前后自检；普通 RTSP/本地监看不依赖该解析器。
- 旧数据导入：显式读取旧 WebOBS 4.x 配置或 v4.5 `NativePreview`，通过 SQLite backup API 保留账号/相机/Scene/Studio/密钥/录像引用，支持账号绑定工作区迁移，拒绝覆盖和损坏输入。
- 原生更新检查、下载、大小/SHA-512 校验、用户确认安装、更新前备份和失败保留；Start Menu 提供主程序、旧数据导入、检查更新和恢复备份入口。
- 卸载保留数据目录、录像和未知用户文件；安装前/后已通过隔离临时目录、Unicode 路径和同机覆盖升级验证。

A single unsigned Windows x64 installer, an OBS/Qt-native media host with authenticated bounded 1–64 wall, saved Studio scenes, real Preview/Program TAKE and projectors, complete same-machine business services, NVR/storage configuration and authenticated recording, events and durable outbox, bundled online-source tooling, explicit old-data/v4.5 migration, native update verification and data-retaining lifecycle gates.

## 验证 / Verification

- **Windows 完整候选运行 / Full Windows candidate run:** [43956468003](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/43956468003) — **success**
- **源码/构建身份 / Source identity:** `8828532c60648f52fae9bee222fa41b80beee7ab`
- **安装包 / Installer:** `WebOBS-Wall-5.0.0-rc.1-windows-x64-SETUP.exe`
  - size: **212,117,618 bytes**
  - SHA-256: `3d16014dab7700e6bc4f73c5c0bfba5700382c78fb3f24041589b58a4e67016c`
  - SHA-512 (base64): `GQaVEz2p2j6dvD4JT/sD/YtkjKIZ0VtTsA6n3hI2PorrdZS2+/xRDKzwh/JmRqMFCtw9yApJzJwoYL70LYfItA==`
- **实际产物回执 / Actual receipts:** portable product UI **52/52 checks**, installed product UI **52/52**, restore isolation **9/9**, real NVR recording + authenticated MP4, event dedupe/durable outbox, online-extractor self-test, TAKE Program final pixels, fixed/Program projectors, account-scope revocation, normal close, restart, password change and launcher-crash cleanup.
- **安装/升级/卸载 / Installer lifecycle:** fresh NSIS pass, same-machine `5.0.0-rc.1 → 5.0.0-rc.2` upgrade pass, profile bytes preserved, uninstall retains profile/recordings and unknown file, application registry/shortcuts removed.
- **安装树 / Installed tree before first start:** **794,551,075 logical bytes / 806,587,720 allocation bytes**, 6,972 files and 956 directories. This includes the complete business services and online-source runtime, not just the native monitor preview.
- **更新元数据 / Update metadata:** `latest.yml` size and SHA-512 bind exactly to the installer bytes above; the build is pre-release, not Latest and not a stable update feed.

上述是 GitHub-hosted Windows runner 上的实际源码构建、产品启动、媒体/服务、NSIS 安装和覆盖升级证据；不是目标机真实相机、逐路硬解或 OBS 同条件性能证明。
These are actual source-built, launched-product, media/service, NSIS installation and in-place upgrade receipts on a GitHub-hosted Windows runner; they are not target-machine camera, per-stream hardware-decode or same-condition OBS performance qualification.

## 已知缺口 / Known limits

- 目标机真实摄像机的五路动态画面、物理多屏/DPI、实际音频设备、逐路硬解和两小时长稳仍需集中验收。
- 尚未以用户本人的旧稳定版/旧开发版档案完成实际迁移；`fullFeatureMigrationQualified` 仍为 false。旧 DPAPI 备份密钥迁移为尽力而为。
- 本候选仍不是完整 24 项 OBS 业务等价的证明：非空逐轨音频、OBS 合成录像/推流输出、LAN/Caddy 远端入口和部分分析叠层的最终像素/设备证据仍需后续关闭。
- 更新入口是安装后的“检查更新”快捷方式，不是应用内后台自动更新；候选 feed 固定指向本候选 Tag，不提供稳定 feed。
- 安装包未做 Authenticode 签名；不宣称发布者身份。
- v4.5 保持历史预览，不因本候选而恢复 Android/容器同步或稳定发布。

The target-machine five-camera run, physical multi-monitor/DPI, real audio devices, per-stream hardware decode and two-hour stability remain for concentrated acceptance. The user's own old-stable/old-dev profile has not yet been migrated in a real run; `fullFeatureMigrationQualified` remains false. Nonempty multi-track audio, OBS composite recording/streaming outputs, LAN/Caddy remote access and some analytics overlays still need later closure. The updater is a user-run shortcut, not in-app background auto-update; this candidate is not a 24-item OBS-equivalence claim.

## 安装与集中验收 / Install and concentrated acceptance

1. 完全退出旧 WebOBS、v4.5 和任何 WebOBS Wall 进程；保留旧安装及数据。
2. 运行上述安装包，使用默认或独立安装目录；首次启动前可运行 Start Menu 的“导入旧版 WebOBS 数据”，选择旧 4.x 或 v4.5 NativePreview 来源。导入目标必须为空，旧文件只读保留。
3. 登录原账号，核对账号、角色/相机授权、设备/Profile、Scene/Studio、布局和录像目录；先不要删除旧安装。
4. 验证五路真实摄像机、Preview/Program/TAKE、固定/Program 投影、NVR 时间线、事件和 go2rtc/网站源；再做正常退出、重启和托盘/后台任务。
5. 用“检查更新”验证 update 下载/校验/确认安装，再复核覆盖升级后账号和数据。
6. 完成后反馈：实际 Windows 版本、显卡/驱动、摄像机编码/分辨率/FPS/音频、逐路硬解、安装/升级/迁移结果、两小时显示稳定性及必要的失败日志（脱敏，不发送密码/Token/摄像机 URL）。

Do not delete the old installation before verifying the migrated account, scenes, permissions and recordings. The target-machine acceptance should cover real cameras, physical displays/DPI, audio, hardware decode, two-hour stability and the saved-data upgrade path.
