# Windows、WSL2 与 Fedora 手工发布 GHCR 镜像

本文用于维护者或 Fork 开发者从可信工作副本手工构建并发布 `linux/amd64` 产品镜像。本项目供普通用户拉取的官方镜像地址是：

```text
ghcr.io/liaoyk001/web-camera-monitor-wall:<version-or-digest>
```

下文的发布命令不把任何个人用户名写死：`GHCR user` 是持有 PAT 的个人 GitHub 账号，`image owner` 是接收镜像的个人或组织 namespace，两者可以不同。示例版本使用 `v1.1`；版本标签应视为不可变，发布前确认标签不存在，发布后不要用另一提交覆盖它。需要修复时发布 `v1.1.1` 或下一版本。`latest` 是可移动的稳定别名，`sha-<12位提交>` 用于精确追踪源码，生产部署最终应锁定 digest。

## 1. 共同前置条件

1. 稳定版只从受保护的 `main` 或可从 `main` 到达的不可变 SemVer Tag 发布；`dev` 只发布 `dev`/`sha-*` 开发镜像或已完成的 `vX-MN` 检查点，不从未知 Fork/PR 工作树运行构建。完整规则见 [版本、里程碑与分支策略](versioning-and-branches.md)。
2. Git 工作树必须干净，OBS submodule 必须递归初始化并保持固定提交。
3. 当前提交必须先存在于公开 GitHub 仓库，使 OCI `revision` 标签和 GPL 对应源码可获取。
4. Docker/Buildx 必须能构建 `linux/amd64`，建议预留至少 8 GB 内存和 20 GB 空间。
5. GHCR 登录使用 personal access token (classic)，至少授予 `write:packages`；私有依赖才需要额外 `repo`。组织启用 SSO 时还要为 token 授权 SSO。
6. token 只通过标准输入交给 `docker login`，不要写入 `.env`、Compose、脚本参数、Dockerfile、Build Argument 或 shell history。
7. 对本项目官方 v2 镜像，必须先按 [本机 Windows 与 WSL2 发布门禁](local-platform-gates.md) 生成同一提交的两份 48 小时内收据；`scripts/release-image-local.sh` 会 fail-closed 验证。Fork 维护者可保留自己的等价私有门禁，但不能把端点、凭据或原始证据提交到公开仓库。

每次发布先同步源码：

```bash
git fetch --prune origin
git switch main
git pull --ff-only origin main
git submodule sync --recursive
git submodule update --init --recursive
git status --short
```

上述稳定发布流程必须停留在 `main`。日常里程碑开发切换到 `dev`，不得把未完成的 `vX-MN` 构建标记为 `latest` 或 `vX.Y`。

`git status --short` 必须没有输出。再确认远端没有同名版本：

```bash
IMAGE=ghcr.io/your-user-or-organization/web-camera-monitor-wall
VERSION=v1.1
docker buildx imagetools inspect "${IMAGE}:${VERSION}"
```

命令报告 `manifest unknown` 表示标签尚不存在；如果能够读取 manifest，应停止发布并选择新版本。

## 2. Windows 11 + Docker Desktop（PowerShell）

### 2.1 准备环境

- Docker Desktop 选择 Linux containers，并启用 WSL2 engine。
- 安装 Git 与 PowerShell 7。
- Docker Desktop 资源建议至少设置 8 GB 内存；确认磁盘剩余空间。
- 在仓库根目录执行：

```powershell
docker version
docker buildx version
docker buildx inspect --bootstrap
docker buildx ls
```

输出必须包含可用的 `linux/amd64` builder。

### 2.2 安全登录 GHCR

下面的 token 只短暂存在于进程内存，不会显示在终端：

```powershell
$GhcrUser = Read-Host 'GitHub username that owns the PAT'
$ImageOwner = Read-Host 'GHCR image owner (personal account or organization)'
if ($GhcrUser -notmatch '^[A-Za-z0-9][A-Za-z0-9-]{0,63}$' -or
    $ImageOwner -notmatch '^[A-Za-z0-9][A-Za-z0-9-]{0,63}$') {
    throw 'GitHub user or image owner has an invalid format'
}
$Image = "ghcr.io/$($ImageOwner.ToLowerInvariant())/web-camera-monitor-wall"
$Version = 'v1.1'

$SecureToken = Read-Host 'GHCR personal access token' -AsSecureString
$TokenPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($SecureToken)
try {
    $PlainToken = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($TokenPointer)
    $PlainToken | docker login ghcr.io --username $GhcrUser --password-stdin
    if ($LASTEXITCODE -ne 0) { throw 'GHCR login failed' }
}
finally {
    if ($TokenPointer -ne [IntPtr]::Zero) {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($TokenPointer)
    }
    Remove-Variable PlainToken, SecureToken -ErrorAction SilentlyContinue
}
```

