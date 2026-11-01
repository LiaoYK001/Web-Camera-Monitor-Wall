# 原生控制认证边界 / Native control authorization boundary

## 当前交付与限制 / Delivered scope and limits

这是 renderer-free C++ 库、真实账号授权后端 adapter 与安全回归，不是已接入原生 OBS UI 的账号产品。没有新增 listener、登录入口、服务启动或 OBS 动作执行；不初始化第二媒体/显示引擎。Electron 兼容产品仍为默认入口。不能把库测试通过写成原生产品认证、旧数据迁移或 P3 已验收。

These renderer-free libraries provide persistent-session authorization and a bounded adapter to the existing account service, not a native login product. They start no service or listener, execute no OBS action and leave the compatibility Electron product as the default.

[NativeControlAuth](../core/include/webobs/native_control_auth.hpp) 直接复用 [SessionStore](../core/include/webobs/authentication.hpp) 的 SQLite 持久会话和令牌哈希。[NativeClusterAuthorizationBackend](../core/include/webobs/native_cluster_authorization.hpp) 实现其 fresh RBAC 回调；没有另造 session 协议、Basic 管理员回退或新账号服务。

## 固定命令与检查 / Allowlisted checks

- `read_scene` → `scene.read`；`write_scene` → `scene.write`；`view_camera` → `live.view`。最后一种必须带一个 camera ID；其余允许一个明确 scope。URL、路径、列表和通配符不能作为 camera scope。
- 在访问会话/账号后端前验证真实 socket/IPC 提供的 loopback peer、精确 Origin/authority、字段长度、命令和 scope。配置只接受明确的 loopback HTTP(S) origin，不接受 userinfo、路径、query、fragment、DNS 后缀或宽泛 localhost 子串匹配。
- SessionStore token 必须为 64 位小写十六进制。逐命令检查本地会话并调用最新账号授权，不缓存角色/许可；许可后再验证会话，拒绝后端请求期间发生的 logout。
- 缺失/失效/未绑定的旧会话 `401`（零后端请求）；账号不存在、禁用或身份/认证 epoch 不符时，成功撤销该 username/userId/authEpoch 的全部本地会话后 `401`，不误撤销同名重建或重新登录的新身份。撤销未确认删除记录则保守 `503`，包括数据库删除失败或并发已删除。权限不足 `403`；未配置、后端故障/异常或未知决定 `503`。许可后再检查 username 与完整绑定，拒绝进行中的 logout/身份替换。拒绝不返回 principal、异常详情或 token。

Each native command requires an explicitly bound username/userId/authEpoch session AND a fresh authoritative permission/scope decision. Legacy unbound sessions are rejected before backend I/O, never adopted by username. Revocation targets that exact binding; fresh same-name logins and recreated accounts are preserved. Allowed replies are followed by a complete local identity recheck. This is a decision-time check, not an execution-time fence or reusable grant.

## 真实账号后端 / Authoritative account backend

- 固定目标 `http://127.0.0.1:<port>/auth/authorize`，默认端口 8095；配置只接受非零 uint16 端口、64 位小写 hex 内部凭据、connect 1–500 ms、total 1–2000 ms 且 connect≤total。未来配置 parser 必须在转换 uint16 前拒绝越界数，不能先截断。
- POST 仅发送 `username`、固定 permission、`cameraId`。**不传 groupId**：现有 cluster 会信任显式 groupId，省略后才按真实 camera registry 查询组。浏览器 cookie、session token 和 Basic 凭据不转发；内部 token 只用于 `X-WebObs-Internal-Admin`。
- 强制 loopback IPv4 HTTP、禁用环境代理、重定向、netrc 和 HTTP Basic；每次创建独立 easy handle，连接/总时限、4 KiB body、16 KiB 聚合 headers/128 次 header callback 均有界。C callback 捕获异常，错误不输出原始响应或秘密。
- 只有严格 JSON（拒绝重复键、NUL、尾随数据）且 `200` 精确包含 `allowed:true`、32 位小写 hex `userId`、请求 permission 回显，才许可。仅精确识别 `403 permission_rejected` 与 `404 user_not_found` 及当前固定 message；错误内部 token、其他状态/结构或措辞变化一律 unavailable，而非默认许可或撤销账号。

The adapter uses the existing [cluster authorization route](../cluster/cluster_service.py), not a replacement service. It validates the full reply rather than trusting status 200. Strict error-message matching deliberately fails closed if the backend contract changes. Proxy/redirect traps and malformed replies are tested separately from the real Handler/ClusterStore/registry integration.

## 接入前仍须保留的契约 / Remaining integration contracts

可信 adapter 必须从 socket 获得 peer，不信任 `X-Forwarded-For` 或请求 principal；在构造请求前拒绝重复/折叠的 Host、Origin、cookie，限制 body/header、连接数与请求时限。当前库不是 HTTP parser，也不验证 OBS 参数。会话及内部凭据文件仍须 owner 私密目录/Windows ACL；账号服务仍须受单实例、Job 与退出回收管理。仅通过授权后在同一原生 frontend 线程操作同一 OBS graph；不开放旧 core 通用可写 API，不启动完整 Supervisor。

库只检查声明的单个 scope，不能解析整场景。可信执行 adapter 必须从实际目标推导所有受影响 camera ID 并逐个授权，对读取结果做可见性过滤。无 scope 的 `scene.read/write` 是粗粒度权限，**不是所有相机范围的豁免**；现有 cluster 的管理员/显式 scope 许可也不是 camera 对象存在性证明，执行前须解析目标。

