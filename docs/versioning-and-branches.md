# Version, milestone and branch policy / 版本、里程碑与分支策略

> Effective / 生效：2026-08-24

## Version and milestone names / 版本与里程碑命名

Release series use `v<major>.<minor>`; implementation milestones use `v<major>-M<number>`. Examples are `v1.1` and `v1-M10`. The milestone number is written as an integer without padding. Historical `M0` remains the pre-version headless proof and is not renamed into a release milestone.

发布系列使用 `v<主版本>.<次版本>`，实施里程碑使用 `v<主版本>-M<序号>`，例如 `v1.1` 与 `v1-M10`。里程碑序号不补零。历史 `M0` 保留为版本化之前的无头闭环验证，不改名为发布里程碑。

| Release series / 发布系列 | Included milestones / 所含里程碑 | State / 状态 |
| --- | --- | --- |
| `v1.0` | `v1-M1` … `v1-M6` | Complete / 已完成 |
| `v1.1` | `v1-M7` … `v1-M11` | `v1-M7`…`v1-M9` complete; current position is `v1-M10`; `v1-M11` planned / `v1-M7`…`v1-M9` 已完成，当前位置为 `v1-M10`，`v1-M11` 已规划 |
| `v2.0` | starts at `v2-M1` / 从 `v2-M1` 开始 | Planned / 已规划 |

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
- Require public audit/tests for `dev`; unknown fork code must never execute on the self-hosted runner / `dev` 要求公开审计与测试；未知 Fork 代码不得在 Self-hosted Runner 上执行。
- Restrict release workflow and package write permission to immutable release tags reachable from `main`, or reviewed manual dispatches / 发布工作流与包写权限只允许用于可从 `main` 到达的不可变发布 Tag，或经过审查的手工触发。
- Delete short-lived feature branches after merge; never place credentials, real camera endpoints, recordings or private acceptance artifacts in any branch / 合并后删除短期功能分支；任何分支都不得包含凭据、真实摄像机端点、录像或私有验收产物。

## GHCR tag mapping / GHCR 标签映射

- `latest`: movable alias for the current stable release from `main` / 从 `main` 发布的当前稳定版本可移动别名。
- `vX.Y` or `vX.Y.Z`: immutable release image / 不可变发布镜像。
- `dev`: movable development image from reviewed `dev` builds / 来自已审查 `dev` 构建的可移动开发镜像。
- `vX-MN`: immutable completed-milestone checkpoint, never a moving work-in-progress alias / 已完成里程碑的不可变检查点，不能作为持续移动的开发别名。
- `sha-xxxxxxxxxxxx`: immutable source identity for either branch / 任一分支的不可变源码身份。
- `@sha256:...`: production deployment lock / 生产部署锁定方式。

The repository's release workflow remains tag-driven. Creating a local branch or milestone label does not authorize publishing `latest`; maintainers must verify branch ancestry, a clean worktree, public-repository audit, corresponding source, SBOM and provenance before release.

仓库发布工作流继续由 Tag 驱动。仅创建本地分支或里程碑名称并不授权发布 `latest`；维护者必须在发布前验证分支祖先关系、干净工作树、公开仓库审计、对应源码、SBOM 与 provenance。
