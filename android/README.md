# WebOBS Android

连接现有产品后端的独立 Android/WebView 客户端。开发、安装、自签密钥与 MuMu 实测说明见 [Android 客户端文档](../docs/android-client.md)。

An independent Android/WebView client for the existing product backend. See [toolchain, installation, local signing and emulator validation](../docs/android-client.md). Existing `clients/` Qt applications remain separate.

v4 应用内更新默认检查并下载可验证的正式 APK，安装需用户及系统确认；开关、恢复与独立实测见 [Android 更新](../docs/android-updates.md)。 / v4 in-app updates check and download verifiable stable APKs by default; user/system confirmation is required to install. See the update contract and isolated qualification guide.

Generated APKs, SDK paths, test data and private signing keys must stay outside Git. Development builds are not stable updater releases.
