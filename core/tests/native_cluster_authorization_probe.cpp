// Test-only interactive probe. Never installed or connected to a user profile.
#include "webobs/native_cluster_authorization.hpp"

#include <jansson.h>
#include <chrono>
#include <cstdlib>
#include <iostream>
#include <map>
#include <memory>
#include <string>

namespace {
std::string text(json_t *value, const char *key)
{
    const auto *field = json_object_get(value, key);
    return json_is_string(field) ? std::string(json_string_value(field), json_string_length(field)) : std::string{};
}
int status(webobs::NativeAuthorizationDecision decision)
{
    using D = webobs::NativeAuthorizationDecision;
    switch (decision) {
    case D::allowed: return 200;
    case D::unknown_user: return 401;
    case D::denied: return 403;
    default: return 503;
    }
}
}

int main(int argc, char **argv)
{
    if (argc != 3)
        return 2;
    try {
        webobs::SessionStore sessions(argv[1], std::chrono::seconds(300), false);
        if (sessions.initialize())
            return 2;
        std::map<std::string, std::string> tokens;
        std::unique_ptr<webobs::NativeClusterAuthorizationBackend> backend;
        std::string line;
        while (std::getline(std::cin, line)) {
            if (line.size() > 8192)
                return 2;
            std::unique_ptr<json_t, decltype(&json_decref)> root(
                json_loadb(line.data(), line.size(), JSON_REJECT_DUPLICATES | JSON_ALLOW_NUL, nullptr), json_decref);
            if (!json_is_object(root.get()))
                return 2;
            const auto op = text(root.get(), "op");
            int reply = 503;
            if (op == "init") {
                webobs::NativeClusterAuthorizationConfig config;
                config.port = static_cast<std::uint16_t>(std::stoi(argv[2]));
                config.internal_token = text(root.get(), "token");
                config.connect_timeout = std::chrono::milliseconds(json_integer_value(json_object_get(root.get(), "connectMs")));
                config.request_timeout = std::chrono::milliseconds(json_integer_value(json_object_get(root.get(), "totalMs")));
                backend = std::make_unique<webobs::NativeClusterAuthorizationBackend>(std::move(config));
                reply = backend->configured() ? 200 : 503;
            } else if (op == "create") {
                const auto token = sessions.create(text(root.get(), "user"), "native-account-contract");
                if (token) {
                    tokens[text(root.get(), "slot")] = *token;
                    reply = 200;
                }
            } else if (op == "direct" && backend) {
                reply = status((*backend)(text(root.get(), "user"), text(root.get(), "permission"), text(root.get(), "camera")));
            } else if (op == "authorize" && backend) {
                webobs::NativeControlAuth auth(sessions, {"http://127.0.0.1:18086", "127.0.0.1:18086"},
                    [&](std::string_view user, std::string_view permission, std::string_view camera) {
                        return (*backend)(user, permission, camera);
                    });
                const auto slot = text(root.get(), "slot");
                const auto camera = text(root.get(), "camera");
                const auto command = static_cast<webobs::NativeControlCommand>(json_integer_value(json_object_get(root.get(), "command")));
                reply = auth.authorize({"127.0.0.1", "http://127.0.0.1:18086", "127.0.0.1:18086",
                    tokens[slot], command, camera}).status_code();
            }
            // Neither raw service credentials nor session cookies leave the probe.
            std::cout << reply << std::endl;
        }
        return 0;
    } catch (...) {
        std::cerr << "native account test probe failed\n";
        return 2;
    }
}
