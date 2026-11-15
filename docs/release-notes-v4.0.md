# v4.0 发布说明 / v4.0 release notes

> **v4.0 已于 2026-10-08 正式发布。** 本文保留发布范围、候选证据与已知限制，第 7 节记录实际发布与公开核验。正式 Tag/Release、25 项稳定附件和镜像摘要以 [GitHub v4.0 Release](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/releases/tag/v4.0) 为准；候选经[发布流程](release-flow.md)和指定版本 PR 合入 `main` 后，从同一提交重新构建、核验并发行。Published on 2026-10-08; section 7 records the actual publication and public verification.

v4.0 是整个监控产品的成熟度版本：把已有的发现、接入、编排、监看、回放与证据能力收口为**操作一致、失败可恢复、诊断可交付**的产品，并把重启/异常退出修复随本版本一起交付。

## 1. 版本身份 / Release identity

| 目标 | 发布身份 | 工程门禁 |
| --- | --- | --- |
| 容器 | 镜像内 WebUI/Core/OCI 标签均为 `4.0.0` | `WEBOBS_TARGET_MILESTONE=v4-M1`（显式提供，缺失即拒绝） |
| Windows x64 | NSIS `4.0.0`，按维护者决定未签名（UNSIGNED） | 同一 v4-M1 门禁 |
| Android | `versionName 4.0.0`、`versionCode 4000000` | 同一 v4-M1 门禁 |
| 开发镜像 | `4.0.0-dev.<12 位提交>` | `WEBOBS_TARGET_MILESTONE=v4-M1-dev`（dev 路径默认值） |

v4+ 稳定发布不得从版本号推断工程门禁；`v4.0.0` 之后的补丁沿用基线门禁（`4.0.1`、`4.0.2` …）。三端身份由 `tests/test_release_identity.py` 的 `TargetIdentityConsistencyTest` 与 `android/tests/test_release_version.py` 共同约束：同一 `A.B.C` 必须被容器与 Android 助手一致接受，Windows 打包必须拒绝“稳定版本不带 -Release”与“-dev 版本带 -Release”，未知的 v4 开发里程碑必须 fail-closed。

本地容器发布器的 OCI `org.opencontainers.image.version` 使用解析后的 `4.0.0`，与 Dockerfile/WebUI/Core 一致；`v4.0` 保留为外部 Git/Release/镜像标签，不覆盖镜像内三位版本。The local publisher keeps the normalized build version in OCI metadata and the release tag as the external alias.

## 2. 范围 / Scope

- **容器重启与异常退出**：临时 FIFO/运行目录按启动隔离、停服与启动失败统一清理；异常退出不再阻断下次启动。见[容器重启与恢复](container-restart-recovery.md)。
- **管理操作一致性**：创建用户、节点注册/批准、撤销、备份、客户端配对批准/撤销统一为逐资源在途锁、有界等待、归属取消与分区块读取失败隔离；非幂等创建区分“已失败”和“结果未确认”，只提供只读核对。
- **播放与资源边界**：浏览器 S3 归档回放改为流式读取（复制前越界拒绝、32 MiB 保守上限、60 秒总时限、取消不等待、按选择归属）。见[归档回放边界](archive-playback.md)。
- **诊断**：用户主动导出的有界脱敏支持报告（固定枚举、时间戳、有界计数，48 KiB/条数上限失败关闭；未知身份显式 `unavailable`）。见[支持诊断](support-diagnostics.md)。
- **PWA 连续性**：安全更新仍立即淘汰旧认证外壳，并以持久记录说明“丢失/保留”，恢复期间不自动同步、不盲目重发未确认的导出。见[安全更新连续性](pwa-update-continuity.md)。
- **依赖安全**：两个工作区的完整与生产依赖审计无已知漏洞；桌面构建链移除无修复版本的 `sprintf-js`/`roarr`，并对 `global-agent` 提交可复核补丁恢复代理 TLS 选项。见[依赖安全](dependency-security.md)。
- **部署与迁移**：基础 Compose 与示例环境统一为“启用账号控制面、关闭旧式 Basic Auth、仅回环”，首次部署在 WebUI 创建管理员；新增[升级与恢复](upgrade-and-recovery.md)。
- **补丁节奏**：三主端自 v4.0 起采用 `vA.B` 功能版本与 `vA.B.C` 补丁，优先 Windows/Android 修复。见[补丁规则](patch-releases-v4.md)。
- **Android 应用内更新**：固定 GitHub 产品附件、大小/摘要/签名/包名/版本码校验、系统 DownloadManager、显式确认交给系统安装器；权限、草稿、下载失败与进程退出均有恢复入口。首次正式签名身份持续保存在仓库外，后续版本沿用同一密钥；开发 APK 的不同签名不能直接覆盖升级。见[Android 更新](android-updates.md)。

