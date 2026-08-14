#pragma once

#include <chrono>
#include <cstddef>
#include <cstdint>
#include <optional>
#include <string>
#include <string_view>
#include <unordered_map>

namespace webobs {

struct BasicAuthCredentials {
    std::string username;
    std::string password;
};

enum class AuthenticationDecision {
    allowed,
    credentials_required,
    invalid_credentials,
    rate_limit_started,
    rate_limited,
};

class BasicAuthenticator {
public:
    BasicAuthenticator(std::optional<BasicAuthCredentials> credentials, std::size_t failure_limit,
                       std::chrono::seconds failure_window);

    [[nodiscard]] bool enabled() const { return credentials_.has_value(); }
    AuthenticationDecision authenticate(std::optional<std::string_view> authorization,
                                        std::string_view client_key,
                                        std::chrono::steady_clock::time_point now =
                                            std::chrono::steady_clock::now());
    [[nodiscard]] std::uint64_t failed_attempts() const { return failed_attempts_; }
    [[nodiscard]] std::size_t retry_after_seconds() const;

private:
    struct FailureWindow {
        std::chrono::steady_clock::time_point started;
        std::size_t failures = 0;
    };

    bool credentials_match(std::string_view authorization) const;
    void prune(std::chrono::steady_clock::time_point now);

    std::optional<BasicAuthCredentials> credentials_;
    std::size_t failure_limit_;
    std::chrono::seconds failure_window_;
    std::unordered_map<std::string, FailureWindow> failures_;
    std::uint64_t failed_attempts_ = 0;
};

} // namespace webobs
