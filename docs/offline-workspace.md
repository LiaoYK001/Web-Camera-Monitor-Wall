# Device layouts and offline editing / 设备布局与离线编辑

## Workflow / 操作流程

1. In Settings → Device offline and sync → Pairing management, create a browser pairing. An administrator enters the eight-digit code, chooses the required Cameras/Profiles and approves it. Finish pairing in the requesting browser. Device keys and the verified credential-free grant are encrypted in that Origin's IndexedDB; this does not replace the normal account login.
2. Load the device layout. The current saved Studio seeds the private cache after pairing; an unsaved draft is not silently cached. Device layouts support camera IDs, text, colors and nested scenes. Raw RTSP/browser URLs and local media paths stay outside this sync contract. Saving an unsupported or unauthorized camera/profile leaves the draft visible with an explanation.
3. Save device edits. The redacted layout, pending queue and selected device workspace are written in one IndexedDB transaction. Refresh restores this layout and pending queue. A paired device with an unexpired cached layout can enter offline editing when the account server is unreachable. Explicit authentication rejection clears private offline authorization; expiration also stops an already open offline session.
4. Visible, paired workspaces try synchronization immediately and every 30 seconds, and retry when network/focus returns. Requests are bounded to 15 seconds and cancelled when private authorization clears. Bootstrap grants are verified against the pinned server signing key before being cached. Projectors do not create another sync worker. Server/local conflict choices are explicit in Settings; server choice discards only conflicting documents and keeps unrelated pending work. Reload the device layout to display the chosen version.
5. To use the device collection on the server, finish synchronization and resolve conflicts, then choose **Copy to server Preview** in Studio. This explicitly appends the collection with fresh scene/source/item IDs and remapped nested references, using the current server revision. Existing server scenes, their credentials and the complete Program graph remain intact. The resulting Preview may be checked and manually taken. Copy conflicts/failures retain the device layout. Copying cannot exceed the 64-scene collection limit.

1. 设置 → 设备离线与同步 → 配对与授权管理，创建浏览器配对。管理员输入八位码，选择所需 Camera/Profile 并批准；发起浏览器再完成配对。设备密钥及已验证的无凭据授权包在当前 Origin 的 IndexedDB 加密保存，不代替正常账号登录。
2. 载入设备布局。配对完成后使用当前已保存的 Studio 建立缓存，不自动缓存未保存草稿。支持摄像机稳定 ID、文字、色块与嵌套场景；原始 RTSP/浏览器地址和本机媒体路径不进入设备同步。保存不支持或未获授权的来源时保留草稿并解释处理办法。
3. 保存设备修改。脱敏布局、待提交队列及设备工作区选择在同一 IndexedDB 事务写入；刷新恢复布局及队列。账号服务器不可达时，具有有效配对及缓存布局的设备可离线编辑；明确的登录拒绝清理私有离线授权，授权到期也会停止已打开的离线会话。
4. 已配对的前台工作区立即及每 30 秒尝试同步，网络/焦点恢复时重试；每次请求最多 15 秒，清理授权时取消请求。Bootstrap 授权包经固定的服务器签名密钥验证后缓存。投影窗口不启动额外同步器。设置中明确选择服务端或本机冲突版本，采用服务端只丢弃冲突文档，保留其他待提交内容；重新载入设备布局显示选择结果。
5. 要在服务器使用布局，先完成同步、处理冲突，然后在 Studio 点击 **复制到服务器预览**。此操作使用当前服务器版本、新建场景/来源/图层 ID 并重映射嵌套引用，将设备集合追加到服务器；原场景、凭据和整个 Program 引用图保持不变。检查 Preview 后可手动 TAKE。复制冲突或失败保留设备布局；复制后总数不得超过 64 个场景。

## Boundaries and validation / 边界与验证

Account configuration profiles, the v2 shared device documents and the core server Studio are distinct stores. Uploading a device document is not a server Studio PUT or TAKE. Device-mode TAKE, server audio workspace and server projectors are unavailable until the collection is explicitly copied. Returning to the server view retains device cache/queued work. Local saves preserve a newer draft edited during a request and adopt the committed server revision; deleting a never-uploaded scene replaces its pending upsert with a deletion.

账号配置档案、v2 共享设备文档与 core 服务器 Studio 分属不同存储。上传设备文档不会执行服务器 Studio PUT 或 TAKE。设备模式在明确复制前不开放 TAKE、服务器声音工作台或服务器投影；返回服务器视图保留设备缓存和队列。保存期间继续编辑时保留新草稿，并使用已提交的服务器版本；删除尚未上传的场景时将其排队的 upsert 改为删除。

`offline-workspace.spec.ts` mounts the real App and LoginGate against synthetic HTTP/WebSocket responses: offline reload/reconnect, explicit Preview copying, login rejection, expiration, conflict choice, private cleanup, in-flight edits, first-use encryption, nested IDs, deletion and phone layout. Its seeded identity is an encrypted-cache fixture, not a signed enrollment qualification. `desktop/tests/native-offline-ui.cjs`, called by `test:main`, uses the packaged UI and real authenticated product services to create a browser pairing, verify/decrypt its grant, upload/reload a layout and explicitly copy it to Preview while preserving Program. Existing native projector/tray/exit checks follow it.

`offline-workspace.spec.ts` 使用真实 App 与 LoginGate 和合成 HTTP/WebSocket 响应，覆盖离线刷新/恢复、预览复制、登录拒绝、到期、冲突、私有清理、请求期间编辑、首次加密、嵌套 ID、删除及手机布局。其预置身份属于加密缓存夹具，不代表签名配对验收。`test:main` 调用 `desktop/tests/native-offline-ui.cjs`，使用打包 UI 与真实认证服务，完成浏览器配对、授权解密验证、布局上传/刷新与明确复制，并检查 Program 保留，随后回归投影、托盘与退出。

The MuMu debug APK regression uses the current WebUI and an isolated full Linux product image. WebView 110 is supported by AbortController-based deadlines, without requiring AbortSignal.any/timeout static helpers. Synthetic H.264 playback and account restart checks do not qualify physical cameras, ARM devices, multi-device conflict UX or long offline retention. Disk/storage denial remains an explicit save failure; v4 readiness still requires the broader [evidence matrix](v4-readiness.md).

MuMu debug APK 回归使用当前 WebUI 与隔离的完整 Linux 产品镜像。请求时限使用 AbortController，兼容 WebView 110，不依赖 AbortSignal.any/timeout 静态方法。合成 H.264 与账号重启检查不代表真实摄像机、ARM、多设备冲突操作或长期离线保留验收；存储失败会明确报告保存失败。v4 仍需完成更广泛的[证据矩阵](v4-readiness.md)。