## 3. 已完成的验证（开发/自动化层）/ Verification performed

以下保留发布前 `dev` 上实际运行过的检查与候选审查历史；最终正式附件、安装升级和公开核验以第 7 节为准。详细命令、逐项结果与未验收边界见 [v4 矩阵](v4-readiness.md)。These are pre-release development/candidate records; section 7 states the final published artifacts and qualification.

- 前端 `typecheck`、`build` 通过；依赖审计（web/desktop，含 `--prod`）无已知漏洞；公开仓库审计通过。
- 浏览器回归：完整 `playwright.local.config.ts` 套件 252 通过（其余 3 项为本机既有负载敏感用例，非本轮回归）；归档 22 项、管理 14 项、支持报告 6 项、安全更新连续性 4 项专项通过，其中管理套件带“移除加固即失败”的反证。
- WSL Ubuntu-24.04：15 个 Linux 套件通过，包含此前在 Windows 上无法运行的 `test_v2_client_control`（30 项，libsodium）与 POSIX 生命周期 `test_container_entrypoint`（13 项）。
- MuMu API 35 x86_64：Android 开发 APK 经 Gradle 单测/lint/打包、包内身份与 `apksigner` 签名校验后安装并启动（设备侧 `versionCode 3050001`、`versionName 3.5.0-dev.android.1`，属开发身份）。
- 桌面：`pnpm test` 与下载器代理/TLS 夹具 9 项通过。

### 2026-10-06 正式候选与发布回归 / Stable candidate and release regression evidence

