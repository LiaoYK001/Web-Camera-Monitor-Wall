# v4+ 补丁发布 / Patch releases from v4

## 当前决定 / Current delivery decision

2026-10-05：容器重启、异常退出及遗留 FIFO 的修复留在源码中，随 **v4.0** 统一交付。暂不发布或应用基于 v3.5 镜像的轻量热修，不修改 v3.5 Tag、Release、GHCR 标签或客户端更新源。当前稳定产品仍是 v3.5；v4.0 尚未发布。

The restart/crash/FIFO fixes are retained for the unified v4.0 release. No v3.5 hotfix is published or applied. Existing artifacts and update feeds remain unchanged; v4.0 is not released yet.

## 版本规则 / Version rules

| 产品 Tag / Product tag | 客户端 / Client | 用途 / Purpose |
| --- | --- | --- |
| `v4.0` | `4.0.0` | 完整新基线 / Complete new baseline |
| `v4.0.1`, `v4.0.2` | `4.0.1`, `4.0.2` | bug、安全与小范围可靠性修复 / Bugs, security and focused reliability fixes |
| `v4.1` | `4.1.0` | 功能增量 / Feature increment |
| `v5.0` | `5.0.0` | 新主版本及拓展平台验收 / New major and expansion-platform qualification |

从 v4.0 起，三主端（容器、Windows x64、Android）采用 `vA.B` 功能版本与 `vA.B.C` 修复补丁。补丁不必等待下一个功能版本；限制修复范围，复用锁定依赖和构建缓存，执行相关回归与发布审计。新功能、大范围架构调整或破坏性迁移使用次/主版本。扩展端（原生 Linux x86/ARM、Windows ARM/32 位）仍通常只在 `vA.0` 验收发布，不因补丁扩大平台承诺。

Starting with v4, the primary targets use minor feature and patch bug/security releases. Patches ship independently with focused scope, locked build caches, relevant regression and release audit. Expansion architectures remain major-milestone targets.

已发布编号不可覆盖。`v4.0.1` 被占用时检查是否为同一产物的幂等完成；否则递增到 `v4.0.2`，不顺位改成 `v4.1`。不得同时创建 `v4.0` 与 `v4.0.0` 两个正式基线载体。版本按数字比较，`4.0.10 > 4.0.9`；正式源排除开发/预发布、相同版本与降级。

Published identities are immutable. Patch conflicts advance C without bypassing gates. `vA.B` maps to `A.B.0`; do not publish an additional `vA.B.0` baseline. Compare versions numerically; exclude development/prerelease/downgrade updates.

## Windows 的轻量更新 / Windows update delivery

沿用正式 NSIS 与 GitHub provider：自动检查/下载可关闭，用户点击“重启更新”才安装。保留每版 EXE、`latest.yml`、blockmap、摘要、SBOM、许可证和对应源码；Windows 暂不要求商业签名，明确标记 `UNSIGNED`。已有 electron-updater 默认尝试差量下载；旧包/blockmap 不可用或差量失败时回退完整下载，最终仍校验完整包 SHA-512/大小。传输量由实际改动决定，不承诺固定的小包大小。

Windows retains full NSIS installation and GitHub updates with optional automatic checking/downloading and explicit installation. Blockmaps can reduce transfer; differential failures fall back to the full installer. Unsigned stable releases remain supported.

安装前处理草稿、导出、录像与推流，正常停服并生成一致性快照，保留上一安装包和恢复映射。补丁不向运行中的页面或后台注入脚本，不能绕过停服、恢复或校验。

Patches keep normal stop/snapshot/recovery and integrity checks. No runtime code injection or bypass of user confirmation is introduced.

## Android 的补丁更新 / Android patch delivery

原生“关于 → 检查 GitHub 更新”从最近 20 个公开发布中选出**版本号最高且包含精确匹配正式 APK** 的非草稿、非预发布 Release，区分补丁、功能与主版本，展示本机版本、发布说明和对应页面。仅后端发布不会遮住可用 Android 补丁。开发 APK 不进入正式源，本机版本更高时不提示降级。请求固定、无 Token、有超时和响应大小上限。

The native checker selects the highest stable Android APK among the latest 20 releases and links matching notes/downloads. Configurable foreground automatic checks/downloads are enabled by default. Backend-only releases do not hide an APK. Requests are fixed, bounded and token-free; development artifacts and downgrades are excluded.

APK 完整覆盖安装，保留相同 applicationId、同一持久自签密钥和递增 versionCode。无需购买证书或向微软申请；Android 安装本身要求 APK 签名。v4+ 正式版本码固定为 `A×1,000,000 + B×1,000 + C`，B/C 范围 0–999，总值不超过 2,100,000,000。4.0.0/4.0.1/4.0.2 对应 4,000,000/4,000,001/4,000,002，高于现有开发版 3,050,001。不要更换密钥、卸载重装或用独立 CI debug key 掩盖升级问题。

