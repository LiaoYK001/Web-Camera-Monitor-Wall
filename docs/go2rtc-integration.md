# go2rtc 与官方 WebUI 集成 / Integrated go2rtc and WebUI

项目将完整 go2rtc 与官方 WebUI 打包进同一个产品镜像，默认随 standalone/controller 启动。来源经 go2rtc 整理后输出 RTSP，再接入现有设备注册、MediaMTX、NVR 和 OBS；普通 RTSP 也可直接接入。

```text
各种来源 → go2rtc + 官方 WebUI → 内部 RTSP → Camera Registry → MediaMTX → 监控墙
                                                        ↘ OBS → Program / 录像
普通 RTSP ───────────────────────────────→ Camera Registry
```

go2rtc 负责协议适配和按需转换；MediaMTX 负责分发；OBS 负责合成。启用桥接不会自动启用 Composite 或为所有来源转码。

The complete upstream module and official WebUI ship in one product image. go2rtc adapts sources with optional FFmpeg conversion; MediaMTX distributes media and OBS composes scenes. Direct RTSP ingestion remains available.

## 使用流程

网站与直播支持新增内置 yt-dlp、Streamlink、Node/EJS 与按需 FFmpeg 转发；容器/Windows x64 打包工具，Android 使用同一后端。固定参数、私密 Cookie、重启影响与验证边界见[网站与直播源](online-sources.md)。Bundled website extraction is shared by the three primary clients through their selected backend.

1. 使用产品账号登录后打开 **go2rtc 管理**（`/#/go2rtc`），需要 `settings.manage` 权限。本地开发同样默认启用账号控制面；没有独立的上游登录绕过入口。
2. 在“设备与发现”使用官方工具，或在“配置”编辑完整 YAML。流管理、播放测试、Links、连接信息/连接图、日志和高级页面全部保留，也可独立打开。
3. 官方 “Save & Restart” 保存配置并重新加载 go2rtc；返回流列表测试播放。
4. 在项目“设备与来源”添加 `rtsp://127.0.0.1:18554/流名称`，通过正常探测、注册和场景流程使用。此地址指 **后端所在环境**（容器或 WSL），不是浏览器所在电脑。特殊流名称需要 URL 编码。
5. 修改或删除流时同步维护项目来源。go2rtc 和 Camera Registry 使用各自模型，当前不会自动建立或删除摄像机记录。

配置和日志可能含设备凭据，管理入口仅供管理员使用；普通监看账号使用项目原有播放器。权限不足或服务不可用会显示状态并支持重试。

## 统一部署与端口

```sh
git submodule update --init --recursive
docker compose up --build -d
```

| 入口 | 默认值 | 用途 |
| --- | --- | --- |
| 项目页面 | `http://127.0.0.1:8080/#/go2rtc` | 工作台 |
| 官方 UI/API | `/api/v1/go2rtc/` | 产品登录、Host、Origin、RBAC |
| 内部 HTTP | `127.0.0.1:11984` | 固定上游，不发布管理端口 |
| 内部 RTSP | `127.0.0.1:18554` | MediaMTX、NVR、OBS 拉取 |
| WebRTC | `18555` TCP/UDP | 官方预览/对讲媒体 |

基础 Compose 仅向主机回环发布产品入口和媒体端口，不发布 go2rtc HTTP/RTSP。远程部署沿用 HTTPS/认证配置，将 `WEBOBS_WEBRTC_ADDITIONAL_HOSTS` 设置为实际主机 IP。overlay 若使用 `ports: !override`，需按需保留 `18555` TCP/UDP；否则可使用官方 MSE 预览。设备发现、USB、HomeKit 广播仍需要对应网络/设备挂载，云协议需要有效账号；完整源码不代表每种设备已验收。

`WEBOBS_GO2RTC_ENABLED=false` 可关闭桥接。镜像已有 FFmpeg/Python，官方 UI 资源本地打包：Monaco `0.55.1`、js-yaml `4.1.0`、vis-network `10.0.2`、qrcodejs `1.0.0`、hls.js `1.7.1`，配置编辑器无需 CDN。厂商云服务与外部链接仍需网络。

## 配置与生命周期

首次启动创建 `/config/webobs/go2rtc/go2rtc.yaml`；整个私有目录随现有 `webobs-config` 卷保存。文件 `0600`、目录 `0700`，不覆盖已有配置。现有加密配置备份与升级快照覆盖该目录；旧版 `docker/backup.sh` 定项备份不包含它，单独使用该脚本时另行备份私有目录。

监督器通过最后一个运行时配置覆盖固定 API 绑定、API 前缀、静态目录、RTSP 回环绑定和 WebRTC 的 `18555` 媒体端口；编辑器修改这些字段也不会打开管理端口。其他模块使用官方配置。可用 `WEBOBS_GO2RTC_CONFIG` 指定私有文件、`WEBOBS_GO2RTC_WEB_ROOT` 指定已准备的 UI；自定义路径应纳入自己的备份策略。

