#pragma once

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
    bool encoder_available = false;
};

struct VideoEncoderCapabilities {
    VideoEncoderBackend x264{true, true};
    VideoEncoderBackend vaapi;
    VideoEncoderBackend qsv;
    VideoEncoderBackend nvenc;
    VideoEncoderPreference requested = VideoEncoderPreference::automatic;
    VideoEncoderKind selected = VideoEncoderKind::x264;
    bool fallback = false;
};

[[nodiscard]] std::string_view video_encoder_preference_name(VideoEncoderPreference preference);
[[nodiscard]] std::string_view video_encoder_kind_name(VideoEncoderKind kind);
[[nodiscard]] bool video_encoder_backend_ready(const VideoEncoderBackend &backend);
[[nodiscard]] VideoEncoderCapabilities select_video_encoder(VideoEncoderPreference preference,
                                                             VideoEncoderCapabilities capabilities);

} // namespace webobs
