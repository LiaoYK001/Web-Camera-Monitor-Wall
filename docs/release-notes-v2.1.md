# v2.1 release notes / 发布说明

`v2.1` completes v2-M4 and v2-M5 for the Local-first PWA. The native Windows, Linux and Android package experiments remain frozen and are not release artifacts.

`v2.1` 完成 Local-first PWA 的 v2-M4 与 v2-M5。Windows、Linux 与 Android 原生包实验继续冻结，不属于本次发布产物。

## Highlights / 主要改动

- Encrypted, incremental and bidirectional Registry/Scene synchronization with field-level conflicts, tombstones, bounded offline audit and camera display preferences / 加密增量双向 Registry/Scene 同步，包含字段级冲突、墓碑、有界离线审计与摄像机显示偏好。
- IndexedDB schema migration, seven-day encrypted local state, clock-rollback fail-closed behavior and atomic revocation cleanup / IndexedDB Schema 迁移、七天加密本地状态、时钟回拨失效保护与撤销后的原子清理。
- Per-tile FPS/bitrate/codec/decoder telemetry without inventing unavailable measurements / 逐画面 FPS、码率、编码与解码器统计，不伪造浏览器无法提供的测量值。
- Stable Scene v5 auto-layouts for every 1–16 input count, M/S slots, sequential or shuffle-bag rotation, event-promotion contracts and low-power profile selection / 支持 1–16 任意输入数量的稳定 Scene v5 自动布局、M/S 槽位、顺序或 shuffle-bag 轮换、事件提升契约与低功耗 Profile 选择。
- Per-profile analytics controls for future motion, scene-change and person providers; all remain opt-in and local-first / 为后续运动、画面变化与人物 Provider 提供逐 Profile 分析开关，全部保持按需启用与本地优先。
- Backup/restore now preserves and validates Camera Registry, v2 clients/sync state, shared Scenes and the Grant signing key as one security boundary / 备份恢复现在把 Camera Registry、v2 客户端与同步状态、共享 Scene 和 Grant 签名密钥作为一个安全边界完整保存并校验。

## Media boundary / 媒体边界

Approved HTTPS WHEP, HLS and Server Push MJPEG can remain Camera→Browser. Ordinary browser RTSP remains an explicit Gateway/Hybrid path through Docker. Statistics, layout and local policy execution do not place Docker into an otherwise qualified True Direct media path.

获批的 HTTPS WHEP、HLS 与 Server Push MJPEG 可以保持 Camera→Browser。普通浏览器 RTSP 仍明确使用经过 Docker 的 Gateway/Hybrid。统计、布局和本地策略执行不会把 Docker 加入原本满足条件的真直连媒体链。

## Qualification disclosure / 验收披露

The release contract requires revision-bound Windows and WSL2 short media receipts covering direct protocols, RTSP fallback, zero server-media increment, revocation, install/offline/update and background resource release. The maintainer explicitly removed the Chrome 16-stream/30-minute and Edge 4-stream/10-minute runs from the mandatory v2.1 publication gate. This release does not claim those long-duration performance results for the final revision; long load remains optional deployment qualification.

发布契约要求绑定最终提交的 Windows 与 WSL2 短时媒体回执，覆盖直连协议、RTSP 回退、零服务端媒体增量、撤销、安装/离线/升级和后台资源释放。维护者明确把 Chrome 16 路 30 分钟与 Edge 4 路 10 分钟从 v2.1 必发门禁移除。本发布不声明最终提交已获得这些长时间性能结果；长负载仍作为可选部署资格测试。

## Artifacts / 发布产物

- GHCR image: `ghcr.io/liaoyk001/web-camera-monitor-wall:v2.1`
- Immutable source Tag: `v2.1`
- Recursive corresponding-source archive and SHA-256 sidecar / 递归对应源码包及 SHA-256 校验文件
- OCI SBOM and provenance attestations / OCI SBOM 与 provenance 证明

Production deployments should pin the published manifest digest rather than the movable `latest` alias / 生产部署应固定发布后的 manifest digest，而不是长期依赖可移动的 `latest`。
