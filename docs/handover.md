# 当前开发交接 / Current development handover

更新：2026-10-06。本文面向 `dev` 的 v4.0 开发，不是发布声明。

## 1. 当前状态 / Status

- 最新已公开产品说明仍为 [v3.5](release-notes-v3.5.md)；v4.0 尚未发布。当前开发修复留到 v4，不执行 v3.5 热修。
- 容器、Windows x64 Electron、独立 Android 是主要交付端；Qt 参考客户端保持独立、冻结。其他原生平台有源码支持不等于发布资格。
- 日常改进留在 `dev`；仅在指定版本明确请求且门禁满足后，通过双语版本发布 PR 更新 `main`。不自动提交、推送、打 Tag 或发布。
- 真机、跨设备 LAN、长时间验收当前暂缓，不得标记通过。同源码完整容器/NSIS/正式签名 Android 候选及真实升级也是独立门禁。
- 当前实现/验证边界以 [v4 验收矩阵](v4-readiness.md)为准。旧手册的 v3.2 / M7 / 工作区干净 / 无认证 / 未提交脚本等陈述已归入[历史快照](history/handover-pre-v4.md)，不能照旧操作。

This is the current development entry point, not a release approval. Historical successful builds, browser fixtures and synthetic protocol tests do not qualify current installed products, physical cameras or soak behavior.

## 2. 第一天 / First day

1. 先读 [仓库指导](../AGENTS.md)、[版本与分支](versioning-and-branches.md)、[v4 验收矩阵](v4-readiness.md)。自行检查分支和工作树；本文不声称机器状态持续有效。
2. 原生开发看[开发环境](development.md)；Docker/WSL 循环看[本地开发](local-dev.md)。启动器已入库，不需从旧机器复制脚本。
3. 基础 [Compose](../compose.yaml) 与[环境示例](../.env.example)默认开启账号/RBAC 控制面、关闭旧式 Basic Auth，只绑定主机回环。首次访问 WebUI 创建管理员，没有默认账号或密码。Vite 代理不绕过登录。
4. 旧环境中的 `WEBOBS_CLUSTER_ENABLED=false` 会覆盖新默认值，迁移前显式检查；不要为解决后端不可用而禁用认证。生产/LAN 要另行配置 HTTPS、Origin 和证书。
5. 先运行与修改相关的短时自动化，记录实际命令、源码、环境、通过/跳过/失败及限制。不要从旧回执推断本轮通过。

## 3. 架构与安全边界 / Architecture and boundaries

| 位置 | 当前职责 |
| --- | --- |
| [WebUI](../web/src/App.tsx) | React/TypeScript/Vite PWA、账号工作区、监控墙、Scenes/Preview/Program、固定 Scene 投影 |
| [核心控制面](../core/src/control_server.cpp) | C++20，统一认证、Origin/RBAC、受控代理、可选 libobs 合成 |
| [账号/集群](../cluster/cluster_service.py) | 数据库账号、Argon2id 密码哈希、角色/资源授权、节点和租约；不是旧的单操作员文件认证 |
| [Camera Registry](../camera/camera_registry.py) / [NVR](../nvr/nvr_service.py) | 设备目录/ONVIF 与独立采集、录像、证据任务，不依赖浏览器保持打开 |
| [go2rtc 集成](go2rtc-integration.md) | 完整固定上游与官方 UI；所有管理/API/媒体经产品认证及 settings.manage，配置持久化在私有卷 |
| [Windows](windows-desktop.md) | Electron 完整本机服务、Job 生命周期、NSIS 和确认更新，区别于浏览器与 Qt |
| [Android](android-client.md) | 独立 Java/WebView 客户端连接已有产品后端；不隐式在手机启动录像服务 |
| [容器](docker-deployment.md) | 单镜像 supervisor、私有配置卷、服务异常退出统一回收 |

保留 Direct-only：启用 go2rtc 不强迫 OBS 或持续转码。普通 RTSP 经网关；获批的 HTTPS WHEP/HLS/MJPEG 可真直连，详见[边界](true-direct-v2.md)。管理端口不对外暴露；不要把凭据、摄像机 URL、日志、录像、运行配置或外部签名密钥提交 Git。

## 4. 日常验证 / Focused validation

在对应目录使用锁定 pnpm；详细命令见[仓库指导](../AGENTS.md)。例如：

~~~powershell
# web 工作目录
pnpm typecheck
pnpm build
pnpm exec playwright test -c playwright.local.config.ts --project=chromium <spec>
# desktop 工作目录
pnpm test
pnpm test:electron
# 仓库根目录（无需真机的身份/默认值契约）
python tests/test_container_entrypoint.py DeploymentDefaultsTests
python tests/test_release_identity.py
python android/tests/test_release_version.py
~~~

- 依赖审计要分别运行 web/desktop 的全量和生产依赖审计，不能用历史 CI 绿色代替当前结果。
- Windows runtime/main/package/install 需要实际运行时/安装包；Android 编译/模拟器/隔离更新包各自有前提。未满足不能用单元测试替代。
- Linux shell 生命周期测试在 Windows 被跳过不等于通过；C++/CTest 需要实际 MSVC/WSL/Docker 构建环境。
- PWA 安全更新必须及时淘汰旧认证外壳；未保存输入和内存任务的恢复边界需明确，不能用无限延迟换取草稿保留。

## 5. 操作、升级与恢复 / Operations and recovery

见[统一迁移与恢复](upgrade-and-recovery.md)。先备份、再应用匹配版本，失败后保留数据并恢复匹配快照；不要盲目把新数据库交给旧程序或删除卷。

| 主题 | 当前权威入口 |
| --- | --- |
| 版本节奏与发布纪律 | [版本与分支](versioning-and-branches.md)、[v4 补丁规则](patch-releases-v4.md) |
| v4.0 范围与已知限制 | [v4.0 发布说明（草案）](release-notes-v4.0.md) |
| 容器重启/异常退出 | [恢复契约](container-restart-recovery.md) |
| Windows 安装/更新 | [Windows 产品](windows-desktop.md)、[可选签名](windows-signing.md) |
| Android 构建/更新 | [Android 产品](android-client.md)、[更新资格](android-updates.md) |
| 设备接入失败恢复 | [设备接入](device-onboarding-recovery.md) |
| 录像/证据 | [NVR](nvr-core.md)、[时间线](timeline-evidence.md) |
| PWA/离线 | [Local-first PWA](local-first-pwa.md)、[安全公告](security-advisory-v3.3.md)、[安全更新连续性](pwa-update-continuity.md) |
| 依赖审计与例外 | [依赖安全](dependency-security.md) |
| 浏览器归档回放上限 | [归档回放边界](archive-playback.md) |
| 支持诊断与脱敏导出 | [支持诊断](support-diagnostics.md) |
| 本轮收口与下一步 | [v4 验收矩阵](v4-readiness.md)、[路线图](../ROADMAP.md) |

记录状态时用“实现”“自动化通过”“实际安装通过”“未验收”分别表述，不把一个层级写成另一个层级。任何发布仍需明确版本授权和与该 revision 绑定的证据。
