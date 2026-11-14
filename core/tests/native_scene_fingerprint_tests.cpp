#include "webobs/native_scene_fingerprint.hpp"
#include <algorithm>
#include <iostream>
#include <stdexcept>

void require(bool value, const char *message) { if (!value) throw std::runtime_error(message); }
int main()
{
    using namespace webobs;
    try {
        SceneDocument scene;
        SceneSource camera;
        camera.id = "camera-source"; camera.name = "Camera"; camera.kind = "camera";
        camera.camera_id = "camera-a"; camera.profile_id = "main";
        scene.sources.push_back(camera);
        SceneItem item; item.id = "camera-item"; item.source_id = camera.id;
        scene.items.push_back(item);
        const auto initial = native_scene_fingerprint(scene, 30);
        require(initial && initial->size() == 64 && std::all_of(initial->begin(), initial->end(), [](char c) {
            return (c >= '0' && c <= '9') || (c >= 'a' && c <= 'f');
        }), "fingerprint missing or malformed");
        const auto require_change = [&](const SceneDocument &candidate, int fps, const char *message) {
            const auto actual = native_scene_fingerprint(candidate, fps);
            require(actual && actual != initial, message);
        };
        auto changed = scene; changed.revision = 89;
        require(native_scene_fingerprint(changed, 30) == initial, "global revision changed scene fingerprint");
        require_change(scene, 60, "fps was not bound");
        changed.items[0].crop.left = 1;
        require_change(changed, 30, "crop was not bound");
        changed = scene; changed.sources[0].profile_id = "sub";
        require_change(changed, 30, "Profile identity was not bound");
        changed = scene; changed.sources[0].audio_inputs_explicit = true;
        require_change(changed, 30, "explicit empty audio policy was not bound");
        changed = scene; changed.items[0].visible = false;
        require_change(changed, 30, "visibility was not bound");
        changed = scene; changed.sources[0].kind = "rtsp"; changed.sources[0].rtsp_url = "rtsp://fixture.invalid/private";
        require(!native_scene_fingerprint(changed, 30), "unbound network source was accepted");
        changed = scene; changed.items[0].source_id = "missing";
        require(!native_scene_fingerprint(changed, 30), "invalid document was accepted");
        require(!native_scene_fingerprint(scene, 0) && !native_scene_fingerprint(scene, 121), "invalid fps was accepted");
        std::cout << "Canonical scene-content preconditions passed; no media or authorization is claimed.\n";
        return 0;
    } catch (const std::exception &error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