Docker Desktop 会把凭据交给系统 credential helper；不要把 `~/.docker/config.json` 复制到仓库或共享给其他机器。

### 2.3 审计、构建并推送

```powershell
pwsh -NoProfile -File ./tests/run-public-audit.ps1
if ($LASTEXITCODE -ne 0) { throw 'Public repository audit failed' }

$Revision = (git rev-parse HEAD).Trim()
$ShortRevision = (git rev-parse --short=12 HEAD).Trim()

docker buildx build `
  --platform linux/amd64 `
  --file docker/Dockerfile `
  --label "org.opencontainers.image.revision=$Revision" `
  --label "org.opencontainers.image.version=$Version" `
  --tag "${Image}:${Version}" `
  --tag "${Image}:sha-${ShortRevision}" `
  --tag "${Image}:latest" `
  --provenance=mode=max `
  --sbom=true `
  --push .

if ($LASTEXITCODE -ne 0) { throw 'Image build or push failed' }
```

该命令直接把镜像、SBOM 和 provenance 推到 GHCR。Buildx 的 registry 输出不一定把镜像加载进本地 Docker image store；需要本地运行时再显式拉取：

```powershell
docker pull "${Image}:${Version}"
docker image inspect "${Image}:${Version}" --format '{{json .RepoDigests}}'
docker buildx imagetools inspect "${Image}:${Version}"
```

### 2.4 本地启动检查

```powershell
docker run --rm `
  -e WEBOBS_HTTP_PORT=0 `
  -e WEBOBS_WEBRTC_ENABLED=true `
  -e WEBOBS_COMPOSITE_ENABLED=false `
  -e WEBOBS_NVR_ENABLED=false `
  "${Image}:${Version}" --duration-seconds 2
```

日志应显示 Gateway Direct-only，命令约两秒后以 `0` 退出，且不应出现凭据、Xvfb 或 OBS 初始化错误。

## 3. Windows WSL2 环境

### 3.1 推荐布局

在 Docker Desktop 的 `Settings → Resources → WSL Integration` 中启用目标发行版。大型构建建议把仓库克隆到 WSL 的 ext4 文件系统，例如 `~/src/Web-Camera-Monitor-Wall`，而不是 `/mnt/c/...`，以减少大量小文件和 submodule 构建开销。

确认 WSL 使用 Docker Desktop daemon：

```bash
docker version
docker buildx inspect --bootstrap
docker buildx ls
```

### 3.2 登录与发布

```bash
read -rp 'GitHub username that owns the PAT: ' ghcr_user
read -rp 'GHCR image owner (personal account or organization): ' image_owner
case "$ghcr_user" in ''|*[!A-Za-z0-9-]*|-*|*-) echo 'invalid GitHub user' >&2; exit 64 ;; esac
case "$image_owner" in ''|*[!A-Za-z0-9-]*|-*|*-) echo 'invalid image owner' >&2; exit 64 ;; esac
image_owner="${image_owner,,}"
image="ghcr.io/${image_owner}/web-camera-monitor-wall"
version="v1.1"

read -rsp 'GHCR personal access token: ' ghcr_token
printf '%s' "$ghcr_token" | docker login ghcr.io -u "$ghcr_user" --password-stdin
unset ghcr_token
echo

./scripts/release-image-local.sh "$image" "$version"
```

脚本会完成干净工作树检查、可执行位检查、公开仓库审计、`linux/amd64` Buildx 构建、SBOM/provenance、`v1.1`/`sha-*`/`latest` 标签推送，以及远端 manifest 检查。缓存保存在被 Git 忽略的 `build/release-cache`。

发布后：

```bash
docker pull "${image}:${version}"
docker buildx imagetools inspect "${image}:${version}"
docker image inspect "${image}:${version}" \
  --format '{{json .RepoDigests}}'
