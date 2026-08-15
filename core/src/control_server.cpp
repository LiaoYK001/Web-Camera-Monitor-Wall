#include "webobs/control_server.hpp"

#include "webobs/authentication.hpp"
#include "webobs/audit_event.hpp"
#include "webobs/scene_controller.hpp"
#include "webobs/studio_controller.hpp"
#include "webobs/scene_document.hpp"

#include <boost/asio.hpp>
#include <boost/beast/core.hpp>
#include <boost/beast/http.hpp>
#include <boost/beast/websocket.hpp>
#include <curl/curl.h>
#include <util/base.h>

#include <csignal>
#include <fcntl.h>
#include <spawn.h>
#include <sys/wait.h>
#include <unistd.h>

#include <algorithm>
#include <array>
#include <atomic>
#include <cerrno>
#include <charconv>
#include <cctype>
#include <chrono>
#include <cstdint>
#include <deque>
#include <filesystem>
#include <fstream>
#include <memory>
#include <mutex>
#include <optional>
#include <random>
#include <string>
#include <string_view>
#include <thread>
#include <unordered_map>
#include <utility>
#include <vector>

extern char **environ;

namespace webobs {
namespace {

namespace net = boost::asio;
namespace beast = boost::beast;
namespace http = beast::http;
namespace websocket = beast::websocket;
using tcp = net::ip::tcp;
using HttpRequest = http::request<http::string_body>;
using HttpResponse = http::response<http::string_body>;

#ifndef WEBOBS_WEB_ROOT
#define WEBOBS_WEB_ROOT "/opt/webobs/ui"
#endif

std::string_view view(beast::string_view value)
{
    return {value.data(), value.size()};
}

std::string lowercase(std::string_view value)
{
    std::string result(value);
    std::transform(result.begin(), result.end(), result.begin(),
                   [](unsigned char character) { return static_cast<char>(std::tolower(character)); });
    return result;
}

bool decimal_port(std::string_view value)
{
    if (value.empty() || value.size() > 5 ||
        !std::all_of(value.begin(), value.end(), [](unsigned char character) { return std::isdigit(character); }))
        return false;
    unsigned int port = 0;
    const auto parsed = std::from_chars(value.data(), value.data() + value.size(), port);
    return parsed.ec == std::errc{} && parsed.ptr == value.data() + value.size() && port > 0 && port <= 65535;
}

bool safe_local_authority(std::string_view authority)
{
    const std::string normalized = lowercase(authority);
    if (normalized.starts_with('[')) {
        const std::size_t bracket = normalized.find(']');
        if (bracket == std::string::npos || normalized.substr(0, bracket + 1) != "[::1]")
            return false;
        return bracket + 1 == normalized.size() ||
               (normalized[bracket + 1] == ':' && decimal_port(normalized.substr(bracket + 2)));
    }

    const std::size_t colon = normalized.rfind(':');
    const std::string_view host = colon == std::string::npos ? std::string_view(normalized)
                                                             : std::string_view(normalized).substr(0, colon);
    if (host != "localhost" && host != "127.0.0.1")
        return false;
    return colon == std::string::npos || decimal_port(std::string_view(normalized).substr(colon + 1));
}

std::string_view origin_authority(std::string_view origin)
{
    const std::size_t separator = origin.find("://");
    return separator == std::string_view::npos ? std::string_view{} : origin.substr(separator + 3);
}

bool control_authority_allowed(std::string_view authority, const std::vector<std::string> &allowed_origins)
{
    if (safe_local_authority(authority))
        return true;
    const std::string normalized = lowercase(authority);
    return std::any_of(allowed_origins.begin(), allowed_origins.end(), [&normalized](const std::string &origin) {
        return lowercase(origin_authority(origin)) == normalized;
    });
}

bool request_origin_allowed(const HttpRequest &request, bool required,
                            const std::vector<std::string> &allowed_origins)
{
    const auto origin = request.find(http::field::origin);
    if (origin == request.end())
        return !required;
    std::string normalized_origin;
    if (normalize_browser_origin(view(origin->value()), normalized_origin))
        return false;
    const std::string_view authority = origin_authority(normalized_origin);
    if (lowercase(authority) != lowercase(view(request[http::field::host])))
        return false;
    if (safe_local_authority(authority))
        return true;
    return std::find(allowed_origins.begin(), allowed_origins.end(), normalized_origin) != allowed_origins.end();
}

bool json_content_type(const HttpRequest &request)
{
    const auto header = request.find(http::field::content_type);
    if (header == request.end())
        return false;
    std::string value = lowercase(view(header->value()));
    const std::size_t semicolon = value.find(';');
    if (semicolon != std::string::npos)
        value.erase(semicolon);
    while (!value.empty() && std::isspace(static_cast<unsigned char>(value.back())))
        value.pop_back();
    const std::size_t first = value.find_first_not_of(" \t");
    return first != std::string::npos && value.substr(first) == "application/json";
}

bool sdp_content_type(const HttpRequest &request)
{
    const auto header = request.find(http::field::content_type);
    if (header == request.end())
        return false;
    std::string value = lowercase(view(header->value()));
    const std::size_t semicolon = value.find(';');
    if (semicolon != std::string::npos)
        value.erase(semicolon);
    while (!value.empty() && std::isspace(static_cast<unsigned char>(value.back())))
        value.pop_back();
    const std::size_t first = value.find_first_not_of(" \t");
    return first != std::string::npos && value.substr(first) == "application/sdp";
}

std::string json_escape(std::string_view value)
{
    constexpr char hexadecimal[] = "0123456789abcdef";
    std::string result;
    result.reserve(value.size() + 8);
    for (unsigned char character : value) {
        switch (character) {
        case '"':
            result += "\\\"";
            break;
        case '\\':
            result += "\\\\";
            break;
        case '\b':
            result += "\\b";
            break;
        case '\f':
            result += "\\f";
            break;
        case '\n':
            result += "\\n";
            break;
        case '\r':
            result += "\\r";
            break;
        case '\t':
            result += "\\t";
            break;
        default:
            if (character < 0x20) {
                result += "\\u00";
                result.push_back(hexadecimal[character >> 4]);
                result.push_back(hexadecimal[character & 0x0f]);
            } else {
                result.push_back(static_cast<char>(character));
            }
        }
    }
    return result;
}

std::string error_body(std::string_view code, std::string_view message, std::uint64_t revision = 0)
{
    return "{\"error\":{\"code\":\"" + json_escape(code) + "\",\"message\":\"" +
           json_escape(message) + "\"},\"revision\":" + std::to_string(revision) + "}";
}

void set_security_headers(HttpResponse &response, std::string_view content_type,
                          std::string_view cache_control)
{
    response.set(http::field::server, "webobsd");
    response.set(http::field::cache_control, cache_control);
    response.set(http::field::content_type, content_type);
    response.set("Content-Security-Policy",
                 "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
                 "connect-src 'self' ws://localhost:* ws://127.0.0.1:* ws://[::1]:*; "
                 "base-uri 'none'; form-action 'none'; frame-ancestors 'none'; object-src 'none'");
    response.set("X-Content-Type-Options", "nosniff");
    response.set("X-Frame-Options", "DENY");
    response.set("Referrer-Policy", "no-referrer");
    response.set("Permissions-Policy", "camera=(), microphone=(), geolocation=()");
    response.set("Cross-Origin-Resource-Policy", "same-origin");
}

HttpResponse response(http::status status, unsigned int version, std::string body,
                      std::string_view content_type = "application/json; charset=utf-8",
                      std::string_view cache_control = "no-store")
{
    HttpResponse result(status, version);
    set_security_headers(result, content_type, cache_control);
    result.keep_alive(false);
    result.body() = std::move(body);
    result.prepare_payload();
    return result;
}

class WhepProxy {
public:
    WhepProxy(bool enabled, SceneController &controller, const std::vector<std::string> &allowed_origins)
        : enabled_(enabled), controller_(controller), allowed_origins_(allowed_origins)
    {
    }

    HttpResponse status(unsigned int version) const
    {
        return response(http::status::ok, version,
                        std::string("{\"enabled\":") + (enabled_ ? "true" : "false") +
                            ",\"endpoint\":\"/api/v1/program/whep\"}");
    }

    HttpResponse capabilities(unsigned int version)
    {
        const SceneDocument document = controller_.private_document_snapshot();
        const std::lock_guard lock(route_state_mutex_);
        std::string body = std::string("{\"defaultMode\":\"composite\",\"modes\":{") +
                           "\"composite\":{\"enabled\":" + (enabled_ ? "true" : "false") +
                           ",\"endpoint\":\"/api/v1/program/whep\"}," +
                           "\"direct\":{\"enabled\":" + (enabled_ ? "true" : "false") +
                           ",\"fallback\":\"composite\"}},\"sources\":[";
        bool first = true;
        for (const SceneSource &source : document.sources) {
            if (!first)
                body.push_back(',');
            first = false;
            if (source.kind == "browser") {
                body += "{\"sourceId\":\"" + json_escape(source.id) +
                        "\",\"preferred\":\"composite\",\"fallback\":\"composite\"," +
                        "\"strategy\":\"composite\",\"codec\":\"\",\"audioCodec\":\"\"}";
                continue;
            }
            const auto route = direct_routes_.find(source.id);
            const std::string strategy = route == direct_routes_.end() || route->second.codec.empty()
                                             ? "unknown"
                                             : route->second.transcode ? "transcode" : "passthrough";
            const std::string codec = route == direct_routes_.end() ? std::string{} : route->second.codec;
            const std::string audio_codec =
                route == direct_routes_.end() ? std::string{} : route->second.audio_codec;
            body += "{\"sourceId\":\"" + json_escape(source.id) +
                    "\",\"endpoint\":\"/api/v1/sources/" + json_escape(source.id) +
                    "/whep\",\"preferred\":\"direct\",\"fallback\":\"composite\"," +
                    "\"strategy\":\"" + strategy + "\",\"codec\":\"" + json_escape(codec) +
                    "\",\"audioCodec\":\"" + json_escape(audio_codec) + "\"}";
        }
        body += "]}";
        return response(http::status::ok, version, std::move(body));
    }

