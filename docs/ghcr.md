# 不使用 Docker Hub：GHCR 发布与部署指南

GHCR（GitHub Container Registry）是 GitHub Packages 的 OCI/Docker 镜像仓库，地址为 `ghcr.io`。对于源码已经托管在 GitHub 的本项目，GHCR 通常比另建 Docker Hub 仓库更直接：Actions 可使用仓库自动生成的 `GITHUB_TOKEN` 发布，镜像可关联源码仓库，public 镜像允许匿名拉取。

本文只配置“产品镜像发布到哪里”。当前 Dockerfile 的 Ubuntu 和 Node 基础镜像仍来自 Docker Hub；如果要求构建阶段也完全不访问 Docker Hub，见文末“完全脱离 Docker Hub”。

## 1. 推荐命名与版本策略

本仓库建议使用：

```text
ghcr.io/liaoyk001/web-camera-monitor-wall:<tag>
```

镜像路径应统一使用小写。组织或 fork 应替换 namespace，并确认最终镜像的 `org.opencontainers.image.source` 标签指向实际维护仓库。

推荐同时生成：

- 发布版本：`v0.2.0`。
- Git 提交：`sha-<12位提交>`。
- 不可变 digest：`@sha256:<digest>`，生产部署优先使用。
- `latest`：当前稳定 Tag；`dev`：人工开发发布。两者都不应作为严格生产升级或回滚依据。

当前产品只支持 `linux/amd64`，发布工作流不得宣称存在未经验证的 `linux/arm64` 变体。

## 2. 手工发布

手工发布适合首次验证；稳定发布更推荐后面的 GitHub Actions 流程。Windows Docker Desktop、WSL2、Fedora Docker/Podman 的完整参数化命令见 [跨平台手工发布指南](manual-ghcr-release.md)。

### 2.1 构建并检查本地镜像

```bash
git submodule update --init --recursive
docker compose --env-file .env build --pull webobs
docker image inspect webobs:m0 --format '{{ index .Config.Labels "org.opencontainers.image.source" }}'
docker run --rm --entrypoint /opt/obs/bin/webobsd webobs:m0 --version
```

源码标签应指向发布该镜像的仓库。当前上游 Dockerfile 已指向本仓库；fork 应在发布前调整或通过构建标签覆盖。

### 2.2 创建最小权限令牌

GHCR 命令行认证目前使用 personal access token (classic)：

- 推送只需要 `write:packages`。
- 拉取 private 镜像只需要 `read:packages`。
- 只有确实需要删除包时才授予 `delete:packages`。
- 不要为镜像推送额外授予宽泛的 `repo` scope。
- 组织启用 SSO 时，需要为令牌授权 SSO。

令牌不得写入仓库、`.env`、Dockerfile、Compose、命令参数或构建参数。把令牌保存在密码管理器中，只通过标准输入登录。

Linux shell：

```bash
read -rsp 'GHCR token: ' CR_PAT
printf '%s' "$CR_PAT" | docker login ghcr.io -u YOUR_GITHUB_USER --password-stdin
unset CR_PAT
```

PowerShell 使用交互输入，并让 token 只短暂存在于进程内存：

```powershell
$ghcrUser = Read-Host 'GitHub username that owns the PAT'
$ghcrToken = Read-Host 'GHCR token' -MaskInput
$ghcrToken | docker login ghcr.io -u $ghcrUser --password-stdin
Remove-Variable ghcrToken
```

登录用户名属于 PAT 持有者；镜像 owner 可以是另一个已授予其 package 写权限的组织。登录成功后由 Docker credential helper 保存凭据，不要复制其配置文件。

### 2.3 打标签并推送

Linux shell 示例：

```bash
IMAGE_OWNER=your-user-or-organization
IMAGE="ghcr.io/${IMAGE_OWNER}/web-camera-monitor-wall"
VERSION=v0.2.0
REVISION="sha-$(git rev-parse --short=12 HEAD)"

docker image tag webobs:m0 "$IMAGE:$VERSION"
docker image tag webobs:m0 "$IMAGE:$REVISION"
docker push "$IMAGE:$VERSION"
docker push "$IMAGE:$REVISION"
```

PowerShell：

```powershell
$imageOwner = 'your-user-or-organization'
$image = "ghcr.io/$($imageOwner.ToLowerInvariant())/web-camera-monitor-wall"
$version = 'v0.2.0'
$revision = 'sha-' + (git rev-parse --short=12 HEAD)
docker image tag webobs:m0 "${image}:$version"
docker image tag webobs:m0 "${image}:$revision"
docker push "${image}:$version"
docker push "${image}:$revision"
```

