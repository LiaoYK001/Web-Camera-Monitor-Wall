#include "webobs/config.hpp"
#include "webobs/obs_engine.hpp"
#include "webobs/redaction.hpp"

#include <iostream>
#include <string>
#include <vector>

int main(int argc, char **argv)
{
    std::vector<std::string> arguments;
    arguments.reserve(argc > 1 ? static_cast<std::size_t>(argc - 1) : 0);
    for (int index = 1; index < argc; ++index)
        arguments.emplace_back(argv[index]);

    const webobs::ParseResult result = webobs::parse_config(arguments, webobs::process_environment);
    if (!result.ok()) {
        std::cerr << "configuration error: " << webobs::redact_rtsp_credentials(result.error) << "\n\n"
                  << webobs::usage_text();
        return static_cast<int>(webobs::ExitCode::invalid_config);
    }
    if (result.action == webobs::ParseAction::show_help) {
        std::cout << webobs::usage_text();
        return 0;
    }
    if (result.action == webobs::ParseAction::show_version) {
        std::cout << webobs::version_text() << '\n';
        return 0;
    }

    return static_cast<int>(webobs::run_obs_engine(*result.config));
}
