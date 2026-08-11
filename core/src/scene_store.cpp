#include "webobs/scene_store.hpp"

#include <jansson.h>

#include <array>
#include <atomic>
#include <cerrno>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <filesystem>
#include <limits>
#include <memory>
#include <string>
#include <string_view>
#include <system_error>
#include <utility>

#include <fcntl.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <unistd.h>

namespace webobs {
namespace {

struct JsonDeleter {
    void operator()(json_t *value) const { json_decref(value); }
};

using JsonPtr = std::unique_ptr<json_t, JsonDeleter>;

class FileDescriptor {
public:
    FileDescriptor() = default;
    explicit FileDescriptor(int descriptor) : descriptor_(descriptor) {}
    FileDescriptor(const FileDescriptor &) = delete;
    FileDescriptor &operator=(const FileDescriptor &) = delete;
    FileDescriptor(FileDescriptor &&other) noexcept : descriptor_(std::exchange(other.descriptor_, -1)) {}
    FileDescriptor &operator=(FileDescriptor &&other) noexcept
    {
        if (this != &other) {
            reset();
            descriptor_ = std::exchange(other.descriptor_, -1);
        }
        return *this;
    }
    ~FileDescriptor() { reset(); }

    [[nodiscard]] int get() const { return descriptor_; }
    [[nodiscard]] explicit operator bool() const { return descriptor_ >= 0; }

    bool close_checked()
    {
        if (descriptor_ < 0)
            return true;
        const int descriptor = std::exchange(descriptor_, -1);
        return close(descriptor) == 0;
    }

    void reset()
    {
        if (descriptor_ >= 0) {
            close(descriptor_);
            descriptor_ = -1;
        }
    }

private:
    int descriptor_ = -1;
};

struct PrivateDirectoryResult {
    FileDescriptor descriptor;
    std::string filename;
    bool missing = false;
    std::string error;

