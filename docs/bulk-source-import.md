# 批量添加视频源 / Batch source import

在“设备与来源”页面点击“批量添加”。每行输入一个来源，格式为 `名称 | 链接`；也接受 `名称: 链接`。空行以及以 `#` 开头的行会跳过。

```text
# 楼层一
门口 | rtsp://user:password@192.168.1.20:554/stream1
仓库: rtsp://192.168.1.21:554/stream2
```

推荐使用竖线 `|`，因为链接中的协议、端口、路径可能包含冒号。输入区会在提交前显示有效条数和格式错误。支持 RTSP/RTSPS，以及可从文件后缀识别的 HTTPS HLS (`.m3u8`)、FLV (`.flv`)、MJPEG (`.mjpg`/`.mjpeg`) 和静态图片 (`.jpg`/`.jpeg`/`.png`)。其他链接可通过单项添加进行协议探测。

链接中的账号密码会由服务端拆出，存入受管 Secret；设备目录仅保存脱敏地址。导入不自动逐路探测，以免大量离线摄像机阻塞录入。导入后在设备详情中点击“探测轨道”，查看实际视频/音频轨道。部分失败时，已成功项会加入目录，输入区保留失败行供修改重试。

Open **Devices & Sources → Batch Add**. Put one source per line as `Name | URL` (or `Name: URL`). Blank lines and lines beginning with `#` are ignored. The UI validates all lines before submission. RTSP/RTSPS and recognized HTTPS HLS, FLV, MJPEG and image URLs are supported. Credentials embedded in a URL are moved into the server secret store; use **Probe Tracks** after import to inspect media. Successful rows are removed from the input; failed rows remain for retry.

## 导入进度与列表操作 / Import progress and catalog navigation

- 添加期间显示完成进度，输入区暂时锁定。点击“停止后续添加”会等待当前项结束，再停止处理；失败和未处理的行保留在输入区，可继续添加。请留在本页面等待结果。
- 目录每页显示 24 台设备，可按名称、标签、分组搜索，并筛选协议或启用状态。输入停止约 250 毫秒后开始搜索，避免每次敲键都请求服务器。
- “全选本页”仅选择当前页；切换页面或筛选条件会清空选择。选择设备后出现批量启停、分组、标签操作。
- 行内“预览”打开独立预览，按 Esc 或点击“关闭”退出。手机端通过底部“更多”进入回放、设置、账号等页面。

- Import progress shows completed items and temporarily locks the input. **Stop further additions** finishes the current item first; failed and unprocessed rows remain for another attempt. Stay on the page until the result appears.
- The catalog displays 24 devices per page. Search by name, tag, or group and filter by protocol or enabled state. Search starts about 250 ms after typing pauses to reduce requests.
- **Select this page** applies only to the visible page. Changing the page or filters clears selection. Selected devices expose bulk enable/disable, group, and tag actions.
- Use the row's **Preview** action and press Esc or **Close** to exit. On phones, use the bottom **More** menu to reach playback, settings, account, and other pages.

## 交互回归测试 / Interaction regression tests

在 `web` 目录运行 `npx playwright test -c playwright.usability.config.ts`。测试使用内存模拟接口，不连接真实摄像机；覆盖搜索竞态、分页选择、批量中止、预览焦点、移动导航及布局保存顺序。它不替代真实设备的媒体链路验收。

Run `npx playwright test -c playwright.usability.config.ts` from `web`. In-memory API fixtures cover search races, pagination and selection, import cancellation, preview focus, mobile navigation, and ordered layout saves. These tests do not connect to real cameras or replace media validation on physical devices.
