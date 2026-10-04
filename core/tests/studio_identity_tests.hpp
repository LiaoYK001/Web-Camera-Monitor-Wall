#pragma once

#include "webobs/studio_document.hpp"

#include <algorithm>
#include <map>
#include <string>
#include <utility>

// Shared by the Linux and Windows binaries: these are runtime identity checks,
// rather than a platform-specific hash implementation test.
template <typename Expect>
void studio_identity_tests(Expect expect)
{
    auto scene = [](std::string id) {
        webobs::SceneDocument value;
        value.id = std::move(id);
        value.name = "Identity fixture";
        return value;
    };
    auto add = [](webobs::SceneDocument &value, std::string id, std::string item,
                  std::string name, int z) {
        webobs::SceneSource source;
        source.id = std::move(id);
        source.name = std::move(name);
        source.kind = "color";
        webobs::SceneItem placed;
        placed.id = std::move(item);
        placed.source_id = source.id;
        placed.x = z * 100;
        placed.z_index = z;
        value.items.push_back(std::move(placed));
        value.sources.push_back(std::move(source));
    };
    auto identities = [](const webobs::StudioFlattenResult &result) {
        std::map<std::string, std::string> values;
        if (result.ok()) {
            for (const auto &source : result.document->sources)
                values[source.name] = source.id;
            for (const auto &item : result.document->items)
                values["item-" + std::to_string(item.x)] = item.id;
        }
        return values;
    };

    auto long_scene = scene("scene-00000000-0000-4000-8000-000000000001");
    add(long_scene, "camera-00000000-0000-4000-8000-000000000001",
        "item-00000000-0000-4000-8000-000000000001", "A", 0);
    add(long_scene, "camera-00000000-0000-4000-8000-000000000002",
        "item-00000000-0000-4000-8000-000000000002", "B", 1);
    webobs::StudioDocument studio;
    studio.program_scene_id = studio.preview_scene_id = long_scene.id;
    studio.scenes = {long_scene};
    const auto before = webobs::flatten_studio_scene(studio, long_scene.id);
    expect(before.ok(), "ordinary UUID Scene/source/item identifiers must flatten");
    std::swap(studio.scenes[0].items[0].z_index, studio.scenes[0].items[1].z_index);
    const auto reordered = webobs::flatten_studio_scene(studio, long_scene.id);
    expect(reordered.ok() && identities(before) == identities(reordered),
           "layer changes must not reassign long source or item identifiers");
    auto copy = studio.scenes[0];
    copy.id = "scene-00000000-0000-4000-8000-000000000002";
    studio.scenes.push_back(copy);
    const auto other = webobs::flatten_studio_scene(studio, copy.id);
    expect(other.ok() && before.ok() &&
               identities(reordered).at("A") != identities(other).at("A"),
           "different Scenes must not reuse counter-based source identifiers");
    const auto stable_id = reordered.ok() ? identities(reordered).at("A") : "";
    studio.scenes[0].sources[0].name = "Renamed A";
    studio.scenes[0].sources[0].volume = 0.25;
    const auto edited = webobs::flatten_studio_scene(studio, long_scene.id);
    expect(edited.ok() && identities(edited).at("Renamed A") == stable_id,
           "source rename and audio edits must retain the source identity");

    auto root = scene("program");
    auto child = scene("child");
    add(child, "camera", "leaf", "Shared", 0);
    webobs::SceneSource nested;
    nested.id = "nested";
    nested.name = "Nested";
    nested.kind = "nested";
    nested.nested_scene_id = child.id;
    root.sources = {nested};
    webobs::SceneItem left;
    left.id = "left";
    left.source_id = "nested";
    auto right = left;
    right.id = "right";
    right.x = 640;
    right.z_index = 1;
    root.items = {left, right};
    studio.program_scene_id = studio.preview_scene_id = root.id;
    studio.scenes = {root, child};
    studio.scenes[0].items.pop_back();
    const auto single = webobs::flatten_studio_scene(studio, root.id);
    studio.scenes[0].items.push_back(right);
    const auto repeated = webobs::flatten_studio_scene(studio, root.id);
    expect(repeated.ok() && repeated.document->sources.size() == 1 &&
               repeated.document->items.size() == 2 &&
               repeated.document->items[0].id != repeated.document->items[1].id,
           "repeated nested Scene instances need distinct items and one shared source");
    expect(single.ok() && repeated.ok() &&
               single.document->items[0].id == repeated.document->items[0].id &&
               single.document->sources[0].id == repeated.document->sources[0].id,
           "adding a nested instance must retain existing item and source identities");
    std::swap(studio.scenes[0].items[0].z_index, studio.scenes[0].items[1].z_index);
    const auto repeated_reorder = webobs::flatten_studio_scene(studio, root.id);
    expect(repeated_reorder.ok() && identities(repeated) == identities(repeated_reorder),
           "repeated nested item identities must survive layer changes");

    // Identical sources reached through two distinct child paths stay deduplicated,
    // and their representative ID is independent of traversal/z-order.
    auto second_child = child;
    second_child.id = "another-child";
    auto second_nested = nested;
    second_nested.id = "second-nested";
    second_nested.nested_scene_id = second_child.id;
    root.sources.push_back(second_nested);
    root.items[1].source_id = second_nested.id;
    studio.scenes = {root, child, second_child};
    const auto aliases = webobs::flatten_studio_scene(studio, root.id);
    std::swap(studio.scenes[0].items[0].z_index, studio.scenes[0].items[1].z_index);
    const auto aliases_reorder = webobs::flatten_studio_scene(studio, root.id);
    expect(aliases.ok() && aliases_reorder.ok() && aliases.document->sources.size() == 1 &&
               aliases.document->sources[0].id == aliases_reorder.document->sources[0].id,
           "deduplicated sources must not take the first layer's namespace");

    auto short_scene = scene("program");
    add(short_scene, "front", "item-front", "Short", 0);
    studio.scenes = {short_scene};
    const auto short_result = webobs::flatten_studio_scene(studio, "program");
    expect(short_result.ok() && short_result.document->sources[0].id == "program.front" &&
               short_result.document->items[0].id == "program.item-front",
           "unambiguous existing short root identifiers must remain compatible");
    auto dotted_scene = scene("a.b");
    add(dotted_scene, "c", "d", "Dots", 0);
    auto dotted_source = scene("a");
    add(dotted_source, "b.c", "b.d", "Dots", 0);
    studio.program_scene_id = studio.preview_scene_id = dotted_scene.id;
    studio.scenes = {dotted_scene, dotted_source};
    const auto first_dot = webobs::flatten_studio_scene(studio, dotted_scene.id);
    const auto second_dot = webobs::flatten_studio_scene(studio, dotted_source.id);
    expect(first_dot.ok() && second_dot.ok() &&
               first_dot.document->sources[0].id != second_dot.document->sources[0].id &&
               first_dot.document->items[0].id != second_dot.document->items[0].id,
           "literal dots must not alias namespace separators across Scenes");
}
