LOCAL_PATH := $(call my-dir)

ifndef GSTREAMER_ROOT_ANDROID
$(error GSTREAMER_ROOT_ANDROID must point to the verified GStreamer 1.28.6 Android bundle)
endif

GSTREAMER_NDK_BUILD_PATH := $(GSTREAMER_ROOT_ANDROID)/share/gst-android/ndk-build
include $(GSTREAMER_NDK_BUILD_PATH)/plugins.mk

# Registration is static and bounded. The final APK runtime probe rejects any
# missing RTSP/MJPEG/HLS/WHEP/codec element before qualification can start.
GSTREAMER_PLUGINS := $(GSTREAMER_PLUGINS_CORE) \
    $(GSTREAMER_PLUGINS_PLAYBACK) \
    $(GSTREAMER_PLUGINS_CODECS) \
    $(GSTREAMER_PLUGINS_NET) \
    $(GSTREAMER_PLUGINS_SYS) \
    rswebrtc
GSTREAMER_EXTRA_DEPS := gstreamer-video-1.0 gstreamer-rtsp-1.0 \
    gstreamer-app-1.0 gstreamer-gl-1.0 gstreamer-gl-egl-1.0
GSTREAMER_JAVA_SRC_DIR := $(LOCAL_PATH)/../src

include $(GSTREAMER_NDK_BUILD_PATH)/gstreamer-1.0.mk
