#pragma once

#include <string>
#include <string_view>

namespace webobs {

std::string redact_rtsp_credentials(std::string_view input);

} // namespace webobs