首次手工推送后，检查 GitHub package 页面是否已经通过 OCI `source` 标签关联到正确仓库。如果没有关联，进入 package settings 手工连接仓库；否则同仓库 Actions 的 `GITHUB_TOKEN` 可能没有后续推送权限。

### 2.4 设置可见性

GHCR 第一次发布的 package 默认为 private，即使源码仓库是 public 也不会自动变成 public。

进入 GitHub 个人或组织的 Packages 页面，打开该 package 的 `Package settings`：

1. 确认关联仓库正确。
2. 决定是否继承仓库访问权限。
3. 若希望任何人无需登录即可拉取，显式把 package visibility 改为 public。
4. private package 只向需要的仓库、用户或团队授予 Read/Write/Admin。

公开 GHCR 镜像允许匿名 `docker pull`。发布者无论 package 是 public 还是 private，都必须认证。

## 3. GitHub Actions 预审与本地发布

稳定镜像只从受保护 `main` 的已审查提交发布。GitHub-hosted Actions 只做公开源码审计和确定性 Web 构建，不取得 GHCR 写权限，也不接触私有媒体夹具。Linux 平台门禁在维护者本机 WSL2 发行版执行，Windows Chrome/Edge 门禁在宿主机执行；两份脱敏收据必须绑定同一提交且不超过 48 小时。完整流程见 [本机 Windows 与 WSL2 发布门禁](local-platform-gates.md)，版本/分支职责见 [版本、里程碑与分支策略](versioning-and-branches.md)。

仓库的 `.github/workflows/release-image.yaml` 现在只是人工预审：它验证远端 `dev`/`main` 精确 HEAD、公开审计和 PWA 构建，但不会登录 GHCR、构建或推送镜像。本机布局由 Windows Docker Desktop 执行 OCI 构建，并在 Buildx 启动前验证两份本地门禁收据；具备原生 Docker/Buildx 的 Linux 主机仍可使用 `scripts/release-image-local.sh`。

```yaml
name: Release preflight audit

on: workflow_dispatch

permissions: { contents: read }

jobs:
  audit:
    runs-on: ubuntu-24.04
    # executable-bit and public-source audit only

    # no package write permission and no self-hosted execution
```

注意事项：

- `submodules: recursive` 不可省略，否则 OBS/obs-browser 来源不完整。
- 实际工作流已固定完整 commit SHA；升级 action 时必须单独审查 release、变更日志和新 SHA，不能改用浮动主版本。
- GitHub 预审的 `GITHUB_TOKEN` 只有 `contents: read`；本地 GHCR 登录使用短期输入且不写入仓库。
- 两台 Self-hosted Runner 保持关闭；未知 Fork 代码不会在维护者机器上自动执行。
- Windows Docker Desktop 的本地 BuildKit cache 保留 OBS/CEF 大层，成功后再原子轮换 `-next` 目录。
- 公开仓库的 max provenance 可能包含 build arguments。构建参数只能是公开版本和校验值，绝不能传入摄像头地址或任何 secret。
- Actions 首次发布通常会自动关联工作流所在仓库。如果同名 package 先由命令行发布且未关联仓库，应先在 package settings 中授予仓库 Actions access。
- `0.x.y` 阶段不建议自动生成容易误解为稳定大版本的 `0` 标签。

## 4. 从 GHCR 部署，不在目标机编译

基础 Compose 支持通过 `WEBOBS_IMAGE` 覆盖镜像名。目标主机仍需克隆仓库以取得 Compose、入口配置和文档，但无需构建 OBS。

在目标主机 `.env` 中设置不可变版本或 digest：

```dotenv
WEBOBS_IMAGE=ghcr.io/liaoyk001/web-camera-monitor-wall@sha256:<verified-digest>
```

public package：

```bash
docker compose --env-file .env pull webobs
docker compose --env-file .env up -d --no-build webobs
```

private package：先使用只有 `read:packages` 的 PAT 执行 `docker login ghcr.io`，再运行上面的命令。

验证实际镜像：

```bash
docker compose --env-file .env images
docker inspect "$(docker compose --env-file .env ps -q webobs)" \
  --format '{{.Config.Image}} {{.Image}}'
```

更新时把 `WEBOBS_IMAGE` 改为新 digest，先执行 `pull`，再使用：

```bash
docker compose --env-file .env up -d --no-build --force-recreate webobs
```

回滚时恢复旧 digest 并重复相同命令。镜像回滚前仍要备份场景，因为应用版本和场景 schema 可能一起变化。

## 5. 验证 digest、标签和证明

拉取后记录 registry 返回的 digest：

```bash
docker pull ghcr.io/liaoyk001/web-camera-monitor-wall:v0.2.0
docker image inspect ghcr.io/liaoyk001/web-camera-monitor-wall:v0.2.0 \
  --format '{{json .RepoDigests}}'
```