    HttpResponse create_program(const HttpRequest &request)
    {
        if (auto invalid = validate_offer(request))
            return std::move(*invalid);
        return create_validated(request, "program", session_prefix);
    }

    HttpResponse create_direct(const HttpRequest &request, std::string_view source_id)
    {
        if (auto invalid = validate_offer(request))
            return std::move(*invalid);
        const SceneDocument document = controller_.private_document_snapshot();
        const auto source = std::find_if(document.sources.begin(), document.sources.end(),
                                         [source_id](const SceneSource &candidate) {
                                             return candidate.id == source_id;
                                         });
        if (source == document.sources.end())
            return response(http::status::not_found, request.version(),
                            error_body("source_not_found", "source not found"));
        if (source->kind != "rtsp")
            return response(http::status::conflict, request.version(),
                            error_body("composite_only", "browser sources use composite playback"));
        std::optional<std::string> route;
        {
            const std::lock_guard operation_lock(route_operation_mutex_);
            route = ensure_playback_route(*source);
        }
        if (!route)
            return response(http::status::bad_gateway, request.version(),
                            error_body("direct_route", "direct source routing is unavailable"));
        const std::string browser_prefix = "/api/v1/sources/" + std::string(source_id) + "/whep/session/";
        return create_validated(request, *route, browser_prefix);
    }

    HttpResponse remove_program(const HttpRequest &request, std::string_view token)
    {
        return remove(request, token, session_prefix);
    }

    HttpResponse remove_direct(const HttpRequest &request, std::string_view source_id, std::string_view token)
    {
        const std::string browser_prefix = "/api/v1/sources/" + std::string(source_id) + "/whep/session/";
        return remove(request, token, browser_prefix);
    }

    void reconcile_sources()
    {
        const std::lock_guard operation_lock(route_operation_mutex_);
        reconcile(controller_.private_document_snapshot());
    }

private:
    HttpResponse remove(const HttpRequest &request, std::string_view token, std::string_view browser_prefix)
    {
        const unsigned int version = request.version();
        if (!request_origin_allowed(request, false, allowed_origins_))
            return response(http::status::forbidden, version,
                            error_body("origin_rejected", "Origin must match the local Host"));
        if (token.size() != token_length ||
            !std::all_of(token.begin(), token.end(), [](unsigned char character) { return std::isxdigit(character); }))
            return response(http::status::not_found, version, error_body("session_not_found", "session not found"));
        std::string upstream_url;
        {
            const std::lock_guard lock(session_mutex_);
            const auto session = sessions_.find(std::string(token));
            if (session == sessions_.end() || session->second.browser_prefix != browser_prefix)
                return response(http::status::not_found, version,
                                error_body("session_not_found", "session not found"));
            upstream_url = std::move(session->second.upstream_url);
            sessions_.erase(session);
        }
        const UpstreamResponse upstream = request_http(upstream_url, {}, "DELETE", {});
        if (!upstream.ok || (upstream.status != 200 && upstream.status != 204 && upstream.status != 404))
            return response(http::status::bad_gateway, version,
                            error_body("whep_upstream", "WebRTC signaling could not close the session"));
        return response(http::status::no_content, version, {}, "application/json; charset=utf-8");
    }

    static constexpr std::size_t maximum_sdp_bytes = 64 * 1024;
    static constexpr std::size_t maximum_sessions = 64;
    static constexpr auto session_retention = std::chrono::minutes(10);
    static constexpr std::size_t token_length = 32;
    static constexpr std::string_view upstream_origin = "http://127.0.0.1:8889";
    static constexpr std::string_view control_origin = "http://127.0.0.1:9997";
    static constexpr std::string_view session_prefix = "/api/v1/program/whep/session/";

    struct Session {
        std::string upstream_url;
        std::chrono::steady_clock::time_point created_at;
        std::string browser_prefix;
    };

    struct DirectRoute {
        std::string path;
        std::string rtsp_url;
        std::string transport;
        std::string codec;
        std::string audio_codec;
        bool transcode = false;
        std::string hybrid_path;
    };

    struct UpstreamResponse {
        bool ok = false;
        long status = 0;
        std::string body;
        std::string location;
        std::vector<std::string> links;
    };

    static std::size_t write_body(char *data, std::size_t size, std::size_t count, void *parameter)
    {
        const std::size_t bytes = size * count;
        auto &body = *static_cast<std::string *>(parameter);
        if (bytes > maximum_sdp_bytes - std::min(body.size(), maximum_sdp_bytes))
            return 0;
        body.append(data, bytes);
        return bytes;
    }

    static std::size_t read_header(char *data, std::size_t size, std::size_t count, void *parameter)
    {
        const std::size_t bytes = size * count;
        auto &result = *static_cast<UpstreamResponse *>(parameter);
        std::string_view line(data, bytes);
        while (!line.empty() && (line.back() == '\r' || line.back() == '\n'))
            line.remove_suffix(1);
        const std::size_t colon = line.find(':');
        if (colon == std::string_view::npos)
            return bytes;
        const std::string name = lowercase(line.substr(0, colon));
        std::string_view value = line.substr(colon + 1);
        const std::size_t first = value.find_first_not_of(" \t");
        value = first == std::string_view::npos ? std::string_view{} : value.substr(first);
        if (value.size() > 4096)
            return bytes;
        if (name == "location")
            result.location = value;
        else if (name == "link" && result.links.size() < 8)
            result.links.emplace_back(value);
        return bytes;
    }

    static UpstreamResponse request_http(std::string_view url, std::string_view body,
                                         std::string_view method, std::string_view content_type)
    {
        UpstreamResponse result;
        CURL *handle = curl_easy_init();
        if (!handle)
            return result;
        const std::string url_value(url);
        curl_slist *headers = nullptr;
        if (!content_type.empty()) {
            const std::string header = "Content-Type: " + std::string(content_type);
            headers = curl_slist_append(headers, header.c_str());
            if (content_type == "application/sdp")
                headers = curl_slist_append(headers, "Accept: application/sdp");
        }
        curl_easy_setopt(handle, CURLOPT_URL, url_value.c_str());
        curl_easy_setopt(handle, CURLOPT_PROTOCOLS_STR, "http");
        curl_easy_setopt(handle, CURLOPT_CONNECTTIMEOUT_MS, 1500L);
        curl_easy_setopt(handle, CURLOPT_TIMEOUT_MS, 15000L);
        curl_easy_setopt(handle, CURLOPT_NOSIGNAL, 1L);
        curl_easy_setopt(handle, CURLOPT_WRITEFUNCTION, &write_body);
        curl_easy_setopt(handle, CURLOPT_WRITEDATA, &result.body);
        curl_easy_setopt(handle, CURLOPT_HEADERFUNCTION, &read_header);
        curl_easy_setopt(handle, CURLOPT_HEADERDATA, &result);
        if (headers)
            curl_easy_setopt(handle, CURLOPT_HTTPHEADER, headers);
        if (method == "POST") {
            curl_easy_setopt(handle, CURLOPT_POST, 1L);
        } else if (method != "GET") {
            const std::string method_value(method);
            curl_easy_setopt(handle, CURLOPT_CUSTOMREQUEST, method_value.c_str());
        }
        if (!body.empty()) {
            curl_easy_setopt(handle, CURLOPT_POSTFIELDS, body.data());
            curl_easy_setopt(handle, CURLOPT_POSTFIELDSIZE_LARGE, static_cast<curl_off_t>(body.size()));
        }
        result.ok = curl_easy_perform(handle) == CURLE_OK;
        if (result.ok)
            curl_easy_getinfo(handle, CURLINFO_RESPONSE_CODE, &result.status);
        curl_slist_free_all(headers);
        curl_easy_cleanup(handle);
        return result;
    }

    static std::optional<std::string> normalize_location(std::string_view location,
                                                          std::string_view expected_prefix)
    {
        if (location.starts_with(upstream_origin))
            location.remove_prefix(upstream_origin.size());
        if (!location.starts_with(expected_prefix) || location.size() <= expected_prefix.size() ||
            location.find_first_of("?#\r\n") != std::string_view::npos)
            return std::nullopt;
        const std::string_view suffix = location.substr(expected_prefix.size());
        if (!std::all_of(suffix.begin(), suffix.end(), [](unsigned char character) {
                return std::isalnum(character) || character == '-';
            }))
            return std::nullopt;
        return std::string(upstream_origin) + std::string(location);
    }

