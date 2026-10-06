# Android 应用内补丁更新 / Android in-app patch updates

Android 客户端在“菜单 → 关于与检查更新”管理完整 APK 更新。默认开启自动检查、自动下载与仅 Wi-Fi 下载，可分别关闭；安装始终需要用户及 Android 系统确认。页面仍从所连接的产品后端加载，APK 更新不代替后端升级。日常实现合入 `dev`，发布时才按[分支规则](versioning-and-branches.md)创建指定版本的 `dev` → `main` PR。

The native About dialog manages complete APK updates. Automatic checking, downloading and Wi-Fi-only downloading default to enabled and have independent switches. Installation requires user and system confirmation. The connected backend owns the WebUI and its services. Implementation goes to dev; release promotion is a separate versioned PR.

## 使用方式 / User flow

1. 首次前台运行检查公开 GitHub Release；此后以前台、跨重启保存的 6 小时间隔检查，也可手动检查。后台不运行客户端更新轮询。 / Check the public GitHub feed on the first foreground run and then at a persisted six-hour foreground interval, or check manually. No application polling runs in the background.
2. 显示当前 APK、更新类型、目标版本和发布说明。符合验证要求的较新正式 APK 按设置自动下载，或点“下载更新”。系统下载管理器负责网络等待、重试和通知；客户端回前台显示进度并校验。仅 Wi-Fi 设置在下一次下载生效，关闭自动下载不取消已开始的任务。 / Show current/target versions, update kind and notes. Download a verifiable newer APK automatically or manually. DownloadManager owns network waiting, retries and notifications. Foreground reconciliation shows progress and verifies completion. Network settings apply to the next download; disabling automatic downloads does not cancel an existing one.
3. 下载后可稍后安装，或“取消 / 删除已下载更新”。取消/失败会暂停该附件的自动重试，可再次手动下载；当前版本继续运行。进程退出后保存的系统任务可恢复。 / A verified download can wait or be cancelled/deleted. Cancellation/failure defers automatic retries of that attachment; manual retry remains available. Persisted system tasks can be reconciled after process restart.
4. 点“安装更新”。若未授权安装此来源，明确打开系统设置，返回后再点安装；不会自动继续。主页面及当前投影报告未保存草稿、保存/导出任务时阻止安装，保留已下载包。旧后端或离线页面不能报告状态时，要求用户自行确认已保存。 / Request installation permission only after clicking install. Returning from settings does not install automatically. Reported drafts or save/export tasks in the main page or projectors block installation. Older/offline pages require explicit confirmation that work was saved.
5. 确认后重新验证 APK，再交给系统安装器确认。相同 applicationId、持久自签密钥和递增版本码支持保留服务器地址、WebView 会话及偏好；Android 不停止远端监控、录像或导出服务。取消系统安装可继续使用当前客户端及已下载包。 / Reverify the APK and ask the system installer to confirm. The same package/key and an increasing versionCode retain local connection/session/preferences. Remote backend services continue independently. Cancelling system installation keeps the current app and download.

Android 本身要求 APK 有签名；这里使用仓库外保存的个人自签密钥，无需商业证书或商店账户。不得卸载现有客户端来掩盖密钥不匹配。开发 APK、不同签名、错误包名/版本或不递增版本码均拒绝自动安装。构建入口与版本码契约见 [Android 客户端](android-client.md)及[补丁规则](patch-releases-v4.md)。

Every APK requires an Android signature. Preserve the personal self-signed key outside Git; no commercial certificate/store account is required. Never uninstall to hide a key mismatch. Development APKs, wrong signers/packages/versions and non-increasing versionCodes are rejected.

## 下载与权限边界 / Download and permission boundaries

- 固定无认证 API 为 `https://api.github.com/repos/LiaoYK001/Web-Camera-Monitor-Wall/releases?per_page=20`。只选最近 20 个发布中最高的正式 Android APK；较新的纯后端发布不遮住它。草稿、预发布和降级排除。 / Use the fixed unauthenticated public endpoint and select the highest eligible APK from the latest 20 releases; backend-only releases do not hide it.
- 下载附件必须为精确的 `WebOBS-A.B.C-android-SELF-SIGNED.apk`、同仓库/Tag 的 HTTPS 附件 URL、`uploaded` 状态、非零且不超过 128 MiB 的声明大小和 GitHub `sha256:` digest。缺少验证信息时只显示对应发布页面供人工核对，不自动下载。GitHub 摘要与本地完整流式 SHA-256/字节数对照；安装身份与**实际已安装 APK** 的签名集合比对，而非信任发布说明中的证书。 / Require an exact product attachment URL/name, uploaded state, bounded declared size and GitHub SHA-256 digest. Missing metadata leaves a manual release-page fallback. Stream verification checks exact bytes/hash; signer identity comes from the installed app.
- Feed 限制 512 KiB；连接/读取超时各 8 秒，总体读取期限 20 秒，并在每次读取前后检查，单次阻塞读取可能额外等待至读取超时。APK 校验缓冲固定 64 KiB，位于原生工作线程，不阻塞 WebView。 / Bound feed allocation, connect/read waits and overall feed reading. A blocked read may extend beyond the overall deadline until its socket timeout. APK verification uses a fixed buffer off the UI thread.
- 系统下载保存到应用专属 Downloads；验证后原子移动到内部私密目录。前台观察超量下载会停止，复制验证有严格字节上限；后台系统下载不承诺硬性网络字节上限。Android/OEM 可能暂停或限制后台下载，回前台显示实际状态，不能将源码支持视为所有设备的续传保证。 / Use app-scoped system downloads and atomically publish the verified file in private storage. Foreground observation stops oversized transfers; copying is strictly bounded. OS background transfers are not a hard network-byte cap and OEM restrictions vary.
- 不发送产品 Cookie、认证头或 GitHub Token。未向页面开放 JavaScript 原生命令桥接、文件读写、任意下载 URL 或安装入口；原生代码只固定读取两项布尔工作状态，最多等待每页 3 秒。 / No product credentials/GitHub token accompany native downloads. There is no renderer command/file/download/install bridge; native preflight only reads two fixed Boolean flags with a per-page deadline.
- 非导出的 ContentProvider 只允许当前已验证摘要对应的单一 APK 只读 URI，临时授予系统安装器读取权限；拒绝其他路径、查询、旧摘要及写入。安装前再次完整校验，权限撤回或没有系统安装器时保留客户端可用状态。 / A non-exported provider grants only the current verified APK read URI to the installer. Unsafe paths/queries, stale hashes and writes are rejected. Reverify before installation and preserve usability on permission/installer failures.

