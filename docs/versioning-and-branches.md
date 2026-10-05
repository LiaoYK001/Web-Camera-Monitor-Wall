# Version, milestone and branch policy / 版本、里程碑与分支策略

> Effective / 生效：2026-08-24；release-only `main` update / `main` 仅发布时更新：2026-10-05

## Version and milestone names / 版本与里程碑命名

### Regular patches from v4.0 / v4.0 起常规补丁（2026-10-05）

三主端从 v4.0 起采用 `vA.B` 功能版本与 `vA.B.C` bug/安全修复补丁，`v4.0` 对应客户端 `4.0.0`，后续可独立发布 `v4.0.1`、`v4.0.2`。扩展架构仍通常只在 `vA.0` 验收。当前重启修复留到 v4.0，暂不发布或应用 v3.5 热修；详见[补丁规则](patch-releases-v4.md)。v4.0 尚未发布。

From v4.0, primary targets use regular minor feature and patch bug/security releases. Patches do not wait for a minor; expansion architectures remain major-milestone targets. The restart fix is held for v4.0, with no v3.5 hotfix rollout.

补丁冲突沿用下方幂等/不可变检查，但递增 **C**，如 `v4.0.1 → v4.0.2`，不改成 `v4.1`；`vA.B` 与 `vA.B.0` 不同时作为两个正式基线。补丁沿用已审查基线门禁，不自动增加工程里程碑。

Patch conflicts advance C after the same immutable/idempotency checks. Do not publish vA.B and vA.B.0 as separate baselines. Patches retain their reviewed engineering gate.

### Unavailable release numbers / 发布编号不可用时顺位递增（2026-09-22）

发布 `vB.A` 时，如果该编号已被其他发布占用、不可变 Release 保留或存在仅针对该编号的限制，不覆盖、删除或强推旧 Tag；改用 `vB.(A+1)`，仍不可用则继续递增次版本号，直到首个可用编号。例如 `v3.1 → v3.2 → v3.3`，`v3.9 → v3.10`，主版本不变。不因跳号而新增功能、改变里程碑、放宽验收或重新构建已指定的镜像。

When `vB.A` is occupied by another release, reserved by an immutable release, or subject to a version-specific restriction, do not overwrite/delete/force-push the old tag. Advance to `vB.(A+1)` and continue until the first available minor version, keeping the major unchanged (`v3.9 → v3.10`). Renumbering does not add features, change milestones, relax acceptance or rebuild a specifically selected image.

先查询远端 Tag、Release（含草稿）及 GHCR 标签；同一次发布的同提交/同 digest 草稿可继续，已成功发布的同一产物视为幂等完成，不无故跳号。其他已占用编号按上述顺位跳过。保留冲突原因及最终编号记录；统一最终 Git Tag、Release 名称、源码附件版本、GHCR 版本标签、README 和 roadmap，发布成功后将 `latest` 指向同一 digest。保留旧 SHA 标签；复用镜像时明确披露不变的内嵌构建标识。

Check remote tags, releases (including drafts), and GHCR tags first. Resume the same attempt's matching commit/digest draft; treat an already-published identical artifact as idempotently complete instead of skipping a number. Record conflicts and the final version. Align the Git tag, Release, source archive version, GHCR version tag, README and roadmap; after publication promote `latest` to the same digest. Preserve SHA tags and disclose unchanged embedded build identifiers when reusing an image.

网络/TLS 错误、身份失效、通用权限不足、全仓库规则限制、构建/测试失败不是“编号不可用”：按原因排查，必要时停止请求维护者处理，禁止用跳号绕过访问控制或无限重试。正式发布时间记录实际时间；历史版本日期另列，不回填 published_at。跳号本身不豁免门禁，任何例外必须由用户明确授权并写入发布说明。

Network/TLS failures, invalid credentials, generic permission/repository-rule failures and failed builds/tests are not unavailable numbers: diagnose them and stop for maintainer action when needed. Never use renumbering to bypass access controls or retry indefinitely. Record actual publication time separately from any historical version date. Gate exceptions require explicit user authorization and release-note disclosure.

本次记录 / This release: `v3.1` 因不可变发布标签冲突未能完成，改为 `v3.2`，沿用源码 `5ab5da0fa4d2` 及原镜像，保留已披露的免长测例外和已知限制。 / `v3.1` could not be completed due to the immutable-release tag conflict; use `v3.2` with source `5ab5da0fa4d2`, the original image, and the disclosed long-test exception and limitations.

Release series use `v<major>.<minor>` and, regularly from v4, `v<major>.<minor>.<patch>`; implementation milestones use `v<major>-M<number>`. Examples are `v4.0.1` and `v1-M10`. The milestone number is an integer without padding. Historical `M0` remains the pre-version headless proof.