    std::optional<HttpResponse> validate_offer(const HttpRequest &request) const
    {
        const unsigned int version = request.version();
        if (!enabled_)
            return response(http::status::service_unavailable, version,
                            error_body("webrtc_disabled", "WebRTC playback is disabled"));
        if (!sdp_content_type(request))
            return response(http::status::unsupported_media_type, version,
                            error_body("content_type", "Content-Type must be application/sdp"));
        if (!request_origin_allowed(request, false, allowed_origins_))
            return response(http::status::forbidden, version,
                            error_body("origin_rejected", "Origin must match the local Host"));
        if (request.body().empty() || request.body().size() > maximum_sdp_bytes)
            return response(request.body().empty() ? http::status::bad_request : http::status::payload_too_large,
                            version, error_body("invalid_sdp", "SDP offer must contain at most 64 KiB"));
        return std::nullopt;
    }

    HttpResponse create_validated(const HttpRequest &request, std::string_view path,
                                  std::string_view browser_prefix)
    {
        const unsigned int version = request.version();
        {
            const std::lock_guard lock(session_mutex_);
            prune_expired_sessions();
            if (sessions_.size() >= maximum_sessions)
                return response(http::status::too_many_requests, version,
                                error_body("session_limit", "Too many active WebRTC playback sessions"));
        }

        const std::string create_url = std::string(upstream_origin) + "/" + std::string(path) + "/whep";
        UpstreamResponse upstream = request_http(create_url, request.body(), "POST", "application/sdp");
        if (!upstream.ok || upstream.status != 201 || upstream.body.empty())
            return response(http::status::bad_gateway, version,
                            error_body("whep_upstream", "WebRTC signaling did not accept the offer"));
        const std::string upstream_prefix = "/" + std::string(path) + "/whep/";
        const auto upstream_location = normalize_location(upstream.location, upstream_prefix);
        if (!upstream_location)
            return response(http::status::bad_gateway, version,
                            error_body("whep_location", "WebRTC signaling returned an invalid session"));

        std::string token;
        bool capacity_exhausted = false;
        {
            const std::lock_guard lock(session_mutex_);
            prune_expired_sessions();
            if (sessions_.size() >= maximum_sessions) {
                capacity_exhausted = true;
            } else {
                do {
                    token = random_token();
                } while (sessions_.contains(token));
                sessions_.emplace(token, Session{*upstream_location, std::chrono::steady_clock::now(),
                                                 std::string(browser_prefix)});
            }
        }
        if (capacity_exhausted) {
            request_http(*upstream_location, {}, "DELETE", {});
            return response(http::status::too_many_requests, version,
                            error_body("session_limit", "Too many active WebRTC playback sessions"));
        }

        HttpResponse result = response(http::status::created, version, std::move(upstream.body), "application/sdp");
        result.set(http::field::location, std::string(browser_prefix) + token);
        for (const std::string &link : upstream.links)
            result.insert(http::field::link, link);
        return result;
    }

    static std::optional<std::string> run_capture(const std::vector<std::string> &arguments,
                                                   std::chrono::seconds timeout)
    {
        if (arguments.empty())
            return std::nullopt;
        int output_pipe[2] = {-1, -1};
        if (pipe(output_pipe) != 0)
            return std::nullopt;
        std::vector<char *> raw;
        raw.reserve(arguments.size() + 1);
        for (const std::string &argument : arguments)
            raw.push_back(const_cast<char *>(argument.c_str()));
        raw.push_back(nullptr);

        posix_spawn_file_actions_t actions;
        if (posix_spawn_file_actions_init(&actions) != 0) {
            close(output_pipe[0]);
            close(output_pipe[1]);
            return std::nullopt;
        }
        posix_spawn_file_actions_addopen(&actions, STDIN_FILENO, "/dev/null", O_RDONLY, 0);
        posix_spawn_file_actions_addopen(&actions, STDERR_FILENO, "/dev/null", O_WRONLY, 0);
        posix_spawn_file_actions_adddup2(&actions, output_pipe[1], STDOUT_FILENO);
        posix_spawn_file_actions_addclose(&actions, output_pipe[0]);
        posix_spawn_file_actions_addclose(&actions, output_pipe[1]);
        pid_t child = -1;
        const int spawn_result = posix_spawnp(&child, raw.front(), &actions, nullptr, raw.data(), environ);
        posix_spawn_file_actions_destroy(&actions);
        close(output_pipe[1]);
        if (spawn_result != 0) {
            close(output_pipe[0]);
            return std::nullopt;
        }

        int status = 0;
        bool finished = false;
        const auto deadline = std::chrono::steady_clock::now() + timeout;
        while (std::chrono::steady_clock::now() < deadline) {
            const pid_t waited = waitpid(child, &status, WNOHANG);
            if (waited == child) {
                finished = true;
                break;
            }
            if (waited < 0 && errno == ECHILD) {
                finished = true;
                break;
            }
            if (waited < 0 && errno != EINTR)
                break;
            std::this_thread::sleep_for(std::chrono::milliseconds(50));
        }
        if (!finished) {
            kill(child, SIGKILL);
            while (waitpid(child, &status, 0) < 0 && errno == EINTR) {
            }
        }
        std::string output;
        std::array<char, 256> buffer{};
        for (;;) {
            const ssize_t count = read(output_pipe[0], buffer.data(), buffer.size());
            if (count > 0 && output.size() < 4096)
                output.append(buffer.data(), static_cast<std::size_t>(count));
            else if (count == 0)
                break;
            else if (count < 0 && errno != EINTR)
                break;
        }
        close(output_pipe[0]);
        while (!output.empty() && std::isspace(static_cast<unsigned char>(output.back())))
            output.pop_back();
        const std::size_t first = output.find_first_not_of(" \t\r\n");
        if (first == std::string::npos)
            return std::nullopt;
        output.erase(0, first);
        if (output.size() > 32 ||
            !std::all_of(output.begin(), output.end(), [](unsigned char character) {
                return std::isalnum(character) || character == '_';
            }))
            return std::nullopt;
        return lowercase(output);
    }

    static bool browser_compatible_codec(std::string_view codec)
    {
        return codec == "h264" || codec == "vp8" || codec == "vp9" || codec == "av1";
    }

    static bool browser_compatible_audio_codec(std::string_view codec)
    {
        return codec.empty() || codec == "opus" || codec == "pcm_alaw" || codec == "pcm_mulaw";
    }

    void delete_config_path(std::string_view path)
    {
        if (path.empty())
            return;
        const std::string url = std::string(control_origin) + "/v3/config/paths/delete/" + std::string(path);
        request_http(url, {}, "DELETE", {});
    }

    std::optional<std::string> ensure_direct_route(const SceneSource &source)
    {
        DirectRoute route;
        bool adding = false;
        std::string previous_hybrid_path;
        {
            const std::lock_guard lock(route_state_mutex_);
            const auto existing = direct_routes_.find(source.id);
            adding = existing == direct_routes_.end();
            if (!adding && existing->second.rtsp_url == source.rtsp_url &&
                existing->second.transport == source.transport)
                return existing->second.path;
            if (adding) {
                if (direct_routes_.size() >= maximum_scene_sources)
                    return std::nullopt;
                do {
                    route.path = "direct-" + random_token();
                } while (std::any_of(direct_routes_.begin(), direct_routes_.end(), [&route](const auto &entry) {
                    return entry.second.path == route.path;
                }));
            } else {
                route = existing->second;
                previous_hybrid_path = route.hybrid_path;
                route.codec.clear();
                route.audio_codec.clear();
                route.transcode = false;
                route.hybrid_path.clear();
            }
        }
        route.rtsp_url = source.rtsp_url;
        route.transport = source.transport;
        const std::string body = "{\"source\":\"" + json_escape(route.rtsp_url) +
                                 "\",\"sourceOnDemand\":true,\"sourceOnDemandStartTimeout\":\"10s\"," +
                                 "\"sourceOnDemandCloseAfter\":\"5s\",\"maxReaders\":8," +
                                 "\"overridePublisher\":false,\"rtspTransport\":\"" +
                                 json_escape(route.transport) + "\"}";
        const std::string operation = adding ? "add" : "patch";
        const std::string method = adding ? "POST" : "PATCH";
        const std::string url = std::string(control_origin) + "/v3/config/paths/" + operation + "/" + route.path;
        const UpstreamResponse configured = request_http(url, body, method, "application/json");
        if (!configured.ok || configured.status != 200)
            return std::nullopt;
        delete_config_path(previous_hybrid_path);
        {
            const std::lock_guard lock(route_state_mutex_);
            direct_routes_[source.id] = route;
        }
        return route.path;
    }

