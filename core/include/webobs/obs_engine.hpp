#pragma once

#include "webobs/config.hpp"

namespace webobs {

enum class ExitCode : int {
    success = 0,
    invalid_config = 2,
    obs_initialization_failed = 3,
    source_timeout = 4,
    output_failed = 5,
    remux_failed = 6,
};

ExitCode run_obs_engine(const Config &config);

} // namespace webobs