发布系列使用 `v<主版本>.<次版本>`，v4 起常规补丁使用 `v<主版本>.<次版本>.<补丁>`；实施里程碑使用 `v<主版本>-M<序号>`，例如 `v4.0.1` 与 `v1-M10`。里程碑不补零；历史 `M0` 保留为版本化之前的无头闭环验证。

| Release series / 发布系列 | Included milestones / 所含里程碑 | State / 状态 |
| --- | --- | --- |
| `v1.0` | `v1-M1` … `v1-M6` | Complete / 已完成 |
| `v1.1` | `v1-M7` … `v1-M11` | Milestone family is implementation-complete; external release qualification is tracked by v1.2 / 里程碑族实现完成；外部发布资格由 v1.2 跟踪 |
| `v1.2` (`v1.2.1` current patch / 当前修复版) | Final v1 closure / v1 最终收口 | Contains no `v1-M12`; patch releases fix the final v1 baseline without adding a milestone / 不新增 `v1-M12`；补丁版本只修复最终 v1 基线，不增加里程碑 |
| `v2.0` (`v2.0.1` final patch / 最终修复版) | `v2-M1` … `v2-M3` | Complete and published / 已完成并发布 |
| `v2.1` | `v2-M4` … `v2-M5` | Complete and published / 已完成并发布 |
| `v2.2` | `v2-M6` | Complete and published: operations workspace / 已完成并发布：运维工作区 |
| `v2.3` | `v2-M7` | Complete and published: scale, ecosystem and resilience / 已完成并发布：扩展、生态与韧性 |
| `v3.0` (immutable preview carrier / 不可移动预览载体) | `v3-M1` | Motion and scene-change analytics / 运动与大范围画面变化分析 | Preview lineage retained; do not move / 保留预览血缘，不得移动 |
| `v3.0.1` (pre-release correction / 预发布修正版) | `v3-M2` | Monitor workspace, telemetry/audio overlays and legacy-source migration / 监控工作区、统计音频叠层与旧来源迁移 | Pending explicit pre-release / 等待明确预发布 |
| `v3.1` | `v3-M2` | Unavailable immutable-release number; superseded by v3.2 / 不可用编号，顺位改用 v3.2 |
| `v3.2` | `v3-M2` + Feedback 5 / 反馈 5 | Historical official baseline; disclosed long-test exception and source limitation retained / 历史正式基底，保留已披露的免长测例外和来源限制 |
| `v3.3` | `v3-M2` + Feedback 6 and account, LAN, and monitor fixes / 反馈 6、账户、局域网与监控修复 | Published historical baseline / 已发布的历史基底 |
| `v3.4` | `v3-M2` + go2rtc, Scenes, account audio, playback recovery and Windows x64 / go2rtc、Scenes、账号声音、播放恢复与 Windows x64 | Published at `4b2ab5f09b48`; Windows 3.4.0-dev.0 is an explicitly unsigned test installer with no updater metadata / 已发布；Windows 为明确标记的未签名测试安装包，不含更新元数据 |
| `v3.5` | `v3-M2` + full unsigned Windows updates / 完整未签名 Windows 自动更新 | Published at `e7b6a2ad5f87`; Windows 3.5.0 UNSIGNED, latest.yml, two-version local NSIS upgrade and public GitHub download verified; clean-system/camera qualification separate / 已发布，实际本机升级与公开下载通过，干净系统/摄像机验收另列 |

A milestone name is an engineering gate, not a release date. A release may be cut only from completed, reviewed gates. Public SemVer tags may add a patch component such as `v1.1.1`; an existing tag is immutable.

里程碑名称是工程门禁，不是发布日期。只有已完成并经审查的门禁才能形成发布。公开 SemVer Tag 可增加补丁位，例如 `v1.1.1`；已经发布的 Tag 不得移动。

## Branch responsibilities / 分支职责

| Branch / 分支 | Responsibility / 职责 | Version identity / 版本身份 | Publication / 发布 |
| --- | --- | --- | --- |
| `main` | Versioned release integration only / 仅集成指定版本的发布 PR | `vX.Y` / `vX.Y.Z` | Immutable release tags and stable GHCR aliases originate here after release integration / 发布集成后，不可变发布 Tag 与稳定 GHCR 别名从这里产生 |
| `dev` | Daily features, fixes, dependencies, documentation and release preparation / 日常功能、修复、依赖、文档与发布准备 | milestone `vX-MN` and release candidates / 里程碑 `vX-MN` 与发布候选 | Moving `dev` and `sha-*` development images; completed milestone checkpoints may be tagged immutably / 可移动 `dev` 与 `sha-*` 开发镜像；完成的里程碑检查点可使用不可变 Tag |