    std::optional<std::string> ensure_playback_route(const SceneSource &source)
    {
        const auto direct_path = ensure_direct_route(source);
        if (!direct_path)
            return std::nullopt;
        DirectRoute route;
        {
            const std::lock_guard lock(route_state_mutex_);
            route = direct_routes_.at(source.id);
        }
        if (route.codec.empty()) {
            const std::string input = "rtsp://127.0.0.1:8554/" + route.path;
            const auto codec = run_capture({"ffprobe", "-v", "error", "-rw_timeout", "8000000",
                                            "-rtsp_transport", "tcp", "-select_streams", "v:0",
                                            "-show_entries", "stream=codec_name", "-of",
                                            "default=noprint_wrappers=1:nokey=1", input},
                                           std::chrono::seconds(12));
            if (!codec)
                return std::nullopt;
            route.codec = *codec;
            const auto audio_codec = run_capture({"ffprobe", "-v", "error", "-rw_timeout", "8000000",
                                                  "-rtsp_transport", "tcp", "-select_streams", "a:0",
                                                  "-show_entries", "stream=codec_name", "-of",
                                                  "default=noprint_wrappers=1:nokey=1", input},
                                                 std::chrono::seconds(12));
            route.audio_codec = audio_codec.value_or("");
            route.transcode = !browser_compatible_codec(route.codec) ||
                              !browser_compatible_audio_codec(route.audio_codec);
            const std::lock_guard lock(route_state_mutex_);
            direct_routes_.at(source.id).codec = route.codec;
            direct_routes_.at(source.id).audio_codec = route.audio_codec;
            direct_routes_.at(source.id).transcode = route.transcode;
        }
        if (!route.transcode)
            return route.path;

        if (route.hybrid_path.empty()) {
            {
                const std::lock_guard lock(route_state_mutex_);
                do {
                    route.hybrid_path = "hybrid-" + random_token();
                } while (std::any_of(direct_routes_.begin(), direct_routes_.end(), [&route](const auto &entry) {
                    return entry.second.hybrid_path == route.hybrid_path;
                }));
            }
            const std::string command = "/opt/webobs/bin/transcode-on-demand " + route.path + " " +
                                        route.hybrid_path;
            const std::string body =
                std::string("{\"source\":\"publisher\",\"overridePublisher\":false,\"maxReaders\":8,") +
                "\"runOnDemand\":\"" + json_escape(command) +
                "\",\"runOnDemandRestart\":false,\"runOnDemandStartTimeout\":\"10s\"," +
                "\"runOnDemandCloseAfter\":\"2s\"}";
            const std::string url = std::string(control_origin) + "/v3/config/paths/add/" + route.hybrid_path;
            const UpstreamResponse configured = request_http(url, body, "POST", "application/json");
            if (!configured.ok || configured.status != 200) {
                route.hybrid_path.clear();
                return std::nullopt;
            }
            const std::lock_guard lock(route_state_mutex_);
            direct_routes_.at(source.id).hybrid_path = route.hybrid_path;
        }
        return route.hybrid_path;
    }

    void reconcile(const SceneDocument &document)
    {
        std::vector<DirectRoute> removed;
        {
            const std::lock_guard lock(route_state_mutex_);
            for (auto iterator = direct_routes_.begin(); iterator != direct_routes_.end();) {
                const bool present = std::any_of(document.sources.begin(), document.sources.end(),
                                                 [&iterator](const SceneSource &source) {
                                                     return source.id == iterator->first && source.kind == "rtsp";
                                                 });
                if (present) {
                    ++iterator;
                    continue;
                }
                removed.push_back(iterator->second);
                iterator = direct_routes_.erase(iterator);
            }
        }
        for (const DirectRoute &route : removed) {
            delete_config_path(route.hybrid_path);
            delete_config_path(route.path);
        }
    }

    static std::string random_token()
    {
        std::array<unsigned char, token_length / 2> bytes{};
        std::random_device random;
        for (unsigned char &byte : bytes)
            byte = static_cast<unsigned char>(random());
        constexpr char hexadecimal[] = "0123456789abcdef";
        std::string token;
        token.reserve(token_length);
        for (unsigned char byte : bytes) {
            token.push_back(hexadecimal[byte >> 4]);
            token.push_back(hexadecimal[byte & 0x0f]);
        }
        return token;
    }

    void prune_expired_sessions()
    {
        const auto cutoff = std::chrono::steady_clock::now() - session_retention;
        std::erase_if(sessions_, [cutoff](const auto &entry) { return entry.second.created_at < cutoff; });
    }

    bool enabled_ = false;
    SceneController &controller_;
    const std::vector<std::string> &allowed_origins_;
    std::mutex session_mutex_;
    std::mutex route_operation_mutex_;
    std::mutex route_state_mutex_;
    std::unordered_map<std::string, Session> sessions_;
    std::unordered_map<std::string, DirectRoute> direct_routes_;
};

class NvrProxy {
public:
    explicit NvrProxy(bool enabled) : enabled_(enabled) {}

    HttpResponse forward(const HttpRequest &request) const
    {
        if (!enabled_)
            return response(http::status::service_unavailable, request.version(),
                            error_body("nvr_disabled", "NVR service is disabled"));
        constexpr std::string_view prefix = "/api/v1/nvr";
        const std::string_view target = view(request.target());
        if (!target.starts_with(prefix))
            return response(http::status::not_found, request.version(),
                            error_body("not_found", "resource not found"));
        std::string_view suffix = target.substr(prefix.size());
        if (suffix.empty())
            suffix = "/status";
        if (suffix.front() != '/' || suffix.size() > 4096 ||
            !std::all_of(suffix.begin(), suffix.end(), [](unsigned char character) {
                return std::isalnum(character) || std::string_view("/?&=._%:-").find(character) !=
                                                      std::string_view::npos;
            }))
            return response(http::status::bad_request, request.version(),
                            error_body("invalid_target", "NVR request target is invalid"));
        const bool mutating = request.method() == http::verb::put || request.method() == http::verb::post ||
                              request.method() == http::verb::delete_;
        if (mutating && !json_content_type(request))
            return response(http::status::unsupported_media_type, request.version(),
                            error_body("content_type", "Content-Type must be application/json"));

        std::string body;
        std::string content_type = "application/json; charset=utf-8";
        std::string content_range;
        std::string accept_ranges;
        const std::string url = "http://127.0.0.1:8091" + std::string(suffix);
        CURL *handle = curl_easy_init();
        if (!handle)
            return unavailable(request.version());
        struct curl_slist *headers = nullptr;
        if (mutating)
            headers = curl_slist_append(headers, "Content-Type: application/json");
        const auto range = request.find(http::field::range);
        if (range != request.end()) {
            const std::string value(view(range->value()));
            if (value.size() > 128 || !std::all_of(value.begin(), value.end(), [](unsigned char character) {
                    return std::isdigit(character) || character == '=' || character == '-';
                })) {
                curl_easy_cleanup(handle);
                if (headers)
                    curl_slist_free_all(headers);
                return response(http::status::bad_request, request.version(),
                                error_body("invalid_range", "Range header is invalid"));
            }
            headers = curl_slist_append(headers, ("Range: " + value).c_str());
        }
        ResponseState state{&body, &content_type, &content_range, &accept_ranges};
        curl_easy_setopt(handle, CURLOPT_URL, url.c_str());
        curl_easy_setopt(handle, CURLOPT_PROTOCOLS_STR, "http");
        curl_easy_setopt(handle, CURLOPT_CONNECTTIMEOUT_MS, 1000L);
        curl_easy_setopt(handle, CURLOPT_TIMEOUT_MS, 30000L);
        curl_easy_setopt(handle, CURLOPT_NOSIGNAL, 1L);
        curl_easy_setopt(handle, CURLOPT_FOLLOWLOCATION, 0L);
        curl_easy_setopt(handle, CURLOPT_WRITEFUNCTION, &write_body);
        curl_easy_setopt(handle, CURLOPT_WRITEDATA, &state);
        curl_easy_setopt(handle, CURLOPT_HEADERFUNCTION, &read_header);
        curl_easy_setopt(handle, CURLOPT_HEADERDATA, &state);
        if (headers)
            curl_easy_setopt(handle, CURLOPT_HTTPHEADER, headers);
        const std::string method(request.method_string());
        curl_easy_setopt(handle, CURLOPT_CUSTOMREQUEST, method.c_str());
        if (!request.body().empty()) {
            curl_easy_setopt(handle, CURLOPT_POSTFIELDS, request.body().data());
            curl_easy_setopt(handle, CURLOPT_POSTFIELDSIZE_LARGE,
                             static_cast<curl_off_t>(request.body().size()));
        }
        const CURLcode code = curl_easy_perform(handle);
        long status = 0;
        if (code == CURLE_OK)
            curl_easy_getinfo(handle, CURLINFO_RESPONSE_CODE, &status);
        if (headers)
            curl_slist_free_all(headers);
        curl_easy_cleanup(handle);
        if (code != CURLE_OK || status < 100 || status > 599)
            return unavailable(request.version());
        HttpResponse result = response(static_cast<http::status>(status), request.version(), std::move(body),
                                       content_type.empty() ? "application/octet-stream" : content_type);
        if (!content_range.empty())
            result.set(http::field::content_range, content_range);
        if (!accept_ranges.empty())
            result.set(http::field::accept_ranges, accept_ranges);
        return result;
    }

private:
    struct ResponseState {
        std::string *body;
        std::string *content_type;
        std::string *content_range;
        std::string *accept_ranges;
    };

    static std::size_t write_body(char *data, std::size_t size, std::size_t count, void *context)
    {
        const std::size_t bytes = size * count;
        auto &state = *static_cast<ResponseState *>(context);
        constexpr std::size_t maximum_proxy_bytes = 64 * 1024 * 1024;
        if (bytes > maximum_proxy_bytes || state.body->size() > maximum_proxy_bytes - bytes)
            return 0;
        state.body->append(data, bytes);
        return bytes;
    }

    static std::size_t read_header(char *data, std::size_t size, std::size_t count, void *context)
    {
        const std::size_t bytes = size * count;
        auto &state = *static_cast<ResponseState *>(context);
        std::string_view line(data, bytes);
        const auto capture = [line](std::string_view name, std::string &destination) {
            if (line.size() <= name.size() || lowercase(line.substr(0, name.size())) != name)
                return;
            std::string_view value = line.substr(name.size());
            while (!value.empty() && (value.front() == ' ' || value.front() == '\t'))
                value.remove_prefix(1);
            while (!value.empty() && (value.back() == '\r' || value.back() == '\n' || value.back() == ' '))
                value.remove_suffix(1);
            if (value.size() <= 256)
                destination.assign(value);
        };
        capture("content-type:", *state.content_type);
        capture("content-range:", *state.content_range);
        capture("accept-ranges:", *state.accept_ranges);
        return bytes;
    }

