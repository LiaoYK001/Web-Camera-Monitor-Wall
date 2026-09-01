# v2.3 扩展、生态与韧性

> 状态：`dev / v2-M7` 开发中。本文描述当前实现契约和发布门禁，不代表 `v2.3` 已发布。

## 部署角色

同一 OCI 镜像通过 `WEBOBS_NODE_ROLE` 运行四种角色：

| 角色 | 职责 | 对外端口 |
| --- | --- | --- |
| `standalone` | 现有单机控制面、媒体与可选 NVR | 现有 HTTP/HTTPS/WebRTC 端口 |
| `controller` | PWA、Registry、RBAC、策略、目录和调度 | 现有控制端口；启用集群后另有私网 `9443/tcp` |
| `recorder` | NVR、多卷目录和节点代理 | 不开放公共控制端口 |
| `worker` | 导出与未来 Detector 预留 | 不开放公共控制端口 |

`standalone` 仍为默认值。只有 `controller` 且显式设置 `WEBOBS_CLUSTER_LISTEN=true` 时才监听集群端口。集群端口必须只位于可信私网或自管 VPN；它使用 TLS 1.3 和节点 mTLS，不应暴露到互联网。

首次用 v2-M7 镜像启动现有 `/config/webobs` 时，入口会在任何服务迁移 SQLite 前创建一次 SHA-256 校验的一致性快照。快照位于 `/config/webobs/.upgrade-backups/`，目录权限为 `0700`、文件权限为 `0600`；核心进程未能启动时，入口先停止所有子进程，再从已完整验真的快照回滚。容器在文件仍可能被子进程写入时不会冒险恢复，而会保留带认证路径约束的 pending 标记，并在下一次安全启动前完成回滚。成功启动会写入 v2-M7 完成标记，因此重启不会不断复制备份。

升级快照是同一受保护配置卷内的本地明文恢复点，不能代替下面使用独立密钥的加密灾备。部署者应像保护 Registry 和 Scene 一样限制该卷的主机访问；升级确认稳定后可以按运维保留策略人工归档或删除旧快照，但程序不会自动删除这一最后恢复点。

## 身份、RBAC 与节点注册

身份库使用 SQLite WAL 和 libsodium Argon2id。内置角色为 `admin`、`operator`、`viewer`、`auditor`、`exporter`；REST、WebSocket、媒体、PTZ、对讲、录像和管理操作都由服务端按权限及 Camera/Group scope 再次校验。登录成功、登录拒绝/限流以及权限/范围拒绝进入有界审计：成功只记录稳定 User ID，失败统一使用 `anonymous`，不保存提交用户名、客户端键、地址、正文或端点。用户被停用或删除后，其下一次受保护请求会原子撤销该用户名的全部浏览器 Session 并清除当前 Cookie；普通权限不足只拒绝当前操作，不会注销合法 Session。兼容 Secret-file 管理员可通过 `WEBOBS_COMPAT_BASIC_AUTH=false` 关闭；Cluster 启动时会确认身份库至少存在一个已启用的 `admin`，否则 fail-closed，避免把维护者锁在系统外。环境变量只接受精确的 `true | false`。

节点注册流程：

1. 管理员创建十分钟的一次性 Enrollment；数据库只保存 token 摘要。
2. 节点本地生成 Ed25519 私钥和 CSR，私钥不离开节点。
3. 管理员批准后，Controller 用挂载的集群 CA 签发 30 天节点证书。
4. 节点使用证书 URI SAN `webobs-node:<id>` 建立 mTLS；请求头中的节点 ID 只能与已经验真的唯一 SAN 绑定，不能独立作为身份。
5. 剩余七天时节点自动续签。撤销后在线请求立即拒绝，离线节点最迟在证书到期时失效。

集群 CA 私钥、服务端私钥、节点私钥、Enrollment token 与内部管理 token 都必须通过 `/run/secrets` 或节点私有状态卷提供。公开日志和问题中心只记录稳定 ID 与错误码。

