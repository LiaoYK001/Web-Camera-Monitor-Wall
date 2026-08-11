#include "webobs/control_server.hpp"

#include "webobs/scene_controller.hpp"
#include "webobs/scene_document.hpp"

#include <boost/asio.hpp>
#include <boost/beast/core.hpp>
#include <boost/beast/http.hpp>
#include <boost/beast/websocket.hpp>

#include <algorithm>
#include <charconv>
#include <cctype>
#include <chrono>
#include <cstdint>
#include <deque>
#include <memory>
#include <optional>
#include <string>
#include <string_view>
#include <thread>
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

void set_security_headers(HttpResponse &response)
{
    response.set(http::field::server, "webobsd");
    response.set(http::field::cache_control, "no-store");
    response.set(http::field::content_type, "application/json; charset=utf-8");
    response.set("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'");
    response.set("X-Content-Type-Options", "nosniff");
    response.set("Referrer-Policy", "no-referrer");
    response.set("Permissions-Policy", "camera=(), microphone=(), geolocation=()");
}

HttpResponse response(http::status status, unsigned int version, std::string body)
{
    HttpResponse result(status, version);
    set_security_headers(result);
    result.keep_alive(false);
    result.body() = std::move(body);
    result.prepare_payload();
    return result;
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
            upgrade.set("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'");
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

HttpResponse handle_request(const HttpRequest &request, SceneController &controller, WebSocketHub &hub)
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
        return response(http::status::ok, version, "{\"status\":\"ok\",\"milestone\":\"M1\"}");

    if (target != "/api/v1/scene")
        return response(http::status::not_found, version, error_body("not_found", "resource not found"));

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
    HttpSession(tcp::socket socket, SceneController &controller, WebSocketHub &hub)
        : stream_(std::move(socket)), controller_(controller), hub_(hub)
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
        send(handle_request(request, controller_, hub_));
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
    std::shared_ptr<HttpResponse> response_;
};

class Listener : public std::enable_shared_from_this<Listener> {
public:
    Listener(net::io_context &context, const tcp::endpoint &endpoint, SceneController &controller,
             WebSocketHub &hub)
        : acceptor_(net::make_strand(context)), controller_(controller), hub_(hub)
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
            std::make_shared<HttpSession>(std::move(socket), controller_, hub_)->run();
        if (acceptor_.is_open())
            do_accept();
    }

    tcp::acceptor acceptor_;
    SceneController &controller_;
    WebSocketHub &hub_;
    std::string error_;
};

} // namespace

struct ControlServer::Impl {
    Impl(const Config &configuration, SceneController &scene_controller)
        : config(configuration), controller(scene_controller)
    {
    }

    const Config &config;
    SceneController &controller;
    net::io_context context{1};
    WebSocketHub hub;
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
        impl_->controller, impl_->hub);
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
