# Third-party build tools

The Android application source uses the repository's GPL-2.0-or-later license. The APK delegates rendering/media to the device's system WebView; it does not bundle OBS, go2rtc, Qt, GStreamer or those upstream binaries.

The checked-in Gradle 8.13 wrapper was generated from the checksum-verified official Gradle distribution and is licensed under Apache-2.0. The original distribution license and notices are retained in `gradle/GRADLE-LICENSE.txt` and `gradle/GRADLE-NOTICE.txt`; the notices also list the distribution's build-time dependencies. The wrapper JAR SHA-256 is pinned in `toolchain.lock.json`.

Android Gradle Plugin 8.13.2 and its build dependencies come from the official Google/Maven repositories. Their resolved artifact hashes are recorded in `gradle/verification-metadata.xml`. JUnit 4.13.2 (EPL-1.0) and Hamcrest 1.3 (BSD-3-Clause) are test-only dependencies and are not packaged in the application.

Android SDK command-line/build tools are external development dependencies, governed by the Android SDK license accepted during environment installation; the SDK is not redistributed in the APK or source bundle.
