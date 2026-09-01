#pragma once

#include <chrono>
#include <cstddef>
#include <cstdint>
#include <optional>
#include <string>
#include <string_view>
#include <unordered_map>
#include <mutex>
#include <memory>

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
    AuthenticationDecision authenticate_plain(std::string_view username, std::string_view password,
                                               std::string_view client_key,
                                               std::chrono::steady_clock::time_point now =
                                                   std::chrono::steady_clock::now());
    [[nodiscard]] std::uint64_t failed_attempts() const { return failed_attempts_; }
    [[nodiscard]] std::size_t retry_after_seconds() const;
    [[nodiscard]] bool credentials_match_plain(std::string_view username,
                                               std::string_view password) const;
    [[nodiscard]] std::string_view configured_username() const;

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

struct SessionRecord {
    std::string user;
    std::int64_t created_at = 0;
    std::int64_t last_seen = 0;
    std::int64_t expires_at = 0;
};

class SessionStore {
public:
    SessionStore(std::string database_path, std::chrono::seconds inactivity_expiry,
                 bool secure_cookie);
    ~SessionStore();

    SessionStore(const SessionStore &) = delete;
    SessionStore &operator=(const SessionStore &) = delete;

    [[nodiscard]] std::optional<std::string> initialize();
    [[nodiscard]] std::optional<std::string> create(std::string_view user,
                                                    std::string_view client_metadata);
    [[nodiscard]] std::optional<SessionRecord> validate_and_slide(std::string_view token);
    bool revoke(std::string_view token);
    std::size_t revoke_user(std::string_view user);
    [[nodiscard]] std::string set_cookie_header(std::string_view token) const;
    [[nodiscard]] std::string clear_cookie_header() const;
    [[nodiscard]] bool enabled() const { return !database_path_.empty(); }
    [[nodiscard]] std::int64_t inactivity_expiry_seconds() const
    {
        return inactivity_expiry_.count();
    }

private:
    struct Impl;
    std::string database_path_;
    std::chrono::seconds inactivity_expiry_;
    bool secure_cookie_;
    std::unique_ptr<Impl> impl_;
    std::mutex mutex_;
};

} // namespace webobs