## Recorder 租约与故障边界

- 心跳每 5 秒；20 秒无心跳后节点显示离线。
- 录像租约为 30 秒，Recorder 每 10 秒续租。
- Controller 失联后，Recorder 最多依据最近有效分配继续 120 秒；之后清空活动分配。
- Controller 在隔离期限结束前不会把同一 Camera 重新分配给另一节点。
- 每次重分配使用递增 `generation`；旧 generation 的续租和 Catalog 更新均被拒绝。
- 节点时钟偏差超过 5 秒时拒绝新工作并返回明确状态。

恢复连接后，节点先上传有界 Catalog 批次并同步分配，再继续工作。冲突 Segment 保留并标记，不自动删除证据文件。

Recorder Catalog 对账会同时提交 UTC 起止时间、时长、类型、编解码器、锁定状态以及稳定的 Camera/Profile/Segment/Node/Volume ID。Controller 的跨节点目录和最近时间线不保存或返回 Recorder `storageKey`、主机路径、S3 object key 或媒体端点；旧节点未上报时间元数据的历史行继续保留，但不会伪造为可定位时间线片段。PWA 运维页按节点、卷和归档状态展示这一脱敏目录。

## 多存储卷与 S3

主机只能把预先创建的卷挂载到 `/recordings/volumes/<volumeId>`；API 不接受主机路径。卷策略包含 `hot|warm|archive` 层级、保留空间、高/低水位和 `online|degraded|read-only|evacuating|offline` 状态。

写入只选择 `online`、可写、低于高水位且满足 reserve 的卷。高水位或 `evacuating` 会停止新分配，并只迁移未锁定、无活动读者的完整 Segment。迁移顺序固定为复制、SHA-256 校验、目录原子切换、删除源文件；失败时保留源文件并标记问题。每日巡检跳过正在写入或读取的 Segment。

S3 归档只允许 HTTPS authority、AWS Signature v4 和 `/run/secrets` 下的凭据引用。每节点最多两个上传，队列最多 4096 项，5 秒至 5 分钟退避。只有对象大小和 SHA-256 metadata 都验证成功后才标为 `uploaded`。本地文件不存在时可按需恢复到有界缓存；恢复过程中再次校验大小和摘要。任何校验失败都不会自动删除本地证据。

Controller 可为已完成、已校验且 Camera scope 匹配的归档片段签发 60 秒 SigV4 只读票据。PWA 不保存该 URL，使用无凭据、无重定向、无缓存请求完整下载最多 512 MiB 的单片，并在本地重新校验长度和 SHA-256 后才播放。Archive Target 必须配置浏览器 Origin 的精确 GET CORS，且该 Origin 还必须进入 PWA CSP 白名单；长期 S3 Secret 始终只从 `/run/secrets` 读取。

## 资源、Provider 与灾备

节点报告实际 runtime probe、CPU、内存、编解码槽位、磁盘和 Reservations。调度优先级为录像、Gateway/Composite、导出、Detector 预留；容量不足时显式拒绝，不静默切到 CPU。未校准节点为 `unrated`，使用保守容量。8/16/32 路结果只分别描述 stream-copy 资格，不能推断转码能力。

外部 Provider 只得到稳定任务 ID 和最长 60 秒的单次媒体授权。授权 token 仅存 SHA-256，消费后重放失败，响应不含 Camera Secret、数据库路径或集群 CA。Controller 只保存稳定 ID、`offered | media-opened | expired` 状态和固定结果码，不落盘任务参数与 token 明文；任务在 60 秒窗口内占用 Provider 并发额度，超时自动释放。录像读取还会核对 Catalog 中 `segmentId + cameraId + profileId` 的绑定，只代理对应只读片段；无法建立绑定的旧记录保持 fail-closed，直到 Recorder 完成重新对账。实时 Detector 媒体仍为预留能力，不会因此取得 Camera Secret 或自动启动新媒体链。Provider 超时或失败不会改变 Recorder 分配、租约或连续录像状态。

