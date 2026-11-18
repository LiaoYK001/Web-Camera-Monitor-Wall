#include "product_scene.hpp"
#include "webobs/obs_scene_items.hpp"

#include <algorithm>
#include <atomic>
#include <map>
#include <tuple>
#include <utility>
#ifdef WEBOBS_NATIVE_PRODUCT_MODE
#include <QCoreApplication>
#include <QDir>
#include <QFileInfo>
#include <QProcess>
#include <QProcessEnvironment>
#include <QStringList>
#include <QTcpServer>
#include <QUrl>
#include <obs-audio-controls.h>
#endif

namespace webobs::native_host {
namespace {
using Data = std::unique_ptr<obs_data_t, decltype(&obs_data_release)>;
std::string settings_json(obs_source_t *source)
{
	Data settings(obs_source_get_settings(source), &obs_data_release);
	const char *json = settings ? obs_data_get_json(settings.get()) : nullptr;
	return json ? json : "";
}
using FilterState = std::tuple<std::string, std::string, std::string, bool>;
std::vector<FilterState> filters_state(obs_source_t *source)
{
	std::vector<FilterState> result;
	obs_source_enum_filters(source, [](obs_source_t *, obs_source_t *filter, void *context) {
		static_cast<std::vector<FilterState> *>(context)->emplace_back(obs_source_get_uuid(filter),
			obs_source_get_unversioned_id(filter), settings_json(filter), obs_source_enabled(filter));
	}, &result);
	return result;
}
obs_monitoring_type monitoring(const SceneSource &source)
{
	if (source.monitoring == "monitor-only") return OBS_MONITORING_TYPE_MONITOR_ONLY;
	if (source.monitoring == "monitor-and-output") return OBS_MONITORING_TYPE_MONITOR_AND_OUTPUT;
	return OBS_MONITORING_TYPE_NONE;
}
bool same_camera(const ProductCamera &a, const ProductCamera &b)
{
	return a.id == b.id && a.profile_id == b.profile_id && a.url == b.url &&
		a.transport == b.transport && a.hardware_decode == b.hardware_decode;
}
bool valid_owner(const std::string &owner)
{
	return owner.size() == 32 && std::all_of(owner.begin(), owner.end(), [](char c) {
		return (c >= '0' && c <= '9') || (c >= 'a' && c <= 'f');
	});
}
std::uint32_t audio_mixers(const SceneSource &configuration)
{
	return configuration.audio_inputs_explicit && configuration.audio_inputs.empty() ? 0u :
		(1u << (configuration.audio_track - 1));
}
bool mixed_audio(const SceneSource &configuration)
{
	if (!configuration.audio_inputs_explicit || configuration.audio_inputs.empty() ||
	    configuration.muted)
		return false;
	return std::any_of(configuration.audio_inputs.begin(), configuration.audio_inputs.end(),
		[](const SceneAudioInput &input) { return !input.muted && input.gain > 0.0; });
}
bool explicit_audio(const SceneSource &configuration)
{
	return configuration.audio_inputs_explicit && !configuration.audio_inputs.empty();
}
int audio_normalization(const SceneSource &configuration)
{
	int normalization = 0;
	for (const auto &input : configuration.audio_inputs)
		if (!input.muted && input.gain > 0.0)
			normalization = (std::max)(normalization, -input.sync_offset_ms);
	return normalization;
}
#ifdef WEBOBS_NATIVE_PRODUCT_MODE
void audio_meter_callback(void *param, const float magnitude[MAX_AUDIO_CHANNELS],
	const float peak[MAX_AUDIO_CHANNELS], const float input_peak[MAX_AUDIO_CHANNELS])
{
	(void)magnitude;
	(void)input_peak;
	float value = -120.0f;
	for (int channel = 0; channel < MAX_AUDIO_CHANNELS; ++channel)
		if (peak[channel] > 0.0f)
			value = (std::max)(value, obs_mul_to_db(peak[channel]));
	static_cast<std::atomic<float> *>(param)->store(value);
}
#endif
} // namespace

struct ProductSceneSource {
	obs_source_t *source = nullptr;
	SceneSource configuration;
	ProductCamera camera;
	std::string document_id;
	std::string settings;
	std::vector<FilterState> filters;
#ifdef WEBOBS_NATIVE_PRODUCT_MODE
	std::unique_ptr<QProcess> audio_mix_process;
	obs_source_t *audio_source = nullptr;
	std::string audio_settings;
	obs_volmeter_t *audio_volmeter = nullptr;
	std::atomic<float> audio_peak_db{-120.0f};
	QByteArray audio_mix_log;
#endif
	bool intact() const
	{
		const bool mixed = mixed_audio(configuration);
		const bool main_silent = explicit_audio(configuration);
		const auto expected_monitoring = main_silent ? OBS_MONITORING_TYPE_NONE : monitoring(configuration);
		const auto expected_mixers = main_silent ? 0u : audio_mixers(configuration);
		const auto expected_volume = main_silent ? 0.0f : float(configuration.volume);
		const auto expected_sync = main_silent ? 0 : std::int64_t(configuration.sync_offset_ms) * 1000000;
		if (!(source && !obs_source_removed(source) && settings_json(source) == settings &&
			filters_state(source) == filters && obs_source_muted(source) == (main_silent || configuration.muted) &&
			obs_source_get_volume(source) == expected_volume &&
			obs_source_get_sync_offset(source) == expected_sync &&
			obs_source_get_audio_mixers(source) == expected_mixers &&
			obs_source_get_monitoring_type(source) == expected_monitoring))
			return false;
#ifdef WEBOBS_NATIVE_PRODUCT_MODE
		if (!mixed)
			return true;
		return audio_source && !obs_source_removed(audio_source) && audio_mix_process &&
			audio_mix_process->state() == QProcess::Running && settings_json(audio_source) == audio_settings &&
			obs_source_get_volume(audio_source) == float(configuration.volume) &&
			obs_source_muted(audio_source) == configuration.muted &&
			obs_source_get_sync_offset(audio_source) ==
				std::int64_t(configuration.sync_offset_ms - audio_normalization(configuration)) * 1000000 &&
			obs_source_get_audio_mixers(audio_source) == audio_mixers(configuration) &&
			obs_source_get_monitoring_type(audio_source) == monitoring(configuration);
#else
		return true;
#endif
	}
	~ProductSceneSource()
	{
		if (!source) return;
#ifdef WEBOBS_NATIVE_PRODUCT_MODE
		if (audio_volmeter) {
			obs_volmeter_remove_callback(audio_volmeter, audio_meter_callback, &audio_peak_db);
			obs_volmeter_detach_source(audio_volmeter);
			obs_volmeter_destroy(audio_volmeter);
			audio_volmeter = nullptr;
		}
		if (audio_source) {
			obs_source_remove(audio_source);
			obs_source_release(audio_source);
			audio_source = nullptr;
		}
		if (audio_mix_process && audio_mix_process->state() != QProcess::NotRunning) {
			audio_mix_process->write("q\n");
			if (!audio_mix_process->waitForFinished(1500)) {
				audio_mix_process->kill();
				audio_mix_process->waitForFinished(1500);
			}
		}
		audio_mix_process.reset();
#endif
		// OBS/frontend can retain deferred references after our last graph. Strip
		// the private endpoint before removing the owned source in that case too.
		Data empty(obs_data_create(), &obs_data_release);
		obs_data_set_bool(empty.get(), "is_local_file", false);
		obs_data_set_string(empty.get(), "input", "");
		obs_data_set_string(empty.get(), "local_file", "");
		obs_source_update(source, empty.get());
		obs_source_remove(source);
		obs_source_release(source);
	}
#ifdef WEBOBS_NATIVE_PRODUCT_MODE
	bool start_audio_mix(const ProductCamera &camera, std::string &error)
	{
		QString ffmpeg = qEnvironmentVariable("WEBOBS_FFMPEG_PATH");
		if (ffmpeg.isEmpty())
			ffmpeg = QDir(QCoreApplication::applicationDirPath()).absoluteFilePath("../../bin/ffmpeg.exe");
		if (!QFileInfo(ffmpeg).isFile()) {
			error = "scene-audio-mixer-unavailable";
			return false;
		}
		QTcpServer server;
		if (!server.listen(QHostAddress::LocalHost, 0)) {
			error = "scene-audio-mixer-port-failed";
			return false;
		}
		const int port = int(server.serverPort());
		server.close();
		QStringList arguments{"-hide_banner", "-loglevel", "error", "-nostats", "-nostdin"};
		const QUrl url(QString::fromStdString(camera.url));
		if (url.scheme() == "rtsp" || url.scheme() == "rtsps") {
			arguments << "-rtsp_transport"
				  << (camera.transport == "udp" ? "udp" : "tcp") << "-timeout"
				  << "8000000";
		}
		arguments << "-i" << QString::fromStdString(camera.url);
		const int normalization = audio_normalization(configuration);
		QString graph;
		QString labels;
		for (std::size_t index = 0; index < configuration.audio_inputs.size(); ++index) {
			const auto &input = configuration.audio_inputs[index];
			const int delay = (std::max)(0, normalization + input.sync_offset_ms);
			const double gain = input.muted ? 0.0 : input.gain;
			graph += QStringLiteral("[0:a:%1]adelay=delays=%2:all=1,volume=%3[m%4];")
					 .arg(input.track)
					 .arg(delay)
					 .arg(gain, 0, 'f', 4)
					 .arg(index);
			labels += QStringLiteral("[m%1]").arg(index);
		}
		graph += labels + QStringLiteral("amix=inputs=%1:normalize=0[amixed]")
					 .arg(configuration.audio_inputs.size());
		arguments << "-filter_complex" << graph << "-map" << "[amixed]" << "-vn" << "-c:a" << "aac"
			  << "-b:a" << "128k" << "-ar" << "48000" << "-ac" << "2" << "-f" << "mpegts"
			  << "-flush_packets" << "1"
			  << QStringLiteral("tcp://127.0.0.1:%1?listen=1").arg(port);
		auto process = std::make_unique<QProcess>();
		process->setProcessChannelMode(QProcess::MergedChannels);
		QProcessEnvironment environment = QProcessEnvironment::systemEnvironment();
		for (const auto &key : environment.keys())
			if (key.startsWith("WEBOBS_"))
				environment.remove(key);
		process->setProcessEnvironment(environment);
		process->start(ffmpeg, arguments);
		if (!process->waitForStarted(3000) || process->state() != QProcess::Running) {
			error = "scene-audio-mixer-start-failed";
			return false;
		}
		audio_mix_process = std::move(process);
		Data settings(obs_data_create(), &obs_data_release);
		obs_data_set_bool(settings.get(), "is_local_file", false);
		obs_data_set_string(settings.get(), "input",
			QStringLiteral("tcp://127.0.0.1:%1").arg(port).toUtf8().constData());
		obs_data_set_string(settings.get(), "input_format", "mpegts");
		// Audio-only media sources have no rendered surface and therefore
		// never acquire OBS's "showing" reference. The upstream ffmpeg_source
		// restart-on-activate path deliberately refuses to start playback when
		// the source is not showing, which would leave the local mixer unread.
		// Start with the owned graph instead: the source lives exactly as long
		// as this graph and is removed by the destructor.
		obs_data_set_bool(settings.get(), "restart_on_activate", false);
		obs_data_set_bool(settings.get(), "close_when_inactive", false);
		obs_data_set_int(settings.get(), "buffering_mb", 1);
		obs_data_set_int(settings.get(), "reconnect_delay_sec", 2);
		const std::string name = "WebOBS audio mix " + camera.id;
		audio_source = obs_source_create("ffmpeg_source", name.c_str(), settings.get(), nullptr);
		if (!audio_source) {
			audio_mix_process.reset();
			error = "scene-audio-mixer-source-failed";
			return false;
		}
		obs_source_set_volume(audio_source, float(configuration.volume));
		obs_source_set_muted(audio_source, configuration.muted);
		obs_source_set_sync_offset(audio_source,
			std::int64_t(configuration.sync_offset_ms - normalization) * 1000000);
		obs_source_set_audio_mixers(audio_source, audio_mixers(configuration));
		obs_source_set_monitoring_type(audio_source, monitoring(configuration));
		audio_settings = settings_json(audio_source);
		audio_volmeter = obs_volmeter_create(OBS_FADER_LOG);
		if (!audio_volmeter || !obs_volmeter_attach_source(audio_volmeter, audio_source)) {
			if (audio_volmeter) {
				obs_volmeter_destroy(audio_volmeter);
				audio_volmeter = nullptr;
			}
			obs_source_remove(audio_source);
			obs_source_release(audio_source);
			audio_source = nullptr;
			audio_mix_process.reset();
			error = "scene-audio-meter-unavailable";
			return false;
		}
		obs_volmeter_add_callback(audio_volmeter, audio_meter_callback, &audio_peak_db);
		return true;
	}
#endif
};

std::shared_ptr<ProductSceneSource> ProductSourcePool::acquire(const std::string &owner,
	const SceneSource &configuration, const ProductCamera &camera, std::string &error)
{
	std::erase_if(entries_, [](const auto &entry) { return entry.expired(); });
	if (!valid_owner(owner) || (!entries_.empty() && owner_ != owner)) {
		error = "scene-owner-mismatch";
		return {};
	}
	owner_ = owner;
	const std::string document_id = configuration.id;
	auto key = configuration;
	key.id.clear();
	key.name.clear();
	// These fields belong to browser sources in the persisted schema. Live
	// cameras must keep playing for AUX-only Scene projectors too: OBS Media
	// Source's restart-on-activate also STOPS playback on Program deactivation.
	// Owned graph lifetime, rather than Program activation, stops protected I/O.
	key.shutdown_when_hidden = false;
	key.restart_when_active = false;
	if (key.audio_inputs_explicit && key.audio_inputs.empty()) {
		// Explicit [] is the existing schema's "contributes no audio" policy.
		// Retain video decoding, with neither output-bus nor monitor contribution.
		key.muted = true;
		key.volume = 0;
		key.monitoring = "off";
		key.audio_track = 1;
		key.sync_offset_ms = 0;
	}
	for (auto &weak : entries_) {
		auto entry = weak.lock();
		if (entry && entry->configuration == key && same_camera(entry->camera, camera)) {
			if (!entry->intact()) {
				error = "scene-source-modified";
				return {};
			}
			entry->document_id = document_id;
			return entry;
		}
	}
	if (entries_.size() >= 256) {
		error = "scene-live-source-limit";
		return {};
	}
	auto entry = std::make_shared<ProductSceneSource>();
	entry->configuration = key;
	entry->camera = camera;
	entry->document_id = document_id;
	entry->source = create_product_camera_source(camera, key.shutdown_when_hidden, key.restart_when_active);
	if (!entry->source) {
		error = "scene-source-create-failed";
		return {};
	}
	const bool main_silent = explicit_audio(key);
	obs_source_set_muted(entry->source, main_silent || key.muted);
	obs_source_set_volume(entry->source, main_silent ? 0.0f : float(key.volume));
	obs_source_set_sync_offset(entry->source,
		main_silent ? 0 : std::int64_t(key.sync_offset_ms) * 1000000);
	obs_source_set_audio_mixers(entry->source, main_silent ? 0u : audio_mixers(key));
	obs_source_set_monitoring_type(entry->source,
		main_silent ? OBS_MONITORING_TYPE_NONE : monitoring(key));
	if (!attach_obs_source_filters(entry->source, configuration, camera.name)) {
		error = "scene-filter-create-failed";
		return {};
	}
	entry->settings = settings_json(entry->source);
	entry->filters = filters_state(entry->source);
#ifdef WEBOBS_NATIVE_PRODUCT_MODE
	if (mixed_audio(key) && !entry->start_audio_mix(camera, error))
		return {};
#endif
	entries_.push_back(entry);
	return entry;
}

ProductSceneGraph::~ProductSceneGraph()
{
	if (scene) {
		obs_scene_enum_items(scene, [](obs_scene_t *, obs_sceneitem_t *item, void *) {
			obs_sceneitem_set_visible(item, false);
			obs_sceneitem_remove(item);
			return true;
		}, nullptr);
		obs_source_remove(obs_scene_get_source(scene));
		obs_scene_release(scene);
	}
	// Source destruction occurs only when no other graph uses the same entry.
	sources_.clear();
}

std::vector<ProductVideoProgress> ProductSceneGraph::video_progress() const
{
	std::vector<ProductVideoProgress> result;
	for (const auto &entry : sources_) {
		if (!entry || !entry->source || obs_source_removed(entry->source)) continue;
		const std::string uuid = obs_source_get_uuid(entry->source);
		if (std::any_of(result.begin(), result.end(), [&](const auto &item) { return item.uuid == uuid; })) continue;
		calldata_t data;
		calldata_init(&data);
		const bool called = proc_handler_call(obs_source_get_proc_handler(entry->source),
			"webobs_get_video_progress", &data);
		long long schema = 0, serial = -1;
		const bool available = called && calldata_get_int(&data, "schema", &schema) && schema == 1 &&
			calldata_get_int(&data, "serial", &serial) && serial >= 0;
		result.push_back({uuid, available, available ? serial : 0});
		calldata_free(&data);
	}
	return result;
}

std::vector<ProductAudioProgress> ProductSceneGraph::audio_progress()
{
	std::vector<ProductAudioProgress> result;
#ifdef WEBOBS_NATIVE_PRODUCT_MODE
	for (const auto &entry : sources_) {
		if (!entry || !entry->audio_source || !entry->audio_mix_process)
			continue;
		entry->audio_mix_log.append(entry->audio_mix_process->readAll());
		if (entry->audio_mix_log.size() > 512)
			entry->audio_mix_log = entry->audio_mix_log.right(512);
		std::string log = entry->audio_mix_log.toStdString();
		for (std::size_t at = log.find("://"); at != std::string::npos; at = log.find("://", at)) {
			const std::size_t begin = log.rfind(' ', at);
			const std::size_t start = begin == std::string::npos ? 0 : begin + 1;
			std::size_t end = log.find_first_of(" \r\n\t", at + 3);
			if (end == std::string::npos) end = log.size();
			log.replace(start, end - start, "<url>");
			at = start + 5;
		}
		result.push_back({entry->document_id,
			entry->audio_mix_process->state() == QProcess::Running,
			obs_source_active(entry->audio_source),
			obs_source_showing(entry->audio_source),
			entry->audio_mix_process->state() == QProcess::NotRunning ? entry->audio_mix_process->exitCode() : -1,
			entry->audio_peak_db.load(std::memory_order_relaxed),
			int(obs_source_media_get_state(entry->audio_source)),
			double(obs_source_get_volume(entry->audio_source)),
			obs_source_muted(entry->audio_source),
			unsigned(obs_source_get_audio_mixers(entry->audio_source)),
			std::int64_t(obs_source_get_sync_offset(entry->audio_source)),
			std::move(log)});
	}
#endif
	return result;
}

std::unique_ptr<ProductSceneGraph> create_product_scene(ProductSourcePool &pool,
	const std::string &owner, const SceneDocument &document,
	const std::vector<ProductCamera> &bindings, std::string &error)
{
	error.clear();
	if (!valid_owner(owner) || validate_scene_document(document).has_value() ||
	    document.sources.empty() || bindings.size() != document.sources.size() ||
	    document.canvas.background_color != "#000000") {
		error = "scene-document-invalid";
		return {};
	}
	// Whole-document preflight precedes scene/source creation, including the
	// final binding. Never accept a raw URL or a partially resolved camera set.
	obs_video_info video{};
	if (!obs_get_video_info(&video) || video.base_width != unsigned(document.canvas.width) ||
	    video.base_height != unsigned(document.canvas.height)) {
		error = "scene-canvas-not-applied";
		return {};
	}
	std::map<std::pair<std::string, std::string>, const ProductCamera *> resolved;
	for (std::size_t i = 0; i < document.sources.size(); ++i) {
		const auto &source = document.sources[i];
		const auto &camera = bindings[i];
		if (source.kind != "camera" || source.camera_id != camera.id ||
		    source.profile_id != camera.profile_id || source.transport != camera.transport ||
		    source.hardware_decode != (camera.hardware_decode.has_value() ?
			(*camera.hardware_decode ? "on" : "off") : "auto") || !valid_product_camera(camera, error)) {
			error = "scene-camera-binding-invalid";
			return {};
		}
		const auto [existing, inserted] = resolved.emplace(std::make_pair(camera.id, camera.profile_id), &camera);
		if (!inserted && !same_camera(*existing->second, camera)) {
			error = "scene-camera-binding-conflict";
			return {};
		}
#ifndef WEBOBS_NATIVE_PRODUCT_MODE
		const bool unresolved_audio = !source.audio_inputs.empty();
#else
		const bool unresolved_audio = false;
#endif
		if (unresolved_audio ||
		    std::any_of(source.filters.begin(), source.filters.end(), [](const auto &filter) {
			return filter.kind == "lut" || filter.kind == "mask-blend";
		    })) {
			error = "scene-routing-or-asset-unresolved";
			return {};
		}
	}
	auto graph = std::make_unique<ProductSceneGraph>();
	std::map<std::string, obs_source_t *> by_id;
	for (std::size_t i = 0; i < document.sources.size(); ++i) {
		auto entry = pool.acquire(owner, document.sources[i], bindings[i], error);
		if (!entry) return {};
		by_id.emplace(document.sources[i].id, entry->source);
		graph->uuids.emplace_back(obs_source_get_uuid(entry->source));
		graph->sources_.push_back(std::move(entry));
	}
	static std::atomic_uint64_t sequence = 0;
	const auto name = "WebOBS scene " + document.id + " " + std::to_string(sequence.fetch_add(1));
	graph->scene = obs_scene_create(name.c_str());
	if (!graph->scene) {
		error = "scene-create-failed";
		return {};
	}
	std::vector<const SceneItem *> ordered;
	for (const auto &item : document.items) ordered.push_back(&item);
	std::sort(ordered.begin(), ordered.end(), [](const auto *a, const auto *b) { return a->z_index < b->z_index; });
	for (const auto *item : ordered) {
		if (!add_obs_scene_item(graph->scene, by_id.at(item->source_id), *item)) {
			error = "scene-item-create-failed";
			return {};
		}
	}
#ifdef WEBOBS_NATIVE_PRODUCT_MODE
	for (const auto &entry : graph->sources_) {
		if (!entry || !entry->audio_source)
			continue;
		if (!obs_scene_add(graph->scene, entry->audio_source)) {
			error = "scene-audio-item-create-failed";
			return {};
		}
		graph->audio_uuids.emplace_back(obs_source_get_uuid(entry->audio_source));
	}
#endif
	return graph;
}
} // namespace webobs::native_host
