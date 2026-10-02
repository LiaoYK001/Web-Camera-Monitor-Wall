#pragma once
#include <chrono>
#include <cstddef>
#include <filesystem>
#include <optional>
#include <string>
#include <string_view>
#include <vector>

namespace webobs {
int runtime_port(int legacy_port);
std::string runtime_http(int legacy_port, std::string_view suffix = {});
std::string runtime_rtsp(int legacy_port, std::string_view suffix = {});
std::string runtime_path(std::string_view environment, std::string_view fallback);
std::string command_quote(std::string_view argument);
struct ProcessResult { int code = -1; std::string output; bool timed_out = false; };
ProcessResult capture_process(const std::vector<std::string>& arguments,
                              std::chrono::seconds timeout, std::size_t limit);
long process_id();
bool readable_device(const std::filesystem::path& path);
void install_owner_shutdown(void (*shutdown)());
struct PrivateRead { bool missing = false; std::string content; std::string error; };
#ifdef _WIN32
PrivateRead windows_private_read(const std::filesystem::path&, std::size_t limit);
std::optional<std::string> windows_private_write(const std::filesystem::path&, std::string_view);
#endif
}
