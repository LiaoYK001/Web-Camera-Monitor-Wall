# v2.3 release notes / 发布说明

`v2.3` completes v2-M7 while preserving the default single-image `standalone` deployment and the existing Local-first PWA media boundary. It adds optional multi-node recording, multi-volume and S3 storage, deny-by-default RBAC, ecosystem integrations, and encrypted recovery. Native EXE/APK packages remain frozen and are not release artifacts.

`v2.3` 完成 v2-M7，同时保留默认单镜像 `standalone` 部署和既有 Local-first PWA 媒体边界。本版本增加可选多节点录像、多卷与 S3 存储、默认拒绝 RBAC、生态集成和加密恢复。原生 EXE/APK 继续冻结，不属于发布产物。

## Highlights / 主要改动

- The same signed image supports `standalone`, `controller`, `recorder`, and `worker` roles. Controller/Recorder traffic uses TLS 1.3 mTLS, one-time enrollment, renewable node certificates, 5-second heartbeats, 30-second leases, generation fencing, and a bounded 120-second isolation window / 同一签名镜像支持 `standalone`、`controller`、`recorder` 和 `worker` 角色；Controller/Recorder 通信使用 TLS 1.3 mTLS、一次性注册、可续签节点证书、5 秒心跳、30 秒租约、generation fencing 与有界 120 秒隔离窗口。
- Five built-in roles (`admin`, `operator`, `viewer`, `auditor`, `exporter`) enforce server-side permissions and Camera/Group scopes across REST, WebSocket, media, PTZ, talk, playback, export, settings, metrics and administration. Passwords use pinned libsodium Argon2id and disabled users lose every active Session / 五种内置角色在服务端为 REST、WebSocket、媒体、PTZ、对讲、回放、导出、设置、指标与管理入口执行权限及 Camera/Group scope；密码使用固定 libsodium Argon2id，停用用户会失去全部活动 Session。
- Recorder placement supports multiple pre-mounted volumes, stable weighted selection, watermarks, read-only/degraded states, verified migration and daily integrity scrub. Optional S3-compatible archive uses HTTPS SigV4, a bounded two-worker queue, digest verification and safe local-release rules / Recorder 放置支持多个预挂载卷、稳定加权选择、水位、只读/降级状态、验真迁移和每日完整性巡检；可选 S3 兼容归档使用 HTTPS SigV4、有界双 Worker 队列、摘要校验和安全本地释放规则。
- Capacity-aware scheduling accounts for CPU, memory, decode/encode slots and disk bandwidth. Assignments carry task type and cost, and mTLS job results require the current owner and generation; overload is rejected explicitly instead of silently falling back to CPU / 容量调度统计 CPU、内存、解码/编码槽位与磁盘带宽；分配携带任务类型和成本，mTLS 任务结果要求当前所有者与 generation；过载会显式拒绝，不静默回落 CPU。
- MQTT/Home Assistant discovery, signed Webhooks and external Provider v1 use bounded queues, stable schemas, SSRF protection and short-lived single-use media grants. They never expose camera credentials, cluster keys or arbitrary filesystem access / MQTT/Home Assistant Discovery、签名 Webhook 与外部 Provider v1 使用有界队列、稳定 Schema、SSRF 防护和短期单次媒体授权，不暴露摄像机凭据、集群密钥或任意文件系统访问。
- Upgrade snapshots protect v2.2→v2.3 migration. Independent-key XChaCha20-Poly1305 backups cover configuration, catalogs, audit and identities with isolated verification before atomic restore; recordings remain outside the default backup / 升级快照保护 v2.2→v2.3 迁移；独立密钥 XChaCha20-Poly1305 备份覆盖配置、目录、审计和身份，并在原子恢复前隔离验真；录像默认不进入备份。

## Media and security boundary / 媒体与安全边界

- Approved HTTPS WHEP/HLS/MJPEG may remain `Camera → Browser`; ordinary RTSP and an explicit HTTP-camera exemption remain `Camera → Docker → Browser` and are never described as True Direct.
- `standalone` remains the zero-cluster default. Port `9443` is opened only for an explicitly enabled Controller and must stay on a private network or user-managed VPN.
- Logs, Issues, WebSocket events, backup manifests, receipts and public artifacts contain no camera endpoint, credential, node private key, host path, recording, or real network identity.
- v2.3 does not include Controller automatic HA, hosted multi-tenancy, vendor P2P cloud, AI detection, production IWA, EXE, or APK.

## Release artifacts / 发布产物

- GHCR image: `ghcr.io/liaoyk001/web-camera-monitor-wall:v2.3`
- Moving stable alias: `ghcr.io/liaoyk001/web-camera-monitor-wall:latest`
- Exact source/image traceability: immutable `v2.3`, `sha-<12>` and OCI digest
- Recursive corresponding-source archive and SHA-256, OCI SBOM, provenance and attestation

The version and `latest` tags are promoted from the already-tested `sha-*` candidate manifest without rebuilding. Production deployments should pin the verified digest / 版本标签与 `latest` 从已经验收的 `sha-*` 候选 manifest 提升，不重新构建；生产部署应固定经验证的 digest。
