#pragma once
#include <boost/asio.hpp>
#include <boost/beast/http.hpp>
#include <string>
#include <string_view>

namespace webobs {
bool nvr_media_target_allowed(std::string_view target);
// Only after product authentication, RBAC, identity replacement and Origin checks.
// GET/HEAD media responses use bounded buffers and backpressure, outside RequestPool.
void start_nvr_media_proxy(boost::asio::ip::tcp::socket socket,
    boost::beast::http::request<boost::beast::http::string_body> request,
    std::string renewed_cookie = {});
}
