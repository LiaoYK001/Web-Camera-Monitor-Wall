#include "webobs/platform_runtime.hpp"
#include <algorithm>
#include <array>
#include <charconv>
#include <cstdlib>
#include <limits>
#include <stdexcept>
#include <thread>
#include <cstdio>
#ifdef _WIN32
#include <windows.h>
#include <sddl.h>
#include <aclapi.h>
#include <io.h>
#include <process.h>
#else
#include <fcntl.h>
#include <poll.h>
#include <spawn.h>
#include <sys/wait.h>
#include <unistd.h>
extern char** environ;
#endif

namespace webobs {
int runtime_port(int port) {
    const char* name = nullptr;
    switch (port) {
    case 8091: name = "WEBOBS_NVR_INTERNAL_PORT"; break;
    case 8092: name = "WEBOBS_CAMERA_INTERNAL_PORT"; break;
    case 8093: name = "WEBOBS_EVENTS_INTERNAL_PORT"; break;
    case 8094: name = "WEBOBS_V2_INTERNAL_PORT"; break;
    case 8095: name = "WEBOBS_CLUSTER_INTERNAL_PORT"; break;
    case 8889: name = "WEBOBS_MEDIAMTX_WEBRTC_PORT"; break;
    case 9997: name = "WEBOBS_MEDIAMTX_API_PORT"; break;
    case 8554: name = "WEBOBS_MEDIAMTX_RTSP_PORT"; break;
    case 11984: name = "WEBOBS_GO2RTC_API_PORT"; break;
    case 18554: name = "WEBOBS_GO2RTC_RTSP_PORT"; break;
    default: return port;
    }
    const char* value = std::getenv(name);
    if (!value || !*value) return port;
    int parsed = 0;
    const std::string_view text(value);
    const auto result = std::from_chars(text.data(), text.data()+text.size(), parsed);
    if (result.ec != std::errc{} || result.ptr != text.data()+text.size() || parsed < 1024 || parsed > 65535)
        throw std::runtime_error("invalid internal runtime port");
    return parsed;
}
std::string runtime_http(int port, std::string_view suffix) {
    return "http://127.0.0.1:" + std::to_string(runtime_port(port)) + std::string(suffix);
}
std::string runtime_rtsp(int port, std::string_view suffix) {
    return "rtsp://127.0.0.1:" + std::to_string(runtime_port(port)) + std::string(suffix);
}
std::string runtime_path(std::string_view name, std::string_view fallback) {
    const char* value = std::getenv(std::string(name).c_str());
    return value && *value ? value : std::string(fallback);
}
std::string command_quote(std::string_view value) {
#ifdef _WIN32
    // CommandLineToArgvW/MSVC rules. Never invoke cmd.exe for camera input.
    std::string result = "\""; std::size_t slashes = 0;
    for (char character : value) {
        if (character == '\\') { ++slashes; continue; }
        result.append(character == '"' ? slashes * 2 + 1 : slashes, '\\');
        result += character; slashes = 0;
    }
    result.append(slashes * 2, '\\'); return result + "\"";
#else
    std::string result = "'";
    for (char character : value) result += character == '\'' ? "'\\''" : std::string(1, character);
    return result + "'";
#endif
}
long process_id() {
#ifdef _WIN32
    return static_cast<long>(GetCurrentProcessId());
#else
    return static_cast<long>(getpid());
#endif
}
bool readable_device(const std::filesystem::path& path) {
#ifdef _WIN32
    return _waccess(path.c_str(), 6) == 0;
#else
    return access(path.c_str(), R_OK | W_OK) == 0;
#endif
}
void install_owner_shutdown(void (*shutdown)()) {
    if (runtime_path("WEBOBS_OWNER_STDIN", "") != "true") return;
    // Only the supervisor possesses this anonymous input pipe. No HTTP shutdown API.
    std::thread([shutdown] {
        std::array<char, 64> line{};
        if (!std::fgets(line.data(), static_cast<int>(line.size()), stdin) || std::string_view(line.data()) == "shutdown\n") shutdown();
    }).detach();
}

ProcessResult capture_process(const std::vector<std::string>& arguments, std::chrono::seconds timeout, std::size_t limit) {
    ProcessResult result;
    if (arguments.empty() || timeout.count() <= 0) return result;
#ifdef _WIN32
    auto wide = [](const std::string& text) {
        const int count = MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, text.data(), static_cast<int>(text.size()), nullptr, 0);
        std::wstring value(count, L'\0');
        if (count) MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, text.data(), static_cast<int>(text.size()), value.data(), count);
        return value;
    };
    std::string command;
    for (const auto& value : arguments) { if (!command.empty()) command += ' '; command += command_quote(value); }
    auto command_line = wide(command);
    SECURITY_ATTRIBUTES security{sizeof(SECURITY_ATTRIBUTES), nullptr, TRUE};
    HANDLE read_handle = nullptr, write_handle = nullptr;
    if (!CreatePipe(&read_handle, &write_handle, &security, 0)) return result;
    SetHandleInformation(read_handle, HANDLE_FLAG_INHERIT, 0);
    HANDLE null_handle = CreateFileW(L"NUL", GENERIC_READ|GENERIC_WRITE, FILE_SHARE_READ|FILE_SHARE_WRITE, &security, OPEN_EXISTING, 0, nullptr);
    STARTUPINFOW startup{sizeof(STARTUPINFOW)};
    startup.dwFlags = STARTF_USESTDHANDLES; startup.hStdOutput = write_handle; startup.hStdError = null_handle; startup.hStdInput = null_handle;
    PROCESS_INFORMATION process{};
    const bool started = CreateProcessW(nullptr, command_line.data(), nullptr, nullptr, TRUE, CREATE_NO_WINDOW, nullptr, nullptr, &startup, &process);
    CloseHandle(write_handle); CloseHandle(null_handle);
    if (!started) { CloseHandle(read_handle); return result; }
    const auto deadline = std::chrono::steady_clock::now() + timeout;
    bool exited = false;
    while (true) {
        if (std::chrono::steady_clock::now() >= deadline) { result.timed_out = true; break; }
        DWORD available = 0, count = 0;
        if (PeekNamedPipe(read_handle, nullptr, 0, nullptr, &available, nullptr) && available) {
            std::array<char, 16384> buffer{};
            if (ReadFile(read_handle, buffer.data(), std::min<DWORD>(available, static_cast<DWORD>(buffer.size())), &count, nullptr)) {
                if (result.output.size()+count > limit) break;
                result.output.append(buffer.data(), count);
            }
            continue;
        }
        exited = WaitForSingleObject(process.hProcess, 0) == WAIT_OBJECT_0;
        if (exited) break;
        if (std::chrono::steady_clock::now() >= deadline) { result.timed_out = true; break; }
        std::this_thread::sleep_for(std::chrono::milliseconds(10));
    }
    if (!exited) TerminateProcess(process.hProcess, 124);
    WaitForSingleObject(process.hProcess, INFINITE);
    DWORD code = 0; GetExitCodeProcess(process.hProcess, &code); result.code = exited ? static_cast<int>(code) : -1;
    CloseHandle(process.hThread); CloseHandle(process.hProcess); CloseHandle(read_handle);
