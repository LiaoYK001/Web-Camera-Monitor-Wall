# Security and CI remediation / 安全与 CI 修复

## Dependency coverage / 依赖覆盖

The web workspace pins DOMPurify 3.4.16 and brace-expansion 2.1.7/5.0.12.
Monaco is upgraded to 0.57.0 because its prebuilt editor bundles DOMPurify
3.4.15 internally; overriding the npm dependency alone would leave the old
sanitizer in go2rtc's configuration editor. The complete local editor and its
workers remain packaged, without loading scripts from a CDN. Public CI runs
`pnpm audit --audit-level=low` against the frozen lockfile.

Web 工作区锁定 DOMPurify 3.4.16 与 brace-expansion 2.1.7/5.0.12。
Monaco 升级为 0.57.0，其预编译编辑器内置 DOMPurify 3.4.15；仅覆盖 npm
依赖无法替换旧版编辑器内的代码。go2rtc 继续完整打包本地编辑器及 Worker，
不从 CDN 加载脚本。公开 CI 对冻结锁文件执行 `pnpm audit --audit-level=low`。

## Camera and credential boundaries / 摄像机与凭据边界

Camera HTTP discovery, ONVIF, snapshots and browser qualification share a
connection guard. Every DNS result is checked before any socket connects.
Connections use the checked numeric address without a second DNS lookup;
HTTPS retains the original hostname for SNI and certificate verification.
RFC1918 and IPv6 ULA camera networks remain available. Loopback, unspecified,
multicast, link-local, reserved and known cloud metadata destinations are
rejected. System HTTP proxies are disabled for these requests. Discovery,
ONVIF and snapshots reject redirects; browser HLS qualification retains bounded
same-origin redirects and cookies. Product-owned fixed loopback service calls
are separate from user-supplied camera requests.

HTTP 发现、ONVIF、快照和浏览器资格探测使用共同连接校验。建立连接前检查所有
DNS 结果，再连接已校验的数字地址，避免二次解析造成 DNS 重绑定；HTTPS 保留
原始主机名用于 SNI 与证书验证。保留 RFC1918 和 IPv6 ULA 局域网摄像机，拒绝
回环、未指定、组播、链路本地、保留及已知云元数据地址。这些请求不使用系统
HTTP 代理。发现、ONVIF 和快照禁止重定向；浏览器 HLS 探测保留受限的同源
重定向与 Cookie。产品固定的回环服务调用与用户提供的摄像机请求分别处理。

The loopback ONVIF emulator requires `WEBOBS_CAMERA_ALLOW_TEST_ENDPOINTS=true`;
browser qualification additionally requires `WEBOBS_BROWSER_PROBE_ALLOW_LOOPBACK=true`.
Neither flag is enabled in normal product startup. TLS camera/notification
connections require TLS 1.2 or later and validate certificates. Client credential
references are bounded basenames; symlinks, traversal and oversized secret files
are rejected at the read boundary.

回环 ONVIF 模拟器需要显式设置 `WEBOBS_CAMERA_ALLOW_TEST_ENDPOINTS=true`，
浏览器探测还需 `WEBOBS_BROWSER_PROBE_ALLOW_LOOPBACK=true`。正常产品启动不
设置这些测试开关。摄像机与通知 TLS 连接要求 TLS 1.2 或更高版本并验证证书。
客户端凭据引用限定为长度受限的文件名；读取时拒绝符号链接、目录穿越与超限文件。

## Alert review and Windows CI / 告警复核与 Windows CI

Review individual remaining protocol/test alerts with their source locations,
not by excluding tests or disabling CodeQL. The emulator verifies SHA-1
WS-Security PasswordDigest and legacy MD5 HTTP Digest because those are the
wire protocols under test, not account password storage. See the
[OASIS UsernameToken profile](https://docs.oasis-open.org/wss-m/wss/v1.1.1/os/wss-UsernameTokenProfile-v1.1.1-os.html)
and [ONVIF Core specification](https://www.onvif.org/specs/2306/ONVIF-Core-Spec-v2306.pdf).
Its credential files contain fixed public fixture strings in a temporary
directory. WS-Discovery uses a validated specific interface and an ephemeral
UDP socket to receive multicast replies; it is not an exposed management listener.
Record precise explanations when dismissing confirmed false positives.

对剩余协议或测试告警逐条结合源码复核，不排除测试目录或关闭 CodeQL。模拟器
验证 SHA-1 WS-Security PasswordDigest 和旧设备 MD5 HTTP Digest，是为了验证
对应的线上协议，不是账号密码存储；规范见上面的 OASIS 与 ONVIF 链接。其临时
凭据文件只包含公开的固定测试字符串。WS-Discovery 在校验后的具体接口上使用
临时 UDP 端口接收组播回复，不是对外开放的管理监听器。确认误报后逐条记录原因。

Historical Windows candidate failures occurred when a development installer
generated `latest.yml`. Development builds now use the `dev` channel; stable
unsigned releases continue to use `latest`. The packaging guard still refuses
development attachments in the stable feed. Revalidate with a fresh manual
`Web runtime public CI` run with `windows_desktop=true`; old failed runs remain
in the repository's audit history. These build/protocol tests do not qualify
real cameras or clean Windows 10/11 installations.

历史 Windows 候选构建曾因开发包生成 `latest.yml` 而失败。开发构建现使用 `dev`
通道，未签名稳定版继续使用 `latest`；打包检查仍拒绝开发包进入稳定更新源。
通过新的手动 `Web runtime public CI` 运行并设置 `windows_desktop=true` 复验。
保留旧失败记录作为审计历史。这些构建与协议测试不代表真实摄像机或干净
Windows 10/11 安装资格已完成。