    static HttpResponse unavailable(unsigned int version)
    {
        return response(http::status::service_unavailable, version,
                        error_body("nvr_unavailable", "NVR service is unavailable"));
    }

    bool enabled_ = false;
};

std::string static_content_type(std::string_view filename)
{
    if (filename.ends_with(".html"))
        return "text/html; charset=utf-8";
    if (filename.ends_with(".js"))
        return "text/javascript; charset=utf-8";
    if (filename.ends_with(".css"))
        return "text/css; charset=utf-8";
    if (filename.ends_with(".png"))
        return "image/png";
    if (filename.ends_with(".ico"))
        return "image/x-icon";
    if (filename.ends_with(".webmanifest"))
        return "application/manifest+json";
    return "application/octet-stream";
}

std::optional<HttpResponse> static_file_response(std::string_view target, unsigned int version)
{
    std::string filename;
    bool immutable = false;
    if (target == "/" || target == "/index.html") {
        filename = "index.html";
    } else if (target.starts_with("/assets/")) {
        const std::string_view asset = target.substr(std::string_view("/assets/").size());
        if (asset.empty() || !std::all_of(asset.begin(), asset.end(), [](unsigned char character) {
                return std::isalnum(character) || character == '.' || character == '_' || character == '-';
            }))
            return std::nullopt;
        filename = "assets/" + std::string(asset);
        immutable = true;
    } else {
        return std::nullopt;
    }

    const std::filesystem::path path = std::filesystem::path(WEBOBS_WEB_ROOT) / filename;
    std::error_code error;
    if (!std::filesystem::is_regular_file(path, error) || error)
        return response(http::status::not_found, version,
                        error_body("ui_not_installed", "Web editor asset is unavailable"));
    const std::uintmax_t size = std::filesystem::file_size(path, error);
    if (error || size > 2 * 1024 * 1024)
        return response(http::status::internal_server_error, version,
                        error_body("ui_asset_invalid", "Web editor asset could not be served"));

    std::ifstream input(path, std::ios::binary);
    if (!input)
        return response(http::status::internal_server_error, version,
                        error_body("ui_asset_unreadable", "Web editor asset could not be read"));
    std::string body(static_cast<std::size_t>(size), '\0');
    if (size > 0 && !input.read(body.data(), static_cast<std::streamsize>(size)))
        return response(http::status::internal_server_error, version,
                        error_body("ui_asset_unreadable", "Web editor asset could not be read"));
    return response(http::status::ok, version, std::move(body), static_content_type(filename),
                    immutable ? "public, max-age=31536000, immutable" : "no-store");
}

std::string etag(std::uint64_t revision)
{
    return "\"" + std::to_string(revision) + "\"";
}

struct ParsedIfMatch {
    bool present = false;
    bool valid = false;
    std::uint64_t revision = 0;
};

ParsedIfMatch parse_if_match(const HttpRequest &request)
{
    ParsedIfMatch result;
    const auto header = request.find(http::field::if_match);
    if (header == request.end())
        return result;
    result.present = true;
    const std::string_view value = view(header->value());
    if (value.size() < 3 || value.front() != '"' || value.back() != '"')
        return result;
    const std::string_view digits = value.substr(1, value.size() - 2);
    const auto parsed = std::from_chars(digits.data(), digits.data() + digits.size(), result.revision);
    result.valid = !digits.empty() && parsed.ec == std::errc{} && parsed.ptr == digits.data() + digits.size();
    return result;
}

std::string scene_event(std::string_view type, std::string scene_json)
{
    while (!scene_json.empty() && (scene_json.back() == '\n' || scene_json.back() == '\r'))
        scene_json.pop_back();
    return "{\"type\":\"" + std::string(type) + "\",\"scene\":" + scene_json + "}";
}

class WebSocketSession;

class WebSocketHub {
public:
    void join(const std::shared_ptr<WebSocketSession> &session);
    void broadcast(const std::string &message);

private:
    std::vector<std::weak_ptr<WebSocketSession>> sessions_;
};

class WebSocketSession : public std::enable_shared_from_this<WebSocketSession> {
public:
    WebSocketSession(tcp::socket socket, WebSocketHub &hub) : stream_(std::move(socket)), hub_(hub) {}

    void run(HttpRequest request, std::string initial_message)
    {
        initial_message_ = std::move(initial_message);
        stream_.set_option(websocket::stream_base::timeout::suggested(beast::role_type::server));
        stream_.read_message_max(64 * 1024);
        stream_.set_option(websocket::stream_base::decorator([](websocket::response_type &upgrade) {
            upgrade.set(http::field::server, "webobsd");
            upgrade.set("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'; object-src 'none'");
            upgrade.set("X-Content-Type-Options", "nosniff");
        }));
        stream_.async_accept(request,
                             beast::bind_front_handler(&WebSocketSession::on_accept, shared_from_this()));
    }

    void send(std::string message)
    {
        net::post(stream_.get_executor(),
                  beast::bind_front_handler(&WebSocketSession::on_send, shared_from_this(),
                                            std::make_shared<const std::string>(std::move(message))));
    }

private:
    void on_accept(beast::error_code error)
    {
        if (error)
            return;
        stream_.text(true);
        hub_.join(shared_from_this());
        send(std::move(initial_message_));
        do_read();
    }

    void do_read()
    {
        stream_.async_read(buffer_, beast::bind_front_handler(&WebSocketSession::on_read, shared_from_this()));
    }

    void on_read(beast::error_code error, std::size_t)
    {
        if (error)
            return;
        buffer_.consume(buffer_.size());
        do_read();
    }

    void on_send(std::shared_ptr<const std::string> message)
    {
        if (outbound_.size() >= 16)
            return;
        outbound_.push_back(std::move(message));
        if (outbound_.size() > 1)
            return;
        do_write();
    }

    void do_write()
    {
        stream_.async_write(net::buffer(*outbound_.front()),
                            beast::bind_front_handler(&WebSocketSession::on_write, shared_from_this()));
    }

    void on_write(beast::error_code error, std::size_t)
    {
        if (error)
            return;
        outbound_.pop_front();
        if (!outbound_.empty())
            do_write();
    }

