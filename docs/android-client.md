# Android WebUI 客户端 / Android WebUI client

第一版是连接现有 Windows、Docker 或 Podman 后端的 Android 应用，复用后端部署的 WebUI、认证、Scenes、go2rtc 接入和账号偏好。OBS、go2rtc、MediaMTX、录像服务仍在后端运行。`android/` 与冻结的 `clients/` Qt/GStreamer 产品独立；不替代或放宽后者的发布验收。

The first Android app connects to an existing product backend and hosts its WebUI. Authentication, Scenes and account preferences use that backend. It does not embed OBS or the backend services, and remains separate from the existing Qt/GStreamer client.

## 当前范围 / Current scope

- Android 10/API 29 及以上；纯 Java/WebView，不含架构专属原生库。
- 服务器选择、持久 Cookie/页面存储、原生菜单、可关闭的保持亮屏、横竖屏、视频全屏、最多四个共享会话的投影子页面。Android 投影使用应用内窗口，不承诺同时在多个物理屏幕显示。后台通过有限的固定可见性信号暂停视频/音轨连接及监听，保留草稿和偏好，回前台后恢复监看；没有向网页开放原生命令接口。
- 关于页面显示 APK 和 WebView 版本、开源仓库、问题反馈和 GitHub 发布记录。手动检查当前正式 Release 是否包含 Android APK；本阶段没有 APK 自动下载/安装。WebUI 随服务器部署更新，继续使用现有 PWA 更新流程。
- 文件导入使用系统文件选择器。麦克风对讲先询问用户，再请求系统录音权限，只授权当前服务器的音频采集。未请求摄像头、全盘存储、未知来源安装或后台服务权限。
- 持久账号偏好仍由后端保存；系统自动播放限制可能要求一次触摸才能恢复声音。输出设备选择受 Android/WebView 能力限制。

Android 10+ uses the system WebView with no native ABI-specific dependencies. Connection/session storage, rotation, full-screen video, limited projector dialogs, file import, explicit microphone consent, About and manual release checks are included. Automatic APK installation, recording downloads/exports and physical multi-display projection are not qualified in this first development build.

## 安装、服务器与证书 / Install, server and certificates

APK 安装后从原生“菜单 → 连接 / 切换服务器”填写 **产品 HTTPS 根地址**，例如 `https://monitor.example.local:18443`，不要填写摄像机 RTSP 地址、go2rtc 内部端口、用户名或密码。使用与电脑端相同的后端账号登录。Windows 后端需先在桌面设置中开启局域网 HTTPS 共享。

局域网自签 CA 需按后端提供的指引在 Android 系统中安装，然后核对 HTTPS 主机名和证书。应用信任系统及用户安装的 CA，但拒绝无效证书、混合内容和普通 LAN 明文 HTTP；没有“忽略证书”按钮。仅字面 `localhost`、`127.0.0.1`、`::1` 允许 HTTP，用于本机 ADB reverse。

Enter the product HTTPS origin and log into the same backend account. Install the backend CA in Android when using a private LAN CA. Invalid certificates and cleartext LAN connections are rejected; only literal loopback permits HTTP for ADB development. No arbitrary native JavaScript bridge, file access or command execution is exposed to pages. Debug WebView inspection is enabled only in development APKs.

MuMu 本机联调示例（端口用当前后端实际值替换）：

```powershell
$adb = 'Q:\Program Files\Netease\MuMu\nx_main\adb.exe'
& $adb connect 127.0.0.1:16384
& $adb -s 127.0.0.1:16384 reverse tcp:18080 tcp:18080
# Android 中填写 http://127.0.0.1:18080；不修改防火墙或公开内部管理端口。
# Cleanup after development:
& $adb -s 127.0.0.1:16384 reverse --remove tcp:18080
```

## 开发环境与构建 / Toolchain and build

锁定清单为 `android/toolchain.lock.json`：AGP 8.13.2、Gradle 8.13（Wrapper 校验 SHA-256）、SDK/target 35、build-tools 35.0.0、JDK 17–23。本机已实测 JDK 22。Maven 依赖使用 `android/gradle/verification-metadata.xml` 校验 SHA-256；不要在常规构建中重新生成校验清单。

Install a supported JDK and the official Android SDK command-line tools. Install the locked SDK packages through `sdkmanager`; Java/SDK locations belong in environment variables or ignored `android/local.properties`. Do not commit local paths or keys. The wrapper distribution and resolved Maven artifacts are checksum-verified. JavaScript and user CA trust produce intentional Android lint warnings; both are required for the product WebUI and private HTTPS deployments. API 35 remains the currently tested target.

```powershell
# SDK package names are supplied through a package file to avoid Windows .bat semicolon parsing.
@('platforms;android-35', 'build-tools;35.0.0', 'platform-tools') | Set-Content "$env:TEMP\webobs-android-packages.txt"
& "$env:ANDROID_HOME\cmdline-tools\latest\bin\sdkmanager.bat" --licenses
& "$env:ANDROID_HOME\cmdline-tools\latest\bin\sdkmanager.bat" "--package_file=$env:TEMP\webobs-android-packages.txt"
./android/scripts/build-android.ps1 -JavaHome 'D:\zulu' -SdkRoot "$env:LOCALAPPDATA\WebOBS-Android\sdk"
# Optional explicit emulator installation; never selects an arbitrary device:
./android/scripts/build-android.ps1 -JavaHome 'D:\zulu' -Serial '127.0.0.1:16384' -Adb $adb
```

其他平台可在 `android/` 使用 `./gradlew :app:testDebugUnitTest :app:lintDebug :app:assembleDebug`。Windows 可使用 `gradlew.bat`。当前 CI 使用 Windows runner，与已校验的 Windows AAPT2 依赖匹配；新增平台依赖应经审核后更新校验清单。

