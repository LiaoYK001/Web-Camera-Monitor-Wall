#include "webobs/native_control_auth.hpp"

#include <sqlite3.h>

#include <chrono>
#include <filesystem>
#include <iostream>
#include <random>
#include <stdexcept>
#include <string>
#include <string_view>
#include <vector>

namespace {

using namespace webobs;

void require(bool condition, const char *message)
{
    if (!condition)
        throw std::runtime_error(message);
}

class PrivateTemporaryDirectory {
public:
    PrivateTemporaryDirectory()
    {
        const auto root = std::filesystem::temp_directory_path();
        std::random_device random;
        for (int attempt = 0; attempt < 32; ++attempt) {
            auto candidate = root / ("webobs-native-control-auth-" + std::to_string(random()) +
                                     "-" + std::to_string(random()));
            if (!std::filesystem::create_directory(candidate))
                continue;
            path = std::filesystem::absolute(candidate).lexically_normal();
            std::filesystem::permissions(path, std::filesystem::perms::owner_all,
                                         std::filesystem::perm_options::replace);
            return;
        }
        throw std::runtime_error("could not create private test directory");
    }

    ~PrivateTemporaryDirectory()
    {
        // Remove only the exact, verified directory this instance created.
        const auto root = std::filesystem::absolute(std::filesystem::temp_directory_path()).lexically_normal();
        if (!path.empty() && path.parent_path() == root &&
            path.filename().string().find("webobs-native-control-auth-") == 0) {
            std::error_code ignored;
            std::filesystem::remove_all(path, ignored);
        }
    }

    std::filesystem::path path;
};

SessionIdentity synthetic_identity()
{
    return {"0123456789abcdef0123456789abcdef", "fedcba9876543210fedcba9876543210"};
}

std::optional<std::string> create_bound(SessionStore &sessions, std::string_view user,
                                      std::string_view metadata,
                                      const SessionIdentity &identity = synthetic_identity())
{
    return sessions.create_bound(user, metadata, identity);
}

struct Backend {
    int calls = 0;
    NativeAuthorizationDecision next = NativeAuthorizationDecision::allowed;
    bool throw_exception = false;
    std::string principal;
    SessionIdentity identity;
    std::string permission;
    std::string camera;

