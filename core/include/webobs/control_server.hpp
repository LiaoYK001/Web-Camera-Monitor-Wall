#pragma once

#include "webobs/config.hpp"

#include <atomic>
#include <memory>
#include <optional>
#include <string>

namespace webobs {

class SceneController;

struct RuntimeStatus {
    std::atomic<bool> recording_active{false};
    std::atomic<bool> webrtc_configured{false};
    std::atomic<bool> webrtc_ready{false};

    [[nodiscard]] bool ready() const
    {
        return recording_active.load() && (!webrtc_configured.load() || webrtc_ready.load());
    }
};

class ControlServer {
public:
    ControlServer(const Config &config, SceneController &controller, RuntimeStatus &status);
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