    websocket::stream<beast::tcp_stream> stream_;
    beast::flat_buffer buffer_;
    WebSocketHub &hub_;
    std::string initial_message_;
    std::deque<std::shared_ptr<const std::string>> outbound_;
};

void WebSocketHub::join(const std::shared_ptr<WebSocketSession> &session)
{
    sessions_.erase(std::remove_if(sessions_.begin(), sessions_.end(),
                                   [](const auto &entry) { return entry.expired(); }),
                    sessions_.end());
    sessions_.push_back(session);
}

void WebSocketHub::broadcast(const std::string &message)
{
    auto iterator = sessions_.begin();
    while (iterator != sessions_.end()) {
        if (const auto session = iterator->lock()) {
            session->send(message);
            ++iterator;
        } else {
            iterator = sessions_.erase(iterator);
        }
    }
}

struct ControlMetrics {
    std::atomic<std::uint64_t> http_requests{0};
};

HttpResponse authentication_response(AuthenticationDecision decision, unsigned int version,
                                     std::size_t retry_after_seconds)
{
    if (decision == AuthenticationDecision::rate_limit_started ||
        decision == AuthenticationDecision::rate_limited) {
        HttpResponse result = response(static_cast<http::status>(429), version,
                                       error_body("auth_rate_limited", "too many authentication failures"));
        result.set(http::field::retry_after, std::to_string(retry_after_seconds));
        return result;
    }
    HttpResponse result = response(http::status::unauthorized, version,
                                   error_body("authentication_required", "valid credentials are required"));
    result.set(http::field::www_authenticate, "Basic realm=\"WebOBS\", charset=\"UTF-8\"");
    return result;
}

HttpResponse metrics_response(unsigned int version, const RuntimeStatus &status,
                              const ControlMetrics &metrics, const BasicAuthenticator &authenticator)
{
    const auto metric = [](bool value) { return value ? "1" : "0"; };
    std::string body =
        "# HELP webobs_up Whether the HTTP control process is running.\n"
        "# TYPE webobs_up gauge\nwebobs_up 1\n"
        "# HELP webobs_ready Whether recording and configured WebRTC outputs are ready.\n"
        "# TYPE webobs_ready gauge\nwebobs_ready " + std::string(metric(status.ready())) + "\n" +
        "# TYPE webobs_recording_active gauge\nwebobs_recording_active " +
        std::string(metric(status.recording_active.load())) + "\n" +
        "# TYPE webobs_webrtc_configured gauge\nwebobs_webrtc_configured " +
        std::string(metric(status.webrtc_configured.load())) + "\n" +
        "# TYPE webobs_webrtc_ready gauge\nwebobs_webrtc_ready " +
        std::string(metric(status.webrtc_ready.load())) + "\n" +
        "# TYPE webobs_sources_visible gauge\nwebobs_sources_visible " +
        std::to_string(status.source_visible.load()) + "\n" +
        "# TYPE webobs_sources_healthy gauge\nwebobs_sources_healthy " +
        std::to_string(status.source_healthy.load()) + "\n" +
        "# TYPE webobs_sources_unhealthy gauge\nwebobs_sources_unhealthy " +
        std::to_string(status.source_unhealthy.load()) + "\n" +
        "# HELP webobs_source_restarts_total Automatic RTSP source restarts since process start.\n"
        "# TYPE webobs_source_restarts_total counter\nwebobs_source_restarts_total " +
        std::to_string(status.source_restarts.load()) + "\n" +
        "# HELP webobs_video_encoder_selected Selected H.264 encoder backend.\n"
        "# TYPE webobs_video_encoder_selected gauge\n"
        "webobs_video_encoder_selected{backend=\"x264\"} " +
        std::string(metric(status.video_encoder.selected == VideoEncoderKind::x264)) + "\n" +
        "webobs_video_encoder_selected{backend=\"vaapi\"} " +
        std::string(metric(status.video_encoder.selected == VideoEncoderKind::vaapi)) + "\n" +
        "webobs_video_encoder_selected{backend=\"qsv\"} " +
        std::string(metric(status.video_encoder.selected == VideoEncoderKind::qsv)) + "\n" +
        "webobs_video_encoder_selected{backend=\"nvenc\"} " +
        std::string(metric(status.video_encoder.selected == VideoEncoderKind::nvenc)) + "\n" +
        "# TYPE webobs_video_encoder_fallback gauge\nwebobs_video_encoder_fallback " +
        std::string(metric(status.video_encoder.fallback)) + "\n" +
        "# HELP webobs_video_encoder_available Device and encoder module are both available.\n"
        "# TYPE webobs_video_encoder_available gauge\n"
        "webobs_video_encoder_available{backend=\"x264\"} 1\n"
        "webobs_video_encoder_available{backend=\"vaapi\"} " +
        std::string(metric(video_encoder_backend_ready(status.video_encoder.vaapi))) + "\n" +
        "webobs_video_encoder_available{backend=\"qsv\"} " +
        std::string(metric(video_encoder_backend_ready(status.video_encoder.qsv))) + "\n" +
        "webobs_video_encoder_available{backend=\"nvenc\"} " +
        std::string(metric(video_encoder_backend_ready(status.video_encoder.nvenc))) + "\n" +
        "# HELP webobs_http_requests_total Parsed HTTP requests since process start.\n"
        "# TYPE webobs_http_requests_total counter\nwebobs_http_requests_total " +
        std::to_string(metrics.http_requests.load()) + "\n" +
        "# HELP webobs_auth_failures_total Invalid Basic Auth attempts since process start.\n"
        "# TYPE webobs_auth_failures_total counter\nwebobs_auth_failures_total " +
        std::to_string(authenticator.failed_attempts()) + "\n";
    return response(http::status::ok, version, std::move(body),
                    "text/plain; version=0.0.4; charset=utf-8");
}

std::string encoder_backend_json(const VideoEncoderBackend &backend)
{
    return std::string("{\"devicePresent\":") + (backend.device_present ? "true" : "false") +
           ",\"encoderAvailable\":" + (backend.encoder_available ? "true" : "false") +
           ",\"ready\":" + (video_encoder_backend_ready(backend) ? "true" : "false") + "}";
}

HttpResponse system_capabilities_response(unsigned int version, const RuntimeStatus &status)
{
    const VideoEncoderCapabilities &encoder = status.video_encoder;
    std::string body = "{\"videoEncoder\":{\"requested\":\"" +
                       std::string(video_encoder_preference_name(encoder.requested)) +
                       "\",\"selected\":\"" + std::string(video_encoder_kind_name(encoder.selected)) +
                       "\",\"fallback\":" + (encoder.fallback ? "true" : "false") +
                       ",\"backends\":{\"x264\":" + encoder_backend_json(encoder.x264) +
                       ",\"vaapi\":" + encoder_backend_json(encoder.vaapi) +
                       ",\"qsv\":" + encoder_backend_json(encoder.qsv) +
                       ",\"nvenc\":" + encoder_backend_json(encoder.nvenc) + "}}}";
    return response(http::status::ok, version, std::move(body));
}

HttpResponse source_health_response(unsigned int version, SceneController &controller)
{
    const SourceHealthSnapshot snapshot = controller.source_health_snapshot();
    std::string body = "{\"visible\":" + std::to_string(snapshot.visible) +
                       ",\"healthy\":" + std::to_string(snapshot.healthy) +
                       ",\"unhealthy\":" + std::to_string(snapshot.unhealthy) +
                       ",\"totalRestarts\":" + std::to_string(snapshot.total_restarts) +
                       ",\"sources\":[";
    for (std::size_t index = 0; index < snapshot.sources.size(); ++index) {
        const SourceHealthEntry &source = snapshot.sources[index];
        if (index != 0)
            body += ',';
        body += "{\"id\":\"" + json_escape(source.id) + "\",\"kind\":\"" +
                json_escape(source.kind) + "\",\"visible\":" +
                std::string(source.visible ? "true" : "false") + ",\"state\":\"" +
                json_escape(source.state) + "\",\"lastFrameAgeMs\":" +
                (source.last_frame_age_ms < 0 ? std::string("null") :
                 std::to_string(source.last_frame_age_ms)) +
                ",\"restartCount\":" + std::to_string(source.restart_count) + "}";
    }
    body += "]}";
    return response(http::status::ok, version, std::move(body));
}

HttpResponse handle_request(const HttpRequest &request, SceneController &controller, StudioController &studio,
                            WebSocketHub &hub,
                            WhepProxy &whep_proxy, NvrProxy &nvr_proxy,
                            const std::vector<std::string> &allowed_origins,
                            const RuntimeStatus &runtime_status, const ControlMetrics &metrics,
                            const BasicAuthenticator &authenticator)
{
    const unsigned int version = request.version();
    if (version != 11)
        return response(http::status::http_version_not_supported, version,
                        error_body("http_version", "HTTP/1.1 is required"));
    const std::string_view host = view(request[http::field::host]);
    if (!control_authority_allowed(host, allowed_origins))
        return response(static_cast<http::status>(421), version,
                        error_body("host_rejected", "Host is not in the configured control origin allowlist"));

    const std::string_view target = view(request.target());
    if (request.method() == http::verb::get && target == "/api/v1/health")
        return response(http::status::ok, version, "{\"status\":\"ok\",\"milestone\":\"M8\"}");
    if (request.method() == http::verb::get && target == "/api/v1/ready") {
        const bool ready = runtime_status.ready();
        return response(ready ? http::status::ok : http::status::service_unavailable, version,
                        ready ? "{\"status\":\"ready\"}" : "{\"status\":\"not_ready\"}");
    }
    if (request.method() == http::verb::get && target == "/metrics")
        return metrics_response(version, runtime_status, metrics, authenticator);
    if (request.method() == http::verb::get && target == "/api/v1/sources/status")
        return source_health_response(version, controller);
    if (request.method() == http::verb::get && target == "/api/v1/system/capabilities")
        return system_capabilities_response(version, runtime_status);

    if (target == "/api/v1/nvr" || target.starts_with("/api/v1/nvr/")) {
        if ((request.method() == http::verb::put || request.method() == http::verb::post ||
             request.method() == http::verb::delete_) &&
            !request_origin_allowed(request, false, allowed_origins))
            return response(http::status::forbidden, version,
                            error_body("origin_rejected", "Origin must match the local Host"));
        return nvr_proxy.forward(request);
    }

    if (request.method() == http::verb::get && target == "/api/v1/program/status")
        return whep_proxy.status(version);
    if (request.method() == http::verb::get && target == "/api/v1/playback/capabilities")
        return whep_proxy.capabilities(version);

    constexpr std::string_view whep_target = "/api/v1/program/whep";
    constexpr std::string_view whep_session_prefix = "/api/v1/program/whep/session/";
    if (target == whep_target) {
        if (request.method() == http::verb::post)
            return whep_proxy.create_program(request);
        HttpResponse result = response(http::status::method_not_allowed, version,
                                       error_body("method_not_allowed", "use POST"));
        result.set(http::field::allow, "POST");
        return result;
    }
    if (target.starts_with(whep_session_prefix)) {
        if (request.method() == http::verb::delete_)
            return whep_proxy.remove_program(request, target.substr(whep_session_prefix.size()));
        HttpResponse result = response(http::status::method_not_allowed, version,
                                       error_body("method_not_allowed", "use DELETE"));
        result.set(http::field::allow, "DELETE");
        return result;
    }

    constexpr std::string_view source_prefix = "/api/v1/sources/";
    if (target.starts_with(source_prefix)) {
        const std::string_view source_route = target.substr(source_prefix.size());
        const std::size_t separator = source_route.find('/');
        if (separator == std::string_view::npos)
            return response(http::status::not_found, version, error_body("not_found", "resource not found"));
        const std::string_view source_id = source_route.substr(0, separator);
        const std::string_view operation = source_route.substr(separator);
        const bool valid_source_id = !source_id.empty() && source_id.size() <= 64 &&
                                     std::all_of(source_id.begin(), source_id.end(), [](unsigned char character) {
                                         return std::isalnum(character) || character == '.' || character == '_' ||
                                                character == '-';
                                     });
        if (!valid_source_id)
            return response(http::status::not_found, version, error_body("not_found", "resource not found"));
        if (operation == "/whep") {
            if (request.method() == http::verb::post)
                return whep_proxy.create_direct(request, source_id);
            HttpResponse result = response(http::status::method_not_allowed, version,
                                           error_body("method_not_allowed", "use POST"));
            result.set(http::field::allow, "POST");
            return result;
        }
        constexpr std::string_view direct_session = "/whep/session/";
        if (operation.starts_with(direct_session)) {
            if (request.method() == http::verb::delete_)
                return whep_proxy.remove_direct(request, source_id,
                                                operation.substr(direct_session.size()));
            HttpResponse result = response(http::status::method_not_allowed, version,
                                           error_body("method_not_allowed", "use DELETE"));
            result.set(http::field::allow, "DELETE");
            return result;
        }
        return response(http::status::not_found, version, error_body("not_found", "resource not found"));
    }

    constexpr std::string_view studio_target = "/api/v1/studio";
    constexpr std::string_view studio_capabilities_target = "/api/v1/studio/capabilities";
    const bool studio_action = target == "/api/v1/studio/take" || target == "/api/v1/studio/undo" ||
                               target == "/api/v1/studio/redo";
    if (target == studio_target || target == studio_capabilities_target || studio_action) {
        if (target == studio_capabilities_target) {
            if (request.method() != http::verb::get) {
                HttpResponse result = response(http::status::method_not_allowed, version,
                                               error_body("method_not_allowed", "use GET"));
                result.set(http::field::allow, "GET");
                return result;
            }
            const StudioUpdateResult snapshot = studio.snapshot();
            if (!snapshot.ok())
                return response(http::status::internal_server_error, version,
                                error_body("serialization_failed", snapshot.error, snapshot.revision));
            StudioParseResult parsed = parse_studio_json(snapshot.public_json);
            if (!parsed.ok())
                return response(http::status::internal_server_error, version,
                                error_body("serialization_failed", parsed.error, snapshot.revision));
            const SceneSerializeResult capabilities =
                serialize_studio_capabilities_json(*parsed.document, false);
            if (!capabilities.ok())
                return response(http::status::internal_server_error, version,
                                error_body("serialization_failed", capabilities.error,
                                           snapshot.revision));
            HttpResponse result = response(http::status::ok, version, capabilities.json);
            result.set(http::field::etag, etag(snapshot.revision));
            return result;
        }
        if (request.method() == http::verb::get && target == studio_target) {
            const StudioUpdateResult snapshot = studio.snapshot();
            if (!snapshot.ok())
                return response(http::status::internal_server_error, version,
                                error_body("serialization_failed", snapshot.error, snapshot.revision));
            HttpResponse result = response(http::status::ok, version, snapshot.public_json);
            result.set(http::field::etag, etag(snapshot.revision));
            return result;
        }
        const bool replacing = request.method() == http::verb::put && target == studio_target;
        const bool acting = request.method() == http::verb::post && studio_action;
        if (!replacing && !acting) {
            HttpResponse result = response(http::status::method_not_allowed, version,
                                           error_body("method_not_allowed", "use GET, PUT, or POST"));
            result.set(http::field::allow, target == studio_target ? "GET, PUT" : "POST");
            return result;
        }
        if (replacing && !json_content_type(request))
            return response(http::status::unsupported_media_type, version,
                            error_body("content_type", "Content-Type must be application/json"));
        if (!request_origin_allowed(request, false, allowed_origins))
            return response(http::status::forbidden, version,
                            error_body("origin_rejected", "Origin must match the local Host"));
        const ParsedIfMatch precondition = parse_if_match(request);
        if (precondition.present && !precondition.valid)
            return response(http::status::bad_request, version,
                            error_body("invalid_if_match", "If-Match must contain one quoted decimal revision"));
        std::optional<std::uint64_t> expected;
        if (precondition.present)
            expected = precondition.revision;
        StudioUpdateResult updated;
        if (replacing)
            updated = studio.replace(request.body(), expected);
        else if (target == "/api/v1/studio/take")
            updated = studio.take(expected);
        else if (target == "/api/v1/studio/undo")
            updated = studio.undo(expected);
        else
            updated = studio.redo(expected);
        if (!updated.ok()) {
            http::status status = http::status::unprocessable_entity;
            std::string_view code = "invalid_studio";
            if (updated.status == StudioUpdateStatus::precondition_required) {
                status = static_cast<http::status>(428);
                code = "precondition_required";
            } else if (updated.status == StudioUpdateStatus::revision_conflict) {
                status = http::status::precondition_failed;
                code = "revision_conflict";
            } else if (updated.status == StudioUpdateStatus::runtime_rejected) {
                status = http::status::conflict;
                code = "runtime_rejected";
            } else if (updated.status == StudioUpdateStatus::persistence_failed) {
                status = http::status::service_unavailable;
                code = "persistence_failed";
            } else if (updated.status == StudioUpdateStatus::history_empty) {
                status = http::status::conflict;
                code = "history_empty";
            }
            HttpResponse result = response(status, version, error_body(code, updated.error, updated.revision));
            result.set(http::field::etag, etag(updated.revision));
            return result;
        }
        const std::string revision = std::to_string(updated.revision);
        const std::string action = replacing ? "studio_update" : std::string(target.substr(8));
        const std::string audit = format_audit_event(action, "accepted", {{"revision", revision}});
        blog(LOG_INFO, "%s", audit.c_str());
        if (target == "/api/v1/studio/take") {
            whep_proxy.reconcile_sources();
            const SceneSnapshot program = controller.snapshot();
            if (program.ok())
                hub.broadcast(scene_event("scene.updated", program.public_json));
        }
        HttpResponse result = response(http::status::ok, version, updated.public_json);
        result.set(http::field::etag, etag(updated.revision));
        return result;
    }

    if (target != "/api/v1/scene") {
        if (request.method() == http::verb::get) {
            if (auto static_response = static_file_response(target, version))
                return std::move(*static_response);
        }
        return response(http::status::not_found, version, error_body("not_found", "resource not found"));
    }

    if (request.method() == http::verb::get) {
        const SceneSnapshot snapshot = controller.snapshot();
        if (!snapshot.ok())
            return response(http::status::internal_server_error, version,
                            error_body("serialization_failed", snapshot.error, snapshot.revision));
        HttpResponse result = response(http::status::ok, version, snapshot.public_json);
        result.set(http::field::etag, etag(snapshot.revision));
        return result;
    }

    if (request.method() != http::verb::put) {
        HttpResponse result =
            response(http::status::method_not_allowed, version, error_body("method_not_allowed", "use GET or PUT"));
        result.set(http::field::allow, "GET, PUT");
        return result;
    }
    if (!json_content_type(request))
        return response(http::status::unsupported_media_type, version,
                        error_body("content_type", "Content-Type must be application/json"));
    if (!request_origin_allowed(request, false, allowed_origins))
        return response(http::status::forbidden, version,
                        error_body("origin_rejected", "Origin must match the local Host"));

    const ParsedIfMatch precondition = parse_if_match(request);
    std::optional<std::uint64_t> expected_revision;
    if (precondition.present && precondition.valid)
        expected_revision = precondition.revision;
    if (precondition.present && !precondition.valid)
        return response(http::status::bad_request, version,
                        error_body("invalid_if_match", "If-Match must contain one quoted decimal revision"));

    const SceneUpdateResult updated = controller.replace(request.body(), expected_revision);
    if (!updated.ok()) {
        http::status status = http::status::unprocessable_entity;
        std::string_view code = "invalid_scene";
        switch (updated.status) {
        case SceneUpdateStatus::precondition_required:
            status = static_cast<http::status>(428);
            code = "precondition_required";
            break;
        case SceneUpdateStatus::revision_conflict:
            status = http::status::precondition_failed;
            code = "revision_conflict";
            break;
        case SceneUpdateStatus::runtime_rejected:
            status = http::status::conflict;
            code = "runtime_rejected";
            break;
        case SceneUpdateStatus::persistence_unavailable:
        case SceneUpdateStatus::persistence_failed:
            status = http::status::service_unavailable;
            code = "persistence_failed";
            break;
        case SceneUpdateStatus::invalid_document:
        case SceneUpdateStatus::success:
            break;
        }
        const std::string revision = std::to_string(updated.revision);
        const std::string audit = format_audit_event(
            "scene_update", "rejected", {{"reason", code}, {"revision", revision}});
        blog(LOG_WARNING, "%s", audit.c_str());
        HttpResponse result = response(status, version, error_body(code, updated.error, updated.revision));
        result.set(http::field::etag, etag(updated.revision));
        return result;
    }

    const std::string event = scene_event("scene.updated", updated.public_json);
    const std::string revision = std::to_string(updated.revision);
    const std::string audit =
        format_audit_event("scene_update", "accepted", {{"revision", revision}});
    blog(LOG_INFO, "%s", audit.c_str());
    whep_proxy.reconcile_sources();
    hub.broadcast(event);
    HttpResponse result = response(http::status::ok, version, updated.public_json);
    result.set(http::field::etag, etag(updated.revision));
    return result;
}

class HttpSession : public std::enable_shared_from_this<HttpSession> {
public:
    HttpSession(tcp::socket socket, SceneController &controller, StudioController &studio,
                WebSocketHub &hub, WhepProxy &whep_proxy, NvrProxy &nvr_proxy,
                BasicAuthenticator &authenticator, ControlMetrics &metrics, RuntimeStatus &runtime_status,
                const std::vector<std::string> &allowed_origins)
        : stream_(std::move(socket)), controller_(controller), studio_(studio), hub_(hub), whep_proxy_(whep_proxy),
          nvr_proxy_(nvr_proxy),
          authenticator_(authenticator), metrics_(metrics), runtime_status_(runtime_status),
          allowed_origins_(allowed_origins)
    {
        beast::error_code error;
        const tcp::endpoint remote = stream_.socket().remote_endpoint(error);
        client_key_ = error ? "unknown" : remote.address().to_string();
    }

