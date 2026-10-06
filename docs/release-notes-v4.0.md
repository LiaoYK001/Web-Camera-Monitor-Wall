# v4.0 发布说明（草案）/ v4.0 release notes (draft)

> **状态：草案，尚未发布。** 本文准备 v4.0 的发布范围、身份与已知限制；只有完成[发布流程](release-flow.md)中指定版本的发布 PR、三主端候选构建与实际升级/安装证据后，才在发布时补全“实际发布与验证”一节。本文不构成发布、不移动 `latest`、不代表任何候选已通过。

v4.0 是整个监控产品的成熟度版本：把已有的发现、接入、编排、监看、回放与证据能力收口为**操作一致、失败可恢复、诊断可交付**的产品，并把重启/异常退出修复随本版本一起交付。

## 1. 版本身份 / Release identity

| 目标 | 发布身份 | 工程门禁 |
| --- | --- | --- |
| 容器 | 镜像内 WebUI/Core/OCI 标签均为 `4.0.0` | `WEBOBS_TARGET_MILESTONE=v4-M1`（显式提供，缺失即拒绝） |
| Windows x64 | NSIS `4.0.0`，按维护者决定未签名（UNSIGNED） | 同一 v4-M1 门禁 |
| Android | `versionName 4.0.0`、`versionCode 4000000` | 同一 v4-M1 门禁 |
| 开发镜像 | `4.0.0-dev.<12 位提交>` | `WEBOBS_TARGET_MILESTONE=v4-M1-dev`（dev 路径默认值） |

v4+ 稳定发布不得从版本号推断工程门禁；`v4.0.0` 之后的补丁沿用基线门禁（`4.0.1`、`4.0.2` …）。三端身份由 `tests/test_release_identity.py` 的 `TargetIdentityConsistencyTest` 与 `android/tests/test_release_version.py` 共同约束：同一 `A.B.C` 必须被容器与 Android 助手一致接受，Windows 打包必须拒绝“稳定版本不带 -Release”与“-dev 版本带 -Release”，未知的 v4 开发里程碑必须 fail-closed。

## 2. 范围 / Scope

- **容器重启与异常退出**：临时 FIFO/运行目录按启动隔离、停服与启动失败统一清理；异常退出不再阻断下次启动。见[容器重启与恢复](container-restart-recovery.md)。
- **管理操作一致性**：创建用户、节点注册/批准、撤销、备份、客户端配对批准/撤销统一为逐资源在途锁、有界等待、归属取消与分区块读取失败隔离；非幂等创建区分“已失败”和“结果未确认”，只提供只读核对。
- **播放与资源边界**：浏览器 S3 归档回放改为流式读取（复制前越界拒绝、32 MiB 保守上限、60 秒总时限、取消不等待、按选择归属）。见[归档回放边界](archive-playback.md)。
- **诊断**：用户主动导出的有界脱敏支持报告（固定枚举、时间戳、有界计数，48 KiB/条数上限失败关闭；未知身份显式 `unavailable`）。见[支持诊断](support-diagnostics.md)。
- **PWA 连续性**：安全更新仍立即淘汰旧认证外壳，并以持久记录说明“丢失/保留”，恢复期间不自动同步、不盲目重发未确认的导出。见[安全更新连续性](pwa-update-continuity.md)。
- **依赖安全**：两个工作区的完整与生产依赖审计无已知漏洞；桌面构建链移除无修复版本的 `sprintf-js`/`roarr`，并对 `global-agent` 提交可复核补丁恢复代理 TLS 选项。见[依赖安全](dependency-security.md)。
- **部署与迁移**：基础 Compose 与示例环境统一为“启用账号控制面、关闭旧式 Basic Auth、仅回环”，首次部署在 WebUI 创建管理员；新增[升级与恢复](upgrade-and-recovery.md)。
- **补丁节奏**：三主端自 v4.0 起采用 `vA.B` 功能版本与 `vA.B.C` 补丁，优先 Windows/Android 修复。见[补丁规则](patch-releases-v4.md)。

## 3. 已完成的验证（开发/自动化层）/ Verification performed

以下为 `dev` 上实际运行过的检查；详细命令、逐项结果与未验收边界见 [v4 矩阵](v4-readiness.md)：

