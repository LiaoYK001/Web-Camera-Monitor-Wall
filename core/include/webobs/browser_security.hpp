#pragma once

#include <optional>
#include <string>
#include <string_view>
#include <vector>

namespace webobs {

struct BrowserUrlParts {
    std::string scheme;
    std::string host;
    std::string origin;
    int port = 0;
};

struct BrowserSecurityPolicy {
    std::vector<std::string> allowed_origins;
    bool allow_private_networks = false;
};

struct BrowserUrlResult {
    std::optional<BrowserUrlParts> parts;
    std::string error;

    [[nodiscard]] bool ok() const { return parts.has_value() && error.empty(); }
};

BrowserUrlResult parse_browser_url(std::string_view url);
std::optional<std::string> normalize_browser_origin(std::string_view input, std::string &normalized);
bool browser_host_is_private_or_local(std::string_view host);
std::optional<std::string> validate_browser_url_policy(std::string_view url,
                                                       const BrowserSecurityPolicy &policy);

} // namespace webobs
