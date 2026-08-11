#include "webobs/control_server.hpp"

#include "webobs/scene_controller.hpp"
#include "webobs/scene_document.hpp"

#include <boost/asio.hpp>
#include <boost/beast/core.hpp>
#include <boost/beast/http.hpp>
#include <boost/beast/websocket.hpp>
#include <curl/curl.h>

#include <algorithm>
#include <array>
#include <charconv>
#include <cctype>
#include <chrono>
#include <cstdint>
#include <deque>
#include <filesystem>
#include <fstream>
#include <memory>
#include <optional>
#include <random>
#include <string>
#include <string_view>
#include <thread>
#include <unordered_map>
#include <utility>
#include <vector>

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

bool same_local_origin(std::string_view origin, std::string_view host)
{
    constexpr std::string_view scheme = "http://";
    if (!origin.starts_with(scheme))
        return false;
    const std::string_view authority = origin.substr(scheme.size());
    return authority.find_first_of("/?#") == std::string_view::npos && safe_local_authority(authority) &&
           lowercase(authority) == lowercase(host);
}

bool request_origin_allowed(const HttpRequest &request, bool required)
{
    const auto origin = request.find(http::field::origin);
    if (origin == request.end())
        return !required;
    return same_local_origin(view(origin->value()), view(request[http::field::host]));
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
    explicit WhepProxy(bool enabled) : enabled_(enabled) {}

    HttpResponse status(unsigned int version) const
    {
        return response(http::status::ok, version,
                        std::string("{\"enabled\":") + (enabled_ ? "true" : "false") +
                            ",\"endpoint\":\"/api/v1/program/whep\"}");
    }

    HttpResponse create(const HttpRequest &request)
    {
        const unsigned int version = request.version();
        if (!enabled_)
            return response(http::status::service_unavailable, version,
                            error_body("webrtc_disabled", "WebRTC program output is disabled"));
        if (!sdp_content_type(request))
            return response(http::status::unsupported_media_type, version,
                            error_body("content_type", "Content-Type must be application/sdp"));
        if (!request_origin_allowed(request, false))
            return response(http::status::forbidden, version,
                            error_body("origin_rejected", "Origin must match the local Host"));
        if (request.body().empty() || request.body().size() > maximum_sdp_bytes)
            return response(request.body().empty() ? http::status::bad_request : http::status::payload_too_large,
                            version, error_body("invalid_sdp", "SDP offer must contain at most 64 KiB"));
        prune_expired_sessions();
        if (sessions_.size() >= maximum_sessions)
            return response(http::status::too_many_requests, version,
                            error_body("session_limit", "Too many active WebRTC playback sessions"));

        UpstreamResponse upstream = request_upstream(upstream_create_url, request.body(), true);
        if (!upstream.ok || upstream.status != 201 || upstream.body.empty())
            return response(http::status::bad_gateway, version,
                            error_body("whep_upstream", "WebRTC signaling did not accept the offer"));
        const auto upstream_location = normalize_location(upstream.location);
        if (!upstream_location)
            return response(http::status::bad_gateway, version,
                            error_body("whep_location", "WebRTC signaling returned an invalid session"));

        std::string token;
        do {
            token = random_token();
        } while (sessions_.contains(token));
        sessions_.emplace(token, Session{*upstream_location, std::chrono::steady_clock::now()});

        HttpResponse result = response(http::status::created, version, std::move(upstream.body), "application/sdp");
        result.set(http::field::location, std::string(session_prefix) + token);
        for (const std::string &link : upstream.links)
            result.insert(http::field::link, link);
        return result;
    }

    HttpResponse remove(const HttpRequest &request, std::string_view token)
    {
        const unsigned int version = request.version();
        if (!request_origin_allowed(request, false))
            return response(http::status::forbidden, version,
                            error_body("origin_rejected", "Origin must match the local Host"));
        if (token.size() != token_length ||
            !std::all_of(token.begin(), token.end(), [](unsigned char character) { return std::isxdigit(character); }))
            return response(http::status::not_found, version, error_body("session_not_found", "session not found"));
        const auto session = sessions_.find(std::string(token));
        if (session == sessions_.end())
            return response(http::status::not_found, version, error_body("session_not_found", "session not found"));

        const std::string upstream_url = std::move(session->second.upstream_url);
        sessions_.erase(session);
        const UpstreamResponse upstream = request_upstream(upstream_url, {}, false);
        if (!upstream.ok || (upstream.status != 200 && upstream.status != 204 && upstream.status != 404))
            return response(http::status::bad_gateway, version,
                            error_body("whep_upstream", "WebRTC signaling could not close the session"));
        return response(http::status::no_content, version, {}, "application/json; charset=utf-8");
    }

private:
    static constexpr std::size_t maximum_sdp_bytes = 64 * 1024;
    static constexpr std::size_t maximum_sessions = 64;
    static constexpr auto session_retention = std::chrono::minutes(10);
    static constexpr std::size_t token_length = 32;
    static constexpr std::string_view upstream_origin = "http://127.0.0.1:8889";
    static constexpr std::string_view upstream_create_url = "http://127.0.0.1:8889/program/whep";
    static constexpr std::string_view upstream_session_prefix = "/program/whep/";
    static constexpr std::string_view session_prefix = "/api/v1/program/whep/session/";

    struct Session {
        std::string upstream_url;
        std::chrono::steady_clock::time_point created_at;
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

    static UpstreamResponse request_upstream(std::string_view url, std::string_view body, bool create)
    {
        UpstreamResponse result;
        CURL *handle = curl_easy_init();
        if (!handle)
            return result;
        const std::string url_value(url);
        curl_slist *headers = nullptr;
        if (create) {
            headers = curl_slist_append(headers, "Content-Type: application/sdp");
            headers = curl_slist_append(headers, "Accept: application/sdp");
        }
        curl_easy_setopt(handle, CURLOPT_URL, url_value.c_str());
        curl_easy_setopt(handle, CURLOPT_PROTOCOLS_STR, "http");
        curl_easy_setopt(handle, CURLOPT_CONNECTTIMEOUT_MS, 1500L);
        curl_easy_setopt(handle, CURLOPT_TIMEOUT_MS, 10000L);
        curl_easy_setopt(handle, CURLOPT_NOSIGNAL, 1L);
        curl_easy_setopt(handle, CURLOPT_WRITEFUNCTION, &write_body);
        curl_easy_setopt(handle, CURLOPT_WRITEDATA, &result.body);
        curl_easy_setopt(handle, CURLOPT_HEADERFUNCTION, &read_header);
        curl_easy_setopt(handle, CURLOPT_HEADERDATA, &result);
        if (headers)
            curl_easy_setopt(handle, CURLOPT_HTTPHEADER, headers);
        if (create) {
            curl_easy_setopt(handle, CURLOPT_POST, 1L);
            curl_easy_setopt(handle, CURLOPT_POSTFIELDS, body.data());
            curl_easy_setopt(handle, CURLOPT_POSTFIELDSIZE_LARGE, static_cast<curl_off_t>(body.size()));
        } else {
            curl_easy_setopt(handle, CURLOPT_CUSTOMREQUEST, "DELETE");
        }
        result.ok = curl_easy_perform(handle) == CURLE_OK;
        if (result.ok)
            curl_easy_getinfo(handle, CURLINFO_RESPONSE_CODE, &result.status);
        curl_slist_free_all(headers);
        curl_easy_cleanup(handle);
        return result;
    }

    static std::optional<std::string> normalize_location(std::string_view location)
    {
        if (location.starts_with(upstream_origin))
            location.remove_prefix(upstream_origin.size());
        if (!location.starts_with(upstream_session_prefix) || location.size() <= upstream_session_prefix.size() ||
            location.find_first_of("?#\r\n") != std::string_view::npos)
            return std::nullopt;
        const std::string_view suffix = location.substr(upstream_session_prefix.size());
        if (!std::all_of(suffix.begin(), suffix.end(), [](unsigned char character) {
                return std::isalnum(character) || character == '-';
            }))
            return std::nullopt;
        return std::string(upstream_origin) + std::string(location);
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
    std::unordered_map<std::string, Session> sessions_;
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

HttpResponse handle_request(const HttpRequest &request, SceneController &controller, WebSocketHub &hub,
                            WhepProxy &whep_proxy)
{
    const unsigned int version = request.version();
    if (version != 11)
        return response(http::status::http_version_not_supported, version,
                        error_body("http_version", "HTTP/1.1 is required"));
    const std::string_view host = view(request[http::field::host]);
    if (!safe_local_authority(host))
        return response(static_cast<http::status>(421), version,
                        error_body("host_rejected", "Host must be localhost or a loopback address"));

    const std::string_view target = view(request.target());
    if (request.method() == http::verb::get && target == "/api/v1/health")
        return response(http::status::ok, version, "{\"status\":\"ok\",\"milestone\":\"M2\"}");

    if (request.method() == http::verb::get && target == "/api/v1/program/status")
        return whep_proxy.status(version);

    constexpr std::string_view whep_target = "/api/v1/program/whep";
    constexpr std::string_view whep_session_prefix = "/api/v1/program/whep/session/";
    if (target == whep_target) {
        if (request.method() == http::verb::post)
            return whep_proxy.create(request);
        HttpResponse result = response(http::status::method_not_allowed, version,
                                       error_body("method_not_allowed", "use POST"));
        result.set(http::field::allow, "POST");
        return result;
    }
    if (target.starts_with(whep_session_prefix)) {
        if (request.method() == http::verb::delete_)
            return whep_proxy.remove(request, target.substr(whep_session_prefix.size()));
        HttpResponse result = response(http::status::method_not_allowed, version,
                                       error_body("method_not_allowed", "use DELETE"));
        result.set(http::field::allow, "DELETE");
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
    if (!request_origin_allowed(request, false))
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
        HttpResponse result = response(status, version, error_body(code, updated.error, updated.revision));
        result.set(http::field::etag, etag(updated.revision));
        return result;
    }

    const std::string event = scene_event("scene.updated", updated.public_json);
    hub.broadcast(event);
    HttpResponse result = response(http::status::ok, version, updated.public_json);
    result.set(http::field::etag, etag(updated.revision));
    return result;
}

class HttpSession : public std::enable_shared_from_this<HttpSession> {
public:
    HttpSession(tcp::socket socket, SceneController &controller, WebSocketHub &hub, WhepProxy &whep_proxy)
        : stream_(std::move(socket)), controller_(controller), hub_(hub), whep_proxy_(whep_proxy)
    {
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
        if (websocket::is_upgrade(request)) {
            const std::string_view host = view(request[http::field::host]);
            if (request.method() != http::verb::get || view(request.target()) != "/api/v1/ws" ||
                !safe_local_authority(host) || !request_origin_allowed(request, true)) {
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
        send(handle_request(request, controller_, hub_, whep_proxy_));
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
    WebSocketHub &hub_;
    WhepProxy &whep_proxy_;
    std::shared_ptr<HttpResponse> response_;
};

class Listener : public std::enable_shared_from_this<Listener> {
public:
    Listener(net::io_context &context, const tcp::endpoint &endpoint, SceneController &controller,
             WebSocketHub &hub, WhepProxy &whep_proxy)
        : acceptor_(net::make_strand(context)), controller_(controller), hub_(hub), whep_proxy_(whep_proxy)
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
            std::make_shared<HttpSession>(std::move(socket), controller_, hub_, whep_proxy_)->run();
        if (acceptor_.is_open())
            do_accept();
    }

    tcp::acceptor acceptor_;
    SceneController &controller_;
    WebSocketHub &hub_;
    WhepProxy &whep_proxy_;
    std::string error_;
};

} // namespace

struct ControlServer::Impl {
    Impl(const Config &configuration, SceneController &scene_controller)
        : config(configuration), controller(scene_controller), whep_proxy(configuration.webrtc_enabled)
    {
    }

    const Config &config;
    SceneController &controller;
    net::io_context context{1};
    WebSocketHub hub;
    WhepProxy whep_proxy;
    std::shared_ptr<Listener> listener;
    std::thread thread;
};

ControlServer::ControlServer(const Config &config, SceneController &controller)
    : impl_(std::make_unique<Impl>(config, controller))
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
        impl_->controller, impl_->hub, impl_->whep_proxy);
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
