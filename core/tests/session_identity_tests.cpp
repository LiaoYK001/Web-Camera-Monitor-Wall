#include "webobs/authentication.hpp"

#include <openssl/evp.h>
#include <sqlite3.h>

#include <array>
#include <chrono>
#include <ctime>
#include <filesystem>
#include <iostream>
#include <random>
#include <stdexcept>
#include <string>
#include <string_view>
#include <vector>

namespace {

using webobs::SessionIdentity;
using webobs::SessionStore;
using namespace std::chrono_literals;

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
            const auto candidate = root / ("webobs-session-identity-" + std::to_string(random()) +
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
        const auto root = std::filesystem::absolute(std::filesystem::temp_directory_path()).lexically_normal();
        // Only remove the exact private directory this instance successfully created.
        if (!path.empty() && path.parent_path() == root &&
            path.filename().string().find("webobs-session-identity-") == 0) {
            std::error_code ignored;
            std::filesystem::remove_all(path, ignored);
        }
    }

    std::filesystem::path path;
};

class Database {
public:
    explicit Database(const std::filesystem::path &path)
    {
        if (sqlite3_open(path.string().c_str(), &database_) != SQLITE_OK) {
            sqlite3_close(database_);
            throw std::runtime_error("could not open temporary SQLite fixture");
        }
    }
    ~Database() { sqlite3_close(database_); }
    Database(const Database &) = delete;
    Database &operator=(const Database &) = delete;

    void execute(std::string_view sql)
    {
        require(sqlite3_exec(database_, std::string(sql).c_str(), nullptr, nullptr, nullptr) == SQLITE_OK,
                "could not execute fixture SQL");
    }

    std::int64_t integer(std::string_view sql)
    {
        sqlite3_stmt *statement = nullptr;
        require(sqlite3_prepare_v2(database_, std::string(sql).c_str(), -1, &statement, nullptr) == SQLITE_OK,
                "could not prepare fixture query");
        const bool found = sqlite3_step(statement) == SQLITE_ROW;
        const auto value = found ? sqlite3_column_int64(statement, 0) : 0;
        sqlite3_finalize(statement);
        require(found, "fixture query did not return a row");
        return value;
    }

    void set_binding(std::string_view user_id, bool null_user, std::string_view epoch, bool null_epoch,
                     bool blob = false)
    {
        sqlite3_stmt *statement = nullptr;
        require(sqlite3_prepare_v2(database_, "UPDATE auth_sessions SET user_id=?,auth_epoch=?", -1,
                                   &statement, nullptr) == SQLITE_OK, "could not prepare binding mutation");
        const auto bind = [&](int index, std::string_view value, bool null_value) {
            return null_value ? sqlite3_bind_null(statement, index) :
                   blob ? sqlite3_bind_blob(statement, index, value.data(), static_cast<int>(value.size()), SQLITE_TRANSIENT) :
                          sqlite3_bind_text(statement, index, value.data(), static_cast<int>(value.size()), SQLITE_TRANSIENT);
        };
        const bool changed = bind(1, user_id, null_user) == SQLITE_OK &&
                             bind(2, epoch, null_epoch) == SQLITE_OK &&
                             sqlite3_step(statement) == SQLITE_DONE;
        sqlite3_finalize(statement);
        require(changed, "could not mutate stored binding");
    }

private:
    sqlite3 *database_ = nullptr;
};

constexpr std::string_view old_schema =
    "CREATE TABLE auth_sessions(session_id_hash TEXT PRIMARY KEY,user_name TEXT NOT NULL,"
    "created_at INTEGER NOT NULL,last_seen INTEGER NOT NULL,expires_at INTEGER NOT NULL,"
    "client_metadata TEXT NOT NULL)";

const SessionIdentity identity{"0123456789abcdef0123456789abcdef", "fedcba9876543210fedcba9876543210"};

