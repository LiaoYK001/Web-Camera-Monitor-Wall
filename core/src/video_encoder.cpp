#include "webobs/video_encoder.hpp"

namespace webobs {

std::string_view video_encoder_preference_name(VideoEncoderPreference preference)
{
    switch (preference) {
    case VideoEncoderPreference::automatic:
        return "auto";
    case VideoEncoderPreference::x264:
        return "x264";
    case VideoEncoderPreference::vaapi:
        return "vaapi";
    case VideoEncoderPreference::qsv:
        return "qsv";
    case VideoEncoderPreference::nvenc:
        return "nvenc";
    }
    return "unknown";
}

std::string_view video_encoder_kind_name(VideoEncoderKind kind)
{
    switch (kind) {
    case VideoEncoderKind::x264:
        return "x264";
    case VideoEncoderKind::vaapi:
        return "vaapi";
    case VideoEncoderKind::qsv:
        return "qsv";
    case VideoEncoderKind::nvenc:
        return "nvenc";
    }
    return "unknown";
}

bool video_encoder_backend_ready(const VideoEncoderBackend &backend)
{
    return backend.device_present && backend.va_driver_loaded && backend.encoder_available &&
           backend.encode_supported && backend.runtime_probe_passed;
}

VideoEncoderCapabilities select_video_encoder(VideoEncoderPreference preference,
                                              VideoEncoderCapabilities capabilities)
{
    capabilities.requested = preference;
    capabilities.selected = VideoEncoderKind::x264;
    capabilities.fallback = false;
    capabilities.fallback_reason.clear();

    const auto select_if_ready = [&capabilities](VideoEncoderKind kind,
                                                 const VideoEncoderBackend &backend) {
        if (!video_encoder_backend_ready(backend))
            return false;
        capabilities.selected = kind;
        return true;
    };

    switch (preference) {
    case VideoEncoderPreference::automatic:
        if (select_if_ready(VideoEncoderKind::nvenc, capabilities.nvenc) ||
            select_if_ready(VideoEncoderKind::qsv, capabilities.qsv) ||
            select_if_ready(VideoEncoderKind::vaapi, capabilities.vaapi))
            return capabilities;
        return capabilities;
    case VideoEncoderPreference::x264:
        return capabilities;
    case VideoEncoderPreference::vaapi:
        capabilities.fallback = !select_if_ready(VideoEncoderKind::vaapi, capabilities.vaapi);
        if (capabilities.fallback)
            capabilities.fallback_reason = "vaapi_runtime_not_ready";
        return capabilities;
    case VideoEncoderPreference::qsv:
        capabilities.fallback = !select_if_ready(VideoEncoderKind::qsv, capabilities.qsv);
        if (capabilities.fallback)
            capabilities.fallback_reason = "qsv_runtime_not_ready";
        return capabilities;
    case VideoEncoderPreference::nvenc:
        capabilities.fallback = !select_if_ready(VideoEncoderKind::nvenc, capabilities.nvenc);
        if (capabilities.fallback)
            capabilities.fallback_reason = "nvenc_runtime_not_ready";
        return capabilities;
    }
    capabilities.fallback = true;
    capabilities.fallback_reason = "unknown_encoder_preference";
    return capabilities;
}

} // namespace webobs
