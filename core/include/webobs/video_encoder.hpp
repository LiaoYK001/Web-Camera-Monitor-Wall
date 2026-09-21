#pragma once

#include <string>
#include <string_view>

namespace webobs {

enum class VideoEncoderPreference {
    automatic,
    x264,
    vaapi,
    qsv,
    nvenc,
};

enum class VideoEncoderKind {
    x264,
    vaapi,
    qsv,
    nvenc,
};

struct VideoEncoderBackend {
    bool device_present = false;
    /** VA-API user-space driver.  NVENC and QSV never depend on this field. */
    bool va_driver_loaded = false;
    /** CUDA/NVENC runtime library is loadable (libcuda / libnvidia-encode). */
    bool library_loaded = false;
    bool encoder_available = false;
    bool encode_supported = false;
    bool decode_supported = false;
    bool runtime_probe_passed = false;
};

struct VideoEncoderCapabilities {
    VideoEncoderBackend x264{true, true, true, true, true, true};
    VideoEncoderBackend vaapi;
    VideoEncoderBackend qsv;
    VideoEncoderBackend nvenc;
    VideoEncoderPreference requested = VideoEncoderPreference::automatic;
    VideoEncoderKind selected = VideoEncoderKind::x264;
    bool fallback = false;
    std::string fallback_reason;
};

struct RendererCapabilities {
    std::string requested = "auto";
    std::string selected = "software";
    bool hardware_probe_passed = false;
    bool fallback = false;
    std::string fallback_reason;
};

struct HardwareDecodeCapabilities {
    std::string requested = "auto";
    std::string selected = "off";
    /** "cuda", "vaapi" or "software"; the backend actually selected at runtime. */
    std::string backend = "software";
    bool fallback = false;
    std::string fallback_reason;
};

[[nodiscard]] std::string_view video_encoder_preference_name(VideoEncoderPreference preference);
[[nodiscard]] std::string_view video_encoder_kind_name(VideoEncoderKind kind);
/** Readiness is per encoder kind: NVENC is not a VA-API backend. */
[[nodiscard]] bool video_encoder_backend_ready(VideoEncoderKind kind, const VideoEncoderBackend &backend);
[[nodiscard]] VideoEncoderCapabilities select_video_encoder(VideoEncoderPreference preference,
                                                             VideoEncoderCapabilities capabilities);

} // namespace webobs
