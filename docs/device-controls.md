# 设备控制与短片段对讲 / Device controls and short talk

在 **设备与来源 → 添加 / ONVIF 发现** 中，已同步的 ONVIF 设备按能力展示 PTZ、预置位、快照、事件与对讲。控制服务继续校验账号权限和设备范围，客户端显示权限拒绝与登录失效；网页成功响应还必须包含对应的命令确认状态。确认表示服务端已处理命令，不代表已通过真实设备位置或扬声器反馈证明结果。

Open the ONVIF device page from the source workspace. The backend enforces permissions/scopes; the UI explains denied permissions and expired login. PTZ/talk success also requires the expected acknowledgment state. Acknowledgment is not physical verification of camera position or speaker output.

- 设备操作最多等待 20 秒，不自动重做修改。超时后明确区分“读取失败”与“结果尚未确认”；可以再次读取状态或发送停止命令。浏览器取消等待不能证明服务端取消了操作。
- 同一设备的普通操作防止重复点击；停止云台仍可使用，不会被较慢的移动请求、快照或其他设备编辑阻挡。停止会取消原请求的界面等待，旧响应不能覆盖停止结果。PTZ 按钮有方向名称及至少 44 像素触控尺寸。
- 连续移动持续时间（100–2000 毫秒）与非有限数值在发往摄像机之前校验；有效连续命令保留后台自动停止。实际设备自动停止、响应丢失、多客户端命令排序及厂商差异仍需要专门实机验收。

Operations have a 20-second client deadline, without automatic mutation retries. The stop control remains available during ordinary requests, and superseded/late responses cannot replace its result. Continuous movement validates its stop budget and finite values before sending SOAP; valid commands retain the backend timer. Real-device stopping, response-loss/concurrent-client ordering and vendor differences require separate qualification.

## 对讲 / Talk

点击“录制对讲”请求麦克风，再点击“停止并发送”，或满 10 秒发送。录音格式根据浏览器能力选择 WebM、Ogg 或 MP4；上限 512 KiB，以分片累计大小控制。发送成功只表示片段已提交，设备播放最多 10 秒；“停止设备对讲”发送明确的停止请求。

丢弃、切换页面、进入后台（包括 Android Activity 生命周期）、麦克风断开、录音初始化/处理失败时都释放麦克风；未发送的录音不上传，返回前台不会自动录音。权限等待最多 20 秒；离开或超时后才取得的麦克风立即关闭。发送等待取消/超时仍保留“结果未确认”语义。

Start a deliberate recording, send it manually or after ten seconds, or discard it. Choose a browser-supported media format and bound cumulative chunks to 512 KiB. Navigation, backgrounding (including Android lifecycle), device disconnect or recording errors release tracks. Late permission grants are closed, and returning never resumes recording. Cancelling a submitted request does not prove that its bounded server playback was cancelled.

## 验证 / Validation

`device-controls.spec.ts` 在实际 Chromium 中使用受控麦克风与网络夹具验证停止失败/错误确认、重复点击、超时晚到响应、释放资源、后台与正常片段提交；它不验证真实音频硬件。`tests/test_camera_registry.py` 复现非法持续时间在发送移动后才报错的问题，并通过摘要认证的本地 SOAP 设备验证有效命令仍自动停止。完整产品和原生候选结果应分别记录具体版本，不据此宣称摄像机或 v4.0 整体已验收。

The browser fixtures validate UI ownership and microphone resource behavior. The authenticated synthetic SOAP fixture verifies command rejection before movement and nominal automatic stopping. These checks are distinct from physical camera/audio, native installation and complete v4.0 qualification.
