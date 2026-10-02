# v3.4 release notes / v3.4 发布说明

## Published artifacts / 已发布附件（2026-10-02）

[GitHub Release v3.4](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/releases/tag/v3.4) 固定源码提交 `4b2ab5f09b485a9f9cd870c918295df4315ab442`，共 13 个附件，上传状态与 SHA-256 均已核验。

- Windows x64：[3.4.0-dev.0 DEVELOPMENT-UNSIGNED 安装包](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/releases/download/v3.4/WebOBS-3.4.0-dev.0-windows-x64-DEVELOPMENT-UNSIGNED.exe)，418,250,597 字节，SHA-256 `c3a54c081808f9214b6cc72f94fc506484abb5363bc639aac2d482f5b7e8f658`。按维护者选择分发未签名测试版，手动下载安装，没有 `latest.yml` 或 `dev.yml`。
- Docker/Podman：`ghcr.io/liaoyk001/web-camera-monitor-wall:v3.4`，公开 `latest` 当前指向相同 OCI index digest：`sha256:a1f2f5cee8df794d8cae04b4a8cf01b68a6ba562ee1ddedacc219063f4e4cdbc`，包含 linux/amd64 镜像、SBOM 与 provenance attestation。
- 对应产品/OBS/go2rtc 源码归档、FFmpeg `29e619e767` 源码与固定 FFmpeg 构建脚本、依赖锁定清单、运行文件清单、CycloneDX SBOM、许可证和摘要随 Release 提供。

The immutable v3.4 tag, public container digests, public installer download, and all 13 attachment digests were verified. The Windows installer remains an unsigned development build with manual installation; this publication does not complete the signed Windows qualification described below.

## 中文

- go2rtc 与产品统一打包：包含固定版本的完整官方 WebUI 和本地依赖，流、配置、诊断和媒体经过产品认证代理；设备管理可识别 go2rtc Streams 并引导建档。保留普通 RTSP 和 Direct-only 使用方式。
- Scenes：支持独立来源和布局预设、命名、复制、上下文菜单，以及同时打开多个固定 Scene 投影。声音监听、输出和音量偏好随账号恢复。
- 弱网播放：自动识别慢速或不稳定来源并调整恢复策略，默认开启；用户可在设置中关闭。
- Windows 10/11 x64 完整客户端：原生 C++/OBS D3D11、Python、go2rtc、MediaMTX、FFmpeg、OpenSSL、Caddy 和 WebUI 一并打包；默认关闭局域网共享及开机启动，关闭主窗口进入托盘。程序和数据分离，私密目录 ACL/DPAPI、Job Object 停服、多个投影共享会话和备份恢复已接入。
- Windows 发布边界：目前为明确标记 `DEVELOPMENT-UNSIGNED` 的 `3.4.0-dev.0` 测试候选。只有附件实际存在时才代表该候选已分发；无 `latest.yml`，开发包不连接正式自动更新源。正式签名、干净 Windows 10/11、真实摄像机、两个签名版本更新及故障恢复仍需另行验收。
- PWA 安全修复：更新 Service Worker 自动激活并重新加载旧页面；认证服务无法验证访问时关闭工作区入口。未联网完成更新的旧客户端仍应按 [v3.3 安全公告](security-advisory-v3.3.md) 清理或更新。
- 依赖修复：固定 `fast-uri` 为 `3.1.8`、`js-yaml` 为 `4.3.2`；go2rtc 本地配置编辑器也使用更新后的 YAML 库。容器构建同时加载 pnpm 工作区配置，确保冻结锁定安装使用相同修复版本。
- 已有验证：Windows MSVC/OBS 编译及 CTest、21 项桌面逻辑测试、10 项原生测试、真实 Electron 和打包 ASAR 检查通过。本机 Windows 11 通过中文及空格路径的 NSIS 安装、清空 PATH 后启动、首次登录、认证 go2rtc、Job 清理、默认卸载保留数据；两个固定 Scene 投影和共享登录通过。RTX 3060 Ti 的 NVENC 样本和 OBS 编码检查通过。这些结果不代表真实摄像机或干净系统验收。
- 本次 `3.4.0` 镜像已完成 Linux C++/CTest 和捆绑服务测试；Docker Desktop 单镜像回归通过首次登录、权限/Origin、完整 go2rtc UI/本地 Monaco、WebSocket/MSE 与 HTTP/MP4 播放、RTSP、配置重启持久化及正常停服。媒体使用合成测试源，不代表真实摄像机验收。
- 前端类型检查与生产构建、19 项 Chromium 账号/声音/Scenes/go2rtc/弱网回归、旧 PWA 自动更新回归，以及 WSL 原生运行、go2rtc 配置和公开仓库审计通过。最终发布镜像的远端 digest 在 Release 正文中记录。

签名和维护者配置步骤见 [Windows 代码签名](windows-signing.md)。容器平台为 `linux/amd64`，继续支持 Docker/Podman。

## English

v3.4 integrates the complete pinned go2rtc WebUI and authenticated product proxy, stream-to-device import, scene presets and concurrent fixed-scene projectors, account audio preferences, and default-on optional playback recovery strategies.

The complete native Windows x64 Electron client bundles its backend, OBS and media dependencies. The current Windows candidate is **3.4.0-dev.0 DEVELOPMENT-UNSIGNED**, with no stable update metadata or automatic stable updates. Distribution is confirmed only by the actual attachment list. Signed releases, clean Windows 10/11 systems, real cameras, two installed signed-version upgrades and recovery qualification remain outstanding.

The PWA security update replaces stale workers and reloads open clients; unavailable authentication fails closed. Disconnected old clients must complete the update or follow the existing security advisory. Windows build, desktop, runtime, packaged-app, and physical Windows 11 NSIS smoke checks passed; they do not qualify real cameras or clean machines. The current 3.4.0 container passed Linux build/CTest, bundled-service tests and single-image authentication, complete go2rtc UI, synthetic WS/HTTP/RTSP media, persistence and graceful shutdown checks. Frontend typecheck/build, 19 focused Chromium regressions, stale-PWA replacement, WSL runtime checks and the public audit passed. The published OCI digest is recorded in the Release body.