Daily feature, bug/security/dependency and documentation PRs target `dev`. Only when preparing an explicitly requested new version, after its release checks pass, open a bilingual versioned release PR from `dev` into `main`, such as `release: 发布 v4.0.5 / release v4.0.5`. Its description records the changes, validation and limitations. This applies equally to major, minor and patch releases; a hotfix is not an exception allowing ordinary work into `main`. Merge the release PR before tagging and publishing from its reviewed `main` commit under [Release flow](release-flow.md). A development commit, PR merge or push must not automatically synchronize `main` or publish a release.

日常功能、bug/安全/依赖修复和文档 PR 的目标分支为 `dev`。只有实际准备发布已明确要求的新版本且发布检查通过时，才创建中英文双语、标明版本的 `dev` → `main` 发布 PR，例如 `release: 发布 v4.0.5 / release v4.0.5`；说明列出变更、验证和限制。主、次及补丁版本均遵守此规则，热修不构成日常工作合入 `main` 的例外。发布 PR 合并后，按[发布流程](release-flow.md)从已审查的 `main` 提交打 Tag 并发布；普通开发提交、PR 合并或 push 不自动同步 `main`，也不自动发布。

At the 2026-10-05 policy change, both branches shared `5c11fe3`; retain that history without resetting `main` to an older release. Subsequent development may leave `dev` ahead of `main` until a release PR. Published tags remain the identities of shipped versions, and an untagged branch tip is not itself a release. Force-pushes and moving published version tags are prohibited.

2026-10-05 调整规则时，两分支同在 `5c11fe3`，保留此历史，不将 `main` 回退到旧发行版。后续开发期间允许 `dev` 领先 `main`，直到发布 PR 再集成；已发布 Tag 才是发行版本身份，无发布 Tag 的分支最新提交本身不等于已发行版本。禁止强推和移动已发布 Tag。

Recommended protection:

建议保护规则：

- Require versioned release pull requests, successful public audit/tests and review for `main`; disallow direct pushes and ordinary development PRs / `main` 要求标明版本的发布 PR、公开审计/测试成功及审查；禁止直推和日常开发 PR。
- Require public audit/tests for `dev`; platform and container verification is a manual step owned by the releaser and described in [Release flow](release-flow.md) / `dev` 要求公开审计与测试；平台与容器验证是由发布者负责的人工步骤，见[发布流程](release-flow.md)。
- Restrict release workflow and package write permission to immutable release tags reachable from `main`, or reviewed manual dispatches / 发布工作流与包写权限只允许用于可从 `main` 到达的不可变发布 Tag，或经过审查的手工触发。
- Delete short-lived feature branches after merge; never place credentials, real camera endpoints, recordings or private acceptance artifacts in any branch / 合并后删除短期功能分支；任何分支都不得包含凭据、真实摄像机端点、录像或私有验收产物。

## GHCR tag mapping / GHCR 标签映射

- `latest`: movable alias for the current stable release from `main` / 从 `main` 发布的当前稳定版本可移动别名。
- `vX.Y` or `vX.Y.Z`: immutable release image / 不可变发布镜像。
- `dev`: movable development image from reviewed `dev` builds / 来自已审查 `dev` 构建的可移动开发镜像。
- `vX-MN`: immutable completed-milestone checkpoint, never a moving work-in-progress alias / 已完成里程碑的不可变检查点，不能作为持续移动的开发别名。
- `v3.0.1` preview: immutable pre-release correction carrier from `dev`; it never moves `latest` / `v3.0.1` 预发布：来自 `dev` 的不可移动修正版载体，不得移动 `latest`。
- `sha-xxxxxxxxxxxx`: immutable source identity for either branch / 任一分支的不可变源码身份。
- `@sha256:...`: production deployment lock / 生产部署锁定方式。

Stable publication remains tag-driven. GHCR/PWA releases retain source, checksums, SBOM, provenance and attestation; v3.4 introduced Windows candidates and v3.5 stable unsigned NSIS updates. v4+ adds regular patch delivery for the three primary targets. The frozen Qt native-client workflow has no tag trigger and requires an explicit confirmation against protected `dev`; it cannot create a Release or stable alias. Platform/container validation is a documented manual step ([Release flow](release-flow.md)); the release path runs automatic, secret-free checks.

稳定发布继续由 Tag 驱动。GHCR/PWA 保留对应源码、摘要、SBOM、provenance 与 attestation；v3.4 已引入 Windows 候选，v3.5 引入未签名正式 NSIS 更新，v4 起三主端采用常规补丁交付。冻结的 Qt 原生工作流没有 Tag 触发器，要求对受保护 `dev` 显式确认，不能创建 Release 或稳定别名。平台/容器验证仍是[发布流程](release-flow.md)规定的人工步骤；发布路径运行自动、无 Secret 的检查。
