# v4.0 发布说明 / v4.0 release notes

> **v4.0 发布基线与验证边界。** 本文记录发布范围、候选证据及已知限制；实际 Tag/Release、稳定附件和镜像摘要以 [GitHub v4.0 Release](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/releases/tag/v4.0) 为准。候选通过后仍须按[发布流程](release-flow.md)经指定版本的发布 PR 合入 `main`，从该提交重新打包并核验；候选构建不会自行发布或移动 `latest`。

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

以下为 `dev` 上实际运行过的检查；详细命令、逐项结果与未验收边界见 [v4 矩阵](v4-readiness.md)：

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

- 三端 `4.0.0` 候选已构建并分别记录验证；候选、源码基线和最终正式附件必须区分，实际发布身份与摘要以 Release 为准。
- 干净 Windows 10/11 安装、真实摄像机与编码矩阵、物理 Android/ARM 真机、跨设备 LAN、长稳（6/24 小时）与参考设备多路性能预算均未验收。
- Windows `v3.5 → v4.0` 数据保留升级仍待最终候选实测；Android 独立验收包的 `4.0.0 → 4.0.1 → 4.0.2` 已实测，生产包与公开源另列。Windows 差量失败回退与损坏包恢复尚未实测。
- 浏览器归档回放的 32 MiB 上限是保守工程限制，不是参考设备的实测安全上限；更大文件需要单独验证的有界散列/存储策略。
- 本机 Docker Desktop 存储栈使容器镜像内的 `test_event_service` p95 预算无法满足（同代码在 tmpfs 上为 1.6–2.3 ms），当前 revision 的镜像需在参考 Linux 主机或 CI 构建。
- 节点注册批准与本地备份没有服务端请求关联标识，核对无法证明“未创建”；管理界面已明确说明。
- Android 生产包/公开 GitHub feed、实体 ARM、真实 Wi-Fi/断网与磁盘故障尚未验收；独立更新包实测不等于这些结果。正式签名不能覆盖既有不同签名的开发 APK，不能通过自动卸载掩盖签名不匹配。

## 5. 升级与迁移 / Upgrade and migration

- 升级前先备份并记录版本—快照映射；失败时安装对应旧版本再恢复匹配快照。见[升级与恢复](upgrade-and-recovery.md)。
- 旧 `.env` 若显式写了 `WEBOBS_CLUSTER_ENABLED=false`，会覆盖新的启用默认值；升级时显式检查，不要通过关闭认证绕过登录问题。
- Windows 按维护者决定继续发布未签名稳定包；已安装的开发 `-dev.*` 包仍需一次手动安装。Android 必须沿用同一自签密钥与递增版本码，不同密钥不能直接覆盖安装。
- v3.5 的轻量热修不再适用；重启/异常退出修复已包含在 v4.0 中。

## 6. 发布前剩余步骤 / Remaining release steps

1. 冻结范围，按[发布流程](release-flow.md)在参考环境构建三主端候选，记录 revision、摘要与 SBOM/许可证。
   容器可先从 `dev` 的 `Release preflight audit` 手动入口选择 `container_candidate=true`、`release_tag=v4.0`、`milestone=v4-M1`，在 Ubuntu 24.04 runner 完整构建并运行认证媒体、Direct/Composite 重启持久化检查。该入口仅保留带摘要与 revision 的未发布 Linux amd64 镜像归档，不持有注册表写权限、不替代真实设备验收；正式发布仍按本地发布流程执行。
   候选附件还保留最小 BuildKit 缓存和 SHA-256 清单；从对应 `main` revision 的成功运行取回并核验后，可将缓存解压至 `build/release-cache`，由现有本地发布脚本复用，继续执行原始 Dockerfile、SBOM/provenance 和发布检查。缓存与未发布镜像不进入稳定更新源。
2. 补齐本次可用主机的实际安装与升级证据；第 4 节的实体设备、干净系统和长稳缺口持续独立跟踪，未完成项在 Release 中披露，不标记为已通过。
3. 准备双语发布 PR（`dev` → `main`），随后从对应 `main` 提交执行打包/Tag/Release，并在本文补全“实际发布与验证”一节。

The v4.0 baseline unifies management workflows, bounded archive playback, redacted diagnostics, honest PWA update continuity, dependency-audit health, deployment defaults, verified Android updates and container restart fixes. Identity is explicitly selected as `v4-M1` and cross-checked across the primary targets. Three stable candidates have been built; current host/synthetic evidence and outstanding qualification are reported separately. Publication follows the reviewed versioned release PR and final artifact verification. Clean-system, physical-device, camera, LAN, long-run and production Android/public-feed qualification remain open.