如果发布工作流生成了 GitHub artifact attestation，可使用 GitHub CLI 验证构建来源：

```bash
docker login ghcr.io
gh attestation verify \
  oci://ghcr.io/liaoyk001/web-camera-monitor-wall:v0.2.0 \
  --repo LiaoYK001/Web-Camera-Monitor-Wall
```

验证通过不代表镜像没有漏洞或业务配置安全；它只证明所验证 digest 与声明的 Actions 构建来源相符。仍需审查 Dockerfile、依赖固定值、发布 workflow 和运行配置。

仓库验证器会把 digest、OCI 标签、attestation 和对应源码检查合并为一个失败即停止的命令：

```powershell
./scripts/verify-image.ps1 `
  -Image 'ghcr.io/liaoyk001/web-camera-monitor-wall@sha256:<digest>'
```

## 6. GPL 源码对应关系

产品采用 `GPL-2.0-or-later`，镜像还包含相应第三方许可证。分发 GHCR 镜像时，应保留：

- 与镜像版本/digest 一一对应的 Git tag 或提交。
- 完整递归 submodule 固定状态。
- Dockerfile、补丁、构建脚本和锁文件。
- 仓库 `LICENSE` 以及镜像内第三方许可证。

发布工作流执行 `scripts/create-source-bundle.sh`，只从 Git 索引及递归 submodule 收集文件，加入根提交、OBS 提交和 `SOURCE_DATE_EPOCH` 元数据，以确定性 tar/gzip 生成 `webobs-source-<version>.tar.gz` 和 SHA-256 sidecar。tag 发布会把二者附加到同名 GitHub Release；`scripts/verify-source-bundle.sh` 会拒绝缺少许可证、Dockerfile、libobs 来源，或包含 `.git`、私有 `.env`、`secrets/` 与危险路径的归档。

不要发布一个无法从公开源码版本重建或无法确定对应源码提交的浮动镜像。具体合规义务应按发布主体所在法域进行法律评审。

## 7. 完全脱离 Docker Hub

“不用 Docker Hub”有两种含义：

1. **不把自己的产品镜像发布到 Docker Hub。** 使用 GHCR 已经满足，用户从 `ghcr.io` 拉取产品镜像。
2. **构建和运行过程完全不访问 Docker Hub。** 当前源码构建尚不满足，因为 Dockerfile 的 Ubuntu 和 Node 基础镜像来自 Docker Hub。

若需要第二种，应由维护者：

1. 把审核过的基础镜像按 digest 镜像到自有 GHCR/Harbor/云厂商 registry。
2. 把 Dockerfile `FROM` 改为内部 registry 的完整名称和固定 digest。
3. 保留原始镜像来源、许可证、SBOM、同步和漏洞修复流程。
4. 在隔离环境中验证所有 APT、GitHub、CEF、MediaMTX 等下载源；仅迁移基础镜像并不等于离线构建。

GHCR 不是 Docker Hub 官方镜像的透明镜像服务，不能只把 `docker.io` 前缀替换成 `ghcr.io`。

## 8. 其他主流选择

| Registry | 适用场景 | 主要特点 |
| --- | --- | --- |
| GHCR | 源码和 CI 在 GitHub | `GITHUB_TOKEN`、仓库权限关联、public 匿名拉取、artifact attestation |
| GitLab Container Registry | GitLab 仓库与 CI | 与 GitLab project/token/CI 原生集成 |
| Amazon ECR | AWS 生产环境 | IAM、EKS/ECS、区域化复制和生命周期策略 |
| Azure Container Registry | Azure/AKS | Entra ID、Managed Identity、私网端点 |
| Google Artifact Registry | GCP/GKE | IAM、区域仓库、GCP 构建与部署集成 |
| Quay | 公共或企业 OCI | 镜像扫描、机器人账号、组织权限 |
| Harbor | 自托管、内网或离线 | 项目权限、复制、扫描、签名和保留策略，运维成本更高 |

本项目当前最自然的公开发布路径是 GHCR；进入特定云环境后，再根据 IAM、网络出口、地域合规和镜像扫描要求选择云厂商 registry。

## 9. 官方参考

- [GitHub：Working with the Container registry](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry)
- [GitHub：Publishing Docker images](https://docs.github.com/en/actions/tutorials/publish-packages/publish-docker-images)
- [GitHub：Package access control and visibility](https://docs.github.com/en/packages/learn-github-packages/configuring-a-packages-access-control-and-visibility)
- [GitHub：Using artifact attestations](https://docs.github.com/en/actions/how-tos/secure-your-work/use-artifact-attestations/use-artifact-attestations)
- [Docker：GitHub Actions build documentation](https://docs.docker.com/build/ci/github-actions/)
