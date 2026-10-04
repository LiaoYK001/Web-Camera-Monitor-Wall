#include "webobs/platform_runtime.hpp"
#include "webobs/scene_store.hpp"
#include "webobs/studio_store.hpp"
#include "studio_identity_tests.hpp"
#include <filesystem>
#include <iostream>
#include <cstdlib>
#include <windows.h>
int main() {
    int identity_failures = 0;
    studio_identity_tests([&](bool condition, std::string_view message) {
        if (!condition) { std::cerr << "FAIL: " << message << '\n'; ++identity_failures; }
    });
    if (identity_failures != 0) return 11;
    const auto root = std::filesystem::temp_directory_path() / (L"webobs-场景-test-" + std::to_wstring(GetCurrentProcessId()));
    const auto path = root / L"场景.json";
    webobs::SceneDocument scene;
    if (const auto error = webobs::save_scene_file_atomic(path, scene)) { std::cerr << *error; return 1; }
    if (!webobs::load_scene_file(path).ok()) return 2;
    if (webobs::windows_private_write(path, "updated")) return 3;
    if (webobs::windows_private_read(path, 100).content != "updated") return 4;
    if (webobs::windows_private_read(path, 2).error.empty()) return 5;
    const auto link = root / L"hardlink.json";
    if (!CreateHardLinkW(link.c_str(), path.c_str(), nullptr)) return 6;
    if (webobs::windows_private_read(link, 100).error.empty()) return 7;
    if (!webobs::windows_private_write(link, "unsafe")) return 8;
    _putenv_s("WEBOBS_CAMERA_INTERNAL_PORT", "29092");
    if (webobs::runtime_http(8092, "/health") != "http://127.0.0.1:29092/health") return 9;
    if (webobs::command_quote("a\\\"b") != "\"a\\\\\\\"b\"") return 10;
    std::filesystem::remove(link); std::filesystem::remove(path); std::filesystem::remove(root);
    std::cout << "Windows private storage and runtime tests passed\n";
}
