# Windows go2rtc 配置重载 / Windows go2rtc configuration reload

## v4.0 已知问题 / Known v4.0 issue

Windows v4.0 中，官方配置编辑器的 **Save & Restart** 会写入配置文件，但运行中的流可能保持旧配置；重新启动整个 WebOBS 后才生效。原因是固定上游 go2rtc v1.9.14 的重启接口调用 `syscall.Exec`，Windows 不支持该操作，上游没有返回执行失败。旧编辑器还在发起重启前弹出 `OK`，并不能证明配置已加载。

In Windows v4.0, Save & Restart persists the file but can leave the running stream configuration unchanged until WebOBS restarts. The pinned upstream restart uses `syscall.Exec`, which Windows does not support, and ignores its error. The old editor's early `OK` alert does not confirm a reload.

v4.0 用户的临时处理：完成保存并关闭提示后，正常退出 WebOBS，再重新启动。配置会保留；无需卸载、清除数据或重新建档设备。重启期间媒体会中断。新建命名流仍需在“从 go2rtc 接入设备”检测并添加，保存 YAML 本身不会自动创建设备或监控墙场景。

For v4.0, save the configuration, dismiss the dialog, then exit WebOBS normally and start it again. Data and configuration remain intact; media is interrupted during restart. A named stream still needs explicit device import and scene assignment.

## 开发分支修复 / Development fix

修复始于 `72e0bf055ce49af226d41238e9f39b47b5585c5b`（`dev`），后续补齐 Windows 退出时连接重置的处理。完整 Windows 测试候选为 `4.0.1-dev.4`，不是正式 `v4.0.1`；现有公开 v4.0 安装包不包含本修复。

The fix starts at `72e0bf055ce49af226d41238e9f39b47b5585c5b` on `dev`, followed by Windows exit/reset handling. The Windows test candidate is `4.0.1-dev.4`, not a stable `v4.0.1` release. Published v4.0 installers remain unchanged.

- 产品认证代理将重启请求转为固定退出码 `75`；监督器仅替换 go2rtc，重新读取私密配置，保留其他服务与登录会话。/ The authenticated proxy requests reserved exit code `75`; the supervisor replaces only go2rtc, preserving other services and sessions.
- 连续保存，包括早于监督器就绪轮询的快速保存，不消耗或重置异常重试预算。/ Repeated saves, including saves before the readiness poll observes startup, neither consume nor reset the crash budget.
- Windows 每代 go2rtc 及其 FFmpeg/exec 子进程属于独立嵌套 Job，重载时收束旧进程。/ A nested Windows Job owns each generation and its FFmpeg/exec descendants.
- 编辑器确认服务恢复后才提示生效，立即刷新工作台流列表；保存失败或重载未确认会分别提示，保留编辑内容。/ The editor confirms readiness, refreshes stream listings and distinguishes save failure from an unconfirmed reload while retaining edits.
- 接口 `POST /api/v1/go2rtc/api/restart` 返回 `202 Accepted`，调用方仍须等待服务恢复。认证、Origin、`settings.manage`、固定回环端口和凭据过滤保持原有边界。/ Restart returns `202 Accepted`; callers must await readiness. Existing authentication, Origin, RBAC, loopback and credential-filtering boundaries apply.

## 验证 / Validation

2026-10-09 本机已完成：

- 使用原 v4.0 捆绑的真实 Windows go2rtc 二进制复现“返回 200 但配置未加载”，然后用修改后的监督器连续七次保存与换代，验证旧流移除、监督器持续运行、真实 FFmpeg 媒体子进程在换代后退出及最终停服清理。全部使用独立临时配置，不修改已安装产品数据。/ Reproduced the old no-op with the actual v4.0 Windows binary; verified seven supervised reloads, removal of old names, supervisor continuity, real FFmpeg cleanup and shutdown in an isolated temporary profile.
- Linux 编译并运行 C++ 代理回归：固定重启目标、202 接受、上游拒绝、连接失败、部分响应、普通请求断连及产品凭据过滤。/ Compiled and ran the C++ proxy regressions on Linux, covering acceptance, failures, method/query handling and credential stripping.
- 固定并核对 SHA-256 的真实 Linux go2rtc 二进制也通过七次连续配置重载、旧流移除及监督器持续运行检查。/ The real pinned and SHA-256-verified Linux binary also passed seven successive reloads, old-name removal and supervisor continuity checks.
- 真实打包 Monaco/编辑器的浏览器夹具及相关 go2rtc/网站源回归共 14 项通过；包括重载成功后刷新、失败提示、重试与外部修改冲突。浏览器后端响应使用夹具，与真实服务测试分别记录。/ Fourteen browser regressions passed with the actual packaged editor and fixture backend responses, recorded separately from actual service checks.
- 监督器单测 6 项在 Linux 全过，Windows 5 项通过、符号链接测试按平台跳过；桌面逻辑 48 项、Monaco 资源 2 项、前端类型检查和生产构建通过。/ Six supervisor tests passed on Linux; five passed on Windows with the POSIX symlink test skipped. Desktop logic (48), packaged assets (2), frontend typecheck and production build passed.

完整 Windows 编译、真实服务及 NSIS 构建验证见[候选工作流](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/workflows/windows-desktop.yaml)。工作流内新增七次完整认证代理重载及产品重启后配置保留检查。首轮 [`4.0.1-dev.1` / #48](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/37915051098) 已通过原生编译和两项 CTest，但真实 go2rtc 退出时连接重置被代理误报为 `503`，新回归阻止了打包；该失败不计为完整候选通过。最终结论以新候选工作流完成结果为准；本机分项验证不代表新安装包已通过完整构建或已经发布。

The [candidate workflow](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/workflows/windows-desktop.yaml) compiles Windows, exercises seven real authenticated reloads and persistence, then packages and checks NSIS. The first dev.1 attempt passed compilation/CTest but failed the real restart assertion: socket reset on exit was reported as `503`, preventing packaging. It is not a successful full candidate. The completed new run determines readiness; component checks alone do not qualify or publish an installer.

第二轮 [`4.0.1-dev.2` / #49](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/37916427221) 已通过原生编译、两项 CTest 和七次完整认证代理配置重载，但新增非法 YAML 用例误将上游 POST 的拒绝状态预期为 400，实际固定版本返回 500，导致后续打包停止。现已按上游源码纠正断言和浏览器夹具，继续保留文件与运行流不变的检查；未放宽重载、服务所有权或会话断言。

The second dev.2 attempt passed native compilation, both CTests and all seven real authenticated reloads. Packaging then stopped because the new invalid-YAML test incorrectly expected 400; the pinned upstream POST handler returns 500. The assertion and browser fixture now match that contract, retaining file/stream preservation checks and all reload, ownership and session assertions.

第三轮 [`4.0.1-dev.3` / #50](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/37917871396) 完整通过原生编译、CTest、七次认证代理重载、产品重启后保留、真实 Electron 入口、完整打包和 NSIS 安装/卸载。它包含配置重载修复，但没有随后发现的 RTSP 自动识别/UI 改动；后者与新增冷导入、MSE、Studio 门禁进入 dev.4，仍需新构建。公开 YouTube 实测与边界见[网站接入验收](online-source-validation-v4.md)。

The dev.3 full Windows run passed compilation, CTest, seven authenticated reloads, restart persistence, actual Electron entry, packaging and NSIS install/uninstall. It predates the additional RTSP automatic-selection/UI changes; those and the new cold import/MSE/Studio gate require dev.4 qualification. Public YouTube checks are recorded separately.
