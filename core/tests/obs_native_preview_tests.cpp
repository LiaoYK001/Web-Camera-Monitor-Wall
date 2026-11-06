// Opt-in real-libobs regression. This test alone performs bounded GPU readback;
// production native preview never downloads pixels. It does not exercise HWND,
// D3D11 Present, DWM, real media decoders, or installed Windows hardware.
#include "webobs/obs_scene_runtime.hpp"

#include <obs.h>
#ifndef _WIN32
#include <obs-nix-platform.h>
#endif
#include <graphics/vec4.h>

#include <array>
#include <chrono>
#include <cstdint>
#include <cstdlib>
#include <iostream>
#include <string>
#include <thread>

namespace {
constexpr std::uint32_t width = 320, height = 180;

// A private fixture with the product color source's ID, not a plugin substitute
// in production. It lets this regression use actual libobs without plugin loads.
struct Color {
    std::uint32_t width, height;
    vec4 rgba;
};
const char *color_name(void *) { return "Native preview regression color"; }
void *color_create(obs_data_t *settings, obs_source_t *)
{
    auto *color = new Color{};
    color->width = static_cast<std::uint32_t>(obs_data_get_int(settings, "width"));
    color->height = static_cast<std::uint32_t>(obs_data_get_int(settings, "height"));
    vec4_from_rgba(&color->rgba, static_cast<std::uint32_t>(obs_data_get_int(settings, "color")));
    return color;
}
void color_destroy(void *data) { delete static_cast<Color *>(data); }
std::uint32_t color_width(void *data) { return static_cast<Color *>(data)->width; }
std::uint32_t color_height(void *data) { return static_cast<Color *>(data)->height; }
void color_render(void *data, gs_effect_t *)
{
    auto &color = *static_cast<Color *>(data);
    gs_effect_t *effect = obs_get_base_effect(OBS_EFFECT_SOLID);
    gs_effect_set_vec4(gs_effect_get_param_by_name(effect, "color"), &color.rgba);
    while (gs_effect_loop(effect, "Solid")) gs_draw_sprite(nullptr, 0, color.width, color.height);
}

struct Pixels {
    bool ready = false;
    // BGRA: one point inside the item and one safely outside it.
    std::array<std::uint8_t, 4> inside{}, outside{};
};
void read_program(void *data)
{
    auto &pixels = *static_cast<Pixels *>(data);
    if (!obs_get_main_texture()) return;
    obs_enter_graphics();
    gs_texrender_t *render = gs_texrender_create(GS_BGRA, GS_ZS_NONE);
    gs_stagesurf_t *stage = gs_stagesurface_create(width, height, GS_BGRA);
    if (render && stage && gs_texrender_begin(render, width, height)) {
        vec4 clear{};
        gs_clear(GS_CLEAR_COLOR, &clear, 0.f, 0);
        gs_viewport_push();
        gs_projection_push();
        gs_set_viewport(0, 0, width, height);
        gs_ortho(0.f, float(width), 0.f, float(height), -100.f, 100.f);
        obs_render_main_texture(); // Same legal Program-texture API as the HWND.
        gs_projection_pop();
        gs_viewport_pop();
        gs_texrender_end(render);
        gs_stage_texture(stage, gs_texrender_get_texture(render));
        std::uint8_t *mapped = nullptr;
        std::uint32_t stride = 0;
        if (gs_stagesurface_map(stage, &mapped, &stride)) {
            for (std::size_t channel = 0; channel < 4; ++channel) {
                pixels.inside[channel] = mapped[70 * stride + 100 * 4 + channel];
                pixels.outside[channel] = mapped[150 * stride + 280 * 4 + channel];
            }
            pixels.ready = true;
            gs_stagesurface_unmap(stage);
        }
    }
    gs_stagesurface_destroy(stage);
    gs_texrender_destroy(render);
    obs_leave_graphics();
}

bool matches(const Pixels &pixels, int primary)
{
    if (!pixels.ready) return false;
    for (int channel = 0; channel < 3; ++channel) {
        const int target = channel == primary ? 255 : 0;
        if (std::abs(int(pixels.inside[static_cast<std::size_t>(channel)]) - target) > 8 ||
            pixels.outside[static_cast<std::size_t>(channel)] > 8) return false;
    }
    return true;
}

bool expect_pixels(int primary, const char *label)
{
    Pixels pixels;
    // At most 20 readbacks per transition, test process only; no encoder output.
    for (int attempt = 0; attempt < 20; ++attempt) {
        pixels = {};
        obs_queue_task(OBS_TASK_GRAPHICS, read_program, &pixels, true);
        if (matches(pixels, primary)) return true;
        std::this_thread::sleep_for(std::chrono::milliseconds(50));
    }
    std::cerr << "FAIL " << label << ": ready=" << pixels.ready << " inside BGR="
              << int(pixels.inside[0]) << ',' << int(pixels.inside[1]) << ',' << int(pixels.inside[2])
              << " outside BGR=" << int(pixels.outside[0]) << ',' << int(pixels.outside[1]) << ','
              << int(pixels.outside[2]) << '\n';
    return false;
}

webobs::SceneDocument document(const char *color)
{
    webobs::SceneDocument scene;
    scene.canvas.width = int(width);
    scene.canvas.height = int(height);
    webobs::SceneSource source;
    source.id = "known-color";
    source.name = "Known test color";
    source.kind = "color";
    source.color = color;
    scene.sources.push_back(source);
    webobs::SceneItem item;
    item.id = "placed-color";
    item.source_id = source.id;
    item.x = 40;
    item.y = 30;
    item.width = 120;
    item.height = 80;
    item.scale_mode = "stretch";
    scene.items.push_back(item);
    return scene;
}

bool exercise_runtime()
{
    webobs::ObsSceneRuntime runtime(1, {}, 10, 1, 2, false);
    auto red = document("#ff0000");
    if (const auto error = runtime.prepare(red)) {
        std::cerr << "FAIL prepare red: " << *error << '\n';
        return false;
    }
    runtime.commit_prepared();
    obs_source_t *output = obs_get_output_source(0);
    if (output) { obs_source_release(output); std::cerr << "FAIL inactive scene bound\n"; return false; }
    runtime.activate();
    output = obs_get_output_source(0);
    const bool active = output && obs_scene_from_source(output) && obs_source_active(output) && obs_source_showing(output);
    if (output) obs_source_release(output);
    if (!active || obs_video_active() || !expect_pixels(2, "activated red main texture without encoder")) return false;

    auto green = document("#00ff00");
    if (const auto error = runtime.prepare(green)) {
        std::cerr << "FAIL prepare green: " << *error << '\n';
        return false;
    }
    if (!expect_pixels(2, "prepare must preserve red Program")) return false;
    runtime.commit_prepared();
    if (!expect_pixels(1, "cut to green main texture")) return false;
    auto invalid = green;
    invalid.canvas.width = 640;
    if (!runtime.prepare(invalid) || !expect_pixels(1, "failed prepare preserves green Program")) return false;
    runtime.deactivate();
    output = obs_get_output_source(0);
    if (output) { obs_source_release(output); std::cerr << "FAIL deactivated scene bound\n"; return false; }
    if (!expect_pixels(-1, "deactivated main texture is black")) return false;
    runtime.activate();
    if (!expect_pixels(1, "reactivated green main texture")) return false;
    runtime.deactivate();
    return true;
}
} // namespace

