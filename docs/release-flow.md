# 发布流程 / Release flow

> 生效 / Effective：2026-09-22（v3.3 起）。本文件是发布流程的**唯一权威说明**。
> 取代 / Supersedes：早期「两份本机平台收据 + v3‑M2 四份收据、48 小时有效、缺一不可」的硬门禁。

## 总览 / Overview

主要交付端为容器、Windows x64、独立 Android，从 v4.0 起按 `vA.B` 功能版本和 `vA.B.C` bug/安全补丁更新。未来原生 Linux x86/ARM、Windows ARM/32 位等端通常只在 `vA.0` 构建、验收及发布，不承诺每次功能/补丁附件。网站源依赖锁、许可证/SBOM 与对应源码审查纳入相同不可变流程，见[网站与直播源](online-sources.md)。The three primary targets use minor feature and patch bug/security releases from v4; future architectures remain qualified major-milestone targets.

本次重启修复统一随 v4.0 交付，不发布或应用 v3.5 热修。后续补丁沿用本流程的审计、人工验证、不可变附件与恢复要求，不能因修复紧急而覆盖旧产物。`vA.B` 映射客户端 `A.B.0`，`vA.B.C` 保持三位；占用的补丁编号递增 C。Windows 保留 NSIS/blockmap/校验/确认/备份；Android 保留同一自签密钥和递增版本码，构建候选不自动上传。默认同步三主端产物及元数据，缺失端在说明中披露。详见[v4+ 补丁规则](patch-releases-v4.md)。

Hold the current restart fix for v4.0. Subsequent patches retain this flow's audit, manual validation, immutable assets and recovery. Patch conflicts advance C; primary artifacts/metadata are synchronized by default with missing-platform disclosure. Stable candidate builds do not publish automatically.

v4+ 稳定镜像发布显式设置 `WEBOBS_TARGET_MILESTONE` 为已审查且与主版本匹配的门禁（如实际采用 `v4-M1`），补丁沿用基线门禁；不得从版本号推断“工程已完成”或沿用历史 v2 默认标识。开发/预览镜像按里程碑选择身份：`webobs_dev_identity` 只接受显式登记的开发里程碑（当前 `v4-M1-dev` → `4.0.0-dev`，历史 v2/v3 条目保留），未登记或拼错的里程碑直接失败，不会借用其他产品线的版本号；dev 路径的默认里程碑为当前产品线的 `v4-M1-dev`。The v4+ publisher requires an explicit matching reviewed engineering gate, reused by its patches; development images resolve their identity from an explicit milestone table and fail closed otherwise.

v4.0 的范围、身份、已完成验证与已知限制见 [v4.0 发布说明（草案）](release-notes-v4.0.md)；发布时在该文补全“实际发布与验证”。

```text
Windows 环境              Linux 环境                docker / podman 环境              发布
┌───────────────┐        ┌───────────────┐        ┌────────────────────────┐
│ dev 开发       │───────>│ WSL 验证       │───────>│ Windows WSL            │
│ (Windows)     │        │ (装了 WSL 时)  │        │ (Docker Desktop) 基本测试│──┐
└───────────────┘        ├───────────────┤        ├────────────────────────┤  ├─> 打包 GHCR
                         │ dev 开发       │───────>│ Linux 自身 docker/      │──┘   镜像发布
                         │ (Linux)       │        │ podman 基本测试         │
                         └───────────────┘        └────────────────────────┘
```

流程：**在 `dev` 上开发 → 在能用的平台上人工验证 → 在容器里做基本测试 → 指定版本的发布 PR 合入 `main` → 打包并发布。** / Develop on `dev`, validate the available platforms and container, merge a versioned release PR into `main`, then package and publish.

## 1. 开发 / Develop

功能、bug/安全/依赖修复和文档通过 PR 合入 `dev`，Windows 原生或 Linux 原生都可以；日常提交不自动同步 `main`。 / Features, bug/security/dependency fixes and documentation target `dev`; daily commits do not synchronize `main`.

```powershell
.\scripts\dev.ps1            # Windows：编译原生后端 + Vite
```

```bash
bash scripts/dev.sh          # Linux / WSL：同上
```

## 2. 平台验证 / Platform verification（人工）

按你手上实际有的环境做，做过的在发布说明里写一句即可：

| 平台 | 做什么 |
| --- | --- |
| Windows | 在 Windows 原生跑通本次改动的功能与 `scripts/dev.ps1 -Check` |
| WSL（装了才需要） | 在 WSL 内 `bash scripts/dev.sh` 跑通同一功能；验证跨平台行为、路径与 shell 差异 |
| Linux | 在 Linux 原生 `bash scripts/dev.sh` 跑通，或用等价的原生依赖环境 |

## 3. 容器基本测试 / Basic container check（人工）

至少在一处容器环境里做一次基本联调：

```bash
# Docker Desktop (Windows + WSL2) 或 Linux 自带 docker / podman
docker compose -f compose.yaml up --build          # 或 podman compose
# 打开 http://127.0.0.1:8080/（回环）或按 overlay 的地址，确认登录、加摄像机、出图、录制
```

跨机器联调可用 `scripts/dev.ps1 -Mode container` 或 `docker save` / `docker load`（见 `docs/development.md` §7）。

## 3.1 发布 PR / Release pull request

