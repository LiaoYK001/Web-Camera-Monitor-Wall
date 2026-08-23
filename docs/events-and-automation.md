# Events, detection and automation / 事件、检测与自动化

v1-M11 runs as a loopback-only service beside the recorder. Its SQLite WAL database, motion evaluator, detector-provider intake, search API and notification outbox do not own NVR processes. Stopping or overloading analytics therefore cannot directly stop continuous recording.

v1-M11 以仅监听回环地址的独立服务运行在录像器旁侧。其 SQLite WAL 数据库、移动检测器、检测提供器入口、搜索 API 与通知发件箱均不持有 NVR 进程；停止或过载分析服务不会直接停止连续录像。

## Normalized event contract / 统一事件契约

Every event has a stable ID, Camera Registry ID, type, source, UTC occurrence time, severity, optional confidence/zone/label, bounded properties, acknowledgement state and immutable NVR segment references. Supported v1 types are motion, tamper, line/region crossing, object, sound, input, device health, recording failure, manual marker and rule result. Biometric identity, plate identity databases, emotion inference and covert tracking are intentionally excluded.

每个事件包含稳定 ID、Camera Registry ID、类型、来源、UTC 发生时间、严重级别、可选置信度/区域/标签、有界属性、确认状态及不可变 NVR 分段引用。v1 支持移动、遮挡、越线/区域、目标、声音、输入、设备健康、录像失败、人工标记和规则结果；明确排除生物身份、车牌身份库、情绪推断及隐蔽追踪。

## Motion and detector isolation / 移动检测与提供器隔离

- Software motion accepts bounded grayscale frames and normalized polygons. Include zones are evaluated after exclude/privacy masks; sensitivity, debounce and cooldown are applied per camera and zone.
- Detector providers use schema version 1, a declared CPU/GPU/remote class and a bounded batch ceiling. Invalid or absent providers do not change recorder state.
- Native ONVIF PullPoint messages are normalized and forwarded best-effort to the event service. Event intake then asynchronously activates an NVR event window; a fixed post-event timer deactivates it. A failed event service or NVR request is isolated.

- 软件移动检测只接受有界灰度帧与归一化多边形；包含区域先扣除排除/隐私遮罩，再逐摄像机/区域应用灵敏度、去抖与冷却。
- 检测提供器使用 schema v1，声明 CPU/GPU/远程类别并受批量上限约束；无效或缺失提供器不会改变录像器状态。
- 原生 ONVIF PullPoint 消息经归一化后尽力转发到事件服务；事件入库后异步激活 NVR 事件窗口，并由固定后事件定时器关闭。事件服务或 NVR 请求失败均被隔离。

## Rules and notification security / 规则与通知安全

Rules may match camera, type, zone, label, minimum confidence, minimum duration and UTC schedule, with a cooldown. Actions create deduplicated outbox rows. The queue is capped at 4096 rows, expires after 24 hours and retries at most eight times with exponential backoff.

规则可匹配摄像机、类型、区域、标签、最低置信度、最低持续时间与 UTC 计划，并带冷却时间。动作只创建去重后的发件箱记录；队列最多 4096 条，24 小时过期，采用指数退避且最多重试八次。

Webhook and MQTT destinations are Secret references under `/run/secrets/webobs-notifications/<reference>.json`. Webhooks require HTTPS and HMAC-SHA256 signing. Both adapters resolve the destination immediately before connecting and reject loopback, private, link-local, multicast and other non-global addresses to prevent SSRF. MQTT uses TLS and may read username/password from the same mounted Secret. Neither API responses nor SQLite rows contain these credentials.

Webhook 与 MQTT 目标通过 `/run/secrets/webobs-notifications/<引用>.json` 间接引用。Webhook 强制 HTTPS 与 HMAC-SHA256 签名；两种 Adapter 均在连接前解析目标并拒绝回环、私网、链路本地、组播及其他非全局地址，以防 SSRF。MQTT 强制 TLS，并可从同一挂载 Secret 读取用户名/密码。API 响应和 SQLite 均不保存这些凭据。

## Verification boundary / 验证边界

`tests/test_event_service.py` deterministically covers normalization, deduplication, acknowledgement audit, segment linkage, motion ground truth, masks, debounce/cooldown, rule/outbox creation, detector validation and SSRF rejection. These fixtures prove the implementation contract, not real-camera accuracy or delivery through a user's external webhook/MQTT infrastructure.

`tests/test_event_service.py` 确定性覆盖归一化、去重、确认审计、分段关联、移动真值、遮罩、去抖/冷却、规则/发件箱创建、检测提供器校验与 SSRF 拒绝。夹具证明实现契约，不代表真实摄像机准确率或用户外部 Webhook/MQTT 基础设施的交付结果。