std::string hash_token(std::string_view token)
{
    std::array<unsigned char, EVP_MAX_MD_SIZE> digest{};
    unsigned int size = 0;
    require(EVP_Digest(token.data(), token.size(), digest.data(), &size, EVP_sha256(), nullptr) == 1,
            "could not hash fixture token");
    constexpr char hexadecimal[] = "0123456789abcdef";
    std::string hash;
    for (unsigned int index = 0; index < size; ++index) {
        hash += hexadecimal[digest[index] >> 4];
        hash += hexadecimal[digest[index] & 15];
    }
    return hash;
}

void expect_identity(SessionStore &store, const std::string &token, const SessionIdentity &expected)
{
    const auto record = store.validate_and_slide(token);
    require(record && record->identity, "bound session did not validate with identity");
    require(record->user == "operator-user", "bound principal changed");
    require(record->identity->user_id == expected.user_id && record->identity->auth_epoch == expected.auth_epoch,
            "identity must round-trip exactly, without swapping or derivation");
}

void expect_legacy(SessionStore &store, const std::string &token)
{
    const auto record = store.validate_and_slide(token);
    require(record && !record->identity, "legacy session was rejected or automatically bound");
}

void legacy_schema_upgrade()
{
    PrivateTemporaryDirectory temporary;
    const auto path = temporary.path / "legacy.db";
    const std::string token(64, 'a');
    const auto expiry = static_cast<std::int64_t>(std::time(nullptr)) + 7200;
    {
        Database database(path);
        database.execute(old_schema);
        database.execute("INSERT INTO auth_sessions VALUES('" + hash_token(token) +
                         "','legacy-user',11,22," + std::to_string(expiry) + ",'legacy-client')");
    }
    for (int restart = 0; restart < 2; ++restart) {
        SessionStore store(path.string(), 3600s, false);
        require(!store.initialize() && !store.initialize(), "legacy migration must be idempotent");
        const auto record = store.validate_and_slide(token);
        require(record && record->user == "legacy-user" && record->created_at == 11 && !record->identity,
                "migration must preserve legacy rows without binding them");
        const auto bound = store.create_bound("legacy-user", "new login", identity);
        require(bound.has_value(), "bound login after legacy upgrade failed");
        expect_legacy(store, token);
        Database database(path);
        require(database.integer("SELECT count(*) FROM pragma_table_info('auth_sessions') "
                                 "WHERE name IN ('user_id','auth_epoch') AND type='TEXT' AND \"notnull\"=0") == 2,
                "migration must add nullable TEXT identity columns");
        require(database.integer("SELECT count(*) FROM auth_sessions WHERE user_name='legacy-user' "
                                 "AND user_id IS NULL AND auth_epoch IS NULL") == 1,
                "old session must retain two actual SQL NULLs");
    }
}

void partial_schema_upgrade()
{
    for (const auto column : {"user_id", "auth_epoch"}) {
        PrivateTemporaryDirectory temporary;
        const auto path = temporary.path / "partial.db";
        {
            Database database(path);
            database.execute(old_schema);
            database.execute(std::string("ALTER TABLE auth_sessions ADD COLUMN ") + column + " TEXT");
            const auto expiry = static_cast<std::int64_t>(std::time(nullptr)) + 7200;
            database.execute("INSERT INTO auth_sessions(session_id_hash,user_name,created_at,last_seen,expires_at,client_metadata) "
                             "VALUES('" + hash_token(std::string(64, 'a')) + "','partial-legacy',11,22," +
                             std::to_string(expiry) + ",'old-client')");
            database.execute(std::string("INSERT INTO auth_sessions(session_id_hash,user_name,created_at,last_seen,expires_at,client_metadata,") +
                             column + ") VALUES('" + hash_token(std::string(64, 'b')) + "','partial-binding',11,22," +
                             std::to_string(expiry) + ",'old-client','" + identity.user_id + "')");
        }
        SessionStore store(path.string(), 3600s, false);
        require(!store.initialize(), "partial identity schema migration failed");
        expect_legacy(store, std::string(64, 'a'));
        require(!store.validate_and_slide(std::string(64, 'b')),
                "migration must not erase or downgrade a pre-existing partial binding");
        const auto legacy = store.create("operator-user", "metadata is not an identity");
        const auto bound = store.create_bound("operator-user", "metadata", identity);
        require(legacy && bound, "partial migration must support both session types");
        expect_legacy(store, *legacy);
        expect_identity(store, *bound, identity);
        SessionStore reopened(path.string(), 3600s, false);
        require(!reopened.initialize(), "partial migration must remain idempotent on reopen");
        expect_identity(reopened, *bound, identity);
    }
}

