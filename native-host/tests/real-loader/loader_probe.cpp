// Test-only real libobs loader gate. This executable accepts no paths or CLI
// options, never discovers modules, never initializes media/video/audio output,
// and deliberately registers a settings-blind, no-I/O synthetic media source.
#include <obs.h>
#include <graphics/matrix4.h>
#include <util/base.h>

#include <algorithm>
#include <atomic>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <initializer_list>
#include <iostream>
#include <limits>
#include <map>
#include <memory>
#include <set>
#include <string>
#include <utility>
#include <vector>
#ifdef _WIN32
#include <fcntl.h>
#include <io.h>
#endif

namespace {
constexpr uint32_t pinned_version = (32u << 24) | (1u << 16) | 2u;
constexpr size_t input_limit = 1024u * 1024u;
struct Failure { const char *stage; };
void require(bool ok, const char *stage = "shape") { if (!ok) throw Failure{stage}; }
template<class T, void (*Release)(T *)> struct ReleaseRef {
    void operator()(T *p) const noexcept { if (p) Release(p); }
};
using Data = std::unique_ptr<obs_data_t, ReleaseRef<obs_data_t, obs_data_release>>;
using Array = std::unique_ptr<obs_data_array_t, ReleaseRef<obs_data_array_t, obs_data_array_release>>;
using Source = std::unique_ptr<obs_source_t, ReleaseRef<obs_source_t, obs_source_release>>;
struct ItemRef {
    obs_data_item_t *p;
    explicit ItemRef(obs_data_item_t *v) : p(v) {}
    ~ItemRef() { obs_data_item_release(&p); }
    ItemRef(const ItemRef &) = delete;
    ItemRef &operator=(const ItemRef &) = delete;
};
void kind(obs_data_t *o, const char *key, obs_data_type type) {
    ItemRef i(obs_data_item_byname(o, key));
    require(i.p && obs_data_item_gettype(i.p) == type);
}
std::string text(obs_data_t *o, const char *key) {
    kind(o, key, OBS_DATA_STRING);
    std::string v = obs_data_get_string(o, key);
    require(v.size() <= 1024);
    return v;
}
int64_t integer(obs_data_t *o, const char *key) {
    kind(o, key, OBS_DATA_NUMBER);
    ItemRef i(obs_data_item_byname(o, key));
    require(obs_data_item_numtype(i.p) == OBS_DATA_NUM_INT);
    return obs_data_get_int(o, key);
}
double number(obs_data_t *o, const char *key) {
    kind(o, key, OBS_DATA_NUMBER);
    double v = obs_data_get_double(o, key);
    require(std::isfinite(v) && std::abs(v) <= 100000000.0);
    return v;
}
bool boolean(obs_data_t *o, const char *key) {
    kind(o, key, OBS_DATA_BOOLEAN); return obs_data_get_bool(o, key);
}
Data object(obs_data_t *o, const char *key) {
    kind(o, key, OBS_DATA_OBJECT); return Data(obs_data_get_obj(o, key));
}
Array array(obs_data_t *o, const char *key, size_t max = 256) {
    kind(o, key, OBS_DATA_ARRAY);
    Array a(obs_data_get_array(o, key));
    require(a && obs_data_array_count(a.get()) <= max); return a;
}
Data at(const Array &a, size_t i) {
    Data d(obs_data_array_item(a.get(), i)); require(bool(d)); return d;
}
void keys(obs_data_t *o, std::initializer_list<const char *> expected) {
    std::set<std::string> remaining;
    for (auto k : expected) remaining.emplace(k);
    ItemRef i(obs_data_first(o));
    while (i.p) {
        require(remaining.erase(obs_data_item_get_name(i.p)) == 1);
        obs_data_item_next(&i.p);
    }
    require(remaining.empty());
}
void empty(obs_data_t *o) { keys(o, {}); }
void synthetic_name(const std::string &s) {
    require(s.size() >= 13 && s.size() <= 256 && s.compare(0, 13, "P3 synthetic ") == 0,
            "synthetic_boundary");
    for (unsigned char c : s) require(c >= 32 && c != 127, "synthetic_boundary");
}
void synthetic_url(const std::string &s) {
    require(s == "rtsp://p3-synthetic.invalid/stream-a" ||
            s == "rtsp://p3-synthetic.invalid/stream-b", "synthetic_boundary");
}
void uuid(const std::string &s) {
    require(s.size() == 36);
    for (size_t i = 0; i < s.size(); ++i) {
        if (i == 8 || i == 13 || i == 18 || i == 23) require(s[i] == '-');
        else require((s[i] >= '0' && s[i] <= '9') || (s[i] >= 'a' && s[i] <= 'f'));
    }
}
bool close(double a, double b) {
    return std::isfinite(a) && std::abs(a - b) <= 0.0001;
}
void equal_num(double a, double b, const char *stage) { require(close(a, b), stage); }
void vec_shape(obs_data_t *v) { keys(v, {"x", "y"}); number(v, "x"); number(v, "y"); }
void vec_field(obs_data_t *o, const char *k) { Data v = object(o, k); vec_shape(v.get()); }
void id_safe(int64_t v) { require(v > 0 && v < (std::numeric_limits<int64_t>::max)() - 256, "id_counter"); }

// A lexical bound before the OBS JSON parser avoids recursion/resource abuse.
// obs_data_create_from_json itself rejects duplicate JSON object keys.
std::string read_input() {
    std::string s; s.reserve(16384);
    char c; bool quoted = false, escaped = false; int depth = 0;
    while (std::cin.get(c)) {
        require(s.size() < input_limit, "input_size");
        require(c != '\0', "input");
        s.push_back(c);
        if (quoted) {
            if (escaped) escaped = false;
            else if (c == '\\') escaped = true;
            else if (c == '"') quoted = false;
        } else if (c == '"') quoted = true;
        else if (c == '{' || c == '[') require(++depth <= 16, "input");
        else if (c == '}' || c == ']') require(--depth >= 0, "input");
    }
    require(!s.empty() && !quoted && depth == 0 && !std::cin.bad(), "input");
    return s;
}
struct ExpectedSource {
    std::string legacy, uuid, name, url, transport;
    double volume;
    int64_t sync;
    bool muted;
};
struct ExpectedItem {
    std::string legacy, source_uuid;
    int64_t id, z;
    double x, y, width, height;
    bool visible, locked;
};
struct Expected {
    std::string scene_uuid, scene_name;
    uint32_t width = 0, height = 0;
    int64_t max_id = 0;
    bool hardware = false;
    std::vector<ExpectedSource> sources;
    std::vector<ExpectedItem> items;
};
Data mapping(const Array &a, const std::string &legacy) {
    Data found;
    for (size_t i = 0; i < obs_data_array_count(a.get()); ++i) {
        Data m = at(a, i);
        if (text(m.get(), "legacyId") == legacy) {
            require(!found); found = std::move(m);
        }
    }
    require(bool(found)); return found;
}
Expected expectation(obs_data_t *manifest) {
    require(integer(manifest, "schema") == 1);
    require(text(manifest, "obsVersion") == "32.1.2");
    require(!boolean(manifest, "applied") && !boolean(manifest, "qualified"));
    Data original = object(manifest, "original");
    Expected e;
    int64_t schema = integer(original.get(), "schemaVersion"); require(schema == 5 || schema == 6);
    e.scene_name = text(original.get(), "name"); synthetic_name(e.scene_name);
    Data sm = object(manifest, "scene");
    require(text(sm.get(), "legacyId") == text(original.get(), "id"));
    e.scene_uuid = text(sm.get(), "nativeId"); uuid(e.scene_uuid);
    Data canvas = object(original.get(), "canvas");
    int64_t w = integer(canvas.get(), "width"), h = integer(canvas.get(), "height");
    require(w > 0 && w <= 16384 && h > 0 && h <= 16384);
    e.width = static_cast<uint32_t>(w); e.height = static_cast<uint32_t>(h);
    Data runtime = object(manifest, "runtimeOptions");
    e.hardware = boolean(runtime.get(), "hardwareDecode");
    Array originals = array(original.get(), "sources", 64), mappings = array(manifest, "sources", 64);
    require(obs_data_array_count(originals.get()) > 0 &&
            obs_data_array_count(originals.get()) == obs_data_array_count(mappings.get()));
    std::set<std::string> ids, uuids{e.scene_uuid}, names{e.scene_name};
    for (size_t i = 0; i < obs_data_array_count(originals.get()); ++i) {
        Data o = at(originals, i);
        ExpectedSource s;
        s.legacy = text(o.get(), "id"); require(ids.insert(s.legacy).second);
        Data m = mapping(mappings, s.legacy); s.uuid = text(m.get(), "nativeId"); uuid(s.uuid);
        require(uuids.insert(s.uuid).second);
        s.name = text(o.get(), "name"); synthetic_name(s.name); require(names.insert(s.name).second);
        require(text(o.get(), "kind") == "rtsp");
        s.url = text(o.get(), "rtspUrl"); synthetic_url(s.url);
        s.transport = text(o.get(), "transport"); require(s.transport == "tcp" || s.transport == "udp");
        s.volume = number(o.get(), "volume"); require(s.volume >= 0 && s.volume <= 20);
        s.muted = boolean(o.get(), "muted");
        int64_t ms = integer(o.get(), "syncOffsetMs"); require(ms >= -20000 && ms <= 20000);
        s.sync = ms * 1000000;
        e.sources.push_back(std::move(s));
    }
    Array items = array(original.get(), "items"), item_maps = array(manifest, "items");
    require(obs_data_array_count(items.get()) > 0 &&
            obs_data_array_count(items.get()) == obs_data_array_count(item_maps.get()));
    std::set<int64_t> obs_ids, zs; ids.clear();
    for (size_t i = 0; i < obs_data_array_count(items.get()); ++i) {
        Data o = at(items, i);
        ExpectedItem v;
        v.legacy = text(o.get(), "id"); require(ids.insert(v.legacy).second);
        Data m = mapping(item_maps, v.legacy);
        v.id = integer(m.get(), "obsItemId"); id_safe(v.id); require(obs_ids.insert(v.id).second);
        e.max_id = (std::max)(e.max_id, v.id);
        const std::string source_id = text(o.get(), "sourceId");
        auto si = std::find_if(e.sources.begin(), e.sources.end(), [&](const auto &s) { return s.legacy == source_id; });
        require(si != e.sources.end()); v.source_uuid = si->uuid;
        require(text(m.get(), "sourceUuid") == v.source_uuid);
        v.z = integer(o.get(), "zIndex"); require(zs.insert(v.z).second);
        v.x = number(o.get(), "x"); v.y = number(o.get(), "y");
        v.width = number(o.get(), "width"); v.height = number(o.get(), "height");
        require(v.width > 0 && v.height > 0 && v.width <= 16384 && v.height <= 16384);
        v.visible = boolean(o.get(), "visible");
        v.locked = obs_data_has_user_value(o.get(), "locked") ? boolean(o.get(), "locked") : false;
        if (obs_data_has_user_value(o.get(), "scaleMode")) require(text(o.get(), "scaleMode") == "contain");
        Data crop = object(o.get(), "crop"); keys(crop.get(), {"left", "top", "right", "bottom"});
        for (auto k : {"left", "top", "right", "bottom"}) require(number(crop.get(), k) == 0);
        e.items.push_back(v);
    }
    std::sort(e.items.begin(), e.items.end(), [](const auto &a, const auto &b) { return a.z < b.z; });
    return e;
}
void media_shape(obs_data_t *s) {
    keys(s, {"is_local_file", "input", "input_format", "hw_decode", "ffmpeg_options", "looping",
             "clear_on_media_end", "restart_on_activate", "linear_alpha", "reconnect_delay_sec",
             "buffering_mb", "speed_percent", "log_changes", "close_when_inactive", "color_range",
             "full_decode", "seekable"});
    synthetic_url(text(s, "input"));
    for (auto k : {"is_local_file", "hw_decode", "looping", "clear_on_media_end", "restart_on_activate",
                   "linear_alpha", "log_changes", "close_when_inactive", "full_decode", "seekable"}) boolean(s, k);
    require(text(s, "input_format").empty());
    auto options = text(s, "ffmpeg_options");
    require(options == "rtsp_transport=tcp" || options == "rtsp_transport=udp", "synthetic_boundary");
    for (auto k : {"reconnect_delay_sec", "buffering_mb", "speed_percent", "color_range"}) integer(s, k);
}
void item_shape(obs_data_t *v) {
    keys(v, {"name", "source_uuid", "visible", "locked", "rot", "scale_ref", "align", "bounds_type",
             "bounds_align", "bounds_crop", "crop_left", "crop_top", "crop_right", "crop_bottom", "id",
             "group_item_backup", "pos", "scale", "bounds", "scale_filter", "blend_method", "blend_type",
             "show_transition", "hide_transition", "private_settings"});
    synthetic_name(text(v, "name")); uuid(text(v, "source_uuid")); id_safe(integer(v, "id"));
    for (auto k : {"visible", "locked", "bounds_crop", "group_item_backup"}) boolean(v, k);
    require(number(v, "rot") == 0 && integer(v, "align") == 5 &&
            integer(v, "bounds_type") == 2 && integer(v, "bounds_align") == 0 &&
            !boolean(v, "bounds_crop") && !boolean(v, "group_item_backup"), "item_transform");
    for (auto k : {"crop_left", "crop_top", "crop_right", "crop_bottom"}) integer(v, k);
    for (auto k : {"scale_ref", "pos", "scale", "bounds"}) vec_field(v, k);
    // Reject unsafe numeric input before real scene_load_item can cast bounds
    // to unsigned dimensions or derive transforms from invalid scale/crop.
    for (auto k : {"bounds", "scale_ref", "scale"}) {
        Data vec = object(v, k);
        for (auto axis : {"x", "y"}) {
            const double value = number(vec.get(), axis);
            require(value >= 1 && value <= 16384 && (std::strcmp(k, "scale") != 0 || value == 1),
                    "item_transform");
        }
    }
    for (auto k : {"crop_left", "crop_top", "crop_right", "crop_bottom"})
        require(integer(v, k) == 0, "item_transform");
    require(text(v, "scale_filter") == "disable" && text(v, "blend_method") == "default" && text(v, "blend_type") == "normal");
    for (auto k : {"show_transition", "hide_transition"}) {
        Data t = object(v, k); keys(t.get(), {"duration"}); require(integer(t.get(), "duration") == 0);
    }
    Data p = object(v, "private_settings"); empty(p.get());
}
Array preflight(obs_data_t *root, Expected &e) {
    keys(root, {"collection", "manifest"});
    Data m = object(root, "manifest"); e = expectation(m.get());
    Data c = object(root, "collection");
    keys(c.get(), {"name", "version", "sources", "groups", "scene_order", "current_scene", "current_program_scene"});
    require(integer(c.get(), "version") == 1);
    for (auto k : {"name", "current_scene", "current_program_scene"}) {
        const auto n = text(c.get(), k); synthetic_name(n); require(n == e.scene_name);
    }
    Array groups = array(c.get(), "groups", 0);
    Array order = array(c.get(), "scene_order", 1); require(obs_data_array_count(order.get()) == 1);
    Data entry = at(order, 0); keys(entry.get(), {"name"}); require(text(entry.get(), "name") == e.scene_name);
    Array a = array(c.get(), "sources", 65);
    require(obs_data_array_count(a.get()) == e.sources.size() + 1);
    std::set<std::string> uuids, names; size_t scenes = 0;
    for (size_t i = 0; i < obs_data_array_count(a.get()); ++i) {
        Data d = at(a, i);
        keys(d.get(), {"prev_ver", "name", "uuid", "id", "versioned_id", "settings", "mixers", "sync", "flags",
                       "volume", "balance", "enabled", "muted", "push-to-mute", "push-to-mute-delay", "push-to-talk",
                       "push-to-talk-delay", "hotkeys", "deinterlace_mode", "deinterlace_field_order", "monitoring_type", "private_settings"});
        std::string id = text(d.get(), "id");
        require((id == "ffmpeg_source" || id == "scene") && text(d.get(), "versioned_id") == id, "source_type");
        require(integer(d.get(), "prev_ver") == pinned_version, "source_type");
        std::string name = text(d.get(), "name"), uid = text(d.get(), "uuid"); synthetic_name(name); uuid(uid);
        require(names.insert(name).second && uuids.insert(uid).second);
        for (auto k : {"mixers", "flags", "monitoring_type", "deinterlace_mode", "deinterlace_field_order",
                       "push-to-mute-delay", "push-to-talk-delay"}) require(integer(d.get(), k) == 0);
        require(!boolean(d.get(), "push-to-talk") && !boolean(d.get(), "push-to-mute"));
        boolean(d.get(), "enabled"); boolean(d.get(), "muted");
        require(number(d.get(), "balance") == 0.5); number(d.get(), "volume");
        int64_t sync = integer(d.get(), "sync"); require(sync >= -20000000000LL && sync <= 20000000000LL);
        for (auto k : {"hotkeys", "private_settings"}) { Data p = object(d.get(), k); empty(p.get()); }
        Data s = object(d.get(), "settings");
        if (id == "ffmpeg_source") media_shape(s.get());
        else {
            require(++scenes == 1 && uid == e.scene_uuid);
            keys(s.get(), {"id_counter", "custom_size", "cx", "cy", "items"});
            id_safe(integer(s.get(), "id_counter"));
            boolean(s.get(), "custom_size");
            for (auto k : {"cx", "cy"}) { int64_t n = integer(s.get(), k); require(n > 0 && n <= 16384); }
            Array items = array(s.get(), "items"); require(obs_data_array_count(items.get()) == e.items.size());
            std::set<int64_t> loaded_ids;
            for (size_t j = 0; j < obs_data_array_count(items.get()); ++j) {
                Data v = at(items, j); item_shape(v.get());
                require(loaded_ids.insert(integer(v.get(), "id")).second, "id_counter");
            }
        }
    }
    require(scenes == 1); return a;
}

std::atomic<size_t> created{0}, destroyed{0};
const char *fake_name(void *) { return "P3 synthetic no-I/O media"; }
void *fake_create(obs_data_t *, obs_source_t *) {
    // Never inspect settings, open a file/socket, or invoke a media subsystem.
    created.fetch_add(1); return &created;
}
void fake_destroy(void *) { destroyed.fetch_add(1); }
uint32_t fake_width(void *) { return 800; }
uint32_t fake_height(void *) { return 600; }
void discard_log(int, const char *, va_list, void *) {}
void barrier(void *) {}
void drain() { obs_queue_task(OBS_TASK_DESTROY, barrier, nullptr, true); }
struct Runtime {
    bool active = false;
    ~Runtime() { if (active) { drain(); obs_shutdown(); } }
};
struct CoordinateMode {
    Data data{obs_get_private_data()};
    bool had = false, previous = false;
    CoordinateMode() {
        require(bool(data), "startup");
        had = obs_data_has_user_value(data.get(), "AbsoluteCoordinates");
        previous = obs_data_get_bool(data.get(), "AbsoluteCoordinates");
        obs_data_set_bool(data.get(), "AbsoluteCoordinates", true);
    }
    ~CoordinateMode() {
        if (had) obs_data_set_bool(data.get(), "AbsoluteCoordinates", previous);
        else obs_data_unset_user_value(data.get(), "AbsoluteCoordinates");
    }
};
struct Loaded {
    std::vector<Source> refs;
    explicit Loaded(size_t n) { refs.reserve(n); }
    static void retain(void *p, obs_source_t *s) {
        auto &v = static_cast<Loaded *>(p)->refs;
        // Capacity was reserved before entering C; no exception crosses its ABI.
        if (v.size() < v.capacity()) v.emplace_back(obs_source_get_ref(s));
    }
    void clear() noexcept {
        // The pinned main canvas owns a SCENE_REF in addition to our callback
        // reference. Detach only our loaded scene while our ref keeps it alive;
        // releasing that final ref queues destruction of its item-held sources.
        for (auto &s : refs) {
            if (s && std::strcmp(obs_source_get_id(s.get()), "scene") == 0) {
                obs_canvas_scene_remove(obs_scene_from_source(s.get()));
                s.reset();
            }
        }
        drain(); refs.clear(); drain(); drain();
    }
    ~Loaded() { clear(); }
};
void module_count(void *p, obs_module_t *) { ++*static_cast<size_t *>(p); }
void no_live_state() {
    size_t modules = 0; obs_enum_modules(module_count, &modules); require(modules == 0, "isolation");
    // obs_get_video dereferences main_canvas->mix in pinned OBS even when no
    // video was reset. The info query checks the null mix before reading it.
    obs_video_info video{};
    require(!obs_get_video_info(&video) && obs_get_audio() == nullptr, "isolation");
    for (uint32_t i = 0; i < MAX_CHANNELS; ++i) {
        Source output(obs_get_output_source(i)); require(!output, "isolation");
    }
}
void verify_media_settings(obs_data_t *settings, const ExpectedSource &s, bool hardware) {
    const char *stage = "source_settings";
    require(text(settings, "input") == s.url && text(settings, "input_format").empty() &&
            text(settings, "ffmpeg_options") == "rtsp_transport=" + s.transport, stage);
    require(boolean(settings, "hw_decode") == hardware, stage);
    for (auto k : {"is_local_file", "looping", "linear_alpha", "log_changes", "close_when_inactive", "full_decode", "seekable"})
        require(!boolean(settings, k), stage);
    for (auto k : {"clear_on_media_end", "restart_on_activate"}) require(boolean(settings, k), stage);
    require(integer(settings, "reconnect_delay_sec") == 10 && integer(settings, "buffering_mb") == 2 &&
            integer(settings, "speed_percent") == 100 && integer(settings, "color_range") == 0, stage);
}
struct Items {
    std::vector<obs_sceneitem_t *> values; // Borrowed only while Loaded retains scene.
    static bool collect(obs_scene_t *, obs_sceneitem_t *v, void *p) {
        auto &items = static_cast<Items *>(p)->values;
        if (items.size() == items.capacity()) return false;
        items.push_back(v); return true;
    }
};
obs_source_t *verify(const Expected &e, const Loaded &loaded) {
    require(loaded.refs.size() == e.sources.size() + 1, "source_identity");
    std::map<std::string, obs_source_t *> sources;
    std::set<obs_source_t *> distinct;
    for (const auto &s : e.sources) {
        Source by_id(obs_get_source_by_uuid(s.uuid.c_str())), by_name(obs_get_source_by_name(s.name.c_str()));
        require(by_id && by_id.get() == by_name.get() && distinct.insert(by_id.get()).second, "source_identity");
        require(std::string(obs_source_get_uuid(by_id.get())) == s.uuid &&
                std::string(obs_source_get_name(by_id.get())) == s.name &&
                std::string(obs_source_get_id(by_id.get())) == "ffmpeg_source", "source_identity");
        require(obs_source_get_width(by_id.get()) == 800 && obs_source_get_height(by_id.get()) == 600, "source_identity");
        require(obs_source_get_audio_mixers(by_id.get()) == 0 &&
                obs_source_get_monitoring_type(by_id.get()) == OBS_MONITORING_TYPE_NONE &&
                obs_source_muted(by_id.get()) == s.muted && obs_source_enabled(by_id.get()) &&
                obs_source_get_sync_offset(by_id.get()) == s.sync, "source_state");
        equal_num(obs_source_get_volume(by_id.get()), s.volume, "source_state");
        Data settings(obs_source_get_settings(by_id.get())); verify_media_settings(settings.get(), s, e.hardware);
        sources.emplace(s.uuid, by_id.get());
    }
    Source scene(obs_get_source_by_uuid(e.scene_uuid.c_str())), named(obs_get_source_by_name(e.scene_name.c_str()));
    require(scene && scene.get() == named.get() && std::string(obs_source_get_id(scene.get())) == "scene", "source_identity");
    require(obs_source_enabled(scene.get()) && !obs_source_muted(scene.get()) &&
            obs_source_get_sync_offset(scene.get()) == 0 && obs_source_get_audio_mixers(scene.get()) == 0 &&
            obs_source_get_monitoring_type(scene.get()) == OBS_MONITORING_TYPE_NONE, "source_state");
    equal_num(obs_source_get_volume(scene.get()), 1, "source_state");
    require(obs_source_get_width(scene.get()) == e.width && obs_source_get_height(scene.get()) == e.height, "scene_canvas");
    obs_scene_t *sc = obs_scene_from_source(scene.get()); require(sc != nullptr, "source_identity");
    Items actual; actual.values.reserve(e.items.size() + 1); obs_scene_enum_items(sc, Items::collect, &actual);
    require(actual.values.size() == e.items.size(), "item_order");
    for (size_t i = 0; i < e.items.size(); ++i) {
        const auto &v = e.items[i]; auto item = actual.values[i];
        require(obs_sceneitem_get_id(item) == v.id, "item_identity");
        require(obs_sceneitem_get_source(item) == sources.at(v.source_uuid), "item_identity");
        require(obs_sceneitem_visible(item) == v.visible && obs_sceneitem_locked(item) == v.locked, "item_state");
        require(obs_sceneitem_get_alignment(item) == (OBS_ALIGN_TOP | OBS_ALIGN_LEFT) &&
                obs_sceneitem_get_bounds_alignment(item) == OBS_ALIGN_CENTER &&
                obs_sceneitem_get_bounds_type(item) == OBS_BOUNDS_SCALE_INNER &&
                !obs_sceneitem_get_bounds_crop(item), "item_transform");
        vec2 pos{}, scale{}, bounds{};
        obs_sceneitem_get_pos(item, &pos); obs_sceneitem_get_scale(item, &scale); obs_sceneitem_get_bounds(item, &bounds);
        equal_num(pos.x, v.x, "item_transform"); equal_num(pos.y, v.y, "item_transform");
        equal_num(scale.x, 1, "item_transform"); equal_num(scale.y, 1, "item_transform");
        equal_num(bounds.x, v.width, "item_transform"); equal_num(bounds.y, v.height, "item_transform");
        equal_num(obs_sceneitem_get_rot(item), 0, "item_transform");
        obs_sceneitem_crop crop{}; obs_sceneitem_get_crop(item, &crop);
        require(!crop.left && !crop.right && !crop.top && !crop.bottom, "item_transform");
        // Force only libobs's CPU transform calculation, never a render/tick.
        obs_sceneitem_force_update_transform(item);
        matrix4 transform{}; obs_sceneitem_get_draw_transform(item, &transform);
        // Pinned OBS aligns the contained image in integer pixels: cast the
        // negative floating-point difference to int, then divide by two. Do
        // not silently accept the ideal fractional-center matrix instead.
        const float bw = static_cast<float>(v.width), bh = static_cast<float>(v.height);
        const float fit = bw / bh < 800.0f / 600.0f ? bw / 800.0f : bh / 600.0f;
        const int ox = static_cast<int>(-(bw - 800.0f * fit)) / 2;
        const int oy = static_cast<int>(-(bh - 600.0f * fit)) / 2;
        equal_num(transform.x.x, fit, "item_transform"); equal_num(transform.y.y, fit, "item_transform");
        equal_num(transform.t.x, static_cast<float>(v.x) - ox, "item_transform");
        equal_num(transform.t.y, static_cast<float>(v.y) - oy, "item_transform");
    }
    // obs_save_source invokes the real scene save callback. Counter/custom-size
    // have no public scalar getter; this supplements, never replaces live checks.
    Data serialized(obs_save_source(scene.get())); Data settings = object(serialized.get(), "settings");
    require(integer(settings.get(), "id_counter") == e.max_id, "id_counter");
    require(boolean(settings.get(), "custom_size") && integer(settings.get(), "cx") == e.width &&
            integer(settings.get(), "cy") == e.height, "scene_canvas");
    return scene.get(); // Borrowed; the load callback owns a reference.
}
void assert_absent(const Expected &e, size_t loads) {
    Source scene(obs_get_source_by_uuid(e.scene_uuid.c_str())); require(!scene, "reload_cleanup");
    for (const auto &s : e.sources) {
        Source id(obs_get_source_by_uuid(s.uuid.c_str())), name(obs_get_source_by_name(s.name.c_str()));
        require(!id && !name, "reload_cleanup");
    }
    require(created.load() == loads * e.sources.size() && destroyed.load() == created.load(), "reload_cleanup");
}
void execute(Array &input, const Expected &e, bool &started) {
    require(obs_get_version() == pinned_version && std::string(obs_get_version_string()) == "32.1.2", "version");
    Runtime runtime;
    require(obs_startup("en-US", nullptr, nullptr), "startup"); runtime.active = true; started = true;
    CoordinateMode absolute;
    no_live_state();
    obs_source_info info{};
    info.id = "ffmpeg_source"; info.type = OBS_SOURCE_TYPE_INPUT;
    info.output_flags = OBS_SOURCE_VIDEO | OBS_SOURCE_AUDIO;
    info.get_name = fake_name; info.create = fake_create; info.destroy = fake_destroy;
    info.get_width = fake_width; info.get_height = fake_height;
    obs_register_source(&info);
    Array saved;
    {
        Loaded loaded(e.sources.size() + 1);
        obs_load_sources(input.get(), Loaded::retain, &loaded);
        verify(e, loaded); no_live_state();
        saved.reset(obs_save_sources()); require(saved && obs_data_array_count(saved.get()) == e.sources.size() + 1, "save");
    }
    assert_absent(e, 1);
    {
        Loaded loaded(e.sources.size() + 1);
        obs_load_sources(saved.get(), Loaded::retain, &loaded);
        obs_source_t *scene = verify(e, loaded); no_live_state();
        Source source(obs_get_source_by_uuid(e.sources.front().uuid.c_str()));
        obs_sceneitem_t *added = obs_scene_add(obs_scene_from_source(scene), source.get());
        require(added && obs_sceneitem_get_id(added) > e.max_id, "id_counter");
        obs_sceneitem_remove(added);
    }
    assert_absent(e, 2); no_live_state();
}
} // namespace
int main(int argc, char **) {
    // Install before even parsing so parser diagnostics cannot echo input.
    base_set_log_handler(discard_log, nullptr);
#ifdef _WIN32
    // Preserve UTF-8 bytes and literal newline JSON protocol on MSVC CRT.
    _setmode(_fileno(stdin), _O_BINARY);
    _setmode(_fileno(stdout), _O_BINARY);
    _setmode(_fileno(stderr), _O_BINARY);
#endif
    bool started = false;
    const char *failure = nullptr;
    try {
        require(argc == 1, "arguments");
        std::string input = read_input();
        Data root(obs_data_create_from_json(input.c_str())); require(bool(root), "input");
        Expected expected; Array sources = preflight(root.get(), expected);
        execute(sources, expected, started);
    } catch (const Failure &e) { failure = e.stage; }
      catch (...) { failure = "internal"; }
    if (failure) {
        std::fprintf(stderr, "native_loader_probe_failed:%s\n", failure);
        std::printf("{\"schema\":1,\"status\":\"failed\",\"started\":%s}\n", started ? "true" : "false");
        return 1;
    }
    std::puts("{\"schema\":1,\"status\":\"passed\",\"obsVersion\":\"32.1.2\",\"loads\":2,\"videoContext\":false,\"libraryIdentity\":\"runtime-version-checked\"}");
    return 0;
}
