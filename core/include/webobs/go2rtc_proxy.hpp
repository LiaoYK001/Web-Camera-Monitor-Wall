#pragma once

#include <boost/asio.hpp>
#include <boost/beast/http.hpp>

#include <string_view>

namespace webobs {

inline constexpr std::string_view go2rtc_prefix = "/api/v1/go2rtc/";
bool go2rtc_enabled();
bool go2rtc_target_allowed(std::string_view target);

// Call only after the control server has checked authentication, RBAC and Origin.
// Streams HTTP bodies and WebSocket frames with bounded buffers and backpressure.
void start_go2rtc_proxy(boost::asio::ip::tcp::socket socket,
                        boost::beast::http::request<boost::beast::http::string_body> request);

} // namespace webobs
