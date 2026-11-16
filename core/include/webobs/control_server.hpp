#pragma once

#include "webobs/config.hpp"
#include "webobs/native_preview.hpp"
#include "webobs/video_encoder.hpp"

#include <atomic>
#include <cstdint>
#include <memory>
#include <mutex>
#include <optional>
#include <string>

namespace webobs {

class SceneController;
class StudioController;

// Latest TAKE requested through the ordinary Studio API and the native host's
// acknowledgement of the actual OBS Program transition. The document commit
// and the Program pixels are separate facts; callers must not report "applied"
// until the host reports the matching revision and scene.
struct NativeProgramStatus {
    mutable std::mutex mutex;
    std::uint64_t revision = 0;
    std::string scene_id;
    std::string fingerprint;
    std::string state = "idle"; // idle, pending, applied, failed
    std::string error;
    std::uint64_t applied_revision = 0;
    std::string applied_scene_id;
};

struct RuntimeStatus {
    int configured_fps = 30; // Immutable after ControlServer construction, not a renderer readback.
    mutable NativePreviewControl native_preview;
    mutable NativeProgramStatus native_program;
    VideoEncoderCapabilities video_encoder;
    RendererCapabilities renderer;
    HardwareDecodeCapabilities hardware_decode;
    std::atomic<bool> control_plane_active{false};
    std::atomic<bool> engine_active{false};
    std::atomic<bool> recording_active{false};
    std::atomic<bool> webrtc_configured{false};
    std::atomic<bool> webrtc_ready{false};
    std::atomic<bool> composite_idle{false};
    std::atomic<std::uint64_t> source_visible{0};
    std::atomic<std::uint64_t> source_healthy{0};
    std::atomic<std::uint64_t> source_unhealthy{0};
    std::atomic<std::uint64_t> source_restarts{0};

    [[nodiscard]] bool ready() const
    {
        return control_plane_active.load() && (!webrtc_configured.load() || composite_idle.load() || webrtc_ready.load()) &&
               source_unhealthy.load() == 0;
    }
};

class ControlServer {
public:
    ControlServer(const Config &config, SceneController &controller, StudioController &studio,
                  RuntimeStatus &status);
    ~ControlServer();

    ControlServer(const ControlServer &) = delete;
    ControlServer &operator=(const ControlServer &) = delete;

    std::optional<std::string> start();
    void stop();
    bool composite_requested();

private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

} // namespace webobs
