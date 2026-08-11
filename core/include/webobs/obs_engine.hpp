#pragma once

#include "webobs/config.hpp"
#include "webobs/scene_document.hpp"

namespace webobs {

enum class ExitCode : int {
    success = 0,
    invalid_config = 2,
    obs_initialization_failed = 3,
    source_timeout = 4,
    output_failed = 5,
    remux_failed = 6,
    scene_store_failed = 7,
    control_server_failed = 8,
};

ExitCode run_obs_engine(const Config &config, const SceneDocument &document);

} // namespace webobs