加密备份每 15 分钟生成一次，使用独立 32 字节 `WEBOBS_BACKUP_KEY_FILE` 和 XChaCha20-Poly1305 流式加密。恢复先在隔离目录验证 AEAD、SHA-256、SQLite integrity、Schema 和安全路径，再原子切换。备份默认不包含录像；恢复后重新对账本地卷与 S3 Manifest。目标为配置/目录/审计数据 `RPO ≤ 15 分钟`、干净安装 `RTO ≤ 30 分钟`。

## 确定性本地门禁

`tests/m7/compose.yaml` 提供只含合成数据的 Controller、三个 Recorder、三个卷、MinIO、Mosquitto、MediaMTX 和 FFmpeg 发布器。所有生成证书、口令、数据库、录像和回执位于 Git 忽略的 `tests/.m7-cluster/`。

```bash
# WSL2/Fedora；正式资格每档运行 900 秒
export WEBOBS_IMAGE=webobs:m7-candidate
export WEBOBS_M7_CAMERA_COUNT=8       # 分别使用 8、16、32
export WEBOBS_M7_GATE_SECONDS=900
./tests/m7/run-gate.sh
```

对 `8`、`16`、`32` 三档分别运行一次会生成仅含当前 Git revision、完成时间、时长和检查项名称的 `build/private-gates/m7-scale-*.json`。故障注入另行执行：

```bash
./tests/m7/run-fault-gate.sh
python3 scripts/verify-m7-gate-receipts.py
```

Windows 宿主机还需在本机 Chrome 与 Edge 执行运维工作区门禁。该入口使用同一合成集群，为控制面和 MinIO 生成临时 CA/HTTPS 证书；浏览器仅在本次私有夹具进程中忽略该临时 CA 的系统信任错误，应用仍运行于 Secure Context，CORS、CSP、无重定向归档下载和 SHA-256 校验保持启用。生成的随机用户、Session、证书、录像和 Playwright 输出全部位于 Git 忽略目录，脚本退出时删除容器与匿名卷。

```powershell
.\tests\m7\run-windows-admin-gate.ps1 -Image webobs:m7-candidate -Browser both
```

Chrome 与 Edge 都通过后才写入 `build/private-gates/windows-m7-admin.json`。门禁覆盖五种内置角色、Camera/Group scope、被停用 Session、节点/卷 UI、跨节点时间线、浏览器本地 S3 摘要复核及离线 PWA 应用壳。Group scope 由服务端按稳定 Camera ID 查询共享 Registry；Registry 缺失、未知 Camera 或无效 Group ID 均 fail-closed。

故障门禁使用相互独立的控制网和媒体网，按生产常量验证 20 秒节点健康边界、120 秒 Recorder 隔离录像、mTLS 重连、MinIO 中断续录/恢复、只读卷拒绝、真实 TLS MQTT/Home Assistant 发布及容器内 libsodium 灾备恢复。最后一个验证命令还要求同一 revision 的 Windows RBAC/节点/存储/PWA 运维回执；缺失、过期、时长不足或包含未知字段都会拒绝发布。

该门禁只使用合成端点。真实节点、真实 S3、六小时耐久与真实网络分区证据仍只保存在维护者私有环境，不进入 Git 或公开 Artifact。

## 发布边界

稳定发布脚本先构建并推送唯一 `sha-<revision>` 候选，随后创建 Draft GitHub Release、生成并核验递归对应源码包，发布 Release 后才使用候选 manifest digest 创建 `v2.3` 与 `latest`。提升阶段不会再次构建镜像。任何已发布版本 Tag 和 Release Asset 都不得覆盖。

v2.3 不包含 Controller 自动高可用、托管多租户、厂商 P2P 云、AI 检测、EXE/APK 或生产 IWA Bundle。