    void run() { do_read(); }

private:
    void do_read()
    {
        parser_.emplace();
        parser_->body_limit(maximum_scene_json_bytes);
        parser_->header_limit(16 * 1024);
        stream_.expires_after(std::chrono::seconds(15));
        http::async_read(stream_, buffer_, *parser_,
                         beast::bind_front_handler(&HttpSession::on_read, shared_from_this()));
    }

    void on_read(beast::error_code error, std::size_t)
    {
        if (error == http::error::body_limit) {
            send(response(http::status::payload_too_large, 11,
                          error_body("body_too_large", "request body exceeds one MiB")));
            return;
        }
        if (error == http::error::header_limit) {
            send(response(static_cast<http::status>(431), 11,
                          error_body("headers_too_large", "request headers exceed 16 KiB")));
            return;
        }
        if (error)
            return;
        HttpRequest request = parser_->release();
        ++metrics_.http_requests;
        const unsigned int version = request.version();
        const std::string_view host = view(request[http::field::host]);
        if (version != 11 || !control_authority_allowed(host, allowed_origins_)) {
            send(handle_request(request, controller_, studio_, hub_, whep_proxy_, nvr_proxy_, allowed_origins_, runtime_status_,
                                metrics_, authenticator_));
            return;
        }
        const std::string_view target = view(request.target());
        const bool public_probe = request.method() == http::verb::get &&
                                  (target == "/api/v1/health" || target == "/api/v1/ready");
        if (!public_probe && authenticator_.enabled()) {
            std::optional<std::string_view> authorization;
            std::size_t authorization_count = 0;
            for (const auto &field : request.base()) {
                if (field.name() == http::field::authorization) {
                    ++authorization_count;
                    authorization = view(field.value());
                }
            }
            if (authorization_count > 1)
                authorization = std::string_view{};
            const AuthenticationDecision decision =
                authenticator_.authenticate(authorization, client_key_);
            if (decision != AuthenticationDecision::allowed) {
                if (decision == AuthenticationDecision::invalid_credentials ||
                    decision == AuthenticationDecision::rate_limit_started) {
                    const std::string outcome =
                        decision == AuthenticationDecision::rate_limit_started ? "rate_limited" : "rejected";
                    const std::string audit = format_audit_event(
                        "authentication", outcome, {{"client", client_key_}});
                    blog(LOG_WARNING, "%s", audit.c_str());
                }
                send(authentication_response(decision, version, authenticator_.retry_after_seconds()));
                return;
            }
        }
        if (websocket::is_upgrade(request)) {
            if (request.method() != http::verb::get || view(request.target()) != "/api/v1/ws" ||
                !control_authority_allowed(host, allowed_origins_) ||
                !request_origin_allowed(request, true, allowed_origins_)) {
                send(response(http::status::forbidden, request.version(),
                              error_body("websocket_rejected", "WebSocket requires a matching local Origin")));
                return;
            }
            const SceneSnapshot snapshot = controller_.snapshot();
            if (!snapshot.ok()) {
                send(response(http::status::internal_server_error, request.version(),
                              error_body("serialization_failed", snapshot.error, snapshot.revision)));
                return;
            }
            std::make_shared<WebSocketSession>(stream_.release_socket(), hub_)
                ->run(std::move(request), scene_event("scene.snapshot", snapshot.public_json));
            return;
        }
        send(handle_request(request, controller_, studio_, hub_, whep_proxy_, nvr_proxy_, allowed_origins_, runtime_status_,
                            metrics_, authenticator_));
    }