int main(int argc, char **argv)
{
    if (argc != 3) {
        std::cerr << "usage: webobs-obs-native-preview-tests <graphics-module> <libobs-data-dir>\n";
        return 2;
    }
#ifndef _WIN32
    obs_set_nix_platform(OBS_NIX_PLATFORM_X11_EGL);
#endif
    if (!obs_startup("en-US", nullptr, nullptr)) return 3;
    std::string data_path = argv[2];
    if (!data_path.ends_with('/')) data_path += '/';
    obs_add_data_path(data_path.c_str());
    obs_video_info video{};
    video.graphics_module = argv[1];
    video.fps_num = 30;
    video.fps_den = 1;
    video.base_width = video.output_width = width;
    video.base_height = video.output_height = height;
    video.output_format = VIDEO_FORMAT_NV12;
    video.colorspace = VIDEO_CS_709;
    video.range = VIDEO_RANGE_PARTIAL;
    video.scale_type = OBS_SCALE_BICUBIC;
    video.gpu_conversion = true;
    const int result = obs_reset_video(&video);
    if (result != OBS_VIDEO_SUCCESS) {
        std::cerr << "FAIL obs_reset_video: " << result << " (real graphics display required)\n";
        obs_shutdown();
        return 4;
    }
    obs_audio_info audio{};
    audio.samples_per_sec = 48000;
    audio.speakers = SPEAKERS_STEREO;
    if (!obs_reset_audio(&audio)) { obs_shutdown(); return 5; }
    obs_source_info info{};
    info.id = "color_source";
    info.type = OBS_SOURCE_TYPE_INPUT;
    info.output_flags = OBS_SOURCE_VIDEO | OBS_SOURCE_CUSTOM_DRAW;
    info.get_name = color_name;
    info.create = color_create;
    info.destroy = color_destroy;
    info.get_width = color_width;
    info.get_height = color_height;
    info.video_render = color_render;
    obs_register_source(&info);
    const bool passed = exercise_runtime();
    obs_wait_for_destroy_queue();
    obs_shutdown();
    if (!passed) return 1;
    std::cout << "libobs Program binding, pixel placement, prepare/cut/deactivate/reactivate passed without encoder.\n"
                 "Not a Windows HWND/D3D11 Present or real-media qualification.\n";
    return 0;
}
