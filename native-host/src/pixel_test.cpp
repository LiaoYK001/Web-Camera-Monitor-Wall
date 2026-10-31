// Deliberately absent from normal builds. Fixed synthetic fixtures and a finite
// local handshake only: no HTTP, arbitrary path, source URL or screenshot API.
#include "pixel_test.hpp"
#include "wall.hpp"
#include "layout.hpp"
#include <obs-module.h>
#include <util/config-file.h>
#include <QApplication>
#include <QCryptographicHash>
#include <QCoreApplication>
#include <QDir>
#include <QDockWidget>
#include <QElapsedTimer>
#include <QFile>
#include <QFileInfo>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QPointer>
#include <QRegularExpression>
#include <QSaveFile>
#include <QSet>
#include <QTimer>
#include <QWidget>
#include <QWindow>
#include <algorithm>
#include <array>
#include <cstring>
#include <stdexcept>
#include <vector>

namespace webobs::native_host {
namespace {
constexpr const char *pin = "fb4d98bf88fae5fc85cb11fc57f7c5e309282194";
using Sources = std::array<obs_source_t *, 5>;
const std::array<std::array<int, 3>, 5> colors{{{216, 50, 50}, {50, 200, 80}, {50, 100, 220}, {220, 190, 50}, {180, 60, 200}}};

QJsonObject read_object(const QString &path)
{
	QFile file(path);
	if (file.size() > 65536 || !file.open(QIODevice::ReadOnly))
		throw std::runtime_error("fixed test metadata unavailable or oversized");
	QJsonParseError error{};
	auto document = QJsonDocument::fromJson(file.readAll(), &error);
	if (error.error != QJsonParseError::NoError || !document.isObject())
		throw std::runtime_error("invalid fixed test metadata");
	return document.object();
}

void write_new(const QString &path, const QJsonObject &object)
{
	if (QFileInfo::exists(path))
		throw std::runtime_error("refusing stale test metadata");
	QSaveFile file(path);
	const auto bytes = QJsonDocument(object).toJson(QJsonDocument::Compact);
	if (!file.open(QIODevice::WriteOnly) || file.write(bytes) != bytes.size() || !file.commit())
		throw std::runtime_error("cannot publish fixed test metadata");
}

QByteArray settings_hash(obs_source_t *source)
{
	auto *settings = obs_source_get_settings(source);
	const QByteArray json(obs_data_get_json(settings));
	obs_data_release(settings);
	return QCryptographicHash::hash(json, QCryptographicHash::Sha256).toHex();
}

struct Snapshot {
	unsigned ffmpeg = 0, inputs = 0, active_outputs = 0, active_encoders = 0;
	std::vector<obs_source_t *> media;
	~Snapshot() { for (auto *source : media) obs_source_release(source); }
	Snapshot()
	{
		// Includes private inputs/Studio clones. Retain refs under enumeration;
		// perform identity/settings work only after the source mutex is released.
		obs_enum_all_sources([](void *data, obs_source_t *source) {
			auto &self = *static_cast<Snapshot *>(data);
			if (obs_source_get_type(source) == OBS_SOURCE_TYPE_INPUT) ++self.inputs;
			if (std::strcmp(obs_source_get_unversioned_id(source), "ffmpeg_source") == 0) {
				++self.ffmpeg;
				self.media.push_back(obs_source_get_ref(source));
			}
			return true;
		}, this);
		obs_enum_outputs([](void *data, obs_output_t *output) {
			if (obs_output_active(output)) ++static_cast<Snapshot *>(data)->active_outputs;
			return true;
		}, this);
		obs_enum_encoders([](void *data, obs_encoder_t *encoder) {
			if (obs_encoder_active(encoder)) ++static_cast<Snapshot *>(data)->active_encoders;
			return true;
		}, this);
	}
	bool idle() const
	{
		return !active_outputs && !active_encoders && !obs_video_active() &&
		       !obs_frontend_streaming_active() && !obs_frontend_recording_active() &&
		       !obs_frontend_replay_buffer_active() && !obs_frontend_virtualcam_active();
	}
};

class Harness final : public QObject {
	QPointer<QWidget> main_, preview_, program_;
	QString directory_, token_;
	QTimer timer_;
	QElapsedTimer clock_;
	qint64 changed_at_ = 0, ready_at_ = -1;
	Sources color_{}, media_{};
	std::array<QByteArray, 5> hashes_{};
	std::array<std::string, 5> uuids_{};
	obs_scene_t *known_ = nullptr, *a_ = nullptr, *b_ = nullptr;
	int phase_ = 0, generation_ = 0;
	bool published_ = false, closing_ = false, take_stopped_ = false, reopening_ = false;