实际准备发布新版本（如 `v4.0.5`）时，将指定版本、变更说明和验证结果准备在 `dev`，相关检查通过后创建 **`dev` → `main`** 的发布 PR，标题与说明保持中英文双语。主、次和补丁版本均通过此入口；仅修复某个 bug 或更新文档时仍只合入 `dev`。发布 PR 合并后才从对应的 `main` 提交执行下方打包/Tag/Release 流程。详见[分支职责](versioning-and-branches.md)。

When preparing the requested version, record its identity, changes and validation on `dev`, pass the relevant checks and open a bilingual **`dev` → `main`** release PR. Major, minor and patch releases all use this entry. Ordinary fixes/docs remain on `dev`; after release integration, package, tag and publish from the matching `main` commit.

## 4. 打包发布 / Package and publish

容器和 Windows 等多个产品附件需要一次性发布时，可先使用 PowerShell 的 `-PrepareOnly`（Bash 设置 `WEBOBS_RELEASE_PREPARE_ONLY=true`）。它仍从干净 `main` 构建并推送 `sha-<提交>` 候选，生成并核验对应源码，上传到 Draft 后停止；不创建正式 Git 标签、不发布 Release、不提升版本或 `latest`。通过既有不可变附件工具核验其他获准附件后，在**同一提交**取消此选项并重新执行完成发布。未签名 Windows 开发附件始终不能包含正式更新元数据；正式 Windows 可按维护者选择发布带完整更新元数据的 UNSIGNED 安装包；签名为可选，源码、摘要、实际安装证据及验收边界检查继续保留。Draft 准备不代表正式发行成功。

For a combined immutable release, `-PrepareOnly` / `WEBOBS_RELEASE_PREPARE_ONLY=true` prepares the candidate and source Draft without publishing the Release or moving stable/version/latest tags. Verify all approved attachments, then resume the normal publisher from the same revision. Stable Windows packages may be explicitly labeled UNSIGNED with complete updater metadata; signing is optional. Source, digest, actual-install evidence and disclosed qualification boundaries still apply.

在 **`main`** 上执行（发布从稳定基线出）：

```bash
export GITHUB_REPOSITORY=<owner>/Web-Camera-Monitor-Wall
export GH_TOKEN=<classic PAT，含 write:packages>
./scripts/release-image-local.sh ghcr.io/<owner>/web-camera-monitor-wall v3.3
```

```powershell
.\scripts\release-image-local.ps1 -Image ghcr.io/<owner>/web-camera-monitor-wall -Version v3.3
```

脚本会**自动**完成（全部无需私有夹具，也不需要检出目录之外的任何东西）：

1. 校验参数、镜像名与版本号；
2. 断言**干净工作树**、当前分支为 `main`、远端同名 Tag 必须指向 HEAD（否则拒绝覆盖）；
3. `scripts/check-executable-bits.sh`（Git index 执行位）；
4. `tests/run-public-audit.sh`（公开仓库防泄漏：凭据、端点、生成物、submodule 固定）；
5. 打印第 2–3 步的**人工清单**（只提示，不校验——验证责任在发布者）；
6. `docker buildx build --platform linux/amd64`：注入版本/里程碑与 OCI 标签，`--provenance=mode=max --sbom=true`，推 `sha-<12位>`；
7. `scripts/create-source-bundle.sh` 生成对应源码包 + SHA‑256（含 OBS 递归子模块）；
8. 建 Draft Release → 幂等上传附件 → 建并推送**不可变 annotated Tag** → 发布；
9. 把 `<image>:vX.Y` 与 `<image>:latest` 提升到**同一 digest**，并逐个复验；
10. `make_latest=true`。

## 门禁边界 / What is gated, what is not

| 项 | 状态 |
| --- | --- |
| 干净工作树、执行位、公开审计 | ✅ 自动，必须通过 |
| 构建、SBOM、provenance、源码包、附件校验、digest 提升 | ✅ 自动，必须通过 |
| Windows / WSL / Linux 人工验证 | ⚠️ 人工，发布者负责（脚本只打印清单） |
| Docker / Podman 容器基本测试 | ⚠️ 人工，发布者负责 |
| 本机私有门禁收据（历史上 6 份、48 小时） | ❌ **不再要求**；相关脚本保留但可选，见 [可选本机门禁](local-platform-gates.md) |
| 30 分钟长稳等长测 | ❌ 不是发布门禁；按需单独执行并单独记录 |

**没有私有夹具也能发布**：除上面标记为自动的检查外，发布路径不读取任何检出目录之外的文件。

## 编号与例外 / Version numbers and exceptions

- 编号不可用时按 `vB.A → vB.(A+1)` 顺位递增；详见[版本策略](versioning-and-branches.md)。
- 网络/TLS、身份失效、通用权限不足、构建或测试失败**不是**「编号不可用」，照实排查，不要用跳号绕过。
- 人工验证若跳过某个平台，请在 Release 说明中写明「哪些平台验过、哪些没验」，不要写成全部通过。

## 回滚 / Rollback

```bash
# 把 latest 指回上一个已知可用的 digest
docker buildx imagetools create --tag <image>:latest <image>@sha256:<previous-digest>
```

已经发布的不可变 Release 与 Tag **不要删除、不要移动**；如需修正，按编号顺位发新版本。
