#include "webobs/obs_scene_items.hpp"

#include <atomic>
#include <cmath>
#include <memory>
#include <string>

namespace webobs {
namespace {
obs_bounds_type bounds_type(std::string_view scale_mode)
{
    if (scale_mode == "cover")
        return OBS_BOUNDS_SCALE_OUTER;
    if (scale_mode == "stretch")
        return OBS_BOUNDS_STRETCH;
    return OBS_BOUNDS_SCALE_INNER;
}

} // namespace

void configure_obs_scene_item(obs_sceneitem_t *scene_item, const SceneItem &configuration)
{
    vec2 position{};
    vec2_set(&position, static_cast<float>(configuration.x), static_cast<float>(configuration.y));
    vec2 bounds{};
    vec2_set(&bounds, static_cast<float>(configuration.width), static_cast<float>(configuration.height));
    obs_sceneitem_set_alignment(scene_item, OBS_ALIGN_LEFT | OBS_ALIGN_TOP);
    obs_sceneitem_set_bounds_type(scene_item, bounds_type(configuration.scale_mode));
    obs_sceneitem_set_bounds_alignment(scene_item, OBS_ALIGN_CENTER);
    obs_sceneitem_set_pos(scene_item, &position);
    obs_sceneitem_set_bounds(scene_item, &bounds);
    const obs_sceneitem_crop crop = {
        .left = configuration.crop.left,
        .top = configuration.crop.top,
        .right = configuration.crop.right,
        .bottom = configuration.crop.bottom,
    };
    obs_sceneitem_set_crop(scene_item, &crop);
    obs_sceneitem_set_rot(scene_item, static_cast<float>(configuration.rotation_degrees));
    obs_blending_type blending = OBS_BLEND_NORMAL;
    if (configuration.blend_mode == "add")
        blending = OBS_BLEND_ADDITIVE;
    else if (configuration.blend_mode == "multiply")
        blending = OBS_BLEND_MULTIPLY;
    else if (configuration.blend_mode == "screen")
        blending = OBS_BLEND_SCREEN;
    obs_sceneitem_set_blending_mode(scene_item, blending);
    obs_sceneitem_set_visible(scene_item, configuration.visible);
    obs_sceneitem_set_locked(scene_item, configuration.locked);
    obs_sceneitem_set_order_position(scene_item, configuration.z_index);
}

obs_sceneitem_t *add_obs_scene_item(obs_scene_t *scene, obs_source_t *source,
                                    const SceneItem &configuration)
{
    obs_sceneitem_t *item = obs_scene_add(scene, source);
    if (!item)
        return nullptr;
    if (configuration.opacity >= 0.999999) {
        configure_obs_scene_item(item, configuration);
        return item;
    }

    static std::atomic_uint64_t group_sequence = 0;
    const std::string group_name = "WebOBS item opacity " + configuration.id + " " +
                                   std::to_string(group_sequence.fetch_add(1));
    obs_sceneitem_t *group = obs_scene_insert_group2(scene, group_name.c_str(), &item, 1, false);
    if (!group) {
        obs_sceneitem_remove(item);
        return nullptr;
    }

    std::unique_ptr<obs_data_t, decltype(&obs_data_release)> settings(obs_data_create(), &obs_data_release);
    if (!settings) {
        obs_sceneitem_remove(group);
        return nullptr;
    }
    obs_data_set_int(settings.get(), "opacity",
                     static_cast<long long>(std::lround(configuration.opacity * 100.0)));
    const std::string filter_name = group_name + " filter";
    std::unique_ptr<obs_source_t, decltype(&obs_source_release)> filter(
        obs_source_create_private("color_filter", filter_name.c_str(), settings.get()), &obs_source_release);
    obs_source_t *group_source = obs_sceneitem_get_source(group);
    if (!filter || !group_source) {
        obs_sceneitem_remove(group);
        return nullptr;
    }
    const std::size_t previous_filter_count = obs_source_filter_count(group_source);
    obs_source_filter_add(group_source, filter.get());
    if (obs_source_filter_count(group_source) != previous_filter_count + 1) {
        obs_sceneitem_remove(group);
        return nullptr;
    }
    configure_obs_scene_item(group, configuration);
    return group;
}

bool attach_obs_source_filters(obs_source_t *source, const SceneSource &configuration,
                               std::string_view internal_name)
{
    for (const SceneFilter &filter : configuration.filters) {
        std::unique_ptr<obs_data_t, decltype(&obs_data_release)> settings(obs_data_create(), &obs_data_release);
        if (!settings)
            return false;
        const char *filter_type = nullptr;
        if (filter.kind == "opacity") {
            filter_type = "color_filter";
            obs_data_set_int(settings.get(), "opacity", static_cast<long long>(filter.amount * 100.0));
        } else if (filter.kind == "color-correction") {
            filter_type = "color_filter";
            obs_data_set_double(settings.get(), "brightness", filter.amount);
        } else if (filter.kind == "delay") {
            filter_type = "async_delay_filter";
            obs_data_set_int(settings.get(), "delay_ms", static_cast<long long>(filter.amount));
        } else if (filter.kind == "scaling") {
            filter_type = "scale_filter";
            obs_data_set_string(settings.get(), "resolution", filter.value.c_str());
            obs_data_set_string(settings.get(), "sampling", "bicubic");
        } else if (filter.kind == "lut") {
            filter_type = "clut_filter";
            obs_data_set_string(settings.get(), "image_path", filter.value.c_str());
            obs_data_set_double(settings.get(), "clut_amount", filter.amount);
        } else if (filter.kind == "mask-blend") {
            filter_type = "mask_filter";
            obs_data_set_string(settings.get(), "image_path", filter.value.c_str());
            obs_data_set_int(settings.get(), "opacity", static_cast<long long>(filter.amount * 100.0));
        } else if (filter.kind == "crop-pad") {
            filter_type = "crop_filter";
            obs_data_set_bool(settings.get(), "relative", true);
            long long crop = static_cast<long long>(filter.amount);
            obs_data_set_int(settings.get(), "left", crop);
            obs_data_set_int(settings.get(), "top", crop);
            obs_data_set_int(settings.get(), "right", crop);
            obs_data_set_int(settings.get(), "bottom", crop);
        }
        if (!filter_type)
            return false;
        const std::string name = std::string(internal_name) + " filter " + filter.id;
        std::unique_ptr<obs_source_t, decltype(&obs_source_release)> instance(
            obs_source_create_private(filter_type, name.c_str(), settings.get()), &obs_source_release);
        if (!instance)
            return false;
        const auto previous_count = obs_source_filter_count(source);
        obs_source_filter_add(source, instance.get());
        if (obs_source_filter_count(source) != previous_count + 1)
            return false;
        obs_source_set_enabled(instance.get(), filter.enabled);
    }
    return true;
}

} // namespace webobs
