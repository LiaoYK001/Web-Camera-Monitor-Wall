#include "webobs/nvr_media_proxy.hpp"
#include "webobs/platform_runtime.hpp"
#include <boost/beast/core.hpp>
#include <algorithm>
#include <array>
#include <atomic>
#include <cctype>
#include <memory>
#include <optional>

namespace webobs {
namespace {
namespace net = boost::asio;
namespace beast = boost::beast;
namespace http = beast::http;
using tcp = net::ip::tcp;
using Request = http::request<http::string_body>;
std::atomic<unsigned> active_transfers{0};
constexpr unsigned maximum_transfers = 64;
constexpr std::string_view prefix = "/api/v1/nvr";

bool identifier(std::string_view value) {
    return value.size() == 32 && std::all_of(value.begin(), value.end(), [](unsigned char c) {
        return (c >= '0' && c <= '9') || (c >= 'a' && c <= 'f');
    });
}
bool safe_name(std::string_view value) {
    return !value.empty() && value.size() <= 160 && value != "." && value != ".." &&
        std::all_of(value.begin(), value.end(), [](unsigned char c) {
            return std::isalnum(c) || c == '.' || c == '_' || c == '-';
        });
}
bool range_allowed(std::string_view value) {
    if (!value.starts_with("bytes=") || value.size() > 128) return false;
    value.remove_prefix(6);
    const auto dash = value.find('-');
    return dash != std::string_view::npos && value.size() > 1 &&
        std::count(value.begin(), value.end(), '-') == 1 &&
        std::all_of(value.begin(), value.end(), [](unsigned char c) { return std::isdigit(c) || c == '-'; });
}

class Transfer : public std::enable_shared_from_this<Transfer> {
public:
    Transfer(tcp::socket socket, Request incoming, std::string cookie)
        : downstream_(std::move(socket)), upstream_(downstream_.get_executor()),
          request_(incoming.method(), incoming.target().substr(prefix.size()), 11),
          renewed_cookie_(std::move(cookie)), header_buffer_(64 * 1024) {
        request_.set(http::field::host, "127.0.0.1");
        request_.set(http::field::connection, "close");
        request_.set("X-WebObs-Nvr-Principal", incoming["X-WebObs-Nvr-Principal"]);
        for (const auto name : {http::field::range, http::field::if_range, http::field::if_none_match}) {
            const auto field = incoming.find(name);
            if (field != incoming.end()) {
                if (field->value().size() > 128) invalid_headers_ = true;
                else request_.set(name, field->value());
            }
        }
        request_.prepare_payload();
        parser_.header_limit(16 * 1024);
        parser_.body_limit(boost::none);
        if (incoming.method() == http::verb::head) parser_.skip(true);
    }
    ~Transfer() { if (counted_) --active_transfers; }
    void run() {
        if (invalid_headers_)
            return fail(http::status::bad_request, "invalid_range", "Media validator header exceeds its limit");
        const auto range = request_.find(http::field::range);
        if (range != request_.end() && !range_allowed(std::string_view(range->value().data(), range->value().size())))
            return fail(http::status::bad_request, "invalid_range", "Range header is invalid");
        if (active_transfers.fetch_add(1) >= maximum_transfers) {
            --active_transfers;
            return fail(http::status::too_many_requests, "nvr_transfer_busy", "Too many media transfers; retry shortly");
        }
        counted_ = true;
        upstream_.expires_after(std::chrono::seconds(5));
        upstream_.async_connect(tcp::endpoint(net::ip::make_address("127.0.0.1"),
            static_cast<unsigned short>(runtime_port(8091))), [self = shared_from_this()](beast::error_code error) {
            if (error) return self->unavailable();
            self->upstream_.expires_after(std::chrono::seconds(30));
            http::async_write(self->upstream_, self->request_, [self](beast::error_code error, std::size_t) {
                if (error) return self->unavailable();
                self->read_header();
            });
        });
    }
private:
    void read_header() {
        http::async_read_header(upstream_, header_buffer_, parser_, [self = shared_from_this()](beast::error_code error, std::size_t) {
            if (error) return self->unavailable();
            const auto &source = self->parser_.get();
            if (source.result_int() < 200 || source.result_int() > 599) return self->unavailable();
            self->reply_.result(source.result());
            self->reply_.version(11);
            for (const auto name : {http::field::content_type, http::field::content_length, http::field::content_range,
                    http::field::accept_ranges, http::field::etag, http::field::last_modified,
                    http::field::content_disposition, http::field::retry_after}) {
                const auto field = source.find(name);
                if (field != source.end() && field->value().size() <= 512) self->reply_.set(name, field->value());
            }
            if (source.chunked()) self->reply_.chunked(true);
            self->reply_.keep_alive(false);
            self->reply_.set(http::field::server, "webobsd");
            self->reply_.set(http::field::cache_control, "no-store");
            self->reply_.set("X-Content-Type-Options", "nosniff");
            self->reply_.set("Referrer-Policy", "no-referrer");
            self->reply_.set("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'; sandbox");
            self->reply_.set("X-Frame-Options", "DENY");
            self->reply_.set("Cross-Origin-Resource-Policy", "same-origin");
            if (!self->renewed_cookie_.empty()) self->reply_.set(http::field::set_cookie, self->renewed_cookie_);
            self->reply_.body().more = !self->parser_.is_done();
            self->serializer_.emplace(self->reply_);
            self->downstream_.expires_after(std::chrono::seconds(30));
            http::async_write_header(self->downstream_, *self->serializer_, [self](beast::error_code error, std::size_t) {
                if (error || self->parser_.is_done()) return self->close();
                self->serializer_->split(false);
                self->read_body();
            });
        });
    }
    void read_body() {
        upstream_.expires_after(std::chrono::seconds(30));
        auto &body = parser_.get().body();
        body.data = bytes_.data(); body.size = bytes_.size();
        http::async_read_some(upstream_, header_buffer_, parser_, [self = shared_from_this()](beast::error_code error, std::size_t) {
            if (error == http::error::need_buffer) error = {};
            if (error) return self->close();
            const auto used = self->bytes_.size() - self->parser_.get().body().size;
            if (!used && !self->parser_.is_done()) return self->read_body();
            auto &body = self->reply_.body();
            body.data = self->bytes_.data(); body.size = used; body.more = !self->parser_.is_done();
            self->downstream_.expires_after(std::chrono::seconds(30));
            http::async_write(self->downstream_, *self->serializer_, [self](beast::error_code error, std::size_t) {
                if (error == http::error::need_buffer) error = {};
                if (error || self->serializer_->is_done()) return self->close();
                self->read_body();
            });
        });
    }
    void unavailable() { fail(http::status::service_unavailable, "nvr_unavailable", "NVR media is unavailable"); }
    void fail(http::status status, std::string_view code, std::string_view message) {
        failure_ = {status, 11};
        failure_.set(http::field::content_type, "application/json");
        failure_.set(http::field::cache_control, "no-store");
        failure_.set("X-Content-Type-Options", "nosniff");
        if (status == http::status::too_many_requests) failure_.set(http::field::retry_after, "2");
        failure_.keep_alive(false);
        failure_.body() = "{\"error\":{\"code\":\"" + std::string(code) + "\",\"message\":\"" + std::string(message) + "\"}}";
        if (request_.method() == http::verb::head) failure_.body().clear();
        failure_.prepare_payload();
        downstream_.expires_after(std::chrono::seconds(5));
        http::async_write(downstream_, failure_, [self = shared_from_this()](beast::error_code, std::size_t) { self->close(); });
    }
    void close() {
        beast::error_code ignored;
        upstream_.socket().close(ignored); downstream_.socket().close(ignored);
    }
    beast::tcp_stream downstream_, upstream_;
    Request request_;
    std::string renewed_cookie_;
    beast::flat_buffer header_buffer_;
    http::response_parser<http::buffer_body> parser_;
    http::response<http::buffer_body> reply_;
    std::optional<http::response_serializer<http::buffer_body>> serializer_;
    http::response<http::string_body> failure_;
    std::array<char, 64 * 1024> bytes_{};
    bool counted_ = false;
    bool invalid_headers_ = false;
};
} // namespace

bool nvr_media_target_allowed(std::string_view target) {
    const auto query = target.find('?');
    auto path = target.substr(0, query);
    constexpr std::string_view media_prefix = "/api/v1/nvr/media/";
    constexpr std::string_view thumbnail_prefix = "/api/v1/nvr/thumbnails/";
    constexpr std::string_view download_prefix = "/api/v1/nvr/downloads/";
    if (path.starts_with(media_prefix)) return query == std::string_view::npos && identifier(path.substr(media_prefix.size()));
    if (path.starts_with(thumbnail_prefix)) {
        if (!identifier(path.substr(thumbnail_prefix.size()))) return false;
        if (query == std::string_view::npos) return true;
        const auto parameters = target.substr(query + 1);
        return parameters.starts_with("offsetMs=") && parameters.size() > 9 && parameters.size() <= 19 &&
            std::all_of(parameters.begin() + 9, parameters.end(), [](unsigned char c) { return std::isdigit(c); });
    }
    if (!path.starts_with(download_prefix) || query != std::string_view::npos) return false;
    path.remove_prefix(download_prefix.size());
    const auto slash = path.find('/');
    if (slash == std::string_view::npos) return path.ends_with(".jpg") && identifier(path.substr(0, path.size()-4));
    const auto name = path.substr(slash + 1);
    return identifier(path.substr(0, slash)) && safe_name(name) && (name.ends_with(".mp4") || name.ends_with(".json"));
}

void start_nvr_media_proxy(tcp::socket socket, Request request, std::string cookie) {
    std::make_shared<Transfer>(std::move(socket), std::move(request), std::move(cookie))->run();
}
} // namespace webobs
