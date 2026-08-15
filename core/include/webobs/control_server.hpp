#pragma once

#include "webobs/config.hpp"
#include "webobs/video_encoder.hpp"

#include <atomic>
#include <cstdint>
#include <memory>
#include <optional>
#include <string>

namespace webobs {

class SceneController;
class StudioController;

struct RuntimeStatus {
    VideoEncoderCapabilities video_encoder;
    std::atomic<bool> recording_active{false};
    std::atomic<bool> webrtc_configured{false};
    std::atomic<bool> webrtc_ready{false};
    std::atomic<std::uint64_t> source_visible{0};
    std::atomic<std::uint64_t> source_healthy{0};
    std::atomic<std::uint64_t> source_unhealthy{0};
    std::atomic<std::uint64_t> source_restarts{0};

    [[nodiscard]] bool ready() const
    {
        return recording_active.load() && (!webrtc_configured.load() || webrtc_ready.load()) &&
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

private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

} // namespace webobs
