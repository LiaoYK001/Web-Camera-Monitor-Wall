#pragma once

#include "webobs/scene_document.hpp"
#include <obs.h>

namespace webobs {
// Shared product-document -> OBS item mapping. Caller owns the scene/source,
// validates the document and performs authorization before making any call.
void configure_obs_scene_item(obs_sceneitem_t *item, const SceneItem &configuration);
// Uses OBS's per-item group/color filter for opacity without changing the
// source settings shared by other items. Removes its partial item on failure.
obs_sceneitem_t *add_obs_scene_item(obs_scene_t *scene, obs_source_t *source,
                                  const SceneItem &configuration);
// Applies existing configured OBS filters; caller validates paths and policy.
bool attach_obs_source_filters(obs_source_t *source, const SceneSource &configuration,
                               std::string_view internal_name);
} // namespace webobs