- `5230e9c2100cc3e58cf2d4dcb4f932ce75fab1a8` 的 [Windows 4.0.0 完整候选](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/37457849323) 通过 CTest、原生服务首次账号/认证媒体/大文件与 H.264/AAC 证据、实际主窗口与两个固定投影、融合 ASAR 的干净 PATH 与 Job 异常退出回收，以及实际 NSIS Unicode 路径安装、启动和默认卸载数据保留。稳定候选按维护者要求标记 UNSIGNED，生成并校验 `latest.yml`；未自动发布。
- 同 revision 的 [Linux amd64 完整容器候选](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/37457854439) 在 Ubuntu 24.04 runner 通过全部镜像内测试（含原有事件 p95 < 50 ms 预算），实际认证官方 UI/CSP/本地 Monaco、HTTP/WS/RTSP 合成媒体、Direct 与 Composite 正常/异常重启、服务崩溃和保留原配置卷的重建。后续 [候选与最小构建缓存](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/37459146172) 对应 `eae5c3f0cf3ca6823d3ce314e5ab768659ad10f4`，同样通过；不持有注册表写权限。
- Android `4.0.0` / `4000000` 正式候选以首次发行授权创建的仓库外持久 RSA 自签身份构建；13 项 release JUnit、lint、APK 身份与签名校验通过。签名证书 SHA-256 为 `d6d4f3bbc30f26a971b548344b3065983c495dec6ca388b57e897ba7a2509d2c`，本次 APK SHA-256 为 `f8f9865baec03176784f15a1b8840d1dbb1f0abd7c6d4b783333d42fad3c914d`。发布前从最终 `main` 重新构建并核验附件，不上传私密签名材料。
- [公开 CI](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/37460685931) 对 `ec03a7e9d194cb76e73d8bae84c676f89e894d81` 通过服务/类型/构建/依赖审计、浏览器性能与音频、四套独立专项和 Windows 更新契约。管理套件新增“请求确已抵达后才推进虚拟超时时钟”的前置条件，保留超时及禁止重发断言；14 项均通过。
- 发布审查发现上述首个 Windows 候选虽报告版本 `4.0.0`，核心仍沿用 CMake 的历史 `v3-M2-dev` 里程碑。该候选不能作为最终 v4 身份验收；Windows 构建现要求显式 `-Milestone v4-M1`，写入运行时 manifest，并由实际 `/api/v1/health` 检查与所选里程碑一致。正式附件必须来自包含此修复的新候选。CodeQL 的两处新增告警均位于测试夹具：下载器错误码改用有界字面量集合、PWA 夹具错误不再回传异常文本；不通过忽略告警发布。
- MuMu API 35 x86_64 的独立 `.updatequalification` 包重跑实际系统下载、错误摘要/大小/签名/包名/版本与恢复检查、权限拒绝、草稿阻止、确认的 `4.0.0 → 4.0.1 → 4.0.2`、连接/偏好/WebView Cookie 保留和 APK 请求不含产品凭据。该检查使用合成 feed 和一次性测试密钥；未更新、卸载或清除已有产品。Playwright Android 驱动是前置依赖，不应将驱动初始化失败误报为产品元素缺失。
- 本机完整容器联调进一步通过 117 MiB H.264 媒体的 HEAD/Range/ETag/断点读取、16 个慢读者与有界内存/控制响应、断连清理、摄像机与导出归属，以及实际 H.264/AAC 证据导出/摘要/重启恢复；网站表单的两种真实解析器、认证 MSE 解码、设备导入与重启后的命名流恢复通过。Windows 固定解析器另通过真实首次 HTTP 断连恢复。
- Windows 收尾构建曾在融合 ASAR 首次启动的原有 120 秒检查预算内失败；本机旧候选复现了运行时校验超时。校验器原先逐文件散列两遍，第二遍只使用文件名；现保留一次完整 SHA-256/规范路径/文件类型校验，最多 8 个并发文件，随后只读目录核对额外文件与链接。相同 7,938 个实际安装文件的热缓存对比为 `43.18 → 11.63 秒`；篡改、缺失、重复、多余文件与目录链接仍被拒绝。原有启动预算保持不变，正式附件必须通过重新打包的实际 ASAR/NSIS 验证。

These are successful stable-candidate builds, real host installation and isolated installed-update checks. Final attachments are rebuilt and verified from the reviewed release `main` commit. Synthetic media, the Windows build host and the separate Android qualification package do not qualify physical cameras, clean systems, ARM or the production APK/public update feed.

## 4. 已知限制与未验收项 / Known limitations

