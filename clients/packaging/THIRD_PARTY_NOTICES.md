# Third-party notices / 第三方声明

WebObs Native dynamically links the following pinned open-source components. The release package
does not include Qt WebEngine. Exact source URLs and SHA-256 digests are recorded in
`dependencies.lock.json`, which is installed beside this notice.

WebObs Native 动态链接下列固定版本的开源组件，发布包不包含 Qt WebEngine。精确源码地址与
SHA-256 记录在随本声明一并安装的 `dependencies.lock.json` 中。

| Component | Version | License used by this project | Upstream |
| --- | --- | --- | --- |
| Qt 6 modules (Core, Core5Compat, Gui, Network, QML, Quick) | 6.11.2 | LGPL-3.0-only / GPL options as published by Qt | https://www.qt.io/licensing/open-source-lgpl-obligations |
| GStreamer and required plug-ins | 1.28.6 | LGPL-2.1-or-later; individual plug-ins retain their upstream notices | https://gstreamer.freedesktop.org/documentation/frequently-asked-questions/legal.html |
| libsodium | 1.0.22 | ISC | https://github.com/jedisct1/libsodium |

The application is distributed under `GPL-2.0-or-later`. Users may replace the dynamically linked
libraries with compatible builds. Corresponding pinned upstream source archives can be downloaded
from the URLs in `dependencies.lock.json`; the recorded digest must be verified before use.

本应用以 `GPL-2.0-or-later` 发布。用户可以用兼容构建替换动态链接库。对应的固定上游源码包
可从 `dependencies.lock.json` 中的地址取得，使用前必须核验其中记录的摘要。
