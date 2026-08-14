#include "webobs/redaction.hpp"

#include <array>

namespace {

std::size_t url_token_end(std::string_view value, std::size_t start)
{
    const std::size_t end = value.find_first_of(" \t\r\n\"'<>)]}", start);
    return end == std::string_view::npos ? value.size() : end;
}

} // namespace

namespace webobs {

std::string redact_rtsp_credentials(std::string_view input)
{
    std::string output(input);
    constexpr std::array<std::string_view, 2> schemes = {"rtsp://", "rtsps://"};

    for (const std::string_view scheme : schemes) {
        std::size_t cursor = 0;
        while ((cursor = output.find(scheme, cursor)) != std::string::npos) {
            const std::size_t authority_start = cursor + scheme.size();
            std::size_t authority_end = output.find_first_of("/?# \t\r\n", authority_start);
            if (authority_end == std::string::npos)
                authority_end = output.size();

            const std::size_t at = output.rfind('@', authority_end);
            if (at != std::string::npos && at >= authority_start && at < authority_end) {
                const std::string_view user_info(output.data() + authority_start, at - authority_start);
                const std::string replacement = user_info.find(':') == std::string_view::npos ? "***" : "***:***";
                output.replace(authority_start, at - authority_start, replacement);
                cursor = authority_start + replacement.size() + 1;
            } else {
                cursor = authority_end;
            }
        }
    }
    return output;
}

std::string redact_browser_url(std::string_view input)
{
    std::string output(input);
    const std::size_t scheme_end = output.find("://");
    if (scheme_end == std::string::npos)
        return output;
    const std::size_t authority_start = scheme_end + 3;
    const std::size_t authority_end = output.find_first_of("/?#", authority_start);
    const std::size_t authority_limit =
        authority_end == std::string::npos ? output.size() : authority_end;
    const std::size_t at = output.rfind('@', authority_limit);
    if (at != std::string::npos && at >= authority_start && at < authority_limit)
        output.replace(authority_start, at - authority_start, "***");

    const std::size_t query = output.find('?', authority_start);
    const std::size_t fragment = output.find('#', authority_start);
    if (query != std::string::npos && (fragment == std::string::npos || query < fragment)) {
        const std::size_t query_end = fragment == std::string::npos ? output.size() : fragment;
        output.replace(query + 1, query_end - query - 1, "***");
    }
    const std::size_t updated_fragment = output.find('#', authority_start);
    if (updated_fragment != std::string::npos)
        output.replace(updated_fragment + 1, output.size() - updated_fragment - 1, "***");
    return output;
}

std::string redact_url_secrets(std::string_view input)
{
    std::string output = redact_rtsp_credentials(input);
    constexpr std::array<std::string_view, 2> schemes = {"http://", "https://"};
    for (const std::string_view scheme : schemes) {
        std::size_t cursor = 0;
        while ((cursor = output.find(scheme, cursor)) != std::string::npos) {
            const std::size_t end = url_token_end(output, cursor);
            const std::string safe = redact_browser_url(
                std::string_view(output).substr(cursor, end - cursor));
            output.replace(cursor, end - cursor, safe);
            cursor += safe.size();
        }
    }
    return output;
}

} // namespace webobs