void persistent_bound_and_legacy_sessions()
{
    PrivateTemporaryDirectory temporary;
    const auto path = temporary.path / "persistent.db";
    std::string bound;
    std::string legacy;
    const std::string metadata = "{\"user_id\":\"" + identity.user_id + "\",\"auth_epoch\":\"" +
                                 identity.auth_epoch + "\"}";
    {
        SessionStore store(path.string(), 3600s, true);
        require(!store.initialize(), "new store initialization failed");
        const auto created = store.create_bound("operator-user", "deliberately different metadata", identity);
        const auto unbound = store.create("operator-user", metadata);
        require(created && unbound && created->size() == 64 && *created != *unbound,
                "both session kinds must receive independent existing-format tokens");
        bound = *created;
        legacy = *unbound;
        expect_identity(store, bound, identity);
        expect_legacy(store, legacy);
        require(store.set_cookie_header(bound) == "webobs_session=" + bound +
                "; Path=/; HttpOnly; SameSite=Strict; Max-Age=3600; Secure", "cookie protocol changed");
        require(store.clear_cookie_header() ==
                "webobs_session=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0; Secure", "clear cookie changed");
        Database database(path);
        require(database.integer("SELECT count(*) FROM auth_sessions WHERE session_id_hash='" + hash_token(bound) +
                                 "' OR session_id_hash='" + hash_token(legacy) + "'") == 2,
                "both token types must use the existing hashed auth_sessions storage");
        require(database.integer("SELECT count(*) FROM auth_sessions WHERE session_id_hash='" + bound +
                                 "' OR session_id_hash='" + legacy + "'") == 0, "raw tokens were persisted");
    }
    SessionStore restarted(path.string(), 3600s, false);
    require(!restarted.initialize(), "session restart failed");
    expect_identity(restarted, bound, identity);
    expect_legacy(restarted, legacy);
    require(restarted.revoke(bound) && !restarted.validate_and_slide(bound), "bound token revoke failed");
    require(restarted.revoke(legacy) && !restarted.validate_and_slide(legacy), "legacy token revoke changed");
}

void invalid_identity_inputs()
{
    PrivateTemporaryDirectory temporary;
    const auto path = temporary.path / "invalid.db";
    SessionStore store(path.string(), 3600s, false);
    require(!store.initialize(), "invalid-input store initialization failed");
    std::vector<std::string> invalid{"", std::string(31, 'a'), std::string(33, 'a'),
                                     std::string(32, 'A'), std::string(32, 'g'), std::string(32, ' ')};
    auto embedded_nul = identity.user_id;
    embedded_nul[15] = '\0';
    invalid.push_back(embedded_nul);
    invalid.push_back(identity.user_id + std::string(1, '\0'));
    for (const auto &value : invalid) {
        require(!store.create_bound("operator-user", "metadata", {value, identity.auth_epoch}),
                "invalid user_id must not create a bound session");
        require(!store.create_bound("operator-user", "metadata", {identity.user_id, value}),
                "invalid auth_epoch must not create a bound session");
        require(store.revoke_identity("operator-user", {value, identity.auth_epoch}) == 0 &&
                store.revoke_identity("operator-user", {identity.user_id, value}) == 0,
                "invalid identity must not revoke sessions");
    }
    require(!store.create_bound("", "metadata", identity) &&
            !store.create_bound(std::string(65, 'a'), "metadata", identity), "invalid username was accepted");
    Database database(path);
    require(database.integer("SELECT count(*) FROM auth_sessions") == 0, "invalid identities persisted rows");
}

