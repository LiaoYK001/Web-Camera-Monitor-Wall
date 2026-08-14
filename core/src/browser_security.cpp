#include "webobs/browser_security.hpp"

#include <algorithm>
#include <array>
#include <charconv>
#include <cctype>
#include <string>

namespace webobs {
namespace {

BrowserUrlResult failure(std::string message)
{
    BrowserUrlResult result;
    result.error = std::move(message);
    return result;
}

std::string lowercase(std::string value)
{
    std::transform(value.begin(), value.end(), value.begin(),
                   [](unsigned char character) { return static_cast<char>(std::tolower(character)); });
    return value;
}

bool parse_port(std::string_view value, int &port)
{
    if (value.empty())
        return false;
    int parsed = 0;
    const auto result = std::from_chars(value.data(), value.data() + value.size(), parsed);
    if (result.ec != std::errc{} || result.ptr != value.data() + value.size() || parsed < 1 ||
        parsed > 65535)
        return false;
    port = parsed;
    return true;
}

bool parse_ipv4(std::string_view host, std::array<int, 4> &octets)
{
    std::size_t cursor = 0;
    for (std::size_t index = 0; index < octets.size(); ++index) {
        const std::size_t separator = host.find('.', cursor);
        const std::size_t end = separator == std::string_view::npos ? host.size() : separator;
        if (end == cursor || (index < 3) != (separator != std::string_view::npos))
            return false;
        int value = -1;
        const auto parsed = std::from_chars(host.data() + cursor, host.data() + end, value);
        if (parsed.ec != std::errc{} || parsed.ptr != host.data() + end || value < 0 || value > 255)
            return false;
        octets[index] = value;
        cursor = end + 1;
    }
    return true;
}

bool valid_dns_name(std::string_view host)
{
    if (host.empty() || host.size() > 253 || host.front() == '.' || host.back() == '.')
        return false;
    std::size_t label_length = 0;
    for (unsigned char character : host) {
        if (character == '.') {
            if (label_length == 0 || label_length > 63)
                return false;
            label_length = 0;
            continue;
        }
        if (!std::isalnum(character) && character != '-')
            return false;
        ++label_length;
    }
    return label_length > 0 && label_length <= 63;
}

} // namespace

BrowserUrlResult parse_browser_url(std::string_view url)
{
    if (url.empty() || url.size() > 2048)
        return failure("browser URL has an invalid length");
    if (std::any_of(url.begin(), url.end(), [](unsigned char character) {
            return character <= 0x20 || character == 0x7f;
        }))
        return failure("browser URL must not contain whitespace or control characters");

    const std::size_t scheme_end = url.find("://");
    if (scheme_end == std::string_view::npos)
        return failure("browser URL must use http or https");
    const std::string scheme = lowercase(std::string(url.substr(0, scheme_end)));
    if (scheme != "http" && scheme != "https")
        return failure("browser URL must use http or https");

    const std::size_t authority_start = scheme_end + 3;
    const std::size_t authority_end = url.find_first_of("/?#", authority_start);
    const std::string_view authority =
        url.substr(authority_start, authority_end == std::string_view::npos ? std::string_view::npos
                                                                           : authority_end - authority_start);
    if (authority.empty() || authority.find('@') != std::string_view::npos)
        return failure("browser URL authority must contain a host and no credentials");

    std::string host;
    int port = scheme == "https" ? 443 : 80;
    if (authority.front() == '[') {
        const std::size_t close = authority.find(']');
        if (close == std::string_view::npos || close == 1)
            return failure("browser URL contains an invalid IPv6 host");
        host = lowercase(std::string(authority.substr(1, close - 1)));
        const std::string_view remainder = authority.substr(close + 1);
        if (!remainder.empty() && (remainder.front() != ':' || !parse_port(remainder.substr(1), port)))
            return failure("browser URL contains an invalid port");
    } else {
        const std::size_t colon = authority.rfind(':');
        std::string_view host_view = authority;
        if (colon != std::string_view::npos) {
            if (authority.find(':') != colon || !parse_port(authority.substr(colon + 1), port))
                return failure("browser URL contains an invalid host or port");
            host_view = authority.substr(0, colon);
        }
        host = lowercase(std::string(host_view));
        std::array<int, 4> octets{};
        if (!parse_ipv4(host, octets) && !valid_dns_name(host))
            return failure("browser URL contains an invalid host");
    }

    if (host.empty())
        return failure("browser URL must contain a host");
    const bool ipv6 = host.find(':') != std::string::npos;
    std::string origin = scheme + "://" + (ipv6 ? "[" + host + "]" : host);
    if ((scheme == "http" && port != 80) || (scheme == "https" && port != 443))
        origin += ":" + std::to_string(port);

    BrowserUrlResult result;
    result.parts = BrowserUrlParts{.scheme = scheme, .host = host, .origin = origin, .port = port};
    return result;
}

std::optional<std::string> normalize_browser_origin(std::string_view input, std::string &normalized)
{
    const BrowserUrlResult parsed = parse_browser_url(input);
    if (!parsed.ok())
        return parsed.error;
    const std::size_t authority_end = input.find_first_of("/?#", input.find("://") + 3);
    if (authority_end != std::string_view::npos && input.substr(authority_end) != "/")
        return "browser allowed origin must not contain a path, query, or fragment";
    normalized = parsed.parts->origin;
    return std::nullopt;
}

bool browser_host_is_private_or_local(std::string_view host)
{
    const std::string normalized = lowercase(std::string(host));
    if (normalized == "localhost" || normalized.ends_with(".localhost") || normalized.ends_with(".local") ||
        normalized.find('.') == std::string::npos)
        return true;

    std::array<int, 4> octets{};
    if (parse_ipv4(normalized, octets)) {
        return octets[0] == 0 || octets[0] == 10 || octets[0] == 127 || octets[0] >= 224 ||
               (octets[0] == 100 && octets[1] >= 64 && octets[1] <= 127) ||
               (octets[0] == 169 && octets[1] == 254) ||
               (octets[0] == 172 && octets[1] >= 16 && octets[1] <= 31) ||
               (octets[0] == 192 && octets[1] == 168) ||
               (octets[0] == 198 && (octets[1] == 18 || octets[1] == 19));
    }

    if (normalized.find(':') != std::string::npos) {
        return normalized == "::" || normalized == "::1" || normalized.starts_with("fc") ||
               normalized.starts_with("fd") || normalized.starts_with("fe8") ||
               normalized.starts_with("fe9") || normalized.starts_with("fea") ||
               normalized.starts_with("feb") || normalized.starts_with("ff");
    }
    return false;
}

std::optional<std::string> validate_browser_url_policy(std::string_view url,
                                                       const BrowserSecurityPolicy &policy)
{
    const BrowserUrlResult parsed = parse_browser_url(url);
    if (!parsed.ok())
        return parsed.error;
    if (std::find(policy.allowed_origins.begin(), policy.allowed_origins.end(), parsed.parts->origin) ==
        policy.allowed_origins.end())
        return "browser URL origin is not present in the administrator allowlist";
    if (!policy.allow_private_networks && browser_host_is_private_or_local(parsed.parts->host))
        return "browser URL resolves to a local or private-network destination that is not enabled";
    return std::nullopt;
}

} // namespace webobs
