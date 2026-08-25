# Fedora Self-hosted Runner 与 GHCR 发布

本指南用于把 OBS/CEF 完整镜像构建放到维护者控制的 Fedora x86_64 主机。仓库的轻量公开源码审计仍运行在 GitHub-hosted runner；只有可从受保护 `main` 到达的受信 SemVer Tag，或维护者审查后手动触发的 release job，会进入标签为 `webobs-builder` 的 Self-hosted Runner。`dev` 的职责和发布边界见 [版本、里程碑与分支策略](versioning-and-branches.md)。

## 安全边界

Self-hosted Runner 会执行仓库代码，因此它不是普通生产服务器。建议使用独立 VM 或专用构建机、独立无特权用户和独立 Docker/Podman 存储，不要在该主机保存摄像机凭据、生产 TLS 私钥、生产录像或可访问生产 VLAN 的长期令牌。

- 不为 Fork Pull Request、未知分支或可被外部贡献者修改的工作流开放该 Runner。
- 使用受保护 Tag/Environment，并把修改 `.github/workflows/**` 设为必须由维护者审查。
- Runner 只取得发布 job 所需的短期 `GITHUB_TOKEN`；不配置长期 PAT 为全局环境变量。
- 不给 Runner 交互式登录用户不必要的 `sudo` 权限。当前 cache 轮换需要对 `/var/cache/webobs-buildkit*` 的限定权限；也可预先把目录所有者改为 Runner 用户后移除 `sudo`。
- 每次发布从干净 Git checkout 开始；发布脚本拒绝脏工作树。

## 1. 准备 Fedora 主机

安装 Git、Git LFS、Docker Engine + Buildx（或提供 Docker 兼容 socket 的受控构建环境）、GitHub CLI，并预留至少 8 GB RAM 与 20 GB 磁盘。创建专用用户和持久缓存：

```bash
sudo useradd --create-home --shell /bin/bash webobs-runner
sudo install -d -o webobs-runner -g webobs-runner -m 0750 /var/cache/webobs-buildkit
sudo loginctl enable-linger webobs-runner
```

如果使用 Docker socket，把该用户加入 `docker` 组等价于授予主机 root 级控制能力。必须把这台机器视为专用且受信的构建边界；更严格的部署应使用隔离 VM 和发布后销毁的短期 Runner。

## 2. 注册 Runner

在 GitHub 仓库打开 `Settings → Actions → Runners → New self-hosted runner`，选择 Linux x64，并只执行页面当次生成的下载、校验和注册命令。注册时增加自定义标签：

```text
self-hosted
linux
x64
webobs-builder
```

注册令牌是短期 secret，不写入 shell history、仓库或配置管理日志。按照 GitHub 页面生成的 `svc.sh` 指令把 Runner 安装为 `webobs-runner` 用户的服务，随后确认它在仓库页面显示 `Idle`。

仓库 release job 的选择器是：

```yaml
runs-on: [self-hosted, linux, x64, webobs-builder]
```

## 3. 保护发布入口

工作流仅响应带点号的 `v*.*` Tag 和 `workflow_dispatch`，并在执行时验证 SemVer 格式及 Tag 提交属于 `main` 历史。仍建议同时配置：

1. 版本 Tag 保护规则，例如 `v*.*` 仅允许维护者创建或删除；`vX-MN` 里程碑检查点不发布 `latest`。
2. `CODEOWNERS`/分支保护，要求 `.github/workflows/**`、`docker/**`、`scripts/release-*` 经维护者审查。
3. 仓库 Actions 权限默认只读；仅 release job 显式取得 `packages: write`、`attestations: write`、`id-token: write` 和发布源码附件所需的 `contents: write`。
4. 禁止 Fork PR 直接使用 Self-hosted Runner；Pull Request 只运行 GitHub-hosted 的轻量审计。

## 4. 缓存与发布

首次发布会完整构建 OBS/CEF。后续构建复用 `/var/cache/webobs-buildkit`；工作流先写入 `-next`，构建成功后才轮换，避免失败构建破坏当前缓存。

创建受保护 Tag 后：

```bash
git tag -s v0.2.0 -m 'v0.2.0'
git push origin v0.2.0
```

