#pragma once

#include "webobs/config.hpp"

#include <memory>
#include <optional>
#include <string>

namespace webobs {

class SceneController;

class ControlServer {
public:
    ControlServer(const Config &config, SceneController &controller);
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