Android replaces the complete APK with the same ID/key and a deterministic increasing versionCode. Preserve the self-signed key outside Git. See [Android versioning](https://developer.android.com/studio/publish/versioning) and [signing](https://developer.android.com/studio/publish/app-signing).

`build-android.ps1 -Release -Version 4.0.1` 生成本机自签**候选**、摘要与构建回执，不自动上传；见[Android 构建](android-client.md)。应用内通过系统下载管理器下载，核对 GitHub SHA-256/大小、实际包名/版本/版本码及已安装签名，再由用户和系统确认安装；草稿/任务阻止、取消及重启恢复见 [Android 更新](android-updates.md)。缺少摘要时只提供人工发布入口。实际两次升级由独立验收包验证，不能由版本比较测试替代公开更新源与真机验收。

The stable-candidate helper does not publish. In-app downloading checks digest/size, APK identity and installed signers before user/system-confirmed installation, with draft/task blocking and recovery. Missing metadata keeps a manual fallback. Isolated actual-upgrade qualification remains distinct from public-feed and physical-device acceptance.

## 发布与验收 / Publication and acceptance

1. 修复先通过 PR 合入 `dev`，中英文说明问题、影响端与验证结果。实际准备发布指定补丁（如 `v4.0.5`）且检查通过后，再创建 `dev` → `main` 的版本发布 PR；普通修复合并不自动同步 `main`。见[分支规则](versioning-and-branches.md)。 / Review fixes into `dev` first, then promote them through a versioned `dev` → `main` release PR when preparing the requested patch and its checks pass. Ordinary fixes do not synchronize `main`.
2. 同一 Tag/Release 对齐源码与产物版本，默认完成三主端打包及可用更新元数据。缺失端明确披露，不宣称完整三端补丁。构建器不直接发布，沿用[唯一发布流程](release-flow.md)的审计、私密验证、不可变附件与摘要检查。v4+ 镜像发布须显式提供与主版本匹配的已审查 `WEBOBS_TARGET_MILESTONE`，不能回落到历史 v2 默认值；补丁沿用所属基线门禁。
3. 记录修复、安全影响、后端/客户端兼容性、迁移与恢复方式。快速交付减少变更范围和等待周期，不跳过完整性、用户确认、数据保留或源码/许可证义务。
4. v4 基线验收实际 `4.0.0 → 4.0.1 → 4.0.2` 的检测、下载/覆盖安装、数据与会话保留；Windows 加测差量失败回退，Android 加测同密钥/错误密钥与版本码。实际设备/安装与协议夹具分别记录。

Patches follow the existing reviewed immutable flow with aligned identities and explicit platform availability. Record compatibility/recovery. Actual installed upgrades and failure/data-retention cases must be qualified separately from synthetic tests; see [v4 readiness](v4-readiness.md).

## 当前验证 / Current validation (2026-10-05)

桌面 38 项逻辑测试、真实 Electron 隔离检查及实际 NsisUpdater 的 v4 补丁检测/下载、blockmap 缺失回退、损坏包拒绝与降级拒绝通过。前端类型检查、构建和 2 项关于/补丁操作浏览器回归通过。Android debug/release JUnit（含 5 项版本/发布选择测试）与 lint 通过；用同一隔离测试密钥实际构建 4.0.1/4.0.2 release APK，核对包内版本码、非 debuggable 标记、签名证书一致性及摘要通过。测试包与密钥不属于正式发行；未覆盖安装、未改变模拟器数据、未发布任何 Release/feed/GHCR。

Desktop logic, real Electron/NSIS protocol, frontend and Android build/signature identity checks passed. The two release-variant APKs used one isolated test key and were not installed or published. These checks do not qualify actual NSIS/APK upgrades, clean systems or physical devices.

同次检查移除桌面构建链中被 [GHSA-ch52-4w7c-c8xp](https://github.com/advisories/GHSA-ch52-4w7c-c8xp) 标记的 `http-cache-semantics 4.2.0`，锁定 npm 已发布的 `4.3.0` 和文件完整性；未更新其他依赖。`pnpm audit --audit-level=low` 返回无已知漏洞；新增实际 Electron 构建下载器的回归验证 `max-stale` 请求不会复用前一响应或携带前一响应 Cookie，桌面共 39 项测试通过。CI 同步执行桌面依赖审计。该依赖来自构建工具，不在产品 production 依赖树中；现有发布包不因此被覆盖。

The flagged 4.2.0 build dependency is replaced by published, integrity-locked 4.3.0 without unrelated dependency changes. Dependency audit reports no known vulnerabilities; the real downloader regression and 39 desktop tests pass. CI now audits desktop dependencies. This is a build-tool dependency update, not a modification to published installers.