    [[nodiscard]] bool ok() const { return descriptor && error.empty(); }
};

SceneMigrationResult migration_failure(std::string message)
{
    SceneMigrationResult result;
    result.error = std::move(message);
    return result;
}

SceneFileLoadResult load_failure(std::string message)
{
    SceneFileLoadResult result;
    result.error = std::move(message);
    return result;
}

std::string system_failure(std::string_view operation, int error_number = errno)
{
    return std::string(operation) + " failed: " + std::strerror(error_number);
}

PrivateDirectoryResult open_private_directory(const std::filesystem::path &path, bool create)
{
    PrivateDirectoryResult result;
    if (!path.is_absolute() || path.filename().empty() || path.parent_path().empty()) {
        result.error = "scene file path must be absolute and include a filename";
        return result;
    }

    const std::filesystem::path parent = path.parent_path();
    if (create) {
        std::error_code error;
        std::filesystem::create_directories(parent, error);
        if (error) {
            result.error = "could not create the scene storage directory";
            return result;
        }
    }

    FileDescriptor directory(open(parent.c_str(), O_RDONLY | O_DIRECTORY | O_CLOEXEC | O_NOFOLLOW));
    if (!directory) {
        result.missing = errno == ENOENT;
        result.error = system_failure("opening the scene storage directory");
        return result;
    }

    struct stat metadata {};
    if (fstat(directory.get(), &metadata) != 0) {
        result.error = system_failure("inspecting the scene storage directory");
        return result;
    }
    if (!S_ISDIR(metadata.st_mode)) {
        result.error = "scene storage parent is not a directory";
        return result;
    }
    if (metadata.st_uid != geteuid()) {
        result.error = "scene storage directory must be owned by the current user";
        return result;
    }
    if (fchmod(directory.get(), S_IRWXU) != 0) {
        result.error = system_failure("restricting the scene storage directory");
        return result;
    }

    result.filename = path.filename().string();
    if (result.filename == "." || result.filename == "..") {
        result.error = "scene file path has an invalid filename";
        return result;
    }
    result.descriptor = std::move(directory);
    return result;
}

std::optional<std::string> validate_existing_target(int directory, const std::string &filename)
{
    struct stat metadata {};
    if (fstatat(directory, filename.c_str(), &metadata, AT_SYMLINK_NOFOLLOW) != 0) {
        if (errno == ENOENT)
            return std::nullopt;
        return system_failure("inspecting the existing scene file");
    }
    if (!S_ISREG(metadata.st_mode))
        return "existing scene path must be a regular file and not a symbolic link";
    if (metadata.st_uid != geteuid())
        return "existing scene file must be owned by the current user";
    if (metadata.st_nlink != 1)
        return "existing scene file must not have additional hard links";
    return std::nullopt;
}

bool write_all(int descriptor, std::string_view data)
{
    std::size_t written = 0;
    while (written < data.size()) {
        const ssize_t result = write(descriptor, data.data() + written, data.size() - written);
        if (result < 0) {
            if (errno == EINTR)
                continue;
            return false;
        }
        if (result == 0) {
            errno = EIO;
            return false;
        }
        written += static_cast<std::size_t>(result);
    }
    return true;
}

std::optional<std::string> read_limited(int descriptor, std::string &content)
{
    std::array<char, 16384> buffer{};
    while (true) {
        const ssize_t count = read(descriptor, buffer.data(), buffer.size());
        if (count < 0) {
            if (errno == EINTR)
                continue;
            return system_failure("reading the scene file");
        }
        if (count == 0)
            return std::nullopt;
        if (content.size() + static_cast<std::size_t>(count) > maximum_scene_json_bytes)
            return "scene file exceeds the one MiB limit";
        content.append(buffer.data(), static_cast<std::size_t>(count));
    }
}

std::string make_temporary_name(std::string_view filename, std::uint64_t sequence)
{
    return "." + std::string(filename) + ".tmp." + std::to_string(static_cast<long long>(getpid())) + "." +
           std::to_string(sequence);
}

} // namespace

SceneMigrationResult migrate_scene_json(std::string_view input)
{
    if (input.empty())
        return migration_failure("scene JSON must not be empty");
    if (input.size() > maximum_scene_json_bytes)
        return migration_failure("scene JSON exceeds the one MiB limit");

    json_error_t parse_error{};
    JsonPtr root(json_loadb(input.data(), input.size(), JSON_REJECT_DUPLICATES, &parse_error));
    if (!root)
        return migration_failure("invalid scene JSON at line " + std::to_string(parse_error.line) + " column " +
                                 std::to_string(parse_error.column));
    if (!json_is_object(root.get()))
        return migration_failure("scene JSON root must be an object");

    json_t *version_value = json_object_get(root.get(), "schemaVersion");
    if (!json_is_integer(version_value) || json_integer_value(version_value) < 0)
        return migration_failure("scene schemaVersion must be a non-negative integer");
    const json_int_t version = json_integer_value(version_value);
    if (version == current_scene_schema_version) {
        SceneParseResult parsed = parse_scene_json(input);
        if (!parsed.ok())
            return migration_failure(std::move(parsed.error));
        SceneMigrationResult result;
        result.document = std::move(parsed.document);
        return result;
    }
    if (version != 0)
        return migration_failure("scene schemaVersion is unsupported");
    if (json_object_get(root.get(), "revision") != nullptr)
        return migration_failure("schemaVersion 0 scene must not contain revision");

    json_t *current_version = json_integer(current_scene_schema_version);
    if (!current_version || json_object_set_new(root.get(), "schemaVersion", current_version) != 0)
        return migration_failure("could not migrate scene JSON");
    json_t *initial_revision = json_integer(0);
    if (!initial_revision || json_object_set_new(root.get(), "revision", initial_revision) != 0)
        return migration_failure("could not migrate scene JSON");

    char *encoded = json_dumps(root.get(), JSON_COMPACT | JSON_SORT_KEYS | JSON_REAL_PRECISION(6));
    if (!encoded)
        return migration_failure("could not encode migrated scene JSON");
    const std::string migrated_json(encoded);
    std::free(encoded);

    SceneParseResult parsed = parse_scene_json(migrated_json);
    if (!parsed.ok())
        return migration_failure(std::move(parsed.error));
    SceneMigrationResult result;
    result.document = std::move(parsed.document);
    result.migrated = true;
    return result;
}

std::optional<std::string> save_scene_file_atomic(const std::filesystem::path &path,
                                                  const SceneDocument &document)
{
    const SceneSerializeResult serialized =
        serialize_scene_json(document, SceneJsonView::persistence, true);
    if (!serialized.ok())
        return serialized.error;
    if (serialized.json.size() > maximum_scene_json_bytes)
        return "encoded scene JSON exceeds the one MiB limit";

    PrivateDirectoryResult directory = open_private_directory(path, true);
    if (!directory.ok())
        return directory.error;
    if (const auto target_error = validate_existing_target(directory.descriptor.get(), directory.filename))
        return target_error;

    static std::atomic_uint64_t temporary_sequence = 0;
    std::string temporary_name;
    FileDescriptor temporary;
    for (int attempt = 0; attempt < 100; ++attempt) {
        temporary_name = make_temporary_name(directory.filename, temporary_sequence.fetch_add(1));
        temporary = FileDescriptor(openat(directory.descriptor.get(), temporary_name.c_str(),
                                          O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC | O_NOFOLLOW,
                                          S_IRUSR | S_IWUSR));
        if (temporary)
            break;
        if (errno != EEXIST)
            return system_failure("creating a temporary scene file");
    }
    if (!temporary)
        return "could not allocate a unique temporary scene file";

    bool renamed = false;
    const auto cleanup = [&] {
        temporary.reset();
        if (!renamed)
            unlinkat(directory.descriptor.get(), temporary_name.c_str(), 0);
    };

    if (fchmod(temporary.get(), S_IRUSR | S_IWUSR) != 0) {
        const std::string error = system_failure("restricting the temporary scene file");
        cleanup();
        return error;
    }
    if (!write_all(temporary.get(), serialized.json)) {
        const std::string error = system_failure("writing the temporary scene file");
        cleanup();
        return error;
    }
    if (fsync(temporary.get()) != 0) {
        const std::string error = system_failure("synchronizing the temporary scene file");
        cleanup();
        return error;
    }
    if (!temporary.close_checked()) {
        const std::string error = system_failure("closing the temporary scene file");
        cleanup();
        return error;
    }
    if (renameat(directory.descriptor.get(), temporary_name.c_str(), directory.descriptor.get(),
                 directory.filename.c_str()) != 0) {
        const std::string error = system_failure("committing the scene file");
        cleanup();
        return error;
    }
    renamed = true;
    if (fsync(directory.descriptor.get()) != 0)
        return system_failure("synchronizing the scene storage directory");
    return std::nullopt;
}

SceneFileLoadResult load_scene_file(const std::filesystem::path &path)
{
    PrivateDirectoryResult directory = open_private_directory(path, false);
    if (!directory.ok()) {
        if (directory.missing) {
            SceneFileLoadResult result;
            result.status = SceneFileStatus::not_found;
            return result;
        }
        return load_failure(std::move(directory.error));
    }

    FileDescriptor file(openat(directory.descriptor.get(), directory.filename.c_str(),
                               O_RDONLY | O_CLOEXEC | O_NOFOLLOW));
    if (!file) {
        if (errno == ENOENT) {
            SceneFileLoadResult result;
            result.status = SceneFileStatus::not_found;
            return result;
        }
        return load_failure(system_failure("opening the scene file"));
    }

    struct stat metadata {};
    if (fstat(file.get(), &metadata) != 0)
        return load_failure(system_failure("inspecting the scene file"));
    if (!S_ISREG(metadata.st_mode))
        return load_failure("scene path must be a regular file and not a symbolic link");
    if (metadata.st_uid != geteuid())
        return load_failure("scene file must be owned by the current user");
    if (metadata.st_nlink != 1)
        return load_failure("scene file must not have additional hard links");
    if (metadata.st_size < 0 || static_cast<std::uintmax_t>(metadata.st_size) > maximum_scene_json_bytes)
        return load_failure("scene file exceeds the one MiB limit");
    if (fchmod(file.get(), S_IRUSR | S_IWUSR) != 0)
        return load_failure(system_failure("restricting the scene file"));

    std::string content;
    content.reserve(static_cast<std::size_t>(metadata.st_size));
    if (const auto read_error = read_limited(file.get(), content))
        return load_failure(*read_error);
    file.reset();

    SceneMigrationResult migrated = migrate_scene_json(content);
    if (!migrated.ok())
        return load_failure(std::move(migrated.error));
    if (migrated.migrated) {
        if (const auto save_error = save_scene_file_atomic(path, *migrated.document))
            return load_failure("scene migration could not be committed: " + *save_error);
    }

    SceneFileLoadResult result;
    result.status = migrated.migrated ? SceneFileStatus::migrated : SceneFileStatus::loaded;
    result.document = std::move(migrated.document);
    return result;
}

} // namespace webobs
