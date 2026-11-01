# 原生控制认证边界 / Native control authorization boundary

## 当前交付与限制 / Delivered scope and limits

这是 renderer-free C++ 库与安全回归，不是已接入原生 OBS UI 的账号产品。它没有监听端口、创建账号、登录、HTTP 解析、服务启动或 OBS 命令执行功能，不初始化第二媒体/显示引擎。Electron 兼容产品仍为默认入口。不能把库测试通过写成原生产品已经完成认证、旧数据迁移或 P3 验收。

This is a renderer-free C++ authorization boundary and regression suite, not a wired native login product. It owns no listener, login endpoint, account service, media runtime or OBS action executor. The compatibility Electron product remains the default.

实现为 [NativeControlAuth](../core/include/webobs/native_control_auth.hpp)，直接复用 [SessionStore](../core/include/webobs/authentication.hpp) 的 SQLite 持久会话和令牌哈希；没有另造 session 数据库协议或 Basic 管理员回退。

## 固定命令与检查 / Allowlisted checks

- `read_scene` → `scene.read`；`write_scene` → `scene.write`；`view_camera` → `live.view`。最后一种必须带一个 camera ID；其余允许带一个明确 scope。任意字符串权限、URL、路径、列表或通配符不能作为 camera scope。
- 在访问会话/账号后端前验证 socket/IPC 提供的 loopback peer、精确配置的 Origin 和 authority 及其长度、命令和 scope。配置只接受明确的 loopback HTTP(S) origin，不接受 userinfo、路径、query、fragment、DNS 后缀匹配或宽泛 localhost 子串。
- token 必须为现有 SessionStore 产生的 64 位小写十六进制字符串。逐命令检查本地会话后调用可信的最新账号授权回调，不缓存角色/许可；后端许可后再检查一次会话，避免后端请求期间退出登录仍获得授权。
- 缺失/失效会话返回 `401`；不存在/禁用账号在成功撤销其全部本地会话后返回 `401`；若撤销未确认删除任何记录，则保守返回 `503`（包含数据库删除失败或并发已删除的情况），不能声称撤销成功。权限不足 `403`；未配置、后端故障/异常或未知决定 `503`。异常消息和 token 不进入返回对象；拒绝时不返回 principal。

Each command requires the existing persistent session AND a fresh authoritative permission/scope decision. Unknown accounts revoke all local sessions for that account. Backend exceptions and invalid decisions fail closed. The result is a one-command decision, not a reusable authorization token.

## 接入前必须保留的契约 / Required integration contracts

可信 adapter 必须从真实 socket 获得 peer，不能信任 `X-Forwarded-For` 或请求里的 principal；在构造请求前拒绝重复/折叠的 Host、Origin、cookie 字段，限制 body/header、连接数和请求时限。当前库不是 HTTP parser，也不会验证 HTTP body 中的 OBS 参数。

The eventual adapter must authenticate its loopback account-service request using a private internal credential, impose time/response-size limits, and map missing, malformed or unavailable backend replies to `unavailable`. It must never forward the browser session cookie as an internal-service credential.

账号服务回调仍需实现并接入真实 cluster API；会话文件仍需由 owner 建立独立用户私密目录/ACL；服务需纳入单实例与 Job/退出回收；通过授权后只允许在原生 frontend 线程操作同一 OBS graph。不能直接开放旧 core 的宽泛可写 scene/studio API，也不能把旧完整 Supervisor 全部启动。

库只检查请求里声明的单个 scope，不解析场景内容或 OBS 参数。可信 adapter 必须从目标对象推导全部受影响的 camera ID，逐一授权，并对场景读取做可见性过滤；不能由调用者填一个获许可的 ID，就读取/修改包含其他受限相机的整个 graph。无 scope 的 `scene.read/write` 不自动豁免账号的相机范围限制。

原生 OBS 自带菜单/快捷键/dock/脚本等可能修改场景的入口必须逐一界定。仅保护新的 API，而任由原生 UI 绕过策略，不构成完整账号隔离。`authorize` 返回之后立即执行对应白名单动作；不能保存结果留待以后使用。与所有分离的授权/执行一样，最后检查之后发生的撤销仍需后续 adapter 的执行序列化策略定义。

## 独立验证 / Standalone validation

只需 C++17、OpenSSL Crypto、SQLite 和 Threads；不配置 libobs/Qt/GStreamer，不启动媒体进程：

```sh
cmake -S native-host/tests/control-auth -B build/native-control-auth -DCMAKE_BUILD_TYPE=Release
cmake --build build/native-control-auth --parallel 2
ctest --test-dir build/native-control-auth --output-on-failure
```

测试使用临时 SQLite 数据库，覆盖权限变化、backend outage、scope、expiry、logout/revoke_user、后端请求期间撤销、伪造 Origin/authority/peer、超长字段、控制字符、未知枚举和安全返回码。非 MSVC 下额外扫描完整静态库符号，拒绝 OBS/media/frontend 初始化或操作入口。它不证明端口/HTTP 认证、真实账号后端、Windows ACL、完整原生 UI 或摄像头验收已经通过。

The standalone CMake project and existing root CTest suite run the same real-session tests. The public CI adds Linux and MSVC builds; the Windows job uses only OpenSSL and SQLite from the existing pinned vcpkg baseline in [the minimal test manifest](../native-host/tests/control-auth-vcpkg/vcpkg.json). These are tests, not shipped services or added product dependencies.

## 后续 / Next

先实现有界且 fail-closed 的真实账号后端 adapter，再接入少量明确 frontend 命令和可拦截 UI；迁移预检与获授权的应用阶段分开。尚未接入的路径保持关闭，不因库存在而切换默认产品。

Implement the bounded authoritative backend adapter, then wire narrowly scoped native frontend actions and their bypass controls. Keep migration preflight separate from an authorized, reversible apply operation and do not switch the product default on the strength of this library alone.