void damaged_binding_is_not_legacy()
{
    PrivateTemporaryDirectory temporary;
    const auto path = temporary.path / "corrupt.db";
    SessionStore store(path.string(), 3600s, false);
    require(!store.initialize(), "corrupt-binding store initialization failed");
    const auto token = store.create_bound("operator-user", "metadata", identity);
    require(token.has_value(), "corrupt-binding fixture creation failed");
    Database database(path);
    const auto sentinel = static_cast<std::int64_t>(std::time(nullptr)) + 7200;
    const auto rejected = [&] {
        database.execute("UPDATE auth_sessions SET last_seen=123,expires_at=" + std::to_string(sentinel));
        require(!store.validate_and_slide(*token), "damaged binding was accepted or downgraded to legacy");
        require(database.integer("SELECT last_seen FROM auth_sessions") == 123 &&
                database.integer("SELECT expires_at FROM auth_sessions") == sentinel,
                "rejected binding must not slide the session");
    };
    database.set_binding({}, true, identity.auth_epoch, false);
    rejected();
    database.set_binding(identity.user_id, false, {}, true);
    rejected();
    for (const auto &bad : std::vector<std::string>{"", std::string(31, 'a'), std::string(33, 'a'),
                                                   std::string(32, 'A'), std::string(32, 'z')}) {
        database.set_binding(bad, false, identity.auth_epoch, false);
        rejected();
        database.set_binding(identity.user_id, false, bad, false);
        rejected();
    }
    auto nul = identity.user_id;
    nul[16] = '\0';
    database.set_binding(nul, false, identity.auth_epoch, false);
    rejected();
    database.set_binding(identity.user_id, false, nul, false);
    rejected();
    database.set_binding(identity.user_id + std::string(1, '\0'), false, identity.auth_epoch, false);
    rejected();
    database.set_binding(identity.user_id, false, identity.auth_epoch, false, true);
    rejected();
    database.set_binding({}, true, {}, true);
    const auto legacy = store.validate_and_slide(*token);
    require(legacy && !legacy->identity, "only two SQL NULLs must represent legacy");
}

void migration_failure_rolls_back_and_closes()
{
    for (bool prepare_failure : {false, true}) {
        PrivateTemporaryDirectory temporary;
        const auto path = temporary.path / "migration-failure.db";
        {
            Database database(path);
            if (prepare_failure) {
                database.execute("CREATE TABLE auth_sessions(session_id_hash TEXT PRIMARY KEY,user_name TEXT NOT NULL,"
                                 "created_at INTEGER NOT NULL,last_seen INTEGER NOT NULL,expires_at INTEGER NOT NULL)");
            } else {
                database.execute(old_schema);
                database.execute("CREATE TABLE auth_sessions_expiry(value TEXT)");
            }
        }
        SessionStore store(path.string(), 3600s, false);
        require(store.initialize().has_value(), "malformed schema migration unexpectedly succeeded");
        require(!store.create("operator-user", "metadata") &&
                !store.create_bound("operator-user", "metadata", identity) &&
                !store.validate_and_slide(std::string(64, 'a')) &&
                !store.revoke(std::string(64, 'a')) && store.revoke_user("operator-user") == 0 &&
                store.revoke_identity("operator-user", identity) == 0, "failed migration left an open store");
        Database database(path);
        require(database.integer("SELECT count(*) FROM pragma_table_info('auth_sessions') "
                                 "WHERE name IN ('user_id','auth_epoch')") == 0,
                "failed SQL/prepare must roll back both identity columns");
        if (prepare_failure)
            database.execute("ALTER TABLE auth_sessions ADD COLUMN client_metadata TEXT NOT NULL DEFAULT ''");
        else
            database.execute("DROP TABLE auth_sessions_expiry");
        require(!store.initialize(), "store must recover after schema repair");
        const auto token = store.create_bound("operator-user", "metadata", identity);
        require(token.has_value(), "repaired schema could not create a session");
        expect_identity(store, *token, identity);
    }
}

