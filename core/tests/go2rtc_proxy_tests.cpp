#include "webobs/go2rtc_proxy.hpp"
#include <boost/beast/core.hpp>
#include <cstdlib>
#include <iostream>
#include <stdexcept>
#include <string>
#include <thread>

namespace net = boost::asio;
namespace http = boost::beast::http;
using tcp = net::ip::tcp;

static void check(bool condition, const char* message) {
    if (!condition) throw std::runtime_error(message);
}

static void exercise(http::verb method, const std::string& target, const std::string& upstream_reply,
                     unsigned expected_status, const std::string& expected_target, bool available = true) {
    net::io_context context;
    tcp::acceptor upstream(context, {net::ip::make_address("127.0.0.1"), 0});
    const auto port = std::to_string(upstream.local_endpoint().port());
#ifdef _WIN32
    _putenv_s("WEBOBS_GO2RTC_API_PORT", port.c_str());
#else
    setenv("WEBOBS_GO2RTC_API_PORT", port.c_str(), 1);
#endif
    http::request<http::string_body> received;
    std::thread server;
    if (available) {
        server = std::thread([&] {
            tcp::socket socket(context);
            upstream.accept(socket);
            boost::beast::flat_buffer buffer;
            http::read(socket, buffer, received);
            if (!upstream_reply.empty()) net::write(socket, net::buffer(upstream_reply));
            // go2rtc api/exit closes without sending any HTTP response.
        });
    } else upstream.close();
    tcp::acceptor gateway(context, {net::ip::make_address("127.0.0.1"), 0});
    const auto endpoint = gateway.local_endpoint();
    gateway.async_accept([&](boost::system::error_code error, tcp::socket socket) {
        if (error) return;
        boost::beast::flat_buffer buffer;
        http::request<http::string_body> request;
        http::read(socket, buffer, request);
        webobs::start_go2rtc_proxy(std::move(socket), std::move(request));
    });
    std::thread proxy([&] { context.run(); });
    net::io_context client_context;
    tcp::socket client(client_context);
    client.connect(endpoint);
    http::request<http::string_body> request{method, target, 11};
    request.set(http::field::host, "127.0.0.1");
    request.set(http::field::cookie, "product-session=private");
    request.set(http::field::authorization, "Bearer private");
    request.set("X-WebOBS-Principal", "private");
    request.body() = "ignored restart body";
    request.prepare_payload();
    http::write(client, request);
    boost::beast::flat_buffer buffer;
    http::response<http::string_body> response;
    boost::system::error_code error;
    http::read(client, buffer, response, error);
    context.stop();
    proxy.join();
    if (server.joinable()) server.join();
    check(!error, "proxy must send an HTTP response");
    check(response.result_int() == expected_status, "unexpected proxy status");
    check(response[http::field::cache_control] == "no-store", "response must not be cached");
    if (available) {
        check(received.target() == expected_target, "unexpected upstream target");
        check(received[http::field::cookie].empty() && received[http::field::authorization].empty() &&
              received["X-WebOBS-Principal"].empty(), "product identity leaked upstream");
        if (expected_status == 202) {
            check(received.body().empty(), "restart must not forward a body");
            check(response.body() == R"({"status":"restarting"})", "missing restart acceptance");
        }
    }
}

int main() {
    try {
        const std::string restart = "/api/v1/go2rtc/api/restart";
        const std::string exit = "/api/v1/go2rtc/api/exit?code=75";
        exercise(http::verb::post, restart + "?code=0", "", 202, exit);
        exercise(http::verb::get, restart, "HTTP/1.1 400 Bad Request\r\nContent-Length: 0\r\n\r\n", 400, restart);
        exercise(http::verb::post, restart, "HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\n\r\n", 403, exit);
        exercise(http::verb::post, restart, "HTTP/1.1 200", 503, exit);
        exercise(http::verb::get, "/api/v1/go2rtc/api/streams?src=test", "", 503, "/api/v1/go2rtc/api/streams?src=test");
        exercise(http::verb::post, restart, "", 503, "", false);
        std::cout << "go2rtc restart acceptance, failure handling, method/query isolation and credential stripping passed\n";
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