构建输出到忽略目录 `build/android/out/WebOBS-<version>-android-DEVELOPMENT.apk`，附带 SHA-256。版本名通过 `-Version`、版本码通过 `-VersionCode` 指定；后续 APK 版本码必须递增。默认为 `3.5.0-dev.android.1` / `3050001`。

## APK 签名 / APK signing

Android 安装要求每个 APK 带签名。这里使用 **本机开发自签密钥**，不购买商业证书、不申请 Microsoft 证书、不上架商店。Gradle debug 密钥通常在 `%USERPROFILE%\.android\debug.keystore`；必须备份并保留同一密钥，覆盖安装才能保留应用数据。密钥在 Git 与 Docker 上下文中排除。

Every installable APK requires a signature. This build uses the local self-signed Android development key, without a certificate authority or store account. Preserve the same private key for updates; a different developer/CI debug key cannot replace this installation. CI APKs are disposable development artifacts and are not published to a stable update feed. Formal personal-use releases will need a preserved release key and explicit APK release integration; an unsigned release APK is not installable. See [Android signing documentation](https://developer.android.com/studio/publish/app-signing).

## 实测与边界 / Validation and limits

```powershell
cd web
pnpm install --frozen-lockfile
pnpm exec playwright install android
pnpm build
cd ..
python android/tests/test_emulator.py --serial 127.0.0.1:16384 --adb $adb --docker 'path\to\docker.exe' --image webobs:security-fixes
```

测试在独立完整产品容器中创建一次性账号和 FFmpeg 合成源，通过 ADB reverse 在 **实际 APK 的 WebView** 中操作。结束后移除测试容器/卷及 reverse，不清空模拟器、不使用现有摄像机密码；截图与结果只保存在忽略的 `tests/artifacts/android/`。WebUI 使用当前 `web/dist` 的只读挂载。

The emulator probe uses the real installed APK, real account APIs, official go2rtc UI, live synthetic H.264 and a stopped recorder's actual H.264/AAC archive. It checks archive play/pause, thumbnails, an authenticated snapshot response/hash and date-switch cleanup. It is not a desktop-browser fixture. This does not qualify physical cameras, ARM devices, microphone hardware, private CA setup, Android DownloadManager/long exports, battery consumption or long-running recovery. Record actual passed checks in the local receipt; do not infer them from source support.

2026-10-03：同一 MuMu Android 15 / API 35 开发 APK 搭配当前生产 WebUI 和隔离完整 Linux 产品镜像，新增真实 H.264/AAC 归档播放/暂停、缩略图、账号截图响应及 SHA-256、切换日期后的旧播放器清理；已有账号、Scenes、投影、官方 go2rtc、声音/优化偏好、HOME/恢复及重启回归全部通过。未安装或正式发布新 APK；CI 开发构建产物与此已安装 APK 的验收分开记录。未验收 Android 原生下载管理器、长导出或真机。

2026-10-03: The installed MuMu Android 15/API 35 development APK passed the added archive checks and all existing account/Scenes/projector/go2rtc/audio/optimization/HOME/restart regressions using the current production WebUI and isolated complete Linux product image. No new APK was installed or formally released; CI development build artifacts are distinct from this installed-APK qualification. Native downloads, long exports and physical-device qualification remain open.

同日追加归档声音与生命周期回归，共 16 项实测通过：播放器遵循账号静音/主音量，固定声音摄像机及刷新恢复通过真实账号接口核对；真实 HOME/返回前台后，播放器与界面一致保持暂停，用户主动播放后才继续。测试读取视频元素音量和静音状态，未测量实体扬声器输出，也不代表真机或持续耗电验收。

The same-day archive audio/lifecycle regression passed 16 actual emulator checks. Player mute/volume and fixed-camera reload restoration were verified against the real account API; actual HOME/foreground transitions keep the player and UI paused until deliberate playback. The checks inspect video volume/mute properties, not physical speaker output, physical-device behavior or sustained power consumption.

2026-10-04：实际已安装 MuMu 开发 APK 的 17 项检查通过，新增将当前来源放在 1000 路账号声音记录末尾，验证音量/静音/本地监听显示及主音量保存、刷新后保留全部记录。使用独立容器中的色块，未启用实体音频。ADB 丢失或 reverse 移除失败时也会执行测试容器清理；只移除本次成功创建的 reverse，不清除模拟器数据。未安装新 APK 或正式发布。

2026-10-04: All 17 installed MuMu development APK checks passed. The new check places the visible source last in 1000 account audio records and verifies its gain/mute/monitoring plus retention through master-volume save/reload. It uses a color source in an isolated container, with no physical audio output. Container cleanup still runs if ADB is lost or reverse removal fails; only a reverse successfully created by this run is removed. No emulator data was cleared, new APK installed or formal release published.

2026-10-02：MuMu Android 15 / API 35（x86_64）已实测安装与覆盖安装、真实账号登录、Scenes 建档与共享登录投影、横竖屏切换、声音输出模式/主音量和弱网开关持久化、官方 go2rtc/本地 Monaco、160×90 H.264 MSE 持续解码、HOME/前台恢复、原生关于页、进程重启后会话与偏好恢复。实际设备或摄像机验证仍待进行。后台连接释放需后端部署本次新增生命周期适配的 WebUI；旧 WebUI 不保证该行为。

2026-10-02 emulator qualification covers installation, real login, scene persistence, account audio/optimization settings, official go2rtc UI, live synthetic H.264 decoding, background/foreground lifecycle, native About and process restart. This is development qualification, not a formal APK release or physical-device qualification.