- 三端 `4.0.0` 已正式发布；第 3 节的历史候选与第 7 节的最终正式附件分别记录，实际发布身份与摘要以 Release 为准。
- 干净 Windows 10/11 安装、真实摄像机与编码矩阵、物理 Android/ARM 真机、跨设备 LAN、长稳（6/24 小时）与参考设备多路性能预算均未验收。
- Windows `v3.5 → v4.0` 已使用冻结正式安装包在 Windows Server 2022 参考 runner 完成实际升级与数据保留验收，范围见第 7 节；公开 feed、交互向导与干净 Windows 10/11 另列。Android 独立验收包的 `4.0.0 → 4.0.1 → 4.0.2` 已实测，生产包与公开源另列。Windows 差量失败回退与损坏包恢复尚未完成实际安装验收。
- 浏览器归档回放的 32 MiB 上限是保守工程限制，不是参考设备的实测安全上限；更大文件需要单独验证的有界散列/存储策略。
- 本机 Docker Desktop 存储栈此前使镜像内的 `test_event_service` p95 超出预算（同代码在 tmpfs 上为 1.6–2.3 ms）；最终正式镜像已在 Ubuntu 24.04 参考 runner 按原预算构建并通过。该结果不代表本机存储栈或其他设备达到同一预算。
- 节点注册批准与本地备份没有服务端请求关联标识，核对无法证明“未创建”；管理界面已明确说明。
- Android 生产包/公开 GitHub feed、实体 ARM、真实 Wi-Fi/断网与磁盘故障尚未验收；独立更新包实测不等于这些结果。正式签名不能覆盖既有不同签名的开发 APK，不能通过自动卸载掩盖签名不匹配。

## 5. 升级与迁移 / Upgrade and migration

- 升级前先备份并记录版本—快照映射；失败时安装对应旧版本再恢复匹配快照。见[升级与恢复](upgrade-and-recovery.md)。
- 旧 `.env` 若显式写了 `WEBOBS_CLUSTER_ENABLED=false`，会覆盖新的启用默认值；升级时显式检查，不要通过关闭认证绕过登录问题。
- Windows 按维护者决定继续发布未签名稳定包；已安装的开发 `-dev.*` 包仍需一次手动安装。Android 必须沿用同一自签密钥与递增版本码，不同密钥不能直接覆盖安装。
- v3.5 的轻量热修不再适用；重启/异常退出修复已包含在 v4.0 中。

## 6. 发布准备步骤（历史记录，已完成）/ Release preparation (completed historical checklist)

1. 冻结范围，按[发布流程](release-flow.md)在参考环境构建三主端候选，记录 revision、摘要与 SBOM/许可证。
   容器可先从 `dev` 的 `Release preflight audit` 手动入口选择 `container_candidate=true`、`release_tag=v4.0`、`milestone=v4-M1`，在 Ubuntu 24.04 runner 完整构建并运行认证媒体、Direct/Composite 重启持久化检查。该入口仅保留带摘要与 revision 的未发布 Linux amd64 镜像归档，不持有注册表写权限、不替代真实设备验收；正式发布仍按本地发布流程执行。
   候选附件还保留最小 BuildKit 缓存和 SHA-256 清单；从对应 `main` revision 的成功运行取回并核验后，可将缓存解压至 `build/release-cache`，由现有本地发布脚本复用，继续执行原始 Dockerfile、SBOM/provenance 和发布检查。缓存与未发布镜像不进入稳定更新源。
2. 补齐本次可用主机的实际安装与升级证据；第 4 节的实体设备、干净系统和长稳缺口持续独立跟踪，未完成项在 Release 中披露，不标记为已通过。
3. 准备双语发布 PR（`dev` → `main`），随后从对应 `main` 提交执行打包/Tag/Release，并在本文补全“实际发布与验证”一节。

The v4.0 baseline unifies management workflows, bounded archive playback, redacted diagnostics, honest PWA update continuity, dependency-audit health, deployment defaults, verified Android updates and container restart fixes. Identity is explicitly selected as `v4-M1` and cross-checked across the primary targets. Three stable candidates have been built; current host/synthetic evidence and outstanding qualification are reported separately. Publication follows the reviewed versioned release PR and final artifact verification. Clean-system, physical-device, camera, LAN, long-run and production Android/public-feed qualification remain open.

## 7. 2026-10-08 实际发布与验证 / Actual publication and verification

