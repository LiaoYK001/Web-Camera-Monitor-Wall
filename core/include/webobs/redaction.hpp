#pragma once

#include <string>
#include <string_view>

namespace webobs {

std::string redact_rtsp_credentials(std::string_view input);
std::string redact_browser_url(std::string_view input);
std::string redact_url_secrets(std::string_view input);

} // namespace webobs