void sql_failures_are_closed()
{
    PrivateTemporaryDirectory temporary;
    const auto path = temporary.path / "sql-failure.db";
    SessionStore store(path.string(), 3600s, false);
    require(!store.initialize(), "SQL-failure store initialization failed");
    Database database(path);
    database.execute("CREATE TRIGGER reject_insert BEFORE INSERT ON auth_sessions "
                     "BEGIN SELECT RAISE(ABORT,'synthetic insert rejection'); END");
    require(!store.create("operator-user", "metadata") &&
            !store.create_bound("operator-user", "metadata", identity), "SQL insert errors must not return a token");
    database.execute("DROP TRIGGER reject_insert");
    const auto token = store.create_bound("operator-user", "metadata", identity);
    require(token.has_value(), "SQL failure fixture creation failed");
    database.execute("UPDATE auth_sessions SET last_seen=123");
    database.execute("CREATE TRIGGER reject_update BEFORE UPDATE ON auth_sessions "
                     "BEGIN SELECT RAISE(ABORT,'synthetic update rejection'); END");
    require(!store.validate_and_slide(*token), "failed SQL slide must not authorize a session");
    require(database.integer("SELECT last_seen FROM auth_sessions") == 123, "failed slide mutated its row");
    database.execute("DROP TRIGGER reject_update");
    expect_identity(store, *token, identity);
    database.execute("CREATE TRIGGER reject_delete BEFORE DELETE ON auth_sessions "
                     "BEGIN SELECT RAISE(ABORT,'synthetic delete rejection'); END");
    require(!store.revoke(*token) && store.revoke_user("operator-user") == 0 &&
            store.revoke_identity("operator-user", identity) == 0, "SQL delete errors must not report success");
    database.execute("DROP TRIGGER reject_delete");
    database.execute("DROP TABLE auth_sessions");
    require(!store.create("operator-user", "metadata") &&
            !store.create_bound("operator-user", "metadata", identity) &&
            !store.validate_and_slide(*token) && !store.revoke(*token) &&
            store.revoke_user("operator-user") == 0 && store.revoke_identity("operator-user", identity) == 0,
            "runtime SQL prepare errors must fail closed");
}

void identity_revocation_is_isolated()
{
    PrivateTemporaryDirectory temporary;
    SessionStore store((temporary.path / "revoke.db").string(), 3600s, false);
    require(!store.initialize(), "revocation store initialization failed");
    const SessionIdentity new_epoch{identity.user_id, std::string(32, 'a')};
    const SessionIdentity recreated{std::string(32, 'b'), identity.auth_epoch};
    const auto old_one = store.create_bound("operator-user", "old one", identity);
    const auto old_two = store.create_bound("operator-user", "old two", identity);
    const auto epoch = store.create_bound("operator-user", "new epoch", new_epoch);
    const auto other_id = store.create_bound("operator-user", "recreated account", recreated);
    const auto other_user = store.create_bound("other-user", "same identifiers", identity);
    const auto legacy = store.create("operator-user", "legacy");
    require(old_one && old_two && epoch && other_id && other_user && legacy, "revocation fixture creation failed");
    require(store.revoke_identity("operator-user", identity) == 2, "precise revoke must remove all matching sessions");
    require(!store.validate_and_slide(*old_one) && !store.validate_and_slide(*old_two), "old binding survived revoke");
    expect_identity(store, *epoch, new_epoch);
    expect_identity(store, *other_id, recreated);
    require(store.validate_and_slide(*other_user).has_value(), "identity revoke crossed username boundary");
    expect_legacy(store, *legacy);
    require(store.revoke_identity("operator-user", identity) == 0, "no-match identity revoke must return zero");
    require(store.revoke_user("operator-user") == 3, "legacy revoke_user must retain username-wide behavior");
    require(!store.validate_and_slide(*epoch) && !store.validate_and_slide(*other_id) &&
            !store.validate_and_slide(*legacy) && store.validate_and_slide(*other_user),
            "legacy username revoke isolation changed");
}

} // namespace

int main()
{
    try {
        legacy_schema_upgrade();
        partial_schema_upgrade();
        persistent_bound_and_legacy_sessions();
        invalid_identity_inputs();
        damaged_binding_is_not_legacy();
        migration_failure_rolls_back_and_closes();
        sql_failures_are_closed();
        identity_revocation_is_isolated();
        std::cout << "session identity tests passed\n";
        return 0;
    } catch (const std::exception &error) {
        std::cerr << "session identity tests failed: " << error.what() << '\n';
        return 1;
    }
}
