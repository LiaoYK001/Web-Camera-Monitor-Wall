#pragma once

#include <initializer_list>
#include <string>
#include <string_view>
#include <utility>

namespace webobs {

using AuditField = std::pair<std::string_view, std::string_view>;

std::string format_audit_event(std::string_view event, std::string_view outcome,
                               std::initializer_list<AuditField> fields = {});

} // namespace webobs
