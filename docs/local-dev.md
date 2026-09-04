# Local `dev` loop / `dev` 本地开发循环

These helpers run the current protected `dev` checkout without publishing to
GHCR. They keep a local image tag (`webobs:dev` by default), start the backend
with Docker Compose, and optionally run the Vite frontend with hot reload.

这两个入口脚本只针对当前 `dev` 工作树，不会创建 Tag、登录 GHCR 或执行
`docker push`。默认使用本地镜像 `webobs:dev`，后端由 Docker Compose 运行，
前端可选用 Vite 热更新。基础 Compose 只绑定主机回环地址并关闭集群
RBAC 认证，因此本地开发不会要求用户名和密码；不要把该基础配置暴露到局域网。

## Windows PowerShell

From the repository root:

```powershell
.\scripts\dev-local.ps1 start -Frontend -Open
```

Open `http://127.0.0.1:5173/`. Vite proxies `/api` to the local backend at
`http://127.0.0.1:8080`; the bundled-image UI is available at
`http://127.0.0.1:8080/`.

常用命令：

```powershell
.\scripts\dev-local.ps1 status
.\scripts\dev-local.ps1 logs -Tail 200
.\scripts\dev-local.ps1 debug
.\scripts\dev-local.ps1 test
.\scripts\dev-local.ps1 build
.\scripts\dev-local.ps1 hotfix
.\scripts\dev-local.ps1 stop
```

`hotfix` 重新构建本地镜像并强制重建 `webobs` 容器，但不会发布任何远程
镜像。只改前端时保持 `start -Frontend` 运行即可；只改后端或 Dockerfile
时执行 `hotfix`。

## Linux / WSL2

From the repository root:

```bash
./scripts/dev-local.sh start --frontend --open
```

如果 WSL2 没有图形化 `xdg-open`，直接在 Windows 浏览器打开
`http://127.0.0.1:5173/`。常用命令：

```bash
./scripts/dev-local.sh status
./scripts/dev-local.sh logs --tail 200
./scripts/dev-local.sh debug
./scripts/dev-local.sh test
./scripts/dev-local.sh build
./scripts/dev-local.sh hotfix
./scripts/dev-local.sh stop
```

脚本要求当前分支为 `dev`。对于一次性实验可以显式增加
`--allow-non-dev`（或 PowerShell 的 `-AllowNonDev`），但不要用它绕过发布
脚本的受保护分支检查。

## Test levels / 测试级别

`test` 默认执行公开仓库审计、TypeScript 检查、IWA 类型检查和本地
Playwright 测试；`test --full`（PowerShell 为 `test -Full`）运行完整的
本地无产品镜像构建验收套件。它要求传入的产品镜像和测试夹具镜像已经存在，
使用 `-Image`/`--image` 选择镜像，不会执行 Docker build、GHCR 登录或 push。

例如使用现有本地候选镜像：

```powershell
.\scripts\dev-local.ps1 test -Full -Image webobs:v3.1-dev-current
```

```bash
./scripts/dev-local.sh test --full --image webobs:v3.1-dev-current
```

完整套件会运行公开审计、依赖锁、Python 单元测试、PWA/Playwright、M0–M9
确定性夹具、NVR、备份、TLS、权限、True Direct 和升级回归。`--long`/`-Long`
额外运行 M7 的 8/16/32 路 900 秒和故障注入门禁。

私有 RTSP、证书、账号、录像和浏览器 Profile 只能放在 Git 忽略的 `.env`
或仓库之外；脚本不会打印 `.env` 内容，也不会把私有门禁原始结果上传。

若要在本机验证登录/Session/RBAC，请按部署文档创建 `secrets/` 下的凭据文件，
并额外使用 `compose.m6-auth.yaml` 覆盖；该覆盖会重新启用集群认证。基础开发模式
没有预置用户名或密码。

不要用 `docker compose down --volumes` 做日常停止操作，否则会删除本地
Registry、Scene 和 Session 数据。