工作流会执行递归 checkout、公开仓库审计、测试/镜像构建、SBOM、provenance、GitHub attestation、GHCR push，并上传与 GPL-2.0-or-later 对应的完整递归源码包。标签规范为：

```text
latest            当前正式 Tag 构建
dev               手动开发发布
sha-xxxxxxxxxxxx  精确 Git 提交
vX.Y.Z            正式版本
@sha256:...       生产部署锁定
```

## 5. Actions 故障时本地发布

本地脚本只接受小写 GHCR 路径和 `dev`/`vX.Y`/`vX.Y.Z` 版本，拒绝脏工作树，并先执行 executable-bit 与公开仓库审计：

```bash
docker login ghcr.io
./scripts/release-image-local.sh \
  ghcr.io/your-user-or-organization/web-camera-monitor-wall \
  v0.2.0
```

令牌只通过 `docker login --password-stdin` 或操作系统凭据存储提供，不能作为脚本参数、Docker build argument 或 `.env` 值。发布完成后，以 digest 部署并使用 `gh attestation verify` 验证来源；详见 [GHCR 指南](ghcr.md)。

## 6. 运维检查

定期升级 Runner 二进制、Docker/Buildx 与主机补丁，监控缓存磁盘占用，并检查 Runner 服务日志。若怀疑工作流或 Runner 被攻破，立即停止服务、从 GitHub 删除注册、撤销令牌、隔离主机，并把已发布 digest 当作不可信重新构建。

## 7. v2 桌面客户端发布 Runner

原生客户端使用独立标签 `webobs-desktop-builder`。Windows 构建机必须是 Windows 11 x86_64，并增加 `windows-11`；Fedora 验收机分别增加 `fedora-current`、`fedora-previous`。这些机器只接受两类入口：可从 `main` 到达的受保护 v2 SemVer Tag，或维护者从 GitHub UI 对受保护 `dev` 精确 HEAD 发起的手工资格验收；不得运行未知 Fork PR、任意分支或落后于远端 `dev` 的提交。

```text
Windows build + acceptance:
self-hosted, windows, x64, windows-11, webobs-desktop-builder

Fedora build/current acceptance:
self-hosted, linux, x64, webobs-desktop-builder, fedora-current

Previous Fedora acceptance:
self-hosted, linux, x64, webobs-desktop-builder, fedora-previous
```

Windows Runner 通过仓库变量引用已审核的 Qt 6.11.2、GStreamer 1.28.6、libsodium 1.0.22、Syft 与 Cosign 路径；签名证书选择器保存在 Secret。Fedora 构建 Runner 还需提供已审核并校验 SHA-256 的 linuxdeploy 与 linuxdeploy Qt plugin。任何 SDK、证书或工具都不得提交到仓库。