    void send(HttpResponse message)
    {
        auto shared = std::make_shared<HttpResponse>(std::move(message));
        response_ = shared;
        http::async_write(stream_, *shared,
                          beast::bind_front_handler(&HttpSession::on_write, shared_from_this()));
    }

    void on_write(beast::error_code, std::size_t)
    {
        beast::error_code ignored;
        stream_.socket().shutdown(tcp::socket::shutdown_send, ignored);
        response_.reset();
    }

    beast::tcp_stream stream_;
    beast::flat_buffer buffer_;
    std::optional<http::request_parser<http::string_body>> parser_;
    SceneController &controller_;
    StudioController &studio_;
    WebSocketHub &hub_;
    WhepProxy &whep_proxy_;
    NvrProxy &nvr_proxy_;
    BasicAuthenticator &authenticator_;
    ControlMetrics &metrics_;
    RuntimeStatus &runtime_status_;
    const std::vector<std::string> &allowed_origins_;
    std::string client_key_;
    std::shared_ptr<HttpResponse> response_;
};

class Listener : public std::enable_shared_from_this<Listener> {
public:
    Listener(net::io_context &context, const tcp::endpoint &endpoint, SceneController &controller,
             StudioController &studio,
             WebSocketHub &hub, WhepProxy &whep_proxy, NvrProxy &nvr_proxy,
             BasicAuthenticator &authenticator,
             ControlMetrics &metrics, RuntimeStatus &runtime_status,
             const std::vector<std::string> &allowed_origins)
        : acceptor_(net::make_strand(context)), controller_(controller), studio_(studio), hub_(hub), whep_proxy_(whep_proxy),
          nvr_proxy_(nvr_proxy),
          authenticator_(authenticator), metrics_(metrics), runtime_status_(runtime_status),
          allowed_origins_(allowed_origins)
    {
        beast::error_code error;
        acceptor_.open(endpoint.protocol(), error);
        if (!error)
            acceptor_.set_option(net::socket_base::reuse_address(true), error);
        if (!error)
            acceptor_.bind(endpoint, error);
        if (!error)
            acceptor_.listen(net::socket_base::max_listen_connections, error);
        if (error)
            error_ = "could not bind the HTTP control listener: " + error.message();
    }

    [[nodiscard]] const std::string &error() const { return error_; }

    void run()
    {
        if (error_.empty())
            do_accept();
    }

    void close()
    {
        beast::error_code ignored;
        acceptor_.cancel(ignored);
        acceptor_.close(ignored);
    }

private:
    void do_accept()
    {
        acceptor_.async_accept(beast::bind_front_handler(&Listener::on_accept, shared_from_this()));
    }

    void on_accept(beast::error_code error, tcp::socket socket)
    {
        if (!error)
            std::make_shared<HttpSession>(std::move(socket), controller_, studio_, hub_, whep_proxy_, nvr_proxy_, authenticator_,
                                          metrics_, runtime_status_, allowed_origins_)->run();
        if (acceptor_.is_open())
            do_accept();
    }

    tcp::acceptor acceptor_;
    SceneController &controller_;
    StudioController &studio_;
    WebSocketHub &hub_;
    WhepProxy &whep_proxy_;
    NvrProxy &nvr_proxy_;
    BasicAuthenticator &authenticator_;
    ControlMetrics &metrics_;
    RuntimeStatus &runtime_status_;
    const std::vector<std::string> &allowed_origins_;
    std::string error_;
};

} // namespace

struct ControlServer::Impl {
    Impl(const Config &configuration, SceneController &scene_controller, StudioController &studio_controller,
         RuntimeStatus &runtime_status)
        : config(configuration), controller(scene_controller), studio(studio_controller), status(runtime_status),
          authenticator(configuration.authentication,
                        static_cast<std::size_t>(configuration.auth_failure_limit),
                        std::chrono::seconds(configuration.auth_failure_window_seconds)),
          whep_proxy(configuration.webrtc_enabled, scene_controller,
                     configuration.control_allowed_origins),
          nvr_proxy(configuration.nvr_enabled)
    {
    }

    const Config &config;
    SceneController &controller;
    StudioController &studio;
    RuntimeStatus &status;
    net::io_context context{1};
    WebSocketHub hub;
    BasicAuthenticator authenticator;
    ControlMetrics metrics;
    WhepProxy whep_proxy;
    NvrProxy nvr_proxy;
    std::shared_ptr<Listener> listener;
    std::thread thread;
};

ControlServer::ControlServer(const Config &config, SceneController &controller, StudioController &studio,
                             RuntimeStatus &status)
    : impl_(std::make_unique<Impl>(config, controller, studio, status))
{
}

ControlServer::~ControlServer()
{
    stop();
}

std::optional<std::string> ControlServer::start()
{
    if (impl_->config.http_port == 0 || impl_->thread.joinable())
        return std::nullopt;
    beast::error_code error;
    const net::ip::address address = net::ip::make_address(impl_->config.listen_address, error);
    if (error)
        return "HTTP listen address is invalid";
    impl_->listener = std::make_shared<Listener>(
        impl_->context, tcp::endpoint(address, static_cast<unsigned short>(impl_->config.http_port)),
        impl_->controller, impl_->studio, impl_->hub, impl_->whep_proxy, impl_->nvr_proxy,
        impl_->authenticator, impl_->metrics,
        impl_->status, impl_->config.control_allowed_origins);
    if (!impl_->listener->error().empty())
        return impl_->listener->error();
    impl_->listener->run();
    impl_->thread = std::thread([this] { impl_->context.run(); });
    return std::nullopt;
}

void ControlServer::stop()
{
    if (!impl_ || !impl_->thread.joinable())
        return;
    impl_->context.stop();
    impl_->thread.join();
    impl_->listener.reset();
}

} // namespace webobs
