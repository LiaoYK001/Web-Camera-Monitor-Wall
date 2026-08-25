# Third-party notices / 第三方声明

WebObs Native links the following pinned open-source components through replaceable platform
libraries. The release package
does not include Qt WebEngine. Exact source URLs and SHA-256 digests are recorded in
`dependencies.lock.json`, which is installed beside this notice.

WebObs Native 通过可替换的平台动态库链接下列固定版本开源组件，发布包不包含 Qt WebEngine。精确源码地址与
SHA-256 记录在随本声明一并安装的 `dependencies.lock.json` 中。

| Component | Version | License used by this project | Upstream |
| --- | --- | --- | --- |
| Qt 6 modules (Core, Core5Compat, Gui, Network, QML, Quick) | 6.11.2 | LGPL-3.0-only / GPL options as published by Qt | https://www.qt.io/licensing/open-source-lgpl-obligations |
| GStreamer and required plug-ins | 1.28.6 | LGPL-2.1-or-later; individual plug-ins retain their upstream notices | https://gstreamer.freedesktop.org/documentation/frequently-asked-questions/legal.html |
| libsodium | 1.0.22 | ISC | https://github.com/jedisct1/libsodium |

The application is distributed under `GPL-2.0-or-later`. Users may replace the dynamically linked
libraries with compatible builds. Corresponding pinned upstream source archives can be downloaded
from the URLs in `dependencies.lock.json`; the recorded digest must be verified before use.

The Android package builds `libgstreamer_android.so` from the official 1.28.6 bundle and statically
registers the qml6 plug-in in the GPL application library. The latter is built from the exact `gst-plugins-good` 1.28.6 source with
`packaging/android/patches/gst-plugins-good-1.28.6-qml6-android.patch`; the patch only enables the
Android/EGL branch already present in the upstream Qt 6 plug-in implementation. This patch and the
complete corresponding-source recipe are part of the source release.

本应用以 `GPL-2.0-or-later` 发布。用户可以用兼容构建替换动态链接库。对应的固定上游源码包
可从 `dependencies.lock.json` 中的地址取得，使用前必须核验其中记录的摘要。

Android 包从官方 1.28.6 bundle 构建 `libgstreamer_android.so`，并将 qml6 插件静态注册到
GPL 应用库。后者使用摘要完全匹配的 `gst-plugins-good` 1.28.6 源码及
`packaging/android/patches/gst-plugins-good-1.28.6-qml6-android.patch` 构建；该补丁只启用
上游 Qt 6 插件实现中已经存在的 Android/EGL 分支。源码发布包包含此补丁及完整对应源码构建配方。