#else
    int pipes[2]; if (pipe(pipes) != 0) return result;
    fcntl(pipes[0], F_SETFL, O_NONBLOCK);
    posix_spawn_file_actions_t actions;
    posix_spawn_file_actions_init(&actions);
    posix_spawn_file_actions_addopen(&actions, STDIN_FILENO, "/dev/null", O_RDONLY, 0);
    posix_spawn_file_actions_addopen(&actions, STDERR_FILENO, "/dev/null", O_WRONLY, 0);
    posix_spawn_file_actions_adddup2(&actions, pipes[1], STDOUT_FILENO);
    posix_spawn_file_actions_addclose(&actions, pipes[0]); posix_spawn_file_actions_addclose(&actions, pipes[1]);
    std::vector<char*> raw; for (const auto& value : arguments) raw.push_back(const_cast<char*>(value.c_str())); raw.push_back(nullptr);
    pid_t child = -1; const int status = posix_spawnp(&child, raw.front(), &actions, nullptr, raw.data(), environ);
    posix_spawn_file_actions_destroy(&actions); close(pipes[1]);
    if (status) { close(pipes[0]); return result; }
    int child_status = 0; bool exited = false, eof = false;
    const auto deadline = std::chrono::steady_clock::now()+timeout;
    while (!exited || !eof) {
        std::array<char, 16384> buffer{};
        const ssize_t count = read(pipes[0], buffer.data(), buffer.size());
        if (count > 0) { if (result.output.size()+static_cast<std::size_t>(count) > limit) break; result.output.append(buffer.data(), static_cast<std::size_t>(count)); }
        else if (count == 0) eof = true;
        else if (errno != EAGAIN && errno != EINTR) break;
        if (!exited) exited = waitpid(child, &child_status, WNOHANG) == child;
        if (std::chrono::steady_clock::now() >= deadline) { result.timed_out = true; break; }
        if (count <= 0) std::this_thread::sleep_for(std::chrono::milliseconds(10));
    }
    if (!exited) { kill(child, SIGKILL); while (waitpid(child, &child_status, 0) < 0 && errno == EINTR) {} }
    close(pipes[0]); result.code = exited && WIFEXITED(child_status) ? WEXITSTATUS(child_status) : -1;
#endif
    return result;
}
}