相关平台契约见 [DownloadManager.Request](https://developer.android.com/reference/android/app/DownloadManager.Request)、[PackageManager](https://developer.android.com/reference/android/content/pm/PackageManager)、[ContentProvider](https://developer.android.com/reference/android/content/ContentProvider) 和 [GitHub Release assets](https://docs.github.com/en/rest/releases/assets)。 / These official references describe the platform/feed contracts.

## 实际升级验证 / Actual installed-update qualification

安装 WebUI 的 Playwright Android 驱动后运行： / Install the existing Playwright Android driver, then run:

```powershell
cd web
pnpm exec playwright install android
cd ..
python android/tests/test_update_install.py --serial 127.0.0.1:16384 --adb 'Q:\Program Files\Netease\MuMu\nx_main\adb.exe'
```

若 JDK 不在脚本默认路径，显式传 `--java-home '<JDK 17–23 目录>'`。先安装当前锁定 Playwright 的 Android 驱动；驱动缺失属于测试环境初始化失败，不能当作产品原生元素缺失。 / Pass `--java-home` when the JDK differs from the helper's default. Install the locked Playwright Android driver first; a missing driver is an environment initialization failure, not a product-selector failure.

此脚本要求显式设备，拒绝已有同名验收包；使用独立 `.updatequalification` applicationId、仓库外一次性自签密钥和私密回执目录。实际系统下载管理器与安装器运行 `4.0.0 → 4.0.1 → 4.0.2`，覆盖摘要/大小、不同签名/包名/版本、降级、丢失附件、取消、临时查询失败、丢失暂存包、进程重启恢复、安装权限及未保存草稿阻止、数据保留和只读 URI。仅测试 APK 的原生 transport 使用 ADB reverse 夹具；生产 APK 无端点覆盖入口。测试负责移除自己的包/reverse/一次性密钥，不清除或更新已有 WebOBS 包。

The helper refuses existing qualification installations and uses a separate application ID with ephemeral external keys. It exercises real system downloading and confirmed successive installation plus failure/recovery/retention checks. Only test transport uses an ADB-reversed fixture; product APKs have no endpoint override. Cleanup removes only owned test packages/reverse/keys, preserving the existing product installation.

回执保存在忽略目录 `build/android/update-qualification/<run>/result.json`，含平台、源码基线、工作树状态、APK 摘要及实际检查项；`--skip-build` 可复用该目录调试测试驱动，源码变更后须重新构建。隔离包/合成源的实测不等于公开 GitHub 更新源、生产包、实体摄像机或 Android ARM 真机的发布验收。完整边界仍由 [v4 验收](v4-readiness.md)跟踪；本实现不发布 APK、Tag 或 Release。

Private receipts identify the source baseline, working tree, artifact hashes, platform and completed checks. Cached APKs can debug the driver, but source changes require rebuilding. Isolated-package/synthetic qualification does not qualify the public feed, production package, cameras or physical ARM devices. No APK/tag/release publication occurs.

2026-10-05：MuMu Android 15 / API 35 x86_64 独立验收包通过完整脚本，包含实际系统下载、所有上述故障检查、进程退出恢复、安装权限拒绝及草稿阻止、系统确认的 `4.0.0 → 4.0.1 → 4.0.2`、两次覆盖后连接/偏好/WebView Cookie 保留及 APK 请求无产品 Cookie/认证头。构建的 release JUnit/lint/签名检查、WebUI 类型/构建及 4 项更新/草稿 Chromium 回归通过。使用一次性测试密钥及 ADB reverse，未触碰已有产品包，未发布稳定 APK 或修改公开更新源。前台 Wi-Fi 策略、真实断网续传、磁盘不足/文件占用、公开源和实体 ARM 设备仍需专项验收。

2026-10-05: The separate MuMu API 35 x86_64 package passed real system downloading, the listed failure/recovery checks, permission denial/draft blocking, confirmed successive installations, retention and credential-free APK requests. Release unit/lint/signature and four related Chromium checks passed. This used ephemeral test keys and synthetic transport; the existing product/public feed was unchanged. Wi-Fi policy, actual disconnected continuation, disk/full-file contention, public-feed and physical ARM qualification remain open.