原生菜单/快捷键/dock/脚本等修改入口必须界定和防绕过。`authorize` 后应立即执行对应白名单动作；最后检查之后发生撤销的处理仍须执行序列化策略定义。现有 SessionStore 以 username 绑定，不检测“删除再用同名重建”的身份替换，也没有密码变更 epoch；这些仍是接入前的独立身份/会话契约，不能因本 adapter 存在就声称解决。

The libraries do not implement native login, graph-derived multi-camera authorization, UI bypass controls, private ACL provisioning, account-service ownership or reversible migration. Username reuse and password-change session epochs remain unresolved integration issues. libcurl ownership is balanced; concurrent invocation assumes normal C++ object lifetime and a supported modern libcurl build with thread-safe global initialization. Destruction/mutation concurrent with a call is not supported.

## 独立验证 / Standalone validation

需要 C++17、OpenSSL Crypto、SQLite、libcurl、Jansson、Python 3 和 Threads；不配置 libobs/Qt/GStreamer，不启动媒体进程：

```sh
cmake -S native-host/tests/control-auth -B build/native-control-auth -DCMAKE_BUILD_TYPE=Release
cmake --build build/native-control-auth --parallel 2
ctest --test-dir build/native-control-auth --output-on-failure
```

测试使用临时 SessionStore、真实 cluster Handler/ClusterStore 和合成 camera registry，密码 hasher 为 fixture（不测试 Argon2/登录）。覆盖同会话角色/直接相机 scope 改变、registry 组改变、禁用账号撤销全部本地会话、错误内部凭据 503 后恢复；独立 hostile HTTP 覆盖状态与 JSON 不符、重复键、控制字符、超限、超时、无代理/重定向泄漏。无效 direct 请求用活跃 observer 断言零网络请求；probe 每次响应有独立时限，CTest 另有整体时限。原会话库的 expiry/logout/SQLite 删除失败等回归继续运行。

The standalone and root CTest projects exercise the actual account-service implementation against disposable data, not a production profile. Non-MSVC builds scan both static libraries for forbidden media/frontend symbols. CI builds on Linux and MSVC using the existing pinned vcpkg baseline and a [minimal test manifest](../native-host/tests/control-auth-vcpkg/vcpkg.json) with OpenSSL/SQLite/curl/Jansson. These are test dependencies, not added shipped services or native installer components. Passing them is not Windows ACL, native UI, camera, pixel or performance qualification.

## 只读 graph 观察基础 / Read-only graph observation

独立的 [wall snapshot](../native-host/src/wall_snapshot.hpp) 现在可观察现有、无 filter 的平面五项 Media Source scene；它只复制 scene/source UUID、item ID 与用户可见标记，包含隐藏项和重复 source。不读 settings/名称/URL，不创建、删除、选择、保存或启动媒体。源码只进入独立 API 契约测试，不接入产品插件或认证库，不暴露管理路由。固定 OBS headers + 15 个只读/引用/加锁替身在本地覆盖 84 情形，包括失败清空、引用平衡、异常不穿越 C callback、第六项及禁用 filter 拒绝。

这只是后续身份解析所需的观测，不是全依赖图、可信绑定或授权预检：不包含 transforms/audio/show-hide transitions，不证明 source settings 或 collection incarnation 未改变。必须由正确 frontend/control context 的调用者序列化 collection/source/filter 编辑；scene lock 不是全图锁，filter 遍历和锁等待无硬时限。未来私密 owner map 不能由请求字段、URL/名称相等或相同 UUID 元组替代；先对每项解析真实对象及可信 camera/profile 身份，再做去重和全 scope 检查。

The internal inspector is now implemented and locally tested, but remains entirely unexposed. Its owned UUID/item/visibility DTO is only an observation: it neither proves authoritative camera/profile identity nor covers transitions, source settings, audio or future graph use. No hard whole-operation deadline is implied. Sequential current RBAC calls can span different policy epochs, and existing sessions are username-based; trusted identity invalidation, immutable user/session epochs, atomic policy consistency, private service ownership, UI bypass prevention and authorized reversible apply still require separate implementation before any live action.

## 后续 / Next

先验证只读的“现有 OBS graph → 可信 registry camera/profile 身份 → 全 scope”预检，不把请求给出的映射、名称/URL 相等或空 scene scope 当作授权依据；当前 product bootstrap 没有建立这份所有权映射。现有 `select_wall` 在非 Studio 会改 Program，`ensure_five_tile_wall` 也有选择/保存副作用，不能复用为只读或 Preview-only 命令。之后才能接入明确 frontend 命令与可拦截 UI、账号服务所有权和私密凭据，再处理经授权的 copy-on-write 导入、逐字段 graph 比对和回滚。此前 product bootstrap 混合 reuse/create 的数组前缀回滚问题现已用实际产品源码 + 固定 OBS headers 的 API 替身复现（113 通过/68 失败），并改为逐槽记录本次创建所有权，所有失败出口只 remove 新建项，再统一 release 引用；本地 181/181 用例通过。它修复错误清理，不建立可信 camera/profile 绑定，也不提供认证或可应用迁移；真实 wall/媒体验收仍独立。迁移只读预检与应用保持分离；未接入路径保持关闭，不切换默认产品。

Next establish a read-only existing-graph/authoritative camera-identity/all-scope preflight: name/URL equality or request-provided bindings are not ownership. Existing wall selection changes Program outside Studio, and ensure has selection/save side effects, so neither is a read-only or Preview-only executor. The product-bootstrap prefix-count rollback concern has now been reproduced against the actual source (113 passed/68 failed) and locally corrected with per-slot creation ownership (181/181 passed). This only fixes cleanup; it establishes neither authoritative camera bindings nor authorized migration. No live action should be wired until these, UI bypass, private service ownership and immutable login/session identity contracts are resolved. Keep read-only migration planning separate from authorized reversible apply; the current libraries alone do not justify a product-default switch.