	void require(bool value, const char *message) const
	{
		if (!value) throw std::runtime_error(message);
	}
	void close_normal()
	{
		closing_ = true;
		timer_.stop();
		if (program_) program_->close();
		if (main_) QTimer::singleShot(0, main_, [window = main_] { if (window) window->close(); });
	}
	void fail(const char *message)
	{
		try {
			write_new(directory_ + "/failed.json", {{"schema", 1}, {"phase", phase_}, {"error", QString::fromUtf8(message)}});
		} catch (...) { /* The external owned-process deadline still fails closed. */ }
		close_normal();
	}
	void open_program()
	{
		const auto before = QApplication::topLevelWidgets();
		obs_frontend_open_projector("StudioProgram", -1, nullptr, nullptr);
		QWidget *found = nullptr;
		for (auto *widget : QApplication::topLevelWidgets()) {
			if (!before.contains(widget) && std::strcmp(widget->metaObject()->className(), "OBSProjector") == 0 &&
			    widget->windowHandle() && widget->windowHandle()->property("isOBSProjectorWindow").toBool()) {
				require(!found, "ambiguous new native Program projector");
				found = widget;
			}
		}
		require(found, "native Program projector identity unavailable");
		program_ = found;
		++generation_;
	}
	void initialize()
	{
		require(main_, "OBS main window unavailable");
		auto previews = main_->findChildren<QWidget *>("preview");
		for (auto *widget : previews) {
			if (std::strcmp(widget->metaObject()->className(), "OBSBasicPreview") == 0) {
				require(!preview_, "ambiguous OBS main Preview widget");
				preview_ = widget;
			}
		}
		require(preview_, "real OBSBasicPreview widget unavailable (not a projector substitute)");
		for (auto *dock : main_->findChildren<QDockWidget *>()) dock->hide();
		main_->showMaximized();
		obs_frontend_set_preview_program_mode(false);
		obs_frontend_set_preview_enabled(true);
		auto *config = obs_frontend_get_profile_config();
		require(config, "portable profile config unavailable");
		config_set_uint(config, "Video", "BaseCX", 960); config_set_uint(config, "Video", "BaseCY", 540);
		config_set_uint(config, "Video", "OutputCX", 960); config_set_uint(config, "Video", "OutputCY", 540);
		config_set_uint(config, "Video", "FPSType", 0); config_set_string(config, "Video", "FPSCommon", "30");
		obs_frontend_reset_video();
		obs_video_info info{};
		require(obs_get_video_info(&info) && info.base_width == 960 && info.base_height == 540,
		        "fixed 960x540 canvas could not be configured");
		const char *color_id = obs_get_latest_input_type_id("color_source");
		require(color_id, "official OBS color source unavailable");
		known_ = obs_scene_create("Synthetic known colors");
		require(known_, "known-color scene unavailable");
		const auto tiles = five_tile_layout(960, 540);
		for (std::size_t i = 0; i < color_.size(); ++i) {
			auto *settings = obs_data_create();
			const auto &rgb = colors[i];
			obs_data_set_int(settings, "color", 0xff000000u | unsigned(rgb[2] << 16) | unsigned(rgb[1] << 8) | unsigned(rgb[0]));
			obs_data_set_int(settings, "width", 320); obs_data_set_int(settings, "height", 180);
			const auto name = "Synthetic color " + std::to_string(i + 1);
			color_[i] = obs_source_create(color_id, name.c_str(), settings, nullptr);
			obs_data_release(settings);
			require(color_[i], "official known-color input creation failed");
			auto *item = obs_scene_add(known_, color_[i]);
			require(item, "known-color item creation failed");
			vec2 pos{float(tiles[i].x), float(tiles[i].y)}, bounds{float(tiles[i].width), float(tiles[i].height)};
			obs_sceneitem_set_alignment(item, OBS_ALIGN_LEFT | OBS_ALIGN_TOP);
			obs_sceneitem_set_bounds_alignment(item, 0); obs_sceneitem_set_bounds_type(item, OBS_BOUNDS_SCALE_INNER);
			obs_sceneitem_set_bounds(item, &bounds); obs_sceneitem_set_pos(item, &pos); obs_sceneitem_select(item, false);
		}
		select_wall(known_);
		open_program();
	}
	void create_media()
	{
		for (std::size_t i = 0; i < media_.size(); ++i) {
			const QString path = directory_ + QString("/fixture-%1.mkv").arg(i + 1);
			const QFileInfo file(path);
			require(file.isFile() && !file.isSymLink() && file.size() > 0 && file.size() <= 32 * 1024 * 1024 &&
			        file.canonicalPath().compare(directory_, Qt::CaseInsensitive) == 0, "fixed local HEVC fixture unavailable");
			auto *settings = obs_data_create();
			const auto utf8 = file.canonicalFilePath().toUtf8();
			obs_data_set_bool(settings, "is_local_file", true); obs_data_set_string(settings, "local_file", utf8.constData());
			obs_data_set_bool(settings, "looping", true); obs_data_set_bool(settings, "hw_decode", false);
			obs_data_set_bool(settings, "restart_on_activate", false); obs_data_set_bool(settings, "close_when_inactive", false);
			const auto name = "Synthetic independent HEVC " + std::to_string(i + 1);
			media_[i] = obs_source_create("ffmpeg_source", name.c_str(), settings, nullptr);
			obs_data_release(settings);
			require(media_[i], "independent HEVC Media Source creation failed");
			uuids_[i] = obs_source_get_uuid(media_[i]); hashes_[i] = settings_hash(media_[i]);
		}
		auto result = create_five_tile_wall(uuids_);
		a_ = result.scene;
		require(a_, "real five-tile wall A creation failed");
		auto reversed = uuids_; std::reverse(reversed.begin(), reversed.end());
		result = create_five_tile_wall(reversed); b_ = result.scene;
		require(b_, "real five-tile wall B creation failed");
		select_wall(a_);
	}
	bool scene_is(obs_source_t *(*getter)(), obs_scene_t *expected) const
	{
		auto *source = getter();
		const bool equal = source == obs_scene_get_source(expected);
		obs_source_release(source);
		return equal;
	}
	bool identities(Snapshot &snapshot)
	{
		if (phase_ == 1) return snapshot.ffmpeg == 0;
		if (snapshot.ffmpeg != 5 || snapshot.media.size() != 5) return false;
		for (std::size_t i = 0; i < media_.size(); ++i) {
			if (std::find(snapshot.media.begin(), snapshot.media.end(), media_[i]) == snapshot.media.end() ||
			    uuids_[i] != obs_source_get_uuid(media_[i]) || hashes_[i] != settings_hash(media_[i])) return false;
		}
		struct Items { const Sources *sources; bool reversed; std::size_t count = 0; bool valid = true; };
		for (int reverse = 0; reverse < 2; ++reverse) {
			Items items{&media_, reverse != 0};
			obs_scene_enum_items(reverse ? b_ : a_, [](obs_scene_t *, obs_sceneitem_t *item, void *data) {
				auto &list = *static_cast<Items *>(data);
				if (list.count >= 5) { list.valid = false; return false; }
				const auto i = list.reversed ? 4 - list.count : list.count;
				if (obs_sceneitem_get_source(item) != (*list.sources)[i]) list.valid = false;
				obs_sceneitem_select(item, false); ++list.count;
				return true;
			}, &items);
			if (!items.valid || items.count != 5) return false;
		}
		return true;
	}
	bool ready()
	{
		if (phase_ == 1) return scene_is(obs_frontend_get_current_scene, known_);
		for (auto *source : media_) {
			if (!source || obs_source_media_get_state(source) != OBS_MEDIA_STATE_PLAYING ||
			    obs_source_get_width(source) != 320 || obs_source_get_height(source) != 180) return false;
		}
		if (phase_ == 2) return !obs_frontend_preview_program_mode_active() && scene_is(obs_frontend_get_current_scene, a_);
		if (phase_ == 3) return obs_frontend_preview_program_mode_active() && scene_is(obs_frontend_get_current_scene, a_) &&
		                      scene_is(obs_frontend_get_current_preview_scene, b_);
		return take_stopped_ && scene_is(obs_frontend_get_current_scene, b_) && scene_is(obs_frontend_get_current_preview_scene, a_);
	}
	QJsonObject window(QWidget *widget, const char *role, int inset) const
	{
		require(widget && widget->isVisible(), "native capture widget not visible");
		const auto handle = QString::number(qulonglong(widget->winId()), 16);
		const auto root = QString::number(qulonglong(widget->window()->winId()), 16);
		return {{"role", QString::fromLatin1(role)}, {"hwnd", handle}, {"rootHwnd", root}, {"canvasInsetPixels", inset},
		        {"qtClass", QString::fromLatin1(widget->metaObject()->className())}};
	}
	void publish(Snapshot &snapshot)
	{
		require(QMetaObject::invokeMethod(main_, "setPreviewScalingWindow", Qt::DirectConnection), "Preview fit-to-window slot unavailable");
		QJsonArray ids;
		if (phase_ > 1) for (std::size_t i = 0; i < media_.size(); ++i)
			ids.append(QJsonObject{{"uuid", QString::fromStdString(uuids_[i])}, {"settingsSha256", QString::fromLatin1(hashes_[i])}});
		const char *names[] = {"", "known-colors", "five-hevc", "studio-preview-no-take", "explicit-take", "program-reopened"};
		const QJsonObject state{{"schema", 1}, {"seq", phase_}, {"phase", QString::fromLatin1(names[phase_])}, {"token", token_},
		                       {"pid", QString::number(QCoreApplication::applicationPid())}, {"canvasWidth", 960}, {"canvasHeight", 540},
		                       {"studio", obs_frontend_preview_program_mode_active()}, {"transitionStopped", take_stopped_},
		                       {"programGeneration", generation_}, {"elapsedMs", double(clock_.elapsed())},
		                       {"globalFfmpegInputsIncludingPrivate", int(snapshot.ffmpeg)}, {"globalInputCountIncludingPrivate", int(snapshot.inputs)},
		                       {"activeOutputs", int(snapshot.active_outputs)}, {"activeEncoders", int(snapshot.active_encoders)},
		                       {"rawVideoActive", obs_video_active()}, {"sameInputPointersAndSettings", true}, {"sources", ids},
		                       {"windows", QJsonArray{window(preview_, "main-preview", 10), window(program_, "program-projector", 0)}},
		                       {"pixelQualified", false}, {"scope", "synthetic-test-only"}};
		write_new(directory_ + QString("/phase-%1.json").arg(phase_, 2, 10, QLatin1Char('0')), state);
		published_ = true;
	}
	void advance()
	{
		++phase_; published_ = false; ready_at_ = -1; changed_at_ = clock_.elapsed();
		if (phase_ == 1) initialize();
		else if (phase_ == 2) create_media();
		else if (phase_ == 3) { obs_frontend_set_preview_program_mode(true); select_wall(b_); }
		else if (phase_ == 4) { take_stopped_ = false; obs_frontend_preview_program_trigger_transition(); }
		else if (phase_ == 5) { require(program_, "Program projector lost before reopen"); program_->close(); reopening_ = true; }
		else {
			write_new(directory_ + "/complete.json", {{"schema", 1}, {"phases", 5}, {"syntheticOnly", true}, {"pixelQualified", false}});
			close_normal();
		}
	}
	void tick()
	{
		if (closing_) return;
		try {
			require(clock_.elapsed() < 240000, "finite test deadline exceeded");
			Snapshot snapshot;
			require(snapshot.idle(), "unexpected active OBS encoder/output/raw consumer");
			if (reopening_) {
				if (program_) return;
				reopening_ = false; open_program();
			}
			require(identities(snapshot), "input pointer/UUID/settings/global private-input identity changed");
			if (!published_) {
				require(clock_.elapsed() - changed_at_ < 30000, "bounded scene/media state readiness timed out");
				if (!ready()) { ready_at_ = -1; return; }
				if (ready_at_ < 0) ready_at_ = clock_.elapsed();
				// Declared warmup, never a retry after a failed screenshot. PLAYING is
				// not proof of pixels; only the external all-sample analyzer qualifies.
				if (clock_.elapsed() - ready_at_ < 1500) return;
				publish(snapshot);
				return;
			}
			const QString path = directory_ + QString("/ack-%1.json").arg(phase_, 2, 10, QLatin1Char('0'));
			if (!QFileInfo::exists(path)) return;
			const auto ack = read_object(path);
			require(ack.size() == 3 && ack.value("schema").toInt() == 1 && ack.value("seq").toInt() == phase_ &&
			        ack.value("token").toString() == token_, "invalid finite phase acknowledgement");
			advance();
		} catch (const std::exception &error) { fail(error.what()); }
	}
public:
	Harness(QWidget *main, QString directory, QString token)
		: QObject(main), main_(main), directory_(std::move(directory)), token_(std::move(token))
	{
		clock_.start();
		QObject::connect(&timer_, &QTimer::timeout, this, [this] { tick(); });
		try { advance(); timer_.start(100); }
		catch (const std::exception &error) { fail(error.what()); }
	}
	~Harness() override
	{
		timer_.stop();
		obs_scene_release(known_); obs_scene_release(a_); obs_scene_release(b_);
		for (auto *source : media_) obs_source_release(source);
		for (auto *source : color_) obs_source_release(source);
	}
	void transition_stopped() { if (phase_ == 4) take_stopped_ = true; }
};
QPointer<Harness> harness;
} // namespace

bool pixel_test_event(enum obs_frontend_event event)
{
	if (event == OBS_FRONTEND_EVENT_EXIT) { delete harness.data(); harness = nullptr; return false; }
	if (harness) {
		if (event == OBS_FRONTEND_EVENT_TRANSITION_STOPPED) harness->transition_stopped();
		return true;
	}
	if (event != OBS_FRONTEND_EVENT_FINISHED_LOADING) return false;
	const QString token = qEnvironmentVariable("WEBOBS_NATIVE_PIXEL_TOKEN");
	if (!QRegularExpression("^[0-9a-f]{32}$").match(token).hasMatch()) return false;
	try {
		const QDir bin(QCoreApplication::applicationDirPath());
		const QString root = QFileInfo(bin.absoluteFilePath("../..")).canonicalFilePath();
		const QString profile = QFileInfo(root + "/config/obs-studio").canonicalFilePath();
		const QString directory = QFileInfo(profile + "/native-pixel-test").canonicalFilePath();
		char *module_path = obs_module_config_path("");
		const QString actual = module_path ? QDir::cleanPath(QFileInfo(QString::fromUtf8(module_path)).absoluteFilePath()) : QString{};
		bfree(module_path);
		if (root.isEmpty() || profile.isEmpty() || directory.isEmpty() ||
		    directory.compare(profile + "/native-pixel-test", Qt::CaseInsensitive) != 0 ||
		    actual.compare(profile + "/plugin_config/webobs-native-host", Qt::CaseInsensitive) != 0) return false;
		const auto manifest = read_object(root + "/webobs-native-prototype.json");
		const auto build = read_object(root + "/webobs-native-pixel-test-build.json");
		const auto request = read_object(directory + "/request.json");
		if (manifest.value("obsCommit").toString() != pin || manifest.value("defaultProduct").toBool(true) ||
		    !manifest.value("pixelTestBuild").toBool() || !manifest.value("redistributable").isBool() || manifest.value("redistributable").toBool(true) ||
		    !build.value("pixelTestBuild").toBool() || build.value("redistributable").toBool(true) ||
		    request.size() != 2 || request.value("schema").toInt() != 1 || request.value("token").toString() != token ||
		    QFileInfo::exists(directory + "/claimed.json") || QFileInfo::exists(directory + "/phase-01.json")) return false;
		if (!QFile::rename(directory + "/request.json", directory + "/claimed.json")) return false;
		harness = new Harness(static_cast<QWidget *>(obs_frontend_get_main_window()), directory, token);
		return true;
	} catch (...) { return false; } // Malformed test opt-in cannot mutate an ordinary profile.
}
} // namespace webobs::native_host
