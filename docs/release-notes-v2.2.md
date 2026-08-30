# v2.2 release notes / 发布说明

`v2.2` completes v2-M6 and turns the Local-first PWA into a monitoring operations workspace. Native Windows, Linux and Android packages remain frozen and are not release artifacts.

`v2.2` 完成 v2-M6，将 Local-first PWA 收口为监控运维工作区。Windows、Linux 与 Android 原生包继续冻结，不属于本次发布产物。

## Highlights / 主要改动

- Responsive Monitor, Studio, Devices, Audio, Events, Playback, Storage and Settings workspaces with stable Hash routes / 响应式监看、Studio、设备、音频、事件、回放、存储和设置工作区，并提供稳定 Hash 路由。
- Camera Registry schema v2 with Camera → Profile → Track hierarchy, pagination, atomic batch operations, revisions, tags, groups, protocol selection and bounded probing / Camera Registry v2，提供 Camera → Profile → Track 分层、分页、原子批量操作、Revision、标签、分组、协议选择和有界探测。
- Isolated Profile preview that reuses the topology planner and releases activation leases without starting Composite Program / 复用拓扑规划器的独立 Profile 预览，离开时释放激活租约且不启动 Composite Program。
- Deduplicated Problem Center with safe technical details, acknowledgement, resolution and redacted copy / 带安全技术详情、确认、解决和脱敏复制的问题中心，并对重复问题聚合。
- Per-source Direct Web Audio and on-demand Composite libobs meters, sharing the Scene v5 mute, volume, monitoring, delay and track controls / 逐来源 Direct Web Audio 与按需 Composite libobs 电平，共享 Scene v5 的静音、音量、监听、延迟和输出轨道控制。
- Revisioned runtime settings separated from encrypted browser preferences and read-only deployment configuration / 带 Revision 的运行时设置，与加密浏览器偏好和只读部署配置明确分离。

## HTTP camera exception / HTTP 摄像机豁免

Plain HTTP remains denied by default. An administrator may set `allowInsecureHttp=true` on one HTTP Profile to permit Docker Gateway or NVR ingestion on a trusted LAN or user-managed VPN. The exception is rejected for non-HTTP endpoints, produces a visible warning issue, never exposes credentials or the endpoint in a browser Grant, and never qualifies an HTTPS PWA for Camera→Browser True Direct. The resulting plan reports `browser_https_required` with Docker as the execution owner.

明文 HTTP 默认仍被拒绝。管理员可在单个 HTTP Profile 上设置 `allowInsecureHttp=true`，仅允许可信局域网或用户自管 VPN 中的 Docker Gateway/NVR 接入。非 HTTP 端点不能使用该开关；启用后会产生明确告警；浏览器 Grant 不包含凭据或端点；HTTPS PWA 也绝不会因此获得 Camera→Browser 真直连资格。对应拓扑会报告 `browser_https_required`，执行端仍为 Docker。

## Media boundary / 媒体边界

Approved HTTPS WHEP, HLS and Server Push MJPEG can remain Camera→Browser. Ordinary browser RTSP and approved plain HTTP media remain explicit Gateway/Hybrid paths through Docker. The source catalog, preview, issues, settings and audio controls do not place Docker into an otherwise qualified True Direct media path.

获批的 HTTPS WHEP、HLS 与 Server Push MJPEG 可以保持 Camera→Browser。普通浏览器 RTSP 与获批的明文 HTTP 媒体仍明确使用经过 Docker 的 Gateway/Hybrid。来源目录、预览、问题、设置和音频控制不会把 Docker 加入原本满足条件的真直连媒体链。

## Qualification disclosure / 验收披露

The final revision passed the public repository audit, production PWA build, deterministic Registry/event/v2 service tests, Docker image build, Windows Chrome/Edge short gate and WSL2 Chromium short gate. The private receipts cover the three direct protocols, explicit RTSP fallback, zero server-media increment, revocation, background release, installation, offline shell and update behavior. The optional 16-stream/30-minute qualification was not executed and is not claimed by this release.

最终提交通过公开仓库审计、正式 PWA 构建、确定性 Registry/事件/v2 服务测试、Docker 镜像构建、Windows Chrome/Edge 短门禁与 WSL2 Chromium 短门禁。私有回执覆盖三种直连协议、明确 RTSP 回退、零服务端媒体增量、撤销、后台释放、安装、离线应用壳和升级行为。可选的 16 路 30 分钟资格测试未执行，本发布不声明该性能结果。

## Artifacts / 发布产物

- GHCR image: `ghcr.io/liaoyk001/web-camera-monitor-wall:v2.2`
- Immutable source Tag: `v2.2`
- Recursive corresponding-source archive and SHA-256 sidecar / 递归对应源码包及 SHA-256 校验文件
- OCI SBOM, provenance and attestation / OCI SBOM、provenance 与 attestation

Production deployments should pin the published manifest digest rather than the movable `latest` alias / 生产部署应固定发布后的 manifest digest，而不是长期依赖可移动的 `latest`。