- 前端 `typecheck`、`build` 通过；依赖审计（web/desktop，含 `--prod`）无已知漏洞；公开仓库审计通过。
- 浏览器回归：完整 `playwright.local.config.ts` 套件 252 通过（其余 3 项为本机既有负载敏感用例，非本轮回归）；归档 22 项、管理 14 项、支持报告 6 项、安全更新连续性 4 项专项通过，其中管理套件带“移除加固即失败”的反证。
- WSL Ubuntu-24.04：15 个 Linux 套件通过，包含此前在 Windows 上无法运行的 `test_v2_client_control`（30 项，libsodium）与 POSIX 生命周期 `test_container_entrypoint`（13 项）。
- MuMu API 35 x86_64：Android 开发 APK 经 Gradle 单测/lint/打包、包内身份与 `apksigner` 签名校验后安装并启动（设备侧 `versionCode 3050001`、`versionName 3.5.0-dev.android.1`，属开发身份）。
- 桌面：`pnpm test` 与下载器代理/TLS 夹具 9 项通过。

## 4. 已知限制与未验收项 / Known limitations

- **未构建、未发布任何 v4.0 候选**：没有 `4.0.0` 容器镜像、NSIS 安装包或正式签名 APK，没有 Tag/Release/GHCR 提升。
- 干净 Windows 10/11 安装、真实摄像机与编码矩阵、物理 Android/ARM 真机、跨设备 LAN、长稳（6/24 小时）与参考设备多路性能预算均未验收。
- 真实 `v3.5 → v4.0` 数据保留升级、`4.0.0 → 4.0.1 → 4.0.2` 连续安装、差量失败回退与损坏包恢复未实测。
- 浏览器归档回放的 32 MiB 上限是保守工程限制，不是参考设备的实测安全上限；更大文件需要单独验证的有界散列/存储策略。
- 本机 Docker Desktop 存储栈使容器镜像内的 `test_event_service` p95 预算无法满足（同代码在 tmpfs 上为 1.6–2.3 ms），当前 revision 的镜像需在参考 Linux 主机或 CI 构建。
- 节点注册批准与本地备份没有服务端请求关联标识，核对无法证明“未创建”；管理界面已明确说明。
- Android 模拟器端到端（`android/tests/test_emulator.py`）需要与源码同 revision 的镜像；本机可用镜像均为较早 revision，故未完成。

## 5. 升级与迁移 / Upgrade and migration

- 升级前先备份并记录版本—快照映射；失败时安装对应旧版本再恢复匹配快照。见[升级与恢复](upgrade-and-recovery.md)。
- 旧 `.env` 若显式写了 `WEBOBS_CLUSTER_ENABLED=false`，会覆盖新的启用默认值；升级时显式检查，不要通过关闭认证绕过登录问题。
- Windows 按维护者决定继续发布未签名稳定包；已安装的开发 `-dev.*` 包仍需一次手动安装。Android 必须沿用同一自签密钥与递增版本码，不同密钥不能直接覆盖安装。
- v3.5 的轻量热修不再适用；重启/异常退出修复已包含在 v4.0 中。

## 6. 发布前剩余步骤 / Remaining release steps

1. 冻结范围，按[发布流程](release-flow.md)在参考环境构建三主端候选，记录 revision、摘要与 SBOM/许可证。
   容器可先从 `dev` 的 `Release preflight audit` 手动入口选择 `container_candidate=true`、`release_tag=v4.0`、`milestone=v4-M1`，在 Ubuntu 24.04 runner 完整构建并运行认证媒体、Direct/Composite 重启持久化检查。该入口仅保留带摘要与 revision 的未发布 Linux amd64 镜像归档，不持有注册表写权限、不替代真实设备验收；正式发布仍按本地发布流程执行。
   候选附件还保留最小 BuildKit 缓存和 SHA-256 清单；从对应 `main` revision 的成功运行取回并核验后，可将缓存解压至 `build/release-cache`，由现有本地发布脚本复用，继续执行原始 Dockerfile、SBOM/provenance 和发布检查。缓存与未发布镜像不进入稳定更新源。
2. 完成第 4 节列出的实际安装、升级、设备与长稳验收。
3. 准备双语发布 PR（`dev` → `main`），随后从对应 `main` 提交执行打包/Tag/Release，并在本文补全“实际发布与验证”一节。

The v4.0 maturity release unifies management workflows, bounded archive playback, bounded redacted diagnostics, honest PWA update continuity, dependency-audit health, deployment defaults and the container restart fixes. Release identity is gated by an explicit reviewed `v4-M1` milestone and cross-checked across the three primary targets. **No v4.0 candidate has been built or published**, and clean-system, physical-device, real-camera, LAN, long-run and real-upgrade qualification remain open.