```text
WEBOBS_WINDOWS_QT_ROOT
WEBOBS_WINDOWS_GSTREAMER_ROOT
WEBOBS_WINDOWS_SODIUM_ROOT
WEBOBS_WINDOWS_SYFT / WEBOBS_WINDOWS_SYFT_SHA256
WEBOBS_WINDOWS_COSIGN / WEBOBS_WINDOWS_COSIGN_SHA256
WEBOBS_WINDOWS_CERTIFICATE_SHA1 (secret)
WEBOBS_WINDOWS_QT_SOURCE_ARCHIVE
WEBOBS_WINDOWS_GSTREAMER_SOURCE_ARCHIVE
WEBOBS_WINDOWS_GSTREAMER_PLUGINS_BASE_SOURCE_ARCHIVE
WEBOBS_WINDOWS_GSTREAMER_PLUGINS_GOOD_SOURCE_ARCHIVE
WEBOBS_WINDOWS_GSTREAMER_PLUGINS_BAD_SOURCE_ARCHIVE
WEBOBS_WINDOWS_GSTREAMER_PLUGINS_UGLY_SOURCE_ARCHIVE
WEBOBS_WINDOWS_GSTREAMER_LIBAV_SOURCE_ARCHIVE
WEBOBS_WINDOWS_GSTREAMER_PLUGINS_RS_SOURCE_ARCHIVE
WEBOBS_WINDOWS_GSTREAMER_INSTALLER
WEBOBS_WINDOWS_SODIUM_SOURCE_ARCHIVE

WEBOBS_LINUX_LINUXDEPLOY / WEBOBS_LINUX_LINUXDEPLOY_SHA256
WEBOBS_LINUX_LINUXDEPLOY_QT_PLUGIN / WEBOBS_LINUX_LINUXDEPLOY_QT_PLUGIN_SHA256
WEBOBS_LINUX_SYFT / WEBOBS_LINUX_SYFT_SHA256
WEBOBS_LINUX_COSIGN / WEBOBS_LINUX_COSIGN_SHA256
WEBOBS_LINUX_QT_SOURCE_ARCHIVE
WEBOBS_LINUX_GSTREAMER_SOURCE_ARCHIVE
WEBOBS_LINUX_GSTREAMER_PLUGINS_BASE_SOURCE_ARCHIVE
WEBOBS_LINUX_GSTREAMER_PLUGINS_GOOD_SOURCE_ARCHIVE
WEBOBS_LINUX_GSTREAMER_PLUGINS_BAD_SOURCE_ARCHIVE
WEBOBS_LINUX_GSTREAMER_PLUGINS_UGLY_SOURCE_ARCHIVE
WEBOBS_LINUX_GSTREAMER_LIBAV_SOURCE_ARCHIVE
WEBOBS_LINUX_GSTREAMER_PLUGINS_RS_SOURCE_ARCHIVE
WEBOBS_LINUX_SODIUM_SOURCE_ARCHIVE

WEBOBS_ANDROID_QT_ROOT
WEBOBS_ANDROID_SDK_ROOT
WEBOBS_ANDROID_NDK_ROOT
WEBOBS_ANDROID_GSTREAMER_ROOT
WEBOBS_ANDROID_SODIUM_ROOT
WEBOBS_ANDROID_DEVICE_SERIAL
WEBOBS_ANDROID_REFERENCE_MANIFEST
WEBOBS_ANDROID_VPN_CONNECT_HELPER
WEBOBS_ANDROID_VPN_DISCONNECT_HELPER
WEBOBS_ANDROID_KEYSTORE
WEBOBS_ANDROID_QT_SOURCE_ARCHIVE
WEBOBS_ANDROID_GSTREAMER_SOURCE_ARCHIVE
WEBOBS_ANDROID_GSTREAMER_PLUGINS_BASE_SOURCE_ARCHIVE
WEBOBS_ANDROID_GSTREAMER_PLUGINS_GOOD_SOURCE_ARCHIVE
WEBOBS_ANDROID_GSTREAMER_PLUGINS_BAD_SOURCE_ARCHIVE
WEBOBS_ANDROID_GSTREAMER_PLUGINS_UGLY_SOURCE_ARCHIVE
WEBOBS_ANDROID_GSTREAMER_LIBAV_SOURCE_ARCHIVE
WEBOBS_ANDROID_GSTREAMER_PLUGINS_RS_SOURCE_ARCHIVE
WEBOBS_ANDROID_GSTREAMER_BUNDLE
WEBOBS_ANDROID_SODIUM_SOURCE_ARCHIVE
```

These archive variables point to runner-local, previously downloaded upstream files. The release
workflow hashes the actual Qt, libsodium, GStreamer core/base/good/bad/ugly/libav and pinned
GStreamer Rust plug-in source archives plus the Windows GStreamer installer against
`clients/dependencies.lock.json`. The Rust source is the immutable commit behind the upstream
`gstreamer-1.28.6` release tag and supplies `whepclientsrc` plus the MediaMTX-compatible `whepsrc`; a core version string or a partial
archive set is not accepted as supply-chain evidence. Use `--require-platform` when reproducing
the check manually so omission is a hard failure.

这些 archive 变量指向 Runner 本地预先下载的上游文件。发布工作流会把真实的 Qt、libsodium、
GStreamer core/base/good/bad/ugly/libav、固定 Rust 插件源码包及 Windows GStreamer 安装器与
`clients/dependencies.lock.json` 对照计算摘要。Rust 包固定到上游 `gstreamer-1.28.6` 标签对应的
不可变提交并提供 `whepclientsrc` 与 MediaMTX 兼容的 `whepsrc`；仅有 core 版本字符串或缺少任一源码包都不能作为供应链证据。
人工复现时必须使用 `--require-platform`，确保遗漏立即失败。