保存重启保持监督器运行；异常退出有有界重试，反复失败会报告服务失败。停止产品时终止 go2rtc 和 FFmpeg/exec 子进程组。Docker 输出经现有日志脱敏器；管理 UI 内原始诊断仅由管理员查看，不要提交配置/日志到 Git。

容器入口使用每次启动独立的私密 tmpfs 目录存放日志 FIFO，并对启动失败和停服统一清理；强制终止后不会复用遗留管道。旧版本 `mkfifo ... File exists` 的原因与恢复验证见[容器重启与恢复](container-restart-recovery.md)；修复留到 v4.0，历史 v3.5 热修不作为当前操作步骤。Container restart recovery and bounded shutdown are documented there.

HTTP 代理持续转发媒体，不积累整个响应；WebSocket 双向传输使用固定缓冲与背压。连接经过产品认证和 `settings.manage`；变更请求/WebSocket 要求匹配 Origin，拒绝路径穿越和跨站请求，产品凭据/内部身份头不转发给上游。官方页面使用独立 CSP，主工作台保留原有脚本限制；API 路径属于 PWA NetworkOnly 区域，不进入离线缓存。

## 开发与版本

native 启动器 `scripts/dev.ps1` / `scripts/dev.sh` 自动准备 UI，下载并校验固定 Linux amd64 go2rtc，与其他服务共同启停；无需安装 Go。配置位于启动器缓存目录 `data/go2rtc/go2rtc.yaml`，默认入口 `http://127.0.0.1:5173/#/go2rtc`。直接运行 `scripts/dev-native.py` 前，在 `web/` 执行 `pnpm install --frozen-lockfile` 与 `pnpm go2rtc:ui`。WSL/LAN WebRTC 需确保 `18555` 可达；MSE 可经同源 WebSocket 播放。

完整上游在 `go2rtc/go2rtc/` 子模块，固定 [v1.9.14](https://github.com/AlexxIT/go2rtc/releases/tag/v1.9.14)、提交 `b5948cfb25404cc5cb37b166ecaa2dca20b11d4b`，MIT 许可。`go2rtc/dependencies.lock.json` 记录版本/提交/原生二进制 SHA-256。Docker 编译完整模块，固定 Go 构建镜像与 `go.sum`；无 Git 构建上下文时上游版本显示 `1.9.14+dev.`，源码身份由锁文件记录。

镜像 `/usr/share/licenses/go2rtc/` 包含上游许可证、模块清单、依赖许可证归档及锁文件；UI vendor 目录保留依赖许可证。源码包递归包含完整上游并在 `SOURCE-REVISION` 记录 `go2rtc_revision`。升级时同步更新子模块、锁文件、二进制校验值、UI 版本与替换规则，再运行下列检查；不要直接改上游 checkout。

```sh
python -m unittest discover -s tests -p test_go2rtc_runtime.py
python tests/test_go2rtc_integration.py --image webobs:go2rtc-dev
cd web
pnpm go2rtc:ui
pnpm build
pnpm test:local -- go2rtc.spec.ts
```

MJPEG 示例：摄像机网页首页不是媒体地址。Canon VB-C60 WV-HTTP 可按 [配置示例](../deploy/go2rtc.example.yaml)，把已确认的媒体 URL 加入 `streams` 并按需转为 H.264，再将内部 RTSP 加入项目；该示例仅转换视频，不虚构音轨。

参考：[上游仓库](https://github.com/AlexxIT/go2rtc)、[API/子路径](https://github.com/AlexxIT/go2rtc/blob/v1.9.14/internal/api/README.md)、[FFmpeg](https://github.com/AlexxIT/go2rtc/blob/v1.9.14/internal/ffmpeg/README.md)。
## 命名流与正式设备的联动

go2rtc 页面、设备目录和“添加设备”页自动列出已配置命名流（每 15 秒及页面重新获得焦点时刷新）。读取仍通过 `/api/v1/go2rtc/api/streams` 和现有 `settings.manage` 权限；列表只展示流名和本产品的内部 RTSP 地址，不展示上游 URL、producer 详情或摄像机凭据。

1. 在 go2rtc 中添加命名流，保存配置，并使用官方 WebUI 测试播放。
2. 返回“设备与来源”，在“从 go2rtc 接入设备”刷新列表，点击“检测并添加设备”。系统检测 `rtsp://127.0.0.1:18554/<流名>`、创建设备与 Profile，然后探测轨道。已有相同内部地址的设备显示“已在设备目录”，避免再次导入。
3. 在设备详情检查轨道和状态；失败时先检查 go2rtc，再重试探测。流建档后即便轨道暂不可用，设备仍保留并显示重试提示。
4. 在 Studio 新建或右键场景 → 选择场景来源，选择设备、调整位置并保存；不同 Scenes 可分别打开投影。

命名流不是需要重新进行 ONVIF 扫描的实体设备；仅经 RTSP 中转时不继承 PTZ/ONVIF 控制。流名变更或删除需同步调整已建档设备地址。自动枚举支持最多 256 个由字母、数字、空格、点、下划线和连字符组成的命名流；其他名称可通过手动设备地址接入。
