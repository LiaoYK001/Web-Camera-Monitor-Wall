# 发布流程 / Release flow

> 生效 / Effective：2026-09-22（v3.3 起）。本文件是发布流程的**唯一权威说明**。
> 取代 / Supersedes：早期「两份本机平台收据 + v3‑M2 四份收据、48 小时有效、缺一不可」的硬门禁。

## 总览 / Overview

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

一句话：**在 `dev` 上开发 → 在能用的平台上人工验证 → 在容器里做基本测试 → 打包并发布 GHCR 镜像。**

## 1. 开发 / Develop

功能开发在 `dev` 分支完成，Windows 原生或 Linux 原生都可以：

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

## 4. 打包发布 / Package and publish

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
