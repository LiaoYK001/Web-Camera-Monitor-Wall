#include "webobs/audit_event.hpp"

#include "webobs/redaction.hpp"

#include <jansson.h>

#include <algorithm>
#include <cctype>
#include <cstdlib>
#include <memory>

namespace webobs {
namespace {

struct JsonDeleter {
    void operator()(json_t *value) const { json_decref(value); }
};

bool valid_field_name(std::string_view name)
{
    return !name.empty() && name.size() <= 32 &&
           std::all_of(name.begin(), name.end(), [](unsigned char character) {
               return std::islower(character) || std::isdigit(character) || character == '_';
           });
}

std::string safe_value(std::string_view value)
{
    constexpr std::size_t maximum_field_bytes = 256;
    std::string redacted = redact_url_secrets(value);
    if (redacted.size() > maximum_field_bytes) {
        redacted.resize(maximum_field_bytes);
        redacted += "...";
    }
    return redacted;
}

} // namespace

std::string format_audit_event(std::string_view event, std::string_view outcome,
                               std::initializer_list<AuditField> fields)
{
    std::unique_ptr<json_t, JsonDeleter> root(json_object());
    if (!root)
        return R"({"component":"webobsd","type":"audit","event":"format_error"})";
    json_object_set_new(root.get(), "component", json_string("webobsd"));
    json_object_set_new(root.get(), "type", json_string("audit"));
    const std::string safe_event = safe_value(event);
    const std::string safe_outcome = safe_value(outcome);
    json_object_set_new(root.get(), "event", json_stringn(safe_event.data(), safe_event.size()));
    json_object_set_new(root.get(), "outcome", json_stringn(safe_outcome.data(), safe_outcome.size()));
    for (const auto &[name, value] : fields) {
        if (!valid_field_name(name))
            continue;
        const std::string safe = safe_value(value);
        json_object_set_new(root.get(), std::string(name).c_str(), json_stringn(safe.data(), safe.size()));
    }
    char *serialized = json_dumps(root.get(), JSON_COMPACT | JSON_ENSURE_ASCII | JSON_SORT_KEYS);
    if (!serialized)
        return R"({"component":"webobsd","type":"audit","event":"format_error"})";
    std::string result(serialized);
    free(serialized);
    return result;
}

} // namespace webobs
