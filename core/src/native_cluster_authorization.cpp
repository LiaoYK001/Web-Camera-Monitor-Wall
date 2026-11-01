#include "webobs/native_cluster_authorization.hpp"

#include <curl/curl.h>
#include <jansson.h>

#include <cstring>
#include <limits>
#include <mutex>
#include <utility>

namespace webobs {
namespace {
using Decision = NativeAuthorizationDecision;

bool alphanumeric(char c) noexcept
{
    return (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9');
}

bool identifier(std::string_view value, std::size_t minimum = 1) noexcept
{
    if (value.size() < minimum || value.size() > 64 || !alphanumeric(value.front()))
        return false;
    for (char c : value)
        if (!alphanumeric(c) && c != '.' && c != '_' && c != '-')
            return false;
    return true;
}

bool lower_hex(std::string_view value, std::size_t length) noexcept
{
    if (value.size() != length)
        return false;
    for (char c : value)
        if (!(c >= '0' && c <= '9') && !(c >= 'a' && c <= 'f'))
            return false;
    return true;
}

// Each object owns one libcurl global reference; copying a backend shares it.
// Serialize our own init/cleanup; unrelated libcurl owners retain their references.
std::mutex &global_mutex() { static std::mutex mutex; return mutex; }
struct CurlRuntime {
    bool ready = false;
    CurlRuntime()
    {
        std::lock_guard lock(global_mutex());
        ready = curl_global_init(CURL_GLOBAL_DEFAULT) == CURLE_OK;
    }
    ~CurlRuntime()
    {
        std::lock_guard lock(global_mutex());
        if (ready)
            curl_global_cleanup();
    }
};

struct Response {
    std::string body;
    std::size_t header_bytes = 0, header_count = 0;
};

bool byte_count(std::size_t size, std::size_t count, std::size_t &bytes) noexcept
{
    if (size != 0 && count > std::numeric_limits<std::size_t>::max() / size)
        return false;
    bytes = size * count;
    return true;
}

std::size_t body_callback(char *data, std::size_t size, std::size_t count, void *context) noexcept
{
    try {
        auto &body = static_cast<Response *>(context)->body;
        std::size_t bytes = 0;
        if (!byte_count(size, count, bytes) || bytes > 4096 || body.size() > 4096 - bytes)
            return 0;
        body.append(data, bytes);
        return bytes;
    } catch (...) { return 0; }
}

std::size_t header_callback(char *data, std::size_t size, std::size_t count, void *context) noexcept
{
    auto &response = *static_cast<Response *>(context);
    std::size_t bytes = 0;
    if (!byte_count(size, count, bytes) || bytes > 16384 ||
        response.header_bytes > 16384 - bytes || response.header_count >= 128 ||
        std::memchr(data, '\0', bytes))
        return 0;
    response.header_bytes += bytes;
    ++response.header_count; // Includes interim status lines, blanks and trailers.
    return bytes;
}

std::string_view string_value(const json_t *value) noexcept
{
    return json_is_string(value) ? std::string_view(json_string_value(value), json_string_length(value))
                                 : std::string_view{};
}

Decision parse_response(long status, const std::string &body, std::string_view permission)
{
    if (body.empty() || body.size() > 4096 || body.find('\0') != std::string::npos)
        return Decision::unavailable;
    std::unique_ptr<json_t, decltype(&json_decref)> root(
        json_loadb(body.data(), body.size(), JSON_REJECT_DUPLICATES, nullptr), &json_decref);
    if (!json_is_object(root.get()))
        return Decision::unavailable;
    if (status == 200) {
        // The real service returns no username echo. Bind this reply to the
        // trusted principal's dedicated POST and correlate the requested permission.
        return json_object_size(root.get()) == 3 &&
            json_is_true(json_object_get(root.get(), "allowed")) &&
            lower_hex(string_value(json_object_get(root.get(), "userId")), 32) &&
            string_value(json_object_get(root.get(), "permission")) == permission
            ? Decision::allowed : Decision::unavailable;
    }
    const json_t *error = json_object_get(root.get(), "error");
    if (json_object_size(root.get()) != 1 || !json_is_object(error) || json_object_size(error) != 2)
        return Decision::unavailable;
    const auto code = string_value(json_object_get(error, "code"));
    const auto message = string_value(json_object_get(error, "message"));
    if (status == 403 && code == "permission_rejected" &&
        message == "permission or resource scope was rejected")
        return Decision::denied;
    if (status == 404 && code == "user_not_found" && message == "user is not managed by RBAC")
        return Decision::unknown_user;
    return Decision::unavailable; // Includes internal_auth_rejected, never a normal deny.
}
} // namespace

NativeClusterAuthorizationBackend::NativeClusterAuthorizationBackend(NativeClusterAuthorizationConfig config)
    : config_(std::move(config))
{
    if (!config_.port || !lower_hex(config_.internal_token, 64) ||
        config_.connect_timeout.count() < 1 || config_.connect_timeout.count() > 500 ||
        config_.request_timeout.count() < 1 || config_.request_timeout.count() > 2000 ||
        config_.connect_timeout > config_.request_timeout)
        return;
    try {
        auto runtime = std::make_shared<CurlRuntime>();
        if (runtime->ready)
            runtime_ = std::move(runtime);
    } catch (...) { /* Unconfigured; never expose configuration or library diagnostics. */ }
}

NativeAuthorizationDecision NativeClusterAuthorizationBackend::operator()(std::string_view principal,
    std::string_view permission, std::string_view camera_id) const noexcept
{
    if (!configured() || !identifier(principal, 3) ||
        (permission != "scene.read" && permission != "scene.write" && permission != "live.view") ||
        (!camera_id.empty() && !identifier(camera_id)) || (permission == "live.view" && camera_id.empty()))
        return Decision::unavailable;
    try {
        const std::string url = "http://127.0.0.1:" + std::to_string(config_.port) + "/auth/authorize";
        // Inputs have an ASCII-only alphabet without JSON escapes; size is <= 190.
        const std::string body = "{\"cameraId\":\"" + std::string(camera_id) + "\",\"permission\":\"" +
            std::string(permission) + "\",\"username\":\"" + std::string(principal) + "\"}";
        const std::string token_header = "X-WebObs-Internal-Admin: " + config_.internal_token;
        Response response;
        std::unique_ptr<curl_slist, decltype(&curl_slist_free_all)> headers(nullptr, &curl_slist_free_all);
        std::unique_ptr<CURL, decltype(&curl_easy_cleanup)> handle(curl_easy_init(), &curl_easy_cleanup);
        if (!handle)
            return Decision::unavailable;
        for (const char *header : {"Content-Type: application/json", "Accept: application/json", "Expect:",
                                   "Connection: close", token_header.c_str()}) {
            curl_slist *next = curl_slist_append(headers.get(), header);
            if (!next)
                return Decision::unavailable;
            (void)headers.release();
            headers.reset(next);
        }
        auto set = [&](CURLoption option, auto value) { return curl_easy_setopt(handle.get(), option, value) == CURLE_OK; };
        if (!(set(CURLOPT_URL, url.c_str()) && set(CURLOPT_PROTOCOLS_STR, "http") &&
              set(CURLOPT_REDIR_PROTOCOLS_STR, "http") && set(CURLOPT_FOLLOWLOCATION, 0L) &&
              set(CURLOPT_PROXY, "") && set(CURLOPT_NOPROXY, "*") &&
              set(CURLOPT_NETRC, static_cast<long>(CURL_NETRC_IGNORED)) && set(CURLOPT_HTTPAUTH, CURLAUTH_NONE) &&
              set(CURLOPT_NOSIGNAL, 1L) && set(CURLOPT_IPRESOLVE, static_cast<long>(CURL_IPRESOLVE_V4)) &&
              set(CURLOPT_CONNECTTIMEOUT_MS, static_cast<long>(config_.connect_timeout.count())) &&
              set(CURLOPT_TIMEOUT_MS, static_cast<long>(config_.request_timeout.count())) &&
              set(CURLOPT_HTTP_VERSION, static_cast<long>(CURL_HTTP_VERSION_1_1)) && set(CURLOPT_HTTP09_ALLOWED, 0L) &&
              set(CURLOPT_VERBOSE, 0L) && set(CURLOPT_HTTPHEADER, headers.get()) && set(CURLOPT_POST, 1L) &&
              set(CURLOPT_POSTFIELDS, body.data()) &&
              set(CURLOPT_POSTFIELDSIZE_LARGE, static_cast<curl_off_t>(body.size())) &&
              set(CURLOPT_WRITEFUNCTION, &body_callback) && set(CURLOPT_WRITEDATA, &response) &&
              set(CURLOPT_HEADERFUNCTION, &header_callback) && set(CURLOPT_HEADERDATA, &response)))
            return Decision::unavailable;
        long status = 0;
        if (curl_easy_perform(handle.get()) != CURLE_OK ||
            curl_easy_getinfo(handle.get(), CURLINFO_RESPONSE_CODE, &status) != CURLE_OK)
            return Decision::unavailable;
        return parse_response(status, response.body, permission);
    } catch (...) { return Decision::unavailable; }
}
} // namespace webobs