精确协议与 30 分钟硬件门禁只读取受保护 Secret/Runner 本地文件。五种私有端点通过 `WEBOBS_PRIVATE_RTSP_H264`、`WEBOBS_PRIVATE_RTSP_H265`、`WEBOBS_PRIVATE_MJPEG`、`WEBOBS_PRIVATE_HLS`、`WEBOBS_PRIVATE_WHEP` 提供；17 路参考清单由 `WEBOBS_WINDOWS_REFERENCE_MANIFEST` 或 `WEBOBS_LINUX_REFERENCE_MANIFEST` 指向 Runner 本地文件，清单引用的每个凭据环境变量都必须非空。脚本只输出协议名、解码器、帧数和掉帧统计，不输出端点、凭据或私有证据文件。证据路径必须是 Git 工作区之外尚不存在的绝对路径，POSIX 上以 `0600` 原子落盘；长时间客户端输出写入有大小上限的私有临时文件，避免管道堵塞。`WEBOBS_REFERENCE_CONTROL_URL` 是必填项，用于比较观看前后服务端 RTSP/媒体进程计数；远端必须使用 HTTPS，仅回环地址可用 HTTP，控制用户名与密码必须成对放入 Secret。

在 M2 阶段，从 Actions 页面选择 `Release native clients`，以 `dev` 分支执行 `Run workflow`。审计 job 会再次读取远端 `dev`，要求当前提交与其精确 HEAD 相同；候选版本使用 `2.0.0-dev.sha.<commit>`，随后执行 Windows/Fedora 签名构建、五协议及三平台 30 分钟门禁，并只保存为 Actions 候选 Artifact，不创建 Tag、GitHub Release 或稳定别名。Windows 候选包也强制要求 Authenticode 证书，不能用未签名开发包冒充 M2 证据。

Android Runner 还需要 JDK 21、Android platform/build-tools 36.0.0、NDK r27c、Qt 6.11.2 Android arm64 工具链、GStreamer 1.28.6 universal bundle、从固定源码构建的 libsodium 1.0.22，以及通过 USB ADB 独占连接的一台 API 29+ `arm64-v8a` 专用参考设备。设备必须在开始时未安装 `org.webobs.nativeclient` 及其验收驱动、未设置会阻止自动唤醒的锁屏 PIN，并连接到允许九路实验室 Camera 且可由 `adb shell svc wifi` 恢复的隔离 Wi-Fi；Wi-Fi ADB 或无线调试序列号会被拒绝，避免断网门禁切断控制通道。`WEBOBS_ANDROID_VPN_CONNECT_HELPER` 与 `WEBOBS_ANDROID_VPN_DISCONNECT_HELPER` 指向工作树外两个可执行、无输出的 Runner 私有文件；工作流只以 ADB serial 作为唯一参数调用它们，前者必须在返回前建立用户自管 VPN，后者必须恢复 Wi-Fi 路径。VPN 配置、证书和口令只由这些私有 helper 管理，禁止进入仓库、命令行或输出。发布密钥路径放 Runner 变量，Alias 与口令放 GitHub Secret；工作流不输出口令。九路私有清单不得包含明文用户名密码，只使用隔离实验室端点。脚本自动验证旋转、五秒断网与十秒内九路重连、真实 `vpn → wifi` 状态及九路连续播放、HOME 五秒内释放与十秒内前台恢复、锁屏资源释放、Wake Lock 及麦克风拒绝/授权，并在成功或失败后断开 VPN、恢复旋转/Wi-Fi、卸载两个 APK 和删除远端清单。工作流生成的同证书 acceptance-driver APK 和 `0600` 实机证据只存在于 `RUNNER_TEMP`，不会作为 Artifact 上传。客户端侧 Grant 过期/撤销仍须在私有设备矩阵中补证，未执行前 v2-M3 不得标记完成。

M1～M3 全部完成并合入 `main` 后，稳定 v2 Tag 的发布顺序固定为：公开审计 → Windows/Fedora/Android 构建与签名 → 固定运行时五协议 → Windows 11、两个 Fedora 版本及 Android 参考设备的 30 分钟硬件/零服务端增量门禁 → SBOM/Sigstore/GitHub attestation → 附加到不可变 GitHub Release。只有来自 `main` 的受保护 SemVer Tag 才允许进入 `publish`；手工 `dev` 资格验收和任一失败 job 都不会发布 Release。
