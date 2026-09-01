# Version, milestone and branch policy / 版本、里程碑与分支策略

> Effective / 生效：2026-08-24

## Version and milestone names / 版本与里程碑命名

Release series use `v<major>.<minor>`; implementation milestones use `v<major>-M<number>`. Examples are `v1.1` and `v1-M10`. The milestone number is written as an integer without padding. Historical `M0` remains the pre-version headless proof and is not renamed into a release milestone.

发布系列使用 `v<主版本>.<次版本>`，实施里程碑使用 `v<主版本>-M<序号>`，例如 `v1.1` 与 `v1-M10`。里程碑序号不补零。历史 `M0` 保留为版本化之前的无头闭环验证，不改名为发布里程碑。

| Release series / 发布系列 | Included milestones / 所含里程碑 | State / 状态 |
| --- | --- | --- |
| `v1.0` | `v1-M1` … `v1-M6` | Complete / 已完成 |
| `v1.1` | `v1-M7` … `v1-M11` | Milestone family is implementation-complete; external release qualification is tracked by v1.2 / 里程碑族实现完成；外部发布资格由 v1.2 跟踪 |
| `v1.2` (`v1.2.1` current patch / 当前修复版) | Final v1 closure / v1 最终收口 | Contains no `v1-M12`; patch releases fix the final v1 baseline without adding a milestone / 不新增 `v1-M12`；补丁版本只修复最终 v1 基线，不增加里程碑 |
| `v2.0` (`v2.0.1` final patch / 最终修复版) | `v2-M1` … `v2-M3` | Complete and published / 已完成并发布 |
| `v2.1` | `v2-M4` … `v2-M5` | Complete and published / 已完成并发布 |
| `v2.2` | `v2-M6` | Complete and published: operations workspace / 已完成并发布：运维工作区 |
| `v2.3` | `v2-M7` | Complete and published: scale, ecosystem and resilience / 已完成并发布：扩展、生态与韧性 |
| `v3.0` | `v3-M1` | Motion and scene-change analytics / 运动与大范围画面变化分析 |
| `v3.1` | `v3-M2` | Person boxes and analytics scheduling / 人物框与分析资源调度 |

A milestone name is an engineering gate, not a release date. A release may be cut only from completed, reviewed gates. Public SemVer tags may add a patch component such as `v1.1.1`; an existing tag is immutable.

里程碑名称是工程门禁，不是发布日期。只有已完成并经审查的门禁才能形成发布。公开 SemVer Tag 可增加补丁位，例如 `v1.1.1`；已经发布的 Tag 不得移动。

## Branch responsibilities / 分支职责

| Branch / 分支 | Responsibility / 职责 | Version identity / 版本身份 | Publication / 发布 |
| --- | --- | --- | --- |
| `main` | Stable release integration and hotfix baseline / 稳定发布集成与热修基线 | release series `vX.Y` / 发布系列 `vX.Y` | Immutable release tags and stable GHCR aliases originate here / 不可变发布 Tag 与稳定 GHCR 别名从这里产生 |
| `dev` | Active milestone integration / 活跃里程碑集成 | milestone `vX-MN` / 里程碑 `vX-MN` | Moving `dev` and `sha-*` development images; completed milestone checkpoints may be tagged immutably / 可移动 `dev` 与 `sha-*` 开发镜像；完成的里程碑检查点可使用不可变 Tag |

The policy starts with both branches at the same reviewed baseline. Subsequent feature work targets `dev`; a release PR merges `dev` into `main` only after the release-series gates pass. A hotfix starts from `main`, is reviewed into `main`, and is then merged back into `dev`. Force-pushes and moving published version tags are prohibited.

策略启用时，两个分支从同一个已审查基线开始。后续功能开发以 `dev` 为目标；只有发布系列门禁通过后，才通过发布 PR 将 `dev` 合入 `main`。热修从 `main` 分出，审查后合回 `main`，随后同步回 `dev`。禁止强推，也禁止移动已经发布的版本 Tag。

Recommended protection:

建议保护规则：

- Require pull requests, successful public audit/tests and review for `main`; disallow direct pushes except an explicitly governed emergency / `main` 要求 PR、公开审计/测试成功及审查；除受控紧急流程外禁止直推。
- Require public audit/tests for `dev`; private platform/media gates run only from a reviewed checkout on the maintainer's WSL2 and Windows hosts / `dev` 要求公开审计与测试；私有平台/媒体门禁只从维护者 WSL2 与 Windows 主机上的已审查检出运行。
- Restrict release workflow and package write permission to immutable release tags reachable from `main`, or reviewed manual dispatches / 发布工作流与包写权限只允许用于可从 `main` 到达的不可变发布 Tag，或经过审查的手工触发。
- Delete short-lived feature branches after merge; never place credentials, real camera endpoints, recordings or private acceptance artifacts in any branch / 合并后删除短期功能分支；任何分支都不得包含凭据、真实摄像机端点、录像或私有验收产物。

## GHCR tag mapping / GHCR 标签映射

- `latest`: movable alias for the current stable release from `main` / 从 `main` 发布的当前稳定版本可移动别名。
- `vX.Y` or `vX.Y.Z`: immutable release image / 不可变发布镜像。
- `dev`: movable development image from reviewed `dev` builds / 来自已审查 `dev` 构建的可移动开发镜像。
- `vX-MN`: immutable completed-milestone checkpoint, never a moving work-in-progress alias / 已完成里程碑的不可变检查点，不能作为持续移动的开发别名。
- `sha-xxxxxxxxxxxx`: immutable source identity for either branch / 任一分支的不可变源码身份。
- `@sha256:...`: production deployment lock / 生产部署锁定方式。

Stable publication remains tag-driven. The v2 series publishes only the GHCR image containing the PWA, corresponding source, checksums, SBOM, provenance and attestation. The frozen native-client workflow has no tag trigger and requires an explicit confirmation phrase against the protected `dev` tip; it cannot create a Release or stable alias. WSL2 Linux and local Windows browser gates must pass before image publication.

稳定发布继续由 Tag 驱动。v2 系列只发布包含 PWA 的 GHCR 镜像、对应源码、校验和、SBOM、provenance 与 attestation。冻结的原生客户端工作流没有 Tag 触发器，且要求对受保护 `dev` 精确 HEAD 输入显式确认短语；它不能创建 Release 或稳定别名。WSL2 Linux 与本机 Windows 浏览器门禁全部通过后才允许发布镜像。
