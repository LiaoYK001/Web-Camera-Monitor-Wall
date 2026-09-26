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