```

## 4. Fedora Linux + Docker Engine

### 4.1 安装和权限

使用 Docker 官方 Fedora 仓库安装 Docker Engine、Buildx 与 Compose plugin。典型安装流程如下；Fedora/DNF 大版本变化时应以 Docker 官方 Fedora 安装页的当前命令为准：

```bash
sudo dnf -y install dnf-plugins-core
sudo dnf config-manager --add-repo https://download.docker.com/linux/fedora/docker-ce.repo
sudo dnf -y install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo systemctl enable --now docker
```

可以始终使用 `sudo docker`。若将维护者加入 `docker` 组，必须理解该组等价于主机 root 权限：

```bash
sudo usermod -aG docker "$USER"
newgrp docker
```

确认环境：

```bash
docker version
docker buildx version
docker buildx inspect --bootstrap
docker buildx ls
```

### 4.2 登录、发布、验证

```bash
read -rp 'GitHub username that owns the PAT: ' ghcr_user
read -rp 'GHCR image owner (personal account or organization): ' image_owner
case "$ghcr_user" in ''|*[!A-Za-z0-9-]*|-*|*-) echo 'invalid GitHub user' >&2; exit 64 ;; esac
case "$image_owner" in ''|*[!A-Za-z0-9-]*|-*|*-) echo 'invalid image owner' >&2; exit 64 ;; esac
image_owner="${image_owner,,}"
image="ghcr.io/${image_owner}/web-camera-monitor-wall"
version="v1.1"

read -rsp 'GHCR personal access token: ' ghcr_token
printf '%s' "$ghcr_token" | docker login ghcr.io -u "$ghcr_user" --password-stdin
unset ghcr_token
echo

./scripts/release-image-local.sh "$image" "$version"

docker pull "${image}:${version}"
docker buildx imagetools inspect "${image}:${version}"
docker image inspect "${image}:${version}" \
  --format '{{json .RepoDigests}}'
```

AMD 机器还应运行实际硬件检查：

```bash
test -e /dev/dri/renderD128
vainfo --display drm --device /dev/dri/renderD128
docker run --rm --device /dev/dri/renderD128:/dev/dri/renderD128 \
  "${image}:${version}" \
  vainfo --display drm --device /dev/dri/renderD128
```

产品容器的入口不是通用 shell，因此最后一条若被入口拦截，可改用同版本镜像配合 `--entrypoint vainfo`：

```bash
docker run --rm --device /dev/dri/renderD128:/dev/dri/renderD128 \
  --entrypoint vainfo "${image}:${version}" \
  --display drm --device /dev/dri/renderD128
```

## 5. Fedora 上使用 Podman 的简化替代

Podman 可以直接构建和推送普通 OCI 镜像，但不会自动复现本项目 Buildx `--sbom`/`--provenance=mode=max` 的发布证明。因此正式 release 推荐上一节的 Docker Buildx；Podman 更适合本地验证或应急镜像：

```bash
read -rp 'GitHub username that owns the PAT: ' ghcr_user
read -rp 'GHCR image owner (personal account or organization): ' image_owner
case "$ghcr_user" in ''|*[!A-Za-z0-9-]*|-*|*-) echo 'invalid GitHub user' >&2; exit 64 ;; esac
case "$image_owner" in ''|*[!A-Za-z0-9-]*|-*|*-) echo 'invalid image owner' >&2; exit 64 ;; esac
image_owner="${image_owner,,}"
image="ghcr.io/${image_owner}/web-camera-monitor-wall"
version="v1.1"

read -rsp 'GHCR personal access token: ' ghcr_token
printf '%s' "$ghcr_token" | podman login ghcr.io -u "$ghcr_user" --password-stdin
unset ghcr_token
echo

revision="$(git rev-parse HEAD)"
podman build --arch amd64 -f docker/Dockerfile \
  --label "org.opencontainers.image.revision=${revision}" \
  --label "org.opencontainers.image.version=${version}" \
  -t "${image}:${version}" .
podman push "${image}:${version}"
```

## 6. 发布后记录与生产锁定

读取最终 digest：

```bash
IMAGE=ghcr.io/your-user-or-organization/web-camera-monitor-wall
VERSION=v1.1
docker buildx imagetools inspect \
  "${IMAGE}:${VERSION}"
```

生产 Compose 不应长期依赖可移动的 `latest`，应记录并使用：

```yaml
image: ghcr.io/your-user-or-organization/web-camera-monitor-wall@sha256:<manifest-digest>
```

同时记录源码 revision、版本、发布时间和 digest。若发布失败，不要删除或覆盖已经被部署引用的版本；修复问题后创建新版本。若 token 疑似泄漏，立即在 GitHub 撤销 token、执行 `docker logout ghcr.io`，检查 package 活动和本地 Docker credential store。
