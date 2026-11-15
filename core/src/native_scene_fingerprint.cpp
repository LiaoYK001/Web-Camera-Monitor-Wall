#include "webobs/native_scene_fingerprint.hpp"
#include <openssl/evp.h>
#include <algorithm>
#include <array>

namespace webobs {
std::optional<std::string> native_scene_fingerprint(const SceneDocument &document, int fps)
{
    if (fps < 1 || fps > 120 || validate_scene_document(document).has_value() || document.sources.empty() ||
        std::any_of(document.sources.begin(), document.sources.end(), [](const auto &source) { return source.kind != "camera"; }))
        return std::nullopt;
    auto canonical = document;
    canonical.revision = 0;
    const auto encoded = serialize_scene_json(canonical, SceneJsonView::public_api, false);
    if (!encoded.ok()) return std::nullopt;
    const auto input = std::string("webobs-native-scene-v1\n") + std::to_string(fps) + "\n" + encoded.json;
    std::array<unsigned char, EVP_MAX_MD_SIZE> bytes{};
    unsigned int length = 0;
    if (EVP_Digest(input.data(), input.size(), bytes.data(), &length, EVP_sha256(), nullptr) != 1 || length != 32)
        return std::nullopt;
    constexpr char hex[] = "0123456789abcdef";
    std::string result;
    result.reserve(64);
    for (unsigned int i = 0; i < length; ++i) {
        result += hex[bytes[i] >> 4];
        result += hex[bytes[i] & 15];
    }
    return result;
}
}