    NativeAuthorizationDecision operator()(std::string_view user, const SessionIdentity &binding,
                                           std::string_view grant, std::string_view scope)
    {
        ++calls;
        principal = user;
        identity = binding;
        permission = grant;
        camera = scope;
        if (throw_exception)
            throw std::runtime_error("sensitive-backend-diagnostic-must-not-be-exposed");
        return next;
    }
};

NativeControlRequest request_for(std::string_view token)
{
    return {"127.0.0.1", "http://127.0.0.1:18086", "127.0.0.1:18086", token,
            NativeControlCommand::read_scene, {}};
}

NativeControlAuthConfig config()
{
    return {"http://127.0.0.1:18086", "127.0.0.1:18086"};
}

void expect_status(const NativeControlAuthorization &reply, int status)
{
    require(reply.status_code() == status, "unexpected authorization status");
    require(reply.allowed() == (status == 200), "inconsistent allowed status");
    require(status == 200 ? !reply.principal.empty() : reply.principal.empty(),
            "principal leaked on a rejected request");
    const auto code = reply.code();
    require(code == "allowed" || code == "invalid_request" || code == "authentication_required" ||
                code == "forbidden" || code == "authorization_unavailable",
            "diagnostic must be a fixed safe code");
}

void execute_sql(const std::filesystem::path &path, const char *sql)
{
    sqlite3 *database = nullptr;
    require(sqlite3_open_v2(path.string().c_str(), &database, SQLITE_OPEN_READWRITE, nullptr) == SQLITE_OK,
            "could not open temporary fixture database");
    const int status = sqlite3_exec(database, sql, nullptr, nullptr, nullptr);
    sqlite3_close(database);
    require(status == SQLITE_OK, "could not update temporary fixture database");
}

void legacy_and_corrupt_binding_never_reach_backend()
{
    PrivateTemporaryDirectory temporary;
    const auto database_path = temporary.path / "sessions.db";
    SessionStore sessions(database_path.string(), std::chrono::seconds(3600), false);
    require(!sessions.initialize(), "SessionStore initialization failed");
    Backend backend;
    NativeControlAuth gate(sessions, config(), std::ref(backend));
    const auto legacy = sessions.create("legacy-user", "legacy-username-only");
    require(legacy.has_value(), "legacy fixture creation failed");
    expect_status(gate.authorize(request_for(*legacy)), 401);
    expect_status(gate.authorize(request_for(*legacy)), 401);
    const auto unchanged = sessions.validate_and_slide(*legacy);
    require(unchanged && !unchanged->identity,
            "first native authorization must not opportunistically bind a legacy session");
    require(backend.calls == 0, "legacy sessions must never reach the authority backend");

    // Exercise persisted damage, including one-sided/NULL bindings, noncanonical
    // hex, lengths, and embedded NUL. Creation deliberately uses only valid IDs.
    for (const auto mutation : {
             "user_id=NULL", "auth_epoch=NULL", "user_id='',auth_epoch=''",
             "user_id='0123456789abcdef0123456789abcde'",
             "auth_epoch='0123456789abcdef0123456789abcdef0'",
             "user_id='ABCDEF0123456789abcdef0123456789'",
             "auth_epoch='gggggggggggggggggggggggggggggggg'",
             "user_id='0123456789abcdef'||char(0)||'123456789abcdef'",
             "auth_epoch='0123456789abcdef'||char(0)||'123456789abcdef'",
             "user_id='0123456789abcdef0123456789abcdef'||char(0)||'tail'",
             "auth_epoch='fedcba9876543210fedcba9876543210'||char(0)||'tail'"}) {
        const auto token = create_bound(sessions, "binding-user", "corrupt-binding");
        require(token.has_value(), "bound fixture creation failed");
        const std::string sql = std::string("UPDATE auth_sessions SET ") + mutation +
                                " WHERE user_name='binding-user'";
        execute_sql(database_path, sql.c_str());
        expect_status(gate.authorize(request_for(*token)), 401);
        require(backend.calls == 0, "damaged binding must not reach the authority backend");
    }
}

void binding_revalidation_and_safe_diagnostics()
{
    // Mutate the real persisted binding from inside the authoritative callback;
    // even a positive decision applies only to the exact pre-callback identity.
    for (const auto mutation : {
             "user_id='11111111111111111111111111111111'",
             "auth_epoch='22222222222222222222222222222222'",
             "user_id='11111111111111111111111111111111',"
             "auth_epoch='22222222222222222222222222222222'",
             "user_name='renamed-user'", "user_id=NULL,auth_epoch=NULL",
             "user_id=NULL", "auth_epoch='BROKEN'"}) {
        PrivateTemporaryDirectory temporary;
        const auto database_path = temporary.path / "sessions.db";
        SessionStore sessions(database_path.string(), std::chrono::seconds(3600), false);
        require(!sessions.initialize(), "SessionStore initialization failed");
        const auto token = create_bound(sessions, "race-user", "binding-race");
        require(token.has_value(), "binding race fixture creation failed");
        int calls = 0;
        NativeControlAuth gate(sessions, config(),
            [&](std::string_view principal, const SessionIdentity &identity,
                std::string_view permission, std::string_view camera) {
                ++calls;
                require(principal == "race-user" && permission == "scene.read" && camera.empty(),
                        "binding race callback received incorrect principal or permission");
                require(identity.user_id == synthetic_identity().user_id &&
                            identity.auth_epoch == synthetic_identity().auth_epoch,
                        "binding race callback lost the original identity");
                const std::string sql = std::string("UPDATE auth_sessions SET ") + mutation;
                execute_sql(database_path, sql.c_str());
                return NativeAuthorizationDecision::allowed;
            });
        const auto reply = gate.authorize(request_for(*token));
        expect_status(reply, 401);
        require(calls == 1, "binding revalidation must follow exactly one fresh backend call");
    }

    PrivateTemporaryDirectory temporary;
    SessionStore sessions((temporary.path / "sessions.db").string(), std::chrono::seconds(3600), false);
    require(!sessions.initialize(), "SessionStore initialization failed");
    const auto token = create_bound(sessions, "diagnostic-user", "safe-diagnostics");
    require(token.has_value(), "diagnostic fixture creation failed");
    NativeControlAuth throwing_gate(sessions, config(),
        [&](std::string_view, const SessionIdentity &identity, std::string_view, std::string_view)
            -> NativeAuthorizationDecision {
            throw std::runtime_error(identity.user_id + ":" + identity.auth_epoch + ":" + *token);
        });
    const auto reply = throwing_gate.authorize(request_for(*token));
    expect_status(reply, 503);
    require(reply.code() == "authorization_unavailable" && reply.principal.empty(),
            "exceptions must expose only a fixed safe code, never identity or session token");

    std::size_t removed = 0;
    NativeControlAuth already_revoked_gate(sessions, config(),
        [&](std::string_view user, const SessionIdentity &identity, std::string_view, std::string_view) {
            removed = sessions.revoke_identity(user, identity);
            return NativeAuthorizationDecision::unknown_user;
        });
    expect_status(already_revoked_gate.authorize(request_for(*token)), 503);
    require(removed == 1, "concurrent exact-binding revocation fixture failed");
}

void stale_binding_cannot_revoke_replacement()
{
    PrivateTemporaryDirectory temporary;
    const auto database_path = temporary.path / "sessions.db";
    SessionStore sessions(database_path.string(), std::chrono::seconds(3600), false);
    require(!sessions.initialize(), "SessionStore initialization failed");
    const auto token = create_bound(sessions, "replacement-user", "replacement-race");
    require(token.has_value(), "replacement fixture creation failed");
    NativeControlAuth gate(sessions, config(),
        [&](std::string_view, const SessionIdentity &, std::string_view, std::string_view) {
            execute_sql(database_path,
                "UPDATE auth_sessions SET auth_epoch='33333333333333333333333333333333'");
            return NativeAuthorizationDecision::unknown_user;
        });
    // The only row is now a different binding: revoking the original deletes
    // zero rows and must return 503 without destroying that replacement.
    expect_status(gate.authorize(request_for(*token)), 503);
    const auto replacement = sessions.validate_and_slide(*token);
    require(replacement && replacement->identity &&
                replacement->identity->user_id == synthetic_identity().user_id &&
                replacement->identity->auth_epoch == "33333333333333333333333333333333",
            "stale backend decision must not revoke a replacement binding");
}

void freshness_scope_and_fail_closed()
{
    PrivateTemporaryDirectory temporary;
    SessionStore sessions((temporary.path / "sessions.db").string(), std::chrono::seconds(3600), false);
    require(!sessions.initialize(), "SessionStore initialization failed");
    const auto token = create_bound(sessions, "operator-user", "native-control-unit-test");
    require(token.has_value(), "SessionStore creation failed");
    Backend backend;
    NativeControlAuth gate(sessions, config(), std::ref(backend));
    require(gate.configured(), "valid boundary must be configured");
    auto request = request_for(*token);

    const auto first = gate.authorize(request);
    expect_status(first, 200);
    require(first.principal == "operator-user" && backend.principal == "operator-user",
            "backend must receive only the validated session principal");
    require(backend.identity.user_id == synthetic_identity().user_id &&
                backend.identity.auth_epoch == synthetic_identity().auth_epoch,
            "backend must receive both exact bound identity fields without transformation");
    require(backend.permission == "scene.read" && backend.camera.empty(), "read permission mapping changed");
    expect_status(gate.authorize(request), 200);
    require(backend.calls == 2, "repeated commands must freshly call the backend");

    request.command = NativeControlCommand::write_scene;
    request.camera_id = "Camera_1.left-2";
    expect_status(gate.authorize(request), 200);
    require(backend.permission == "scene.write" && backend.camera == request.camera_id,
            "write command must forward exact scope and fixed permission");
    request.command = NativeControlCommand::view_camera;
    expect_status(gate.authorize(request), 200);
    require(backend.permission == "live.view" && backend.camera == request.camera_id,
            "camera command must use live.view and an explicit scope");

    backend.next = NativeAuthorizationDecision::denied;
    expect_status(gate.authorize(request), 403);
    require(sessions.validate_and_slide(*token).has_value(), "role denial must not revoke a valid session");
    backend.next = NativeAuthorizationDecision::allowed;
    expect_status(gate.authorize(request), 200);
    backend.next = NativeAuthorizationDecision::unavailable;
    expect_status(gate.authorize(request), 503);
    require(sessions.validate_and_slide(*token).has_value(), "temporary outage must not destroy the session");
    backend.throw_exception = true;
    const auto failure = gate.authorize(request);
    expect_status(failure, 503);
    require(failure.code() == "authorization_unavailable", "backend exception text must not escape");
    backend.throw_exception = false;
    backend.next = static_cast<NativeAuthorizationDecision>(999);
    expect_status(gate.authorize(request), 503);

    const auto second = create_bound(sessions, "operator-user", "second-session");
    const auto unrelated = create_bound(sessions, "different-user", "unrelated-session");
    auto new_epoch = synthetic_identity();
    new_epoch.auth_epoch = "11111111111111111111111111111111";
    auto new_account = synthetic_identity();
    new_account.user_id = "22222222222222222222222222222222";
    const auto reauthenticated = create_bound(sessions, "operator-user", "new-epoch", new_epoch);
    const auto recreated = create_bound(sessions, "operator-user", "new-account", new_account);
    const auto legacy = sessions.create("operator-user", "legacy-session");
    require(second && unrelated && reauthenticated && recreated && legacy,
            "additional session fixture creation failed");
    backend.next = NativeAuthorizationDecision::unknown_user;
    expect_status(gate.authorize(request), 401);
    require(!sessions.validate_and_slide(*token) && !sessions.validate_and_slide(*second),
            "unknown identity must revoke every local session for the exact binding");
    require(sessions.validate_and_slide(*unrelated).has_value(), "revocation must not affect another user");
    require(sessions.validate_and_slide(*reauthenticated) && sessions.validate_and_slide(*recreated) &&
                sessions.validate_and_slide(*legacy),
            "old identity revocation must preserve same-name new bindings and legacy sessions");
    const int calls_after_revoke = backend.calls;
    backend.next = NativeAuthorizationDecision::allowed;
    expect_status(gate.authorize(request), 401);
    require(backend.calls == calls_after_revoke, "revoked token must not reach the backend");
}

void failed_revocation_is_unavailable()
{
    PrivateTemporaryDirectory temporary;
    const auto database_path = temporary.path / "sessions.db";
    SessionStore sessions(database_path.string(), std::chrono::seconds(3600), false);
    require(!sessions.initialize(), "SessionStore initialization failed");
    const auto first = create_bound(sessions, "disabled-user", "first-session");
    const auto second = create_bound(sessions, "disabled-user", "second-session");
    const auto unrelated = create_bound(sessions, "different-user", "unrelated-session");
    require(first && second && unrelated, "revocation failure fixture creation failed");
    Backend backend;
    backend.next = NativeAuthorizationDecision::unknown_user;
    NativeControlAuth gate(sessions, config(), std::ref(backend));
    const auto request = request_for(*first);

    // Exercise a real SQLite DELETE failure, not an injected SessionStore mock.
    execute_sql(database_path,
        "CREATE TRIGGER block_session_revocation BEFORE DELETE ON auth_sessions "
        "WHEN OLD.user_name='disabled-user' "
        "BEGIN SELECT RAISE(ABORT, 'fixture revocation denied'); END");
    expect_status(gate.authorize(request), 503);
    require(backend.calls == 1, "revocation failure must still perform fresh authority lookup");
    require(sessions.validate_and_slide(*first) && sessions.validate_and_slide(*second),
            "fixture must prove failed DELETE leaves target sessions present");
    require(sessions.validate_and_slide(*unrelated).has_value(), "failed revocation changed unrelated session");
    // No grant is returned even while the persistent revocation failure recurs.
    expect_status(gate.authorize(request), 503);
    require(backend.calls == 2, "revocation failure must not cache any authorization result");

    execute_sql(database_path, "DROP TRIGGER block_session_revocation");
    expect_status(gate.authorize(request), 401);
    require(backend.calls == 3, "successful retry must freshly consult authority");
    require(!sessions.validate_and_slide(*first) && !sessions.validate_and_slide(*second),
            "retry must remove every target user session");
    require(sessions.validate_and_slide(*unrelated).has_value(), "retry revoked an unrelated session");
    expect_status(gate.authorize(request), 401);
    require(backend.calls == 3, "revoked session must not reach backend after successful retry");
}

void structural_rejection_precedes_session_and_backend()
{
    PrivateTemporaryDirectory temporary;
    const auto database_path = temporary.path / "sessions.db";
    SessionStore sessions(database_path.string(), std::chrono::seconds(3600), false);
    require(!sessions.initialize(), "SessionStore initialization failed");
    const auto token = create_bound(sessions, "scope-user", "structural-tests");
    require(token.has_value(), "SessionStore creation failed");
    Backend backend;
    NativeControlAuth gate(sessions, config(), std::ref(backend));
    auto valid = request_for(*token);
    // If malformed metadata touched SessionStore, sliding would overwrite this.
    execute_sql(database_path, "UPDATE auth_sessions SET last_seen=7");
    const auto reject = [&](const NativeControlRequest &request, int expected) {
        const int before = backend.calls;
        expect_status(gate.authorize(request), expected);
        require(backend.calls == before, "invalid input reached the authority backend");
    };

    for (const auto peer : {"192.168.1.1", "0.0.0.0", "127.1", "0177.0.0.1", "127.0.0.01",
                            "2130706433", "localhost", "::ffff:127.0.0.1", "[::1]", "::1%lo", ""}) {
        auto request = valid;
        request.peer_address = peer;
        reject(request, 403);
    }
    for (const auto origin : {"", "null", "https://127.0.0.1:18086", "http://127.0.0.1:18087",
                              "http://localhost:18086", "http://127.0.0.1:18086/", "http://127.0.0.1:18086?x=1",
                              "http://127.0.0.1:18086#x", "http://127.0.0.1:18086.evil.invalid",
                              "http://user@127.0.0.1:18086", "http://127.0.0.1:18086\r\nX: y"}) {
        auto request = valid;
        request.origin = origin;
        reject(request, 403);
    }
    for (const auto authority : {"", "127.0.0.1:18087", "localhost:18086", "127.0.0.1:018086",
                                 "127.0.0.1:0", "127.0.0.1:65536", "127.0.0.1:", "127.0.0.1:18086/path",
                                 "user@127.0.0.1:18086", "127.0.0.1:18086,127.0.0.1:18086",
                                 "127.0.0.1:18086\r\nX: y", "[::1]:18086"}) {
        auto request = valid;
        request.authority = authority;
        reject(request, 403);
    }
    const std::string oversize(4096, 'a');
    // Construct actual control bytes explicitly, not printable backslash text.
    const std::string embedded_nul = std::string("http://127.0.0.1:18086") + char(0) + ".evil";
    const std::string crlf_origin = std::string("http://127.0.0.1:18086") + char(13) + char(10) + "X: y";
    const std::string crlf_authority = std::string("127.0.0.1:18086") + char(13) + char(10) + "X: y";
    require(embedded_nul.size() == 28 && embedded_nul[22] == char(0), "NUL origin fixture is not byte-exact");
    require(crlf_origin[22] == char(13) && crlf_origin[23] == char(10), "CRLF fixture is not byte-exact");
    auto request = valid;
    request.origin = oversize;
    reject(request, 403);
    request.origin = embedded_nul;
    reject(request, 403);
    request.origin = crlf_origin;
    reject(request, 403);
    request = valid;
    request.authority = crlf_authority;
    reject(request, 403);
    const std::string nul_authority = std::string("127.0.0.1:18086") + char(0) + ".evil";
    request.authority = nul_authority;
    reject(request, 403);
    request = valid;
    request.authority = oversize;
    reject(request, 403);
    request = valid;
    request.peer_address = oversize;
    reject(request, 403);

    for (const auto camera : {"../camera", ".", "..", "camera/1", "camera%2f1", "camera,other",
                              "camera?other=1", "camera#other", "camera\\other", "*", " camera", "camera\r\n"}) {
        request = valid;
        request.camera_id = camera;
        reject(request, 400);
    }
    request = valid;
    request.camera_id = oversize;
    reject(request, 400);
    const std::string nul_camera = std::string("camera") + char(0) + "other";
    require(nul_camera.size() == 12 && nul_camera[6] == char(0), "NUL camera fixture is not byte-exact");
    request.camera_id = nul_camera;
    reject(request, 400);
    const std::string crlf_camera = std::string("camera") + char(13) + char(10);
    request.camera_id = crlf_camera;
    reject(request, 400);
    const std::string too_long_camera(65, 'a');
    request.camera_id = too_long_camera;
    reject(request, 400);
    request = valid;
    request.command = NativeControlCommand::view_camera;
    reject(request, 400);
    request = valid;
    request.command = static_cast<NativeControlCommand>(999);
    reject(request, 400);
    request = valid;
    request.session_token = oversize;
    reject(request, 400);
    request.session_token = {};
    reject(request, 401);
    request.session_token = "Basic not-a-session";
    reject(request, 401);
    const std::string upper(64, 'A');
    request.session_token = upper;
    reject(request, 401);
    const std::string unknown(64, 'f');
    request.session_token = unknown;
    reject(request, 401);
    require(backend.calls == 0, "invalid structural requests must never consult backend");

    sqlite3 *database = nullptr;
    require(sqlite3_open_v2(database_path.string().c_str(), &database, SQLITE_OPEN_READONLY, nullptr) == SQLITE_OK,
            "could not inspect temporary database");
    sqlite3_stmt *statement = nullptr;
    const int prepared = sqlite3_prepare_v2(database,
        "SELECT last_seen,session_id_hash FROM auth_sessions", -1, &statement, nullptr);
    require(prepared == SQLITE_OK && sqlite3_step(statement) == SQLITE_ROW, "session fixture row missing");
    require(sqlite3_column_int64(statement, 0) == 7, "rejected metadata must not slide the session");
    const std::string stored_hash(reinterpret_cast<const char *>(sqlite3_column_text(statement, 1)));
    require(stored_hash.size() == 64 && stored_hash != *token, "SessionStore must persist a hash, not the token");
    sqlite3_finalize(statement);
    sqlite3_close(database);

    request = valid;
    request.peer_address = "127.15.2.3";
    expect_status(gate.authorize(request), 200);
    request.peer_address = "::1";
    expect_status(gate.authorize(request), 200);
    const std::string maximum_camera(64, 'a');
    request.camera_id = maximum_camera;
    request.command = NativeControlCommand::view_camera;
    expect_status(gate.authorize(request), 200);
    require(backend.camera == maximum_camera, "maximum bounded camera ID must retain exact scope");
}

void configuration_expiry_revocation_and_races()
{
    PrivateTemporaryDirectory temporary;
    const auto database_path = temporary.path / "sessions.db";
    SessionStore sessions(database_path.string(), std::chrono::seconds(3600), false);
    require(!sessions.initialize(), "SessionStore initialization failed");
    auto token = create_bound(sessions, "expiry-user", "expiry-tests");
    require(token.has_value(), "SessionStore creation failed");
    Backend backend;
    NativeControlAuth gate(sessions, config(), std::ref(backend));
    auto request = request_for(*token);
    execute_sql(database_path, "UPDATE auth_sessions SET expires_at=0");
    expect_status(gate.authorize(request), 401);
    require(backend.calls == 0, "expired token must not reach backend");
    token = create_bound(sessions, "expiry-user", "revocation-tests");
    require(token.has_value(), "SessionStore recreation failed");
    request = request_for(*token);
    require(sessions.revoke(*token), "fixture token revocation failed");
    expect_status(gate.authorize(request), 401);
    require(backend.calls == 0, "revoked token must not reach backend");

    token = create_bound(sessions, "expiry-user", "in-flight-revocation-test");
    require(token.has_value(), "in-flight session fixture failed");
    request = request_for(*token);
    NativeControlAuth racing_gate(sessions, config(), [&](std::string_view, const SessionIdentity &,
                                                        std::string_view, std::string_view) {
        require(sessions.revoke(*token), "backend fixture revocation failed");
        return NativeAuthorizationDecision::allowed;
    });
    expect_status(racing_gate.authorize(request), 401);

    SessionStore disabled("", std::chrono::seconds(3600), false);
    NativeControlAuth disabled_gate(disabled, config(), std::ref(backend));
    require(!disabled_gate.configured(), "disabled SessionStore must fail configuration");
    expect_status(disabled_gate.authorize(request), 503);
    NativeControlAuth missing_backend(sessions, config(), {});
    require(!missing_backend.configured(), "missing backend must fail configuration");
    expect_status(missing_backend.authorize(request), 503);
    const std::string oversized_configuration(4096, 'a');
    for (const auto &invalid : std::vector<NativeControlAuthConfig>{
             {oversized_configuration, "127.0.0.1:18086"},
             {"http://127.0.0.1:18086", oversized_configuration},
             {oversized_configuration, oversized_configuration},
             {"", ""}, {"http://monitor.invalid:8080", "monitor.invalid:8080"},
             {"http://127.0.0.1:8080/", "127.0.0.1:8080"},
             {"http://localhost:8080", "127.0.0.1:8080"},
             {"http://127.0.0.1:0", "127.0.0.1:0"},
             {"http://127.0.0.1:08080", "127.0.0.1:08080"},
             {"file://127.0.0.1", "127.0.0.1"},
             {"http://127.0.0.1:8080@evil.invalid", "127.0.0.1:8080@evil.invalid"}}) {
        NativeControlAuth invalid_gate(sessions, invalid, std::ref(backend));
        require(!invalid_gate.configured(), "unsafe configuration must be rejected");
        expect_status(invalid_gate.authorize(request), 503);
    }
    for (const auto &valid : std::vector<NativeControlAuthConfig>{
             {"http://localhost", "localhost"}, {"http://127.0.0.1:65535", "127.0.0.1:65535"},
             {"https://[::1]:8443", "[::1]:8443"}, {"http://[::1]", "[::1]"}}) {
        const auto fresh = create_bound(sessions, "config-user", "origin-tests");
        require(fresh.has_value(), "configuration fixture token creation failed");
        NativeControlAuth configured_gate(sessions, valid, std::ref(backend));
        require(configured_gate.configured(), "valid canonical loopback origin must configure");
        auto matching = request_for(*fresh);
        matching.origin = valid.origin;
        matching.authority = valid.authority;
        expect_status(configured_gate.authorize(matching), 200);
    }
    require(NativeControlAuthorization{static_cast<NativeControlStatus>(999), {}}.code() ==
                "authorization_unavailable", "unknown status must have a fixed safe diagnostic");
}

} // namespace

int main()
{
    try {
        legacy_and_corrupt_binding_never_reach_backend();
        binding_revalidation_and_safe_diagnostics();
        stale_binding_cannot_revoke_replacement();
        freshness_scope_and_fail_closed();
        failed_revocation_is_unavailable();
        structural_rejection_precedes_session_and_backend();
        configuration_expiry_revocation_and_races();
        std::cout << "Native control authorization boundary: session/RBAC/scope/fail-closed tests passed\n";
        return 0;
    } catch (const std::exception &error) {
        // Test assertions have fixed messages; never print a session token.
        std::cerr << "Native control authorization boundary test failed: " << error.what() << '\n';
        return 1;
    }
}
