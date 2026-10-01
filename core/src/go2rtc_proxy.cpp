#include "webobs/platform_runtime.hpp"
#include "webobs/go2rtc_proxy.hpp"

#include <boost/beast/core.hpp>
#include <boost/beast/websocket.hpp>

#include <array>
#include <algorithm>
#include <cctype>
#include <cstdlib>
#include <memory>
#include <optional>
#include <string>

namespace webobs {
namespace {
namespace net = boost::asio;
namespace beast = boost::beast;
namespace http = beast::http;
using tcp = net::ip::tcp;
using Request = http::request<http::string_body>;

class ProxySession : public std::enable_shared_from_this<ProxySession> {
public:
    ProxySession(tcp::socket socket, Request request)
        : downstream_(std::move(socket)), upstream_(downstream_.get_executor()), request_(std::move(request))
    {
        // Never pass product credentials or internal identity headers to go2rtc.
        Request clean{request_.method(), request_.target(), request_.version()};
        for (const auto &field : request_) {
            switch (field.name()) {
            case http::field::host:
            case http::field::content_type:
            case http::field::accept:
            case http::field::range:
            case http::field::upgrade:
            case http::field::sec_websocket_key:
            case http::field::sec_websocket_version:
            case http::field::sec_websocket_protocol:
                clean.set(field.name(), field.value());
                break;
            default: break;
            }
        }
        upgrade_ = beast::websocket::is_upgrade(request_);
        clean.set(http::field::connection, upgrade_ ? "Upgrade" : "close");
        clean.body() = std::move(request_.body());
        clean.prepare_payload();
        request_ = std::move(clean);
        parser_.header_limit(16 * 1024);
        parser_.body_limit(boost::none); // bodies are relayed, never accumulated
    }

    void run()
    {
        upstream_.expires_after(std::chrono::seconds(5));
        upstream_.async_connect(tcp::endpoint(net::ip::make_address("127.0.0.1"), static_cast<unsigned short>(runtime_port(11984))),
            [self = shared_from_this()](beast::error_code error) {
                if (error) return self->unavailable();
                http::async_write(self->upstream_, self->request_,
                    [self](beast::error_code error, std::size_t) {
                        if (error) return self->unavailable();
                        self->read_header();
                    });
            });
    }

private:
    void read_header()
    {
        http::async_read_header(upstream_, header_buffer_, parser_,
            [self = shared_from_this()](beast::error_code error, std::size_t) {
                if (error) return self->unavailable();
                self->reply_ = self->parser_.release();
                if (self->reply_.result_int() == 101 && !self->upgrade_) return self->unavailable();
                self->reply_.erase(http::field::set_cookie);
                self->reply_.erase(http::field::access_control_allow_origin);
                self->reply_.set(http::field::cache_control, "no-store");
                self->reply_.set("X-Content-Type-Options", "nosniff");
                self->reply_.set("Referrer-Policy", "no-referrer");
                self->reply_.set("X-Frame-Options", "SAMEORIGIN");
                // Upstream UI uses inline scripts/styles, Monaco eval and workers.
                // Its third-party assets are packaged locally by prepare-go2rtc-ui.
                self->reply_.set("Content-Security-Policy",
                    "default-src 'self'; script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
                    "style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
                    "media-src 'self' blob:; connect-src 'self'; worker-src 'self' blob: data:; "
                    "frame-ancestors 'self'; object-src 'none'; base-uri 'self'; form-action 'self'");
                self->reply_.set("Permissions-Policy", "camera=(self), microphone=(self), fullscreen=(self)");
                if (self->reply_.result_int() != 101) self->reply_.keep_alive(false);
                self->serializer_.emplace(self->reply_);
                self->downstream_.expires_after(std::chrono::seconds(15));
                http::async_write_header(self->downstream_, *self->serializer_,
                    [self](beast::error_code error, std::size_t) {
                        if (error) return self->close();
                        self->upstream_.expires_never();
                        self->downstream_.expires_never();
                        if (self->reply_.result_int() == 101) self->read_client();
                        self->flush_buffer();
                    });
            });
    }

    void flush_buffer()
    {
        if (header_buffer_.size() == 0) return read_upstream();
        net::async_write(downstream_, header_buffer_.data(),
            [self = shared_from_this()](beast::error_code error, std::size_t bytes) {
                if (error) return self->close();
                self->header_buffer_.consume(bytes);
                self->read_upstream();
            });
    }

    void read_upstream()
    {
        upstream_.async_read_some(net::buffer(server_bytes_),
            [self = shared_from_this()](beast::error_code error, std::size_t bytes) {
                if (error) return self->close();
                net::async_write(self->downstream_, net::buffer(self->server_bytes_.data(), bytes),
                    [self](beast::error_code error, std::size_t) {
                        if (error) return self->close();
                        self->read_upstream();
                    });
            });
    }

    void read_client()
    {
        downstream_.async_read_some(net::buffer(client_bytes_),
            [self = shared_from_this()](beast::error_code error, std::size_t bytes) {
                if (error) return self->close();
                net::async_write(self->upstream_, net::buffer(self->client_bytes_.data(), bytes),
                    [self](beast::error_code error, std::size_t) {
                        if (error) return self->close();
                        self->read_client();
                    });
            });
    }

    void unavailable()
    {
        failure_ = {http::status::service_unavailable, 11};
        failure_.set(http::field::content_type, "application/json");
        failure_.set(http::field::cache_control, "no-store");
        failure_.keep_alive(false);
        failure_.body() = R"({"error":{"code":"go2rtc_unavailable","message":"go2rtc service is unavailable"}})";
        failure_.prepare_payload();
        downstream_.expires_after(std::chrono::seconds(5));
        http::async_write(downstream_, failure_,
            [self = shared_from_this()](beast::error_code, std::size_t) { self->close(); });
    }

    void close()
    {
        beast::error_code ignored;
        downstream_.socket().shutdown(tcp::socket::shutdown_both, ignored);
        upstream_.socket().shutdown(tcp::socket::shutdown_both, ignored);
        downstream_.socket().close(ignored);
        upstream_.socket().close(ignored);
    }

    beast::tcp_stream downstream_, upstream_;
    Request request_;
    http::response_parser<http::empty_body> parser_;
    http::response<http::empty_body> reply_;
    std::optional<http::response_serializer<http::empty_body>> serializer_;
    http::response<http::string_body> failure_;
    beast::flat_buffer header_buffer_;
    std::array<char, 16384> server_bytes_{}, client_bytes_{};
    bool upgrade_ = false;
};
} // namespace

bool go2rtc_enabled()
{
    const char *value = std::getenv("WEBOBS_GO2RTC_ENABLED");
    return value && std::string_view(value) == "true";
}

bool go2rtc_target_allowed(std::string_view target)
{
    if (!target.starts_with(go2rtc_prefix)) return false;
    const auto path = target.substr(0, target.find('?'));
    // Reject escaped/dot paths rather than letting the upstream normalize a
    // request outside the protected prefix. Query strings stay byte-for-byte.
    if (path.find("..") != std::string_view::npos) return false;
    return std::all_of(path.begin(), path.end(), [](unsigned char c) {
        return std::isalnum(c) || c == '/' || c == '.' || c == '-' || c == '_';
    });
}

void start_go2rtc_proxy(tcp::socket socket, Request request)
{
    std::make_shared<ProxySession>(std::move(socket), std::move(request))->run();
}
} // namespace webobs
