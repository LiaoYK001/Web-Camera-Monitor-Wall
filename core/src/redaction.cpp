#include "webobs/redaction.hpp"

#include <array>

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

} // namespace webobs