[v4.0 正式 Release](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/releases/tag/v4.0) 已发布，三主端均为 `4.0.0`。经双语 [发布 PR #50](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/pull/50) 合入的产品基线为 `54392d8e9ea42b18cf118f113cf455e048ba9899`；不可变 annotated `v4.0` 标签指向该提交，旧版本标签保留。Release 的 25 个附件包括 Windows 安装包及更新元数据、Android APK 与验证证据、两组产品对应源码、六份固定第三方源码及摘要/清单/验证汇总。

The stable Release delivers all three primary targets as `4.0.0` from the reviewed product revision above. The immutable annotated tag resolves to that revision; previous tags are preserved. Its 25 attachments include both client deliveries, updater metadata, corresponding product/third-party sources and verification evidence.

- **容器 / Container:** `ghcr.io/liaoyk001/web-camera-monitor-wall:v4.0` 与 `latest` 指向同一 OCI 摘要 `sha256:5f8fb22de948048ba0bbbfc4e6b79fc39021089312b96d55025379d7b476a6f9`，包含 SBOM/provenance，平台为 Linux amd64。[最终完整镜像检查](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/37732612280) 通过原始镜像内测试、认证 HTTP/WebSocket 合成媒体及 Direct/Composite 重启、异常退出和配置保留；原事件 p95 < 50 ms 预算未放宽。The aliases share the verified digest; the original image, authenticated media and restart/persistence gates passed without relaxing timing budgets.
- **Windows x64:** `WebOBS-4.0.0-windows-x64-UNSIGNED.exe` 为 454,116,555 bytes，SHA-256 `8495886a4efbf532a1a89d89b34c3b2621ef04d030fafb41a27e350dfd5499ab`。[最终完整构建](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/37732484146) 通过原生服务、实际入口、融合 ASAR/Job 生命周期及 Unicode NSIS 安装/卸载数据保留检查；实际 7,938 个运行文件、`latest.yml` 的大小/SHA-512 与未签名状态均已核验。The complete native runtime, entry, packaged lifecycle and actual NSIS checks passed; all runtime files and updater integrity metadata were verified.
- **Windows 实际升级 / Installed upgrade:** [参考主机验收](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/37755314969) 使用同一冻结安装包，从已发布 v3.5 实际升级至 v4.0，六项下载/确认/停服快照/安装/账号数据保留/健康检查通过。NSIS 用时 60.282 秒、退出 0，保留原 300 秒预算。测试器来自 `dev` 的 `703f926`；先初始化固定 Electron，再用独立 Node 进程提取旧版模块，避免将 v4 新增组件要求用于 v3.5。此前本机尝试未通过，不计为升级成功。The tester revision differs from the unchanged product revision. The successful Windows Server 2022 probe uses a synthetic loopback feed and silent test launcher; it does not qualify public-feed delivery or an interactive wizard.
- **Android:** `WebOBS-4.0.0-android-SELF-SIGNED.apk` 为 90,208 bytes，SHA-256 `f8f9865baec03176784f15a1b8840d1dbb1f0abd7c6d4b783333d42fad3c914d`，实际 `versionCode 4000000`；仓库外持久签名证书 SHA-256 `d6d4f3bbc30f26a971b548344b3065983c495dec6ca388b57e897ba7a2509d2c`。最终干净 `main` 显式 `-Release` 构建、13 项 JUnit、lint（0 错误/4 个已有警告）、实际包身份与签名校验通过；独立验收包完成确认的 `4.0.0 → 4.0.1 → 4.0.2` 系统安装与两次数据保留。The stable APK uses the preserved external identity; real successive system-install probes used separate packages and ephemeral keys, leaving the existing product untouched.
- **公开发布核验 / Public verification:** 匿名访问的最新 Release 为 v4.0，正式标签、25 项远端摘要/大小与本机核验产物一致；实际下载核对公开 `latest.yml`、Android APK/证据、源码摘要与验证清单。大型安装包及源码以远端 GitHub SHA-256/大小和本机实际散列比对，不宣称全部重新下载。Anonymous latest/tag/inventory checks and bounded public downloads passed; large assets were compared through remote digests/sizes and actual local hashing.

[三端验证汇总](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/releases/download/v4.0/webobs-v4.0-verification.json) 与 [第三方源码清单](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/releases/download/v4.0/webobs-third-party-4.0.0-source-manifest.json) 记录对应 revision、摘要、工具适配与审查范围。第 4 节的干净 Windows 10/11、物理摄像机/ARM、生产 Android 公开更新源、LAN、故障/长稳和参考设备性能仍未验收；附件发布不把这些限制改写为通过。The evidence and source manifest state exact provenance and scope; outstanding clean-system, physical-device, production-feed, LAN, fault, soak and performance qualification remains open.

发行期间发现共享 Draft 按标签查询返回 404，以及首轮公开时关联临时标签并被不可变保护锁定。使用数字 Release ID 上传并在公开请求中显式绑定正式标签后，最终 `v4.0` 的公开地址和全部附件通过匿名核验。先前的[标签关联异常记录](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/releases/tag/untagged-4bf93dc14cfde7a839ed) 保留并明确标为历史，不移旧标签、不覆盖附件或关闭不可变保护。发行工具及测试器修复留在 `dev`，产品冻结基线仍为上述 `main`。The earlier immutable temporary-tag record is retained and labeled historical; the official `v4.0` publication passed anonymous checks. Tooling fixes stay on `dev` without rewriting the frozen product tag or assets.

## 8. 2026-10-08 GitHub 发布后复查 / Post-publication GitHub audit

- **Actions 与代码检查 / Actions and code checks:** 发布基线的完整容器、Windows 构建与五类 CodeQL 分析均成功；复查时 `dev` 的 `ed8db65` [公开 CI](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/37760674916) 成功。普通 push 的完整 Windows 候选 job 按设计跳过，实际正式构建与升级另有第 7 节的成功运行。旧提交上的权限启动错误和 Electron 冷初始化失败已修复，其历史失败记录保留。The release baseline and audited development tip pass their respective checks; optional full Windows builds are manual and have separate successful evidence.
- **安全告警 / Security alerts:** GitHub API 返回未关闭 CodeQL、Dependabot、Secret scanning 告警各 0 条。最终产品基线的 Python 分析仍有 7 条已处置历史结果：2 条 SSRF 与 1 条 UDP 绑定误报、3 条固定测试夹具结果、1 条 OASIS SHA-1 协议兼容例外；各条理由保留在 GitHub，说明见[安全与 CI 修复](security-ci-remediation.md)。这是“未关闭告警为零”，不是“分析从未报告任何问题”。Open alerts are zero; seven existing Python results remain explicitly dismissed for documented false positives, test usage or protocol compatibility, rather than being described as an empty analysis.
- **动作运行时 / Action runtime:** 复查发现旧 `setup-node` 与 Windows `cache` 的 Node 20 退役警告；`dev` 更新为经官方标签与 `action.yml` 核验的 SHA 固定 `setup-node v7.1.0` / `cache v6.1.0`（Node 24），显式关闭隐式包管理器缓存。项目 Node/pnpm 版本、既有缓存路径/键、权限和产品附件不因此改变；后续运行见 [Actions](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions)。Verified immutable action pins use Node 24, with automatic package-manager caching disabled and the existing build/deployment contract retained.
- **公开交付 / Public delivery:** 再次匿名核对最新稳定 Release、正式 annotated 标签和 25 项远端摘要/大小，并实际下载验证 12 项小附件、Android 包身份/签名及 `latest.yml`；GHCR 三个正式别名、产品标签、SBOM/provenance 和旧 v3.5 摘要核对通过。GitHub 正式 Release 已有中英文变更、验证、限制、迁移与直接下载说明。The repeated anonymous verification passes; the official GitHub Release contains both languages and the qualification limits. Large assets use remote digest/size versus local actual hashing rather than a second complete download.
