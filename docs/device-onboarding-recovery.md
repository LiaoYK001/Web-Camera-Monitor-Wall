# Device onboarding and recovery / 设备接入与故障恢复

## Workflow / 操作流程

In Devices & sources, import a saved go2rtc named stream or open Add / ONVIF discovery.
Import reads the authenticated runtime's internal RTSP address, detects the stream and
creates one stable device ID. Track probing follows creation; a probing failure does
not remove the device. Select the device in Studio's scene sources afterwards.

在“设备与来源”直接导入已保存的 go2rtc 命名流，或打开“添加 / ONVIF 发现”。
导入使用经过认证的运行时内部 RTSP 地址，检测后建立固定设备 ID，再探测轨道；
探测失败不撤销建档，可在设备详情重试，之后从 Studio 的场景来源中选择设备。
无法读取内部地址时停止导入并提示检查服务，不猜测部署端口。

Changing the manual address clears its detection, staged login and Secret reference.
Detection/ONVIF reads have an explicit cancellation button. Late replies cannot populate
a different address or a closed editor. Credentials remain in memory until an explicit
save; they are not stored as a browser draft.

手动更换地址会清除旧检测、暂存账号密码和 Secret 引用；读取可明确取消，
晚到响应不会写入新地址或已经关闭的编辑页。凭据草稿只在本页内存中保存，
明确提交后由后端加密，不写入浏览器草稿存储。

## Unconfirmed writes / 未确认写入

Foreground editor operations wait at most 20 seconds. A timeout or lost response
does not mean the server cancelled the change. Camera creation and go2rtc import
retain their frozen submission and ID in the current page. Check the result first;
the explicit Continue submitting the same device action reuses that ID. An existing-ID
409 is reconciled through the authenticated directory. No automatic creation retry runs.
Reloading/leaving discards this in-memory recovery context, so inspect the directory
before starting a new import. Delete, credential and policy timeouts also require
refreshing the result before retrying.

前台操作最多等待 20 秒；超时或响应丢失不代表服务端撤销。手动添加和 go2rtc 导入
会在当前页保留原提交内容与 ID，先点击“核对添加结果／核对导入结果”；
明确选择“继续提交同一设备”时复用原 ID，通过认证目录核对重复 ID 的 409，
不会自动重试创建。刷新或离开会丢弃内存中的恢复上下文，重新导入前先查看设备目录。
删除、凭据或策略保存超时也需先刷新核对再重试。

## Account drafts and installation / 账号草稿与安装

Camera display preferences use compact partial writes with a baseline. Under the
account-store lock, only changed fields are merged; another camera or an unchanged
field retains the latest value. The same changed field follows the last accepted write.
Refresh rebases local edits onto incoming unchanged fields, and saving one camera does
not submit another camera's draft. Failed account reads never trigger legacy migration
writes. Legacy local preferences require explicit per-camera synchronization.
Older backends that reject partial writes keep the draft and show the failure; there is
no unsafe full-map fallback.

设备显示偏好采用带基线的紧凑字段更新，在账号存储锁内合并实际修改：
其他设备及未修改字段保留最新值；同时修改同一个字段时，以最后接受的写入为准。
刷新将本地修改合并到新的未修改字段上，保存一台不会提交另一台的草稿。
账号读取失败不触发旧本地偏好覆盖，旧偏好需逐台明确同步；旧后端若拒绝部分更新，
保留草稿并显示失败，不回落为整张偏好表覆盖。

Unsaved device/credential/policy/preference drafts prompt before normal navigation.
Active registry/import/control/microphone operations block normal departure and report
work to Windows/Android install preflight. Complete or discard the recording before
leaving. Forced unmount/background microphone cleanup remains in place.
This is a client safeguard, not a server-side transaction or guarantee against power loss.

设备、凭据、策略和偏好草稿在正常离开前提示；在途建档、导入、控制及麦克风操作
阻止正常切页，并向 Windows/Android 安装预检报告。离开前完成或丢弃录音，
强制卸载页面或进入后台时仍清理麦克风。此机制属于客户端保护，
不等于后端事务或断电保证。

## Validation / 验证

- `web/tests/local-runtime/camera-registry-recovery.spec.ts`: credential destination,
  ignored cancellation, duplicate clicks, permission denial, timeout/409 recovery,
  independent reads, draft rebase, per-camera saves and native work flags.
- `tests/test_cluster_service.py`: account isolation, concurrent field merges and
  invalid bounded writes without stored-value changes.
- `node tests/camera_registry_runtime.cjs --image <matching-image>`: actual authenticated
  go2rtc import, account API/UI and lost-response recovery against a disposable complete
  product with synthetic RTSP.
- `tests/device_controls_runtime.cjs` and Android `test_emulator.py --device-controls`
  additionally exercise current rendered UI and normal departure/microphone ownership.

Keep source/image revisions and actual results together. Synthetic media, a locally
layered image and installed MuMu WebView checks are separate from physical camera/ARM,
fresh Windows 10/11 installation, public updates and prolonged-operation qualification.

记录源码/镜像及实际结果；合成流、本机分层镜像与已安装 MuMu WebView
检查分别记录，不作为摄像机/ARM 真机、干净 Windows 10/11、公开更新或长测验收。

2026-10-05: typecheck/production build, 41 focused Chromium checks and 42 cluster tests
passed. The local layered image `webobs:v4-registry-recovery-checked` was built from
`webobs:v4-ptz-deadline` with current camera/cluster sources and production WebUI.
Its image ID is `sha256:6eb6164bf3c2668538fe84a62518fd839d22a66a3dcdfd4836e5f30997045c91`.
Both registry and device-control runtime scripts passed; the installed MuMu APK on
explicit ADB device `127.0.0.1:16384` also passed the added registry workflow and existing
login, preferences, projectors, H.264/AAC, snapshot and lifecycle smoke.
No new complete Windows/NSIS artifact was built for this follow-up, and no product
release/feed was published.

2026-10-05：类型与生产构建、41 项 Chromium、42 项 cluster 通过。
本机分层镜像包含当前摄像机/账号服务和 WebUI，两个实际后端脚本及 MuMu 已安装 APK
的新增接入与现有媒体验证通过。此次未构建全新 Windows/NSIS 产物，未发布产品版本或更新源。
