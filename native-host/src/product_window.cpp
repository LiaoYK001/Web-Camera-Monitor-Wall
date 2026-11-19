#include "product_window.hpp"
#include "product_bootstrap.hpp"
#include "product_http_client.hpp"
#include "product_output.hpp"
#include "product_scene.hpp"
#include "renderer_device_qt.hpp"
#include "layout.hpp"
#include "projector_placement.hpp"
#include "wall.hpp"

#include <obs-frontend-api.h>
#include <obs-module.h>
#include <util/platform.h>
#include <QAction>
#include <QApplication>
#include <QCloseEvent>
#include <QComboBox>
#include <QCoreApplication>
#include <QDateTime>
#include <QDesktopServices>
#include <QElapsedTimer>
#include <QEvent>
#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QFormLayout>
#include <QHBoxLayout>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QLabel>
#include <QLineEdit>
#include <QKeyEvent>
#include <QMenu>
#include <QMouseEvent>
#include <QPointer>
#include <QPushButton>
#include <QRegularExpression>
#include <QSaveFile>
#include <QScreen>
#include <QSignalBlocker>
#include <QSpinBox>
#include <QStandardItemModel>
#include <QScrollArea>
#include <QStringList>
#include <QSystemTrayIcon>
#include <QThread>
#include <QTimer>
#include <QUrl>
#include <QUrlQuery>
#include <QVBoxLayout>
#include <QWidget>

#include <algorithm>
#include <array>
#include <atomic>
#include <cstdint>
#include <functional>
#include <memory>
#include <map>
#include <mutex>
#include <set>
#include <tuple>
#include <vector>

namespace webobs::native_host {
namespace {
class ProductWindow;
QPointer<ProductWindow> product_window;

class ProductWindow final : public QWidget {
	QWidget *frontend_;
	QWidget *preview_ = nullptr;
	std::unique_ptr<ProductHttpClient> client_;
	QTimer heartbeat_;
	QTimer program_sync_;
	QTimer retirement_;
	QTimer settlement_;
	QTimer placement_save_;
	QJsonObject projector_placements_;
	QElapsedTimer settlement_elapsed_;
	QElapsedTimer retirement_elapsed_;
	QUrl origin_;
	QByteArray host_secret_;
	QLineEdit *username_, *password_;
	QLabel *status_;
	QLabel *video_health_;
	QLabel *audio_health_;
	QLabel *renderer_label_;
	RendererDevice renderer_device_;
	QElapsedTimer health_clock_;
	struct InputHealth { std::int64_t serial = 0; qint64 changed_ms = 0; bool sampled = false, advanced = false; };
	std::map<std::string, InputHealth> input_health_;
	// Test-only (WEBOBS_PRODUCT_RENDER_PROBE=1): the product draws the preview Scene and
	// the Program channel into its own textures and reports per-cell content digests.
	// A frozen tile then has a cause: the Scene render stayed identical, or it changed
	// while the captured window pixels stayed identical. Nothing here changes the Scene
	// graph, and the probe stays off unless the environment explicitly asks for it.
	struct RenderProbeSlot {
		gs_texrender_t *target = nullptr;
		gs_stagesurf_t *stage = nullptr;
		uint32_t width = 0, height = 0;
		bool staged = false;
		qint64 staged_frames = -1;
		qint64 staged_ms = 0;
		qint64 next_draw_ms = 0;
		QString scene;
	};
	struct RenderProbeSample {
		qint64 ms = 0;
		qint64 render_frames = -1;
		QString scene;
		QJsonArray cells;
	};
	bool render_probe_enabled_ = qEnvironmentVariable("WEBOBS_PRODUCT_RENDER_PROBE") == "1";
	bool render_probe_attached_ = false;
	int render_probe_ticks_ = 0;
	// The probe only draws inside a window the harness opens in a control file beside
	// product-state.json. Without an open window nothing is drawn, no source is marked
	// showing and no readback blocks the graphics thread, so the probe cannot revive a
	// feed, take async frames out of the queue or slow the Program encoder.
	std::atomic<qint64> render_probe_until_ms_{0};
	qint64 render_probe_control_checked_ms_ = 0;
	QString render_probe_control_path_;
	RenderProbeSlot render_probe_slots_[2];
	std::vector<RenderProbeSample> render_preview_samples_;
	std::vector<RenderProbeSample> render_program_samples_;
	std::mutex render_probe_mutex_;
	QPushButton *login_, *create_account_, *watch_, *save_, *logout_, *refresh_, *scene_watch_;
	QComboBox *scenes_ = nullptr;
	QSpinBox *slot_count_ = nullptr;
	QFormLayout *camera_form_ = nullptr;
	QStandardItemModel *camera_choices_ = nullptr;
	std::vector<QComboBox *> slots_;
	ProductSourcePool source_pool_;
	std::shared_ptr<ProductSceneGraph> wall_;
	std::shared_ptr<ProductSceneGraph> program_;
	QString program_scene_id_;
	QString program_fingerprint_;
	qint64 program_studio_revision_ = -1;
	qint64 program_reported_revision_ = -1;
	qint64 program_target_revision_ = -1;
	QString program_target_scene_id_;
	QString program_target_fingerprint_;
	QString program_apply_state_ = "idle";
	QString program_apply_error_;
	bool program_apply_transient_ = false;
	int program_apply_attempts_ = 0;
	bool program_sync_pending_ = false;
	quint64 program_generation_ = 0;
	obs_scene_t *blank_scene_ = nullptr;
	QString idle_program_uuid_;
	bool tearing_down_ = false;
	struct ProjectorView {
		quint64 id = 0;
		QPointer<QWidget> window;
		std::shared_ptr<ProductSceneGraph> graph;
		QJsonArray cameras;
		QJsonObject versions;
		QString scene_id;
		QString scene_fingerprint;
		qint64 studio_revision = -1;
		bool heartbeat_pending = false;
	};
	std::array<std::unique_ptr<ProjectorView>, 2> projectors_;
	std::array<QPushButton *, 2> projector_buttons_{};
	QPushButton *close_projectors_ = nullptr;
	QPushButton *program_projector_button_ = nullptr;
	QPointer<QWidget> program_projector_;
	std::unique_ptr<ProductProgramOutput> program_output_;
	QPushButton *record_program_ = nullptr;
	QPushButton *stream_program_ = nullptr;
	QLabel *output_health_ = nullptr;
	QPushButton *support_bundle_ = nullptr;
	QString last_support_bundle_;
	QString support_bundle_error_;
	QSystemTrayIcon *tray_ = nullptr;
	bool quitting_ = false;
	QPushButton *stats_button_ = nullptr;
	QPointer<QWidget> stats_window_;
	std::array<bool, 2> projector_pending_{};
	quint64 next_projector_id_ = 0;
	QJsonArray watching_;
	QJsonObject watching_versions_;
	QString watching_scene_id_;
	QString watching_scene_fingerprint_;
	qint64 watching_studio_revision_ = -1;
	QString user_id_;
	quint64 main_generation_ = 0;
	bool heartbeat_pending_ = false;
	// A heartbeat tick that arrives late means the UI thread was held somewhere else.
	// That is what makes a product control refuse UI Automation, so the observation has
	// to carry the real stall duration and when it ended instead of leaving the receipt
	// with only "the window was not addressable".
	static constexpr qint64 heartbeat_interval_ms = 2000;
	qint64 heartbeat_last_ms_ = 0;
	qint64 ui_stall_last_ms_ = 0;
	qint64 ui_stall_max_ms_ = 0;
	qint64 ui_stall_at_ms_ = 0;
	bool applying_ = false;
	int transient_renewals_ = 0;
	QString last_lock_ = QStringLiteral("none");
	int last_lock_code_ = 0;
	qint64 last_retirement_ms_ = 0;

	using Reply = std::function<void(int, const QJsonObject &)>;
	void refresh_renderer()
	{
		renderer_device_ = observe_renderer_device();
		QString adapter = tr("状态未知");
		if (renderer_device_.available) {
			if (renderer_device_.software) adapter = tr("软件适配器");
			else if (renderer_device_.vendor_id == 0x10de) adapter = "NVIDIA";
			else if (renderer_device_.vendor_id == 0x8086) adapter = "Intel";
			else if (renderer_device_.vendor_id == 0x1002) adapter = "AMD";
			else adapter = tr("其他适配器");
			adapter += " (D3D11)";
		}
		renderer_label_->setText(tr("画面渲染：%1").arg(adapter));
	}
	void refresh_video_health()
	{
		std::map<std::string, ProductVideoProgress> inputs;
		bool has_audio = false;
		int audio_count = 0;
		float audio_peak = -120.0f;
		std::set<std::string> audio_seen;
		auto collect = [&](const std::shared_ptr<ProductSceneGraph> &graph) {
			if (!graph) return;
			for (const auto &audio : graph->audio_progress()) {
				if (!audio_seen.insert(audio.source_id).second) continue;
				has_audio = true;
				++audio_count;
				audio_peak = (std::max)(audio_peak, audio.peak_dbfs);
			}
			for (const auto &input : graph->video_progress()) inputs.emplace(input.uuid, input);
		};
		collect(wall_);
		collect(program_);
		for (const auto &view : projectors_) if (view && view->window) collect(view->graph);
		std::erase_if(input_health_, [&](const auto &entry) { return !inputs.contains(entry.first); });
		int received = 0, progressing = 0, stalled = 0, unavailable = 0;
		const auto now = health_clock_.elapsed();
		for (const auto &[uuid, input] : inputs) {
			if (!input.available) { ++unavailable; input_health_.erase(uuid); continue; }
			auto &health = input_health_[uuid];
			if (!health.sampled || health.serial != input.serial) {
				health.advanced = health.sampled && health.serial != input.serial;
				health.serial = input.serial;
				health.changed_ms = now;
				health.sampled = true;
			}
			if (input.serial > 0) {
				++received;
				if (now - health.changed_ms >= 6000) ++stalled;
				else if (health.advanced) ++progressing;
			}
		}
		if (inputs.empty()) video_health_->setText(tr("视频输入：未监看"));
		else video_health_->setText(tr("视频输入：%1 路，已收帧 %2，近期推进 %3，停滞 %4，状态未知 %5。")
			.arg(inputs.size()).arg(received).arg(progressing).arg(stalled).arg(unavailable));
		if (audio_health_) {
			if (!has_audio) audio_health_->setText(tr("音频混音：无（空选择或未配置）"));
			else audio_health_->setText(tr("音频混音：%1 源，峰值 %2 dBFS")
				.arg(audio_count).arg(double(audio_peak), 0, 'f', 1));
		}
		if (has_audio && !tearing_down_ && !user_id_.isEmpty())
			observe_current_media();
	}
	void refresh_output_health()
	{
		if (!output_health_ || !program_output_) return;
		const auto value = program_output_->status();
		QStringList parts;
		if (value.recording)
			parts << tr("Program 录制中 %1 秒 · %2 MB")
				.arg(value.recording_seconds)
				.arg(QString::number(double(value.recording_bytes) / (1024.0 * 1024.0), 'f', 1));
		else if (value.recording_ready)
			parts << tr("最近 Program 录像已保存");
		if (value.streaming)
			parts << (value.stream_connected ? tr("Program 推流中") : tr("Program 推流连接中"));
		if (!value.recording_error.isEmpty())
			parts << tr("录像错误：%1").arg(value.recording_error);
		if (!value.stream_error.isEmpty())
			parts << tr("推流错误：%1").arg(value.stream_error);
		if (value.recording || value.streaming)
			parts << (value.audio_tracks ? tr("节目音轨掩码 %1").arg(QString::number(value.audio_tracks))
				: tr("节目无音轨"));
		output_health_->setText(parts.isEmpty() ? tr("Program 输出：空闲") : parts.join(" · "));
		if (record_program_)
			record_program_->setText(value.recording ? tr("停止 Program 录制") : tr("录制 Program"));
		if (stream_program_)
			stream_program_->setText(value.streaming ? tr("停止 Program 推流") : tr("推流 Program"));
	}
	void toggle_recording()
	{
		if (!program_output_ || user_id_.isEmpty()) return;
		QString error;
		const auto before = program_output_->status();
		if (before.recording) {
			if (!program_output_->stop_recording(error))
				status_->setText(tr("Program 录像停止失败：%1").arg(error));
			else
				status_->setText(tr("Program 录像已保存：%1").arg(program_output_->status().recording_path));
		} else {
			if (!program_ || program_apply_state_ != "applied") {
				status_->setText(tr("请先应用并确认 Program 场景，再开始录制。"));
				return;
			}
			// The recording must encode the tracks the applied Program actually
			// uses; a fixed track 0 would save a silent file while the product
			// meter still reports a peak.
			if (!program_output_->start_recording(error, program_->audio_output_tracks()))
				status_->setText(tr("Program 录像启动失败：%1").arg(error));
			else
				status_->setText(tr("Program 录制中，使用同一原生宿主输出。"));
		}
		refresh_output_health();
	}
	void toggle_streaming()
	{
		if (!program_output_ || user_id_.isEmpty()) return;
		QString error;
		const auto before = program_output_->status();
		if (before.streaming) {
			if (!program_output_->stop_streaming(error))
				status_->setText(tr("Program 推流停止失败：%1").arg(error));
			else
				status_->setText(tr("Program 推流已停止，本机推流进程已释放。"));
		} else {
			if (!program_ || program_apply_state_ != "applied") {
				status_->setText(tr("请先应用并确认 Program 场景，再开始推流。"));
				return;
			}
			if (!program_output_->start_streaming(error, program_->audio_output_tracks()))
				status_->setText(tr("Program 推流启动失败：%1").arg(error));
			else
				status_->setText(tr("Program 正在通过本机 MediaMTX 以 RTSP/WHEP 发布。"));
		}
		refresh_output_health();
	}
	void generate_support_bundle()
	{
		if (user_id_.isEmpty()) return;
		support_bundle_error_.clear();
		QJsonArray audio_sources;
		std::set<std::string> audio_seen;
		int video_sources = 0, video_received = 0, video_stalled = 0, video_unknown = 0;
		std::set<std::string> video_seen;
		const auto collect = [&](const std::shared_ptr<ProductSceneGraph> &graph) {
			if (!graph) return;
			for (const auto &audio : graph->audio_progress()) {
				if (!audio_seen.insert(audio.source_id).second) continue;
				audio_sources.append(QJsonObject{{"sourceId", QString::fromStdString(audio.source_id)},
					{"available", audio.available}, {"active", audio.source_active},
					{"peakDbfs", double(audio.peak_dbfs)}});
			}
			for (const auto &video : graph->video_progress()) {
				if (!video_seen.insert(video.uuid).second) continue;
				++video_sources;
				if (!video.available) ++video_unknown;
				else if (video.serial > 0) ++video_received;
				else ++video_stalled;
			}
		};
		collect(wall_);
		collect(program_);
		for (const auto &view : projectors_)
			if (view && view->window) collect(view->graph);
		QJsonArray windows;
		if (preview_)
			windows.append(QJsonObject{{"role", "main-preview"},
				{"qtClass", QString::fromLatin1(preview_->metaObject()->className())}});
		if (program_projector_)
			windows.append(QJsonObject{{"role", program_projector_->isFullScreen() ?
					"program-fullscreen" : "program-projector"},
				{"qtClass", QString::fromLatin1(program_projector_->metaObject()->className())}});
		for (std::size_t i = 0; i < projectors_.size(); ++i)
			if (projectors_[i] && projectors_[i]->window)
				windows.append(QJsonObject{{"role", QString("fixed-scene-%1").arg(i + 1)},
					{"qtClass", QString::fromLatin1(projectors_[i]->window->metaObject()->className())}});
		QJsonObject output = program_output_state();
		output.remove("recordingPath");
		output.remove("recordingError");
		output.remove("streamPublishUrl");
		output.remove("streamPlaybackUrl");
		output.remove("streamPlaybackWhep");
		output.remove("streamError");
		const QStringList markers{"Switched to Preview/Program mode", "Switched to regular Preview mode",
			"Failed to initialize", "Failed to create", "QWidget", "QObject", "QLayout",
			"Shutting down", "All scene data cleared", "Number of remaining allocations"};
		QJsonObject marker_counts;
		const QString log_dir = QDir(qEnvironmentVariable("WEBOBS_NATIVE_PROFILE_ROOT"))
			.absoluteFilePath("obs-studio/logs");
		const auto logs = QDir(log_dir).entryInfoList({"*.txt"}, QDir::Files, QDir::Time);
		if (!logs.isEmpty()) {
			QFile log(logs.first().absoluteFilePath());
			if (log.size() <= 4 * 1024 * 1024 && log.open(QIODevice::ReadOnly)) {
				log.seek((std::max)(qint64(0), log.size() - 2 * 1024 * 1024));
				const QString tail = QString::fromUtf8(log.read(2 * 1024 * 1024));
				for (const auto &marker : markers)
					marker_counts.insert(marker, (std::min)(1000, int(tail.count(marker))));
			}
		}
		const QJsonObject bundle{{"schema", 1},
			{"kind", "native-product-support-bundle"},
			{"generatedAt", QDateTime::currentDateTimeUtc().toString(Qt::ISODateWithMs)},
			{"productVersion", qEnvironmentVariable("WEBOBS_NATIVE_PRODUCT_VERSION")},
			{"bootId", qEnvironmentVariable("WEBOBS_NATIVE_BOOT_ID")},
			{"phase", watching_.isEmpty() ? "authenticated" : "graph-applied"},
			{"programApplyState", program_apply_state_},
			{"mediaSources", media_source_count()},
			{"renderer", renderer_device_json(renderer_device_)},
			{"videoInputs", QJsonObject{{"sources", video_sources}, {"received", video_received},
				{"stalled", video_stalled}, {"unknown", video_unknown}}},
			{"audioSources", audio_sources},
			{"programOutput", output},
			{"programApply", QJsonObject{{"state", program_apply_state_},
				{"error", program_apply_error_},
				{"transient", program_apply_transient_},
				{"attempts", program_apply_attempts_},
				{"sceneId", program_scene_id_},
				{"targetSceneId", program_target_scene_id_}}},
			{"windows", windows},
			{"obsLogMarkers", marker_counts}};
		const QByteArray payload = QJsonDocument(bundle).toJson(QJsonDocument::Compact) + '\n';
		if (payload.size() > 262144) {
			support_bundle_error_ = "support-bundle-too-large";
			status_->setText(tr("支持包超过大小上限，未保存。"));
			return;
		}
		QString root = qEnvironmentVariable("WEBOBS_SUPPORT_BUNDLE_ROOT");
		if (root.isEmpty())
			root = QDir(qEnvironmentVariable("WEBOBS_NATIVE_PROFILE_ROOT")).absoluteFilePath("../support");
		if (!QDir().mkpath(root)) {
			support_bundle_error_ = "support-bundle-directory-failed";
			status_->setText(tr("无法创建支持包目录。"));
			return;
		}
		const QString path = QDir(root).absoluteFilePath(
			"WebOBS-support-" + QDateTime::currentDateTime().toString("yyyyMMdd-HHmmss") + ".json");
		QSaveFile file(path);
		if (!file.open(QIODevice::WriteOnly) || file.write(payload) != payload.size() || !file.commit()) {
			support_bundle_error_ = "support-bundle-write-failed";
			status_->setText(tr("支持包写入失败。"));
			return;
		}
		last_support_bundle_ = path;
		status_->setText(tr("支持包已保存：%1").arg(path));
	}
	int media_source_count() const
	{
		int media_sources = 0;
		obs_enum_all_sources([](void *count, obs_source_t *source) {
			if (QString::fromUtf8(obs_source_get_unversioned_id(source)) == "ffmpeg_source")
				++*static_cast<int *>(count);
			return true;
		}, &media_sources);
		return media_sources;
	}
	std::size_t owned_media_source_count() const
	{
		std::set<std::string> inputs;
		if (wall_) inputs.insert(wall_->uuids.begin(), wall_->uuids.end());
		if (wall_) inputs.insert(wall_->audio_uuids.begin(), wall_->audio_uuids.end());
		if (program_) inputs.insert(program_->uuids.begin(), program_->uuids.end());
		if (program_) inputs.insert(program_->audio_uuids.begin(), program_->audio_uuids.end());
		for (const auto &view : projectors_)
			if (view && view->window) {
				inputs.insert(view->graph->uuids.begin(), view->graph->uuids.end());
				inputs.insert(view->graph->audio_uuids.begin(), view->graph->audio_uuids.end());
			}
		return inputs.size();
	}
	QJsonObject program_state() const
	{
		auto *source = obs_frontend_get_current_scene();
		int media_sources = 0;
		if (source)
			obs_source_enum_full_tree(source, [](obs_source_t *, obs_source_t *child, void *context) {
				if (const char *id = obs_source_get_unversioned_id(child); id && std::string_view(id) == "ffmpeg_source")
					++*static_cast<int *>(context);
			}, &media_sources);
		QJsonObject result{{"studioMode", obs_frontend_preview_program_mode_active()},
			{"sceneUuid", source ? QString::fromUtf8(obs_source_get_uuid(source)) : QString{}},
			{"mediaSources", media_sources},
			{"monitorIsProgram", source && wall_ && source == obs_scene_get_source(wall_->scene)}};
		obs_source_release(source);
		return result;
	}
	QJsonObject program_output_state() const
	{
		if (!program_output_) return {};
		const auto value = program_output_->status();
		return QJsonObject{{"recording", value.recording},
			{"recordingReady", value.recording_ready},
			{"recordingPath", value.recording_path},
			{"recordingError", value.recording_error},
			{"recordingBytes", double(value.recording_bytes)},
			{"recordingSeconds", double(value.recording_seconds)},
			{"streaming", value.streaming},
			{"streamConnected", value.stream_connected},
			{"mediaMtxRunning", value.media_mtx_running},
			{"streamPublishUrl", value.stream_publish_url},
			{"streamPlaybackUrl", value.stream_playback_url},
			{"streamPlaybackWhep", value.stream_playback_whep},
			{"streamTransport", value.stream_transport},
			{"streamError", value.stream_error},
			// Duration of the Program teardowns the calling thread actually waited for.
			{"teardown", QJsonObject{{"relayStopMs", double(value.relay_stop_last_ms)},
				{"relayStopMaxMs", double(value.relay_stop_max_ms)},
				{"publishReleaseMs", double(value.publish_release_last_ms)},
				{"publishReleaseMaxMs", double(value.publish_release_max_ms)},
				{"publishStopWaitMs", double(value.publish_stop_wait_last_ms)},
				{"publishStopWaitMaxMs", double(value.publish_stop_wait_max_ms)}}},
			// audioTracks is what the running output encodes; selectedAudioTracks is
			// the mask the applied Program Scene actually routes right now, so an
			// idle receipt still proves which bus the next recording will encode.
			{"audioTracks", double(value.audio_tracks)},
			{"selectedAudioTracks", double(program_ ? program_->audio_output_tracks() : 0u)}};
	}
	bool select_monitor(obs_scene_t *scene)
	{
		// A local view must NEVER fall back to changing global output when
		// Studio mode is unavailable. Program will have its own TAKE consumer.
		if (!scene || !obs_frontend_preview_program_mode_active()) return false;
		obs_frontend_set_current_preview_scene(obs_scene_get_source(scene));
		auto *selected = obs_frontend_get_current_preview_scene();
		const bool matched = selected == obs_scene_get_source(scene);
		obs_source_release(selected);
		return matched;
	}
	// fnv1a over sampled BGRA bytes of one canvas cell; the same 3x2 grid the pixel
	// analysis applies to the captured window, so the two timelines can be compared.
	static uint32_t render_probe_digest(const uint8_t *pixels, uint32_t linesize, uint32_t height, uint32_t x,
		uint32_t y, uint32_t cell_width, uint32_t cell_height)
	{
		uint32_t hash = 2166136261u;
		const uint32_t step_x = (std::max)(1u, cell_width / 20u), step_y = (std::max)(1u, cell_height / 15u);
		for (uint32_t row = 0; row < cell_height; ++row) {
			if (row % step_y)
				continue;
			if (y + row >= height)
				break;
			const uint8_t *line = pixels + size_t(y + row) * size_t(linesize);
			for (uint32_t column = 0; column < cell_width; ++column) {
				if (column % step_x)
					continue;
				const size_t at = size_t(x + column) * 4u;
				if (at + 2u >= size_t(linesize))
					break;
				hash = (hash ^ line[at]) * 16777619u;
				hash = (hash ^ line[at + 1u]) * 16777619u;
				hash = (hash ^ line[at + 2u]) * 16777619u;
			}
		}
		return hash;
	}
	static void render_probe_tick(void *param, float)
	{
		auto *self = static_cast<ProductWindow *>(param);
		if (!self->render_probe_attached_ || self->tearing_down_)
			return;
		// Reading a few bytes at most four times per second keeps the window request
		// responsive without putting file I/O on the graphics thread every tick.
		const qint64 now = QDateTime::currentMSecsSinceEpoch();
		if (now - self->render_probe_control_checked_ms_ >= 250)
			self->render_probe_read_control(now);
		if (now >= self->render_probe_until_ms_.load())
			return;
		obs_enter_graphics();
		const int index = self->render_probe_ticks_ % 2;
		if (self->render_probe_slots_[index].staged)
			self->render_probe_collect(index);
		else
			self->render_probe_draw(index);
		++self->render_probe_ticks_;
		obs_leave_graphics();
	}
	// Harness window request: {"schema":1,"untilMs":<unix ms>}. A missing or unreadable
	// file keeps the previous window, so a concurrent writer cannot silently close an
	// open window mid-capture; the harness closes it explicitly with untilMs 0.
	void render_probe_read_control(qint64 now)
	{
		render_probe_control_checked_ms_ = now;
		if (render_probe_control_path_.isEmpty()) {
			char *base = obs_module_config_path("product-render-probe.control");
			render_probe_control_path_ = QString::fromUtf8(base ? base : "");
			bfree(base);
			if (render_probe_control_path_.isEmpty())
				return;
		}
		QFile file(render_probe_control_path_);
		if (!file.open(QIODevice::ReadOnly))
			return;
		const auto parsed = QJsonDocument::fromJson(file.read(256)).object();
		if (!parsed.contains("untilMs"))
			return;
		const qint64 until = parsed.value("untilMs").toVariant().toLongLong();
		render_probe_until_ms_.store(until > 0 ? until : 0);
	}

	// Runs inside obs_enter_graphics on the graphics thread (the same pattern OBS's own
	// screenshot helper uses): draw the Scene copy, then stage it for the next tick.
	void render_probe_draw(int index)
	{
		auto &slot = render_probe_slots_[index];
		// Bounded readback: at most ~6 draws per second per slot and never larger than
		// 960x540, so the probe cannot distort a CPU/GPU measurement window.
		const qint64 now = QDateTime::currentMSecsSinceEpoch();
		if (slot.next_draw_ms > now)
			return;
		slot.next_draw_ms = now + 160;
		obs_source_t *scene = index == 0 ? obs_frontend_get_current_preview_scene() : obs_get_output_source(0);
		if (!scene)
			return;
		obs_video_info info{};
		uint32_t width = 0, height = 0;
		if (obs_get_video_info(&info)) {
			width = info.base_width;
			height = info.base_height;
		}
		if (width > 960u) {
			height = uint32_t((uint64_t(height) * 960u) / uint64_t(width));
			width = 960u;
		}
		if (!width || !height) {
			obs_source_release(scene);
			return;
		}
		if (!slot.target || !slot.stage || slot.width != width || slot.height != height) {
			if (slot.target)
				gs_texrender_destroy(slot.target);
			if (slot.stage)
				gs_stagesurface_destroy(slot.stage);
			slot.target = gs_texrender_create(GS_BGRA_UNORM, GS_ZS_NONE);
			slot.stage = gs_stagesurface_create(width, height, GS_BGRA_UNORM);
			slot.width = width;
			slot.height = height;
		}
		if (!slot.target || !slot.stage) {
			obs_source_release(scene);
			return;
		}
		if (gs_texrender_begin(slot.target, slot.width, slot.height)) {
			vec4 zero;
			vec4_zero(&zero);
			gs_clear(GS_CLEAR_COLOR, &zero, 0.0f, 0);
			gs_ortho(0.0f, float(slot.width), 0.0f, float(slot.height), -100.0f, 100.0f);
			gs_blend_state_push();
			gs_blend_function(GS_BLEND_ONE, GS_BLEND_ZERO);
			obs_source_inc_showing(scene);
			obs_source_video_render(scene);
			obs_source_dec_showing(scene);
			gs_blend_state_pop();
			gs_texrender_end(slot.target);
		}
		gs_stage_texture(slot.stage, gs_texrender_get_texture(slot.target));
		slot.staged = true;
		slot.staged_frames = qint64(obs_get_total_frames());
		slot.staged_ms = QDateTime::currentMSecsSinceEpoch();
		slot.scene = QString::fromUtf8(obs_source_get_name(scene));
		obs_source_release(scene);
	}
	// Map the frame staged on the previous tick, exactly as OBS's screenshot helper does.
	void render_probe_collect(int index)
	{
		auto &slot = render_probe_slots_[index];
		if (!slot.staged || !slot.stage)
			return;
		slot.staged = false;
		uint8_t *pixels = nullptr;
		uint32_t linesize = 0;
		if (!gs_stagesurface_map(slot.stage, &pixels, &linesize) || !pixels) {
			if (pixels)
				gs_stagesurface_unmap(slot.stage);
			return;
		}
		const uint32_t width = gs_stagesurface_get_width(slot.stage);
		const uint32_t height = gs_stagesurface_get_height(slot.stage);
		const uint32_t cell_width = width / 3u, cell_height = height / 2u;
		QJsonArray cells;
		for (uint32_t row = 0; row < 2u; ++row)
			for (uint32_t column = 0; column < 3u; ++column)
				cells.append(int(render_probe_digest(pixels, linesize, height, column * cell_width,
					row * cell_height, cell_width, cell_height)));
		gs_stagesurface_unmap(slot.stage);
		RenderProbeSample sample;
		sample.ms = slot.staged_ms;
		sample.render_frames = slot.staged_frames;
		sample.scene = slot.scene;
		sample.cells = cells;
		std::lock_guard<std::mutex> guard(render_probe_mutex_);
		auto &target = index == 0 ? render_preview_samples_ : render_program_samples_;
		target.push_back(std::move(sample));
		if (target.size() > 32)
			target.erase(target.begin(), target.begin() + (target.size() - 32));
	}
	void render_probe_attach()
	{
		if (!render_probe_enabled_ || render_probe_attached_ || !obs_initialized())
			return;
		obs_add_tick_callback(render_probe_tick, this);
		render_probe_attached_ = true;
	}
	void render_probe_detach()
	{
		if (!render_probe_attached_)
			return;
		render_probe_attached_ = false;
		obs_remove_tick_callback(render_probe_tick, this);
		if (obs_initialized()) {
			obs_enter_graphics();
			for (auto &slot : render_probe_slots_) {
				if (slot.target)
					gs_texrender_destroy(slot.target);
				if (slot.stage)
					gs_stagesurface_destroy(slot.stage);
				slot.target = nullptr;
				slot.stage = nullptr;
				slot.width = slot.height = 0;
				slot.staged = false;
			}
			obs_leave_graphics();
		}
	}
	QJsonArray render_probe_samples_json(const std::vector<RenderProbeSample> &samples)
	{
		QJsonArray out;
		for (const auto &sample : samples)
			out.append(QJsonObject{{"atMs", sample.ms}, {"renderFrames", sample.render_frames},
				{"scene", sample.scene}, {"cells", sample.cells}});
		return out;
	}
	void publish_render_probe(QJsonObject &state)
	{
		if (!render_probe_enabled_)
			return;
		std::lock_guard<std::mutex> guard(render_probe_mutex_);
		const qint64 until = render_probe_until_ms_.load();
		state.insert("renderProbe", QJsonObject{{"enabled", true},
			{"windowUntilMs", until},
			{"windowOpen", until > QDateTime::currentMSecsSinceEpoch()},
			{"preview", render_probe_samples_json(render_preview_samples_)},
			{"program", render_probe_samples_json(render_program_samples_)}});
	}
	void observe_state(const char *phase)
	{
		remember_open_projector_placements();
		const int media_sources = media_source_count();
		obs_video_info video{};
		const bool video_available = obs_get_video_info(&video);
		QJsonArray bindings;
		QJsonArray selection_indices;
		QJsonArray studio_choices;
		if (scenes_)
			for (int i = 1; i < scenes_->count(); ++i)
				studio_choices.append(scenes_->itemData(i).toJsonObject().value("sceneId"));
		for (auto *slot : slots_)
			selection_indices.append(slot ? slot->currentIndex() : -1);
		for (int i = 0; i < watching_.size(); ++i) {
			auto binding = watching_[i].toObject();
			binding.insert("sourceUuid", QString::fromStdString(wall_->uuids[std::size_t(i)]));
			bindings.append(binding);
		}
		QJsonObject state{{"schema", 1}, {"phase", QString::fromLatin1(phase)},
			{"bootId", qEnvironmentVariable("WEBOBS_NATIVE_BOOT_ID")},
			{"pid", QString::number(QCoreApplication::applicationPid())},
			{"catalogItems", slots_[0] && slots_[0]->count() > 0 ? slots_[0]->count() - 1 : 0},
			{"selectionIndices", selection_indices},
			{"slotCount", int(slots_.size())},
			{"sceneId", watching_scene_id_}, {"studioRevision", watching_studio_revision_},
			{"sceneFingerprint", watching_scene_fingerprint_},
			{"studioChoices", studio_choices},
			{"mainGeneration", qint64(main_generation_)},
			{"sessionBound", !user_id_.isEmpty()}, {"mediaSources", media_sources}, {"bindings", bindings},
			{"lastLock", last_lock_}, {"lockCode", last_lock_code_}, {"renewTransient", transient_renewals_},
			{"videoAvailable", video_available}, {"hardwareDecodeVerified", false}};
		state.insert("previewLocked", preview_ && preview_->property("webobsPreviewLocked").toBool());
		// Bounded per-input progress and scene item counts. A frozen preview can mean a
		// decoder stopped feeding frames or that this Scene no longer renders the item,
		// and the two need different fixes; only uuid prefixes, counters and counts
		// leave this snapshot.
		// Which layer stalled: the graphics thread (renderFrames), the media side of
		// a source (serial) or a Scene item that still receives frames but is no longer
		// showing. Together these separate the three causes of a frozen tile.
		state.insert("renderFrames", qint64(obs_get_total_frames()));
		state.insert("laggedFrames", qint64(obs_get_lagged_frames()));
		// When this observation was written. A reader must know that its own polling
		// rate cannot exceed this publish rate, otherwise a 2 s observation gap looks
		// like an input that stopped delivering frames.
		state.insert("publishedAtMs", QDateTime::currentMSecsSinceEpoch());
		// UI-thread stall evidence and the Program teardown durations behind it. These
		// exist so a control refusal can be attributed without guessing.
		state.insert("uiStallMs", double(ui_stall_last_ms_));
		state.insert("uiStallMaxMs", double(ui_stall_max_ms_));
		state.insert("uiStallAtMs", double(ui_stall_at_ms_));
		struct MediaHealth {
			bool showing;
			bool active;
			bool removed;
			int media_state;
			QString name;
		};
		std::map<std::string, MediaHealth> media_showing;
		obs_enum_all_sources([](void *context, obs_source_t *source) {
			const char *uuid = obs_source_get_uuid(source);
			const char *id = obs_source_get_unversioned_id(source);
			if (uuid && id && std::string_view(id) == "ffmpeg_source") {
				const char *name = obs_source_get_name(source);
				static_cast<std::map<std::string, MediaHealth> *>(context)->emplace(
					uuid, MediaHealth{obs_source_showing(source), obs_source_active(source),
						obs_source_removed(source), int(obs_source_media_get_state(source)),
						name ? QString::fromUtf8(name).left(48) : QString()});
			}
			return true;
		}, &media_showing);
		// Read the decoder's own counter at snapshot time instead of trusting the heartbeat
		// cache. That cache refreshes only every two seconds and stops refreshing whenever the
		// main thread is busy (a Program apply or a UI Automation capture), which made run
		// 44356064395 report five wall inputs as frozen for 30 s while the captured fixture
		// counters kept advancing every ~330 ms. A missing entry means "this owned source
		// exposes no video callback counter yet (or is already removed)"; the gate must read
		// that as "no frame delivered", never as a frozen tile.
		std::map<std::string, ProductVideoProgress> raw_counter;
		auto collect_raw = [&](const std::shared_ptr<ProductSceneGraph> &graph) {
			if (!graph) return;
			for (const auto &input : graph->video_progress()) raw_counter.emplace(input.uuid, input);
		};
		collect_raw(wall_);
		collect_raw(program_);
		for (const auto &view : projectors_)
			if (view && view->window)
				collect_raw(view->graph);
		std::set<std::string> owned_video_uuids;
		if (wall_) owned_video_uuids.insert(wall_->uuids.begin(), wall_->uuids.end());
		if (program_) owned_video_uuids.insert(program_->uuids.begin(), program_->uuids.end());
		for (const auto &view : projectors_)
			if (view && view->window)
				owned_video_uuids.insert(view->graph->uuids.begin(), view->graph->uuids.end());
		QJsonArray video_inputs;
		const auto health_now = health_clock_.elapsed();
		for (const auto &uuid : owned_video_uuids) {
			if (video_inputs.size() >= 16)
				break;
			const auto found = media_showing.find(uuid);
			const auto health = input_health_.find(uuid);
			const auto counter = raw_counter.find(uuid);
			video_inputs.append(QJsonObject{{"uuid", QString::fromStdString(uuid).left(8)},
				{"serial", counter != raw_counter.end() && counter->second.available
					 ? qint64(counter->second.serial) : qint64(-1)},
				// Kept for the window's own health label only; a receipt must never treat
				// this tick-cached value as proof that a decoder stopped.
				{"healthSerial", health != input_health_.end() ? qint64(health->second.serial) : qint64(-1)},
				{"stalledMs", health != input_health_.end() && health->second.sampled
					 ? qint64(health_now - health->second.changed_ms) : qint64(-1)},
				{"showing", found != media_showing.end() ? found->second.showing : false},
				{"active", found != media_showing.end() ? found->second.active : false},
				{"mediaState", found != media_showing.end() ? found->second.media_state : 0},
				// Which owned Media Source this counter belongs to and whether OBS has
				// already marked it removed: an input that reports PLAYING but never
				// delivers a frame is only decidable once the receipt says which source
				// it is. Product-generated names only (never a camera URL).
				{"name", found != media_showing.end() ? found->second.name : QString()},
				{"removed", found != media_showing.end() ? found->second.removed : false},
				// Identity of the frame the media callback last handed to this source:
				// its own timestamp, a content digest and how long ago it arrived.
				// Advancing digests prove changing content reached the input even when
				// the counter alone could also be a repeated frame. -1 means the
				// running OBS exposes no such telemetry, never "no frame".
				{"frameTs", counter != raw_counter.end() ? qint64(counter->second.frame_timestamp) : qint64(-1)},
				{"frameHash", counter != raw_counter.end() ? qint64(counter->second.frame_hash) : qint64(-1)},
				// Both sides use libobs's monotonic clock, so this age is a real
				// elapsed value rather than a comparison of two different time bases.
				{"frameAgeMs", counter != raw_counter.end() && counter->second.frame_ms >= 0
					   ? qint64(qint64(os_gettime_ns() / 1000000ULL) - counter->second.frame_ms) : qint64(-1)}});
		}
		state.insert("videoInputs", video_inputs);
		publish_render_probe(state);
		const auto count_items = [](obs_scene_t *scene) {
			int items = 0;
			if (scene)
				obs_scene_enum_items(scene, [](obs_scene_t *, obs_sceneitem_t *item, void *count) {
					if (obs_sceneitem_visible(item))
						++*static_cast<int *>(count);
					return true;
				}, &items);
			return items;
		};
		state.insert("wallItems", count_items(wall_ ? wall_->scene : nullptr));
		state.insert("programItems", count_items(program_ ? program_->scene : nullptr));
		state.insert("programSceneId", program_scene_id_);
		state.insert("programSceneFingerprint", program_fingerprint_);
		state.insert("programStudioRevision", program_studio_revision_);
		state.insert("programApplyState", program_apply_state_);
		state.insert("programApplyError", program_apply_error_);
		state.insert("programApplyTransient", program_apply_transient_);
		state.insert("programApplyAttempts", program_apply_attempts_);
		state.insert("programTargetSceneId", program_target_scene_id_);
		state.insert("programSyncPending", program_sync_pending_);
		state.insert("program", program_state());
		state.insert("programOutput", program_output_state());
		QJsonArray audio_sources;
		std::set<std::string> audio_seen;
		const auto collect_audio = [&](const std::shared_ptr<ProductSceneGraph> &graph) {
			if (!graph)
				return;
			for (const auto &audio : graph->audio_progress()) {
				if (!audio_seen.insert(audio.source_id).second)
					continue;
				QJsonArray audio_inputs;
				for (const auto &input : audio.inputs)
					audio_inputs.append(QJsonObject{{"track", input.track}, {"gain", input.gain},
						{"muted", input.muted}, {"syncOffsetMs", input.sync_offset_ms},
						{"appliedDelayMs", input.applied_delay_ms}});
				audio_sources.append(QJsonObject{{"sourceId", QString::fromStdString(audio.source_id)},
					{"available", audio.available}, {"active", audio.source_active},
					{"showing", audio.source_showing}, {"processExitCode", audio.process_exit_code},
					{"peakDbfs", double(audio.peak_dbfs)},
					{"mediaState", audio.media_state}, {"volume", audio.volume},
					{"muted", audio.muted}, {"mixers", double(audio.mixers)},
					{"syncOffset", double(audio.sync_offset)},
					{"audioInputs", audio_inputs},
					{"mixerPort", audio.mixer_port},
					{"mixerLog", QString::fromStdString(audio.mixer_log)}});
			}
		};
		collect_audio(wall_);
		collect_audio(program_);
		for (const auto &view : projectors_)
			if (view && view->window)
				collect_audio(view->graph);
		state.insert("audioSources", audio_sources);
		state.insert("supportBundle", QJsonObject{{"path", last_support_bundle_},
			{"error", support_bundle_error_}});
		state.insert("startupStudioDeferred", frontend_->property("webobsStudioDeferredToProduct").toBool());
		state.insert("restoreGuardHits", frontend_->property("webobsRestoreGuardHits").toInt());
		state.insert("refusedCollection", frontend_->property("webobsRefusedCollection").toString());
		state.insert("lastRetirementMs", last_retirement_ms_);
		state.insert("renderer", renderer_device_json(renderer_device_));
		state.insert("statsOpen", stats_window_ && stats_window_->isVisible());
		if (stats_window_ && stats_window_->isVisible())
			state.insert("statsWindow", QJsonObject{{"role", "host-stats"},
				{"qtClass", QString::fromLatin1(stats_window_->metaObject()->className())},
				{"rootHwnd", QString::number(quintptr(stats_window_->winId()), 16)}});
		if (preview_)
			state.insert("windows", QJsonArray{QJsonObject{{"role", "main-preview"},
				{"qtClass", QString::fromLatin1(preview_->metaObject()->className())},
				{"hwnd", QString::number(quintptr(preview_->winId()), 16)},
				{"rootHwnd", QString::number(quintptr(window()->winId()), 16)}}});
		QJsonArray projector_states;
		auto windows = state.value("windows").toArray();
		if (program_projector_ && program_projector_->isVisible()) {
			windows.append(QJsonObject{{"role", program_projector_->isFullScreen() ? "program-fullscreen" : "program-projector"},
				{"qtClass", QString::fromLatin1(program_projector_->metaObject()->className())},
				{"hwnd", QString::number(quintptr(program_projector_->winId()), 16)},
				{"rootHwnd", QString::number(quintptr(program_projector_->winId()), 16)}});
		}
		for (std::size_t i = 0; i < projectors_.size(); ++i) {
			if (!projectors_[i] || !projectors_[i]->window) continue;
			const auto &view = *projectors_[i];
			QJsonArray view_bindings;
			for (int item = 0; item < view.cameras.size(); ++item) {
				auto binding = view.cameras[item].toObject();
				binding.insert("sourceUuid", QString::fromStdString(view.graph->uuids[std::size_t(item)]));
				view_bindings.append(binding);
			}
			projector_states.append(QJsonObject{{"slot", int(i + 1)}, {"sceneId", view.scene_id},
				{"sceneFingerprint", view.scene_fingerprint},
				{"studioRevision", view.studio_revision}, {"bindings", view_bindings},
				{"fullscreen", view.window->isFullScreen()},
				{"geometry", QJsonObject{{"x", view.window->geometry().x()}, {"y", view.window->geometry().y()},
					{"width", view.window->geometry().width()}, {"height", view.window->geometry().height()}}}});
			const auto role = view.window->isFullScreen() ? "fixed-scene-fullscreen-%1" : "fixed-scene-%1";
			windows.append(QJsonObject{{"role", QString::fromLatin1(role).arg(i + 1)},
				{"qtClass", QString::fromLatin1(view.window->metaObject()->className())},
				{"hwnd", QString::number(quintptr(view.window->winId()), 16)},
				{"rootHwnd", QString::number(quintptr(view.window->winId()), 16)}});
		}
		state.insert("windows", windows);
		state.insert("projectors", projector_states);
		state.insert("projectorPreferences", projector_placements_);
		if (video_available)
			state.insert("videoInfo", QJsonObject{{"baseWidth", int(video.base_width)},
				{"baseHeight", int(video.base_height)}, {"outputWidth", int(video.output_width)},
				{"outputHeight", int(video.output_height)}, {"fpsNumerator", int(video.fps_num)},
				{"fpsDenominator", int(video.fps_den)}});
		char *path = obs_module_config_path("product-state.json");
		const QString state_path = QString::fromUtf8(path ? path : "");
		bfree(path);
		const auto encoded = QJsonDocument(state).toJson();
		bool published = state_path.isEmpty();
		// The UI gate and support tooling read this private observation file
		// while the product writes it. Windows can transiently reject a
		// QSaveFile replace when a reader still has the old handle open; retry
		// a bounded number of times instead of leaving the observation stale.
		for (int attempt = 0; attempt < 8 && !published; ++attempt) {
			QSaveFile file(state_path);
			if (QDir().mkpath(QFileInfo(file.fileName()).absolutePath()) && file.open(QIODevice::WriteOnly) &&
			    file.write(encoded) == encoded.size() && file.commit()) {
				published = true;
				break;
			}
			if (attempt < 7)
				QThread::msleep(15);
		}
		if (!published)
			blog(LOG_WARNING, "WebOBS product state observation is unavailable");
	}
	void request(const QString &path, const QByteArray &method, const QJsonObject &body, Reply callback,
		     int timeout_ms = 2000)
	{
		if (client_) client_->request(path, method, body, std::move(callback), timeout_ms);
		else callback(0, {});
	}

	void update_projector_controls()
	{
		for (std::size_t i = 0; i < projector_buttons_.size(); ++i)
			if (projector_buttons_[i])
				projector_buttons_[i]->setEnabled(!user_id_.isEmpty() && !applying_ && wall_ && !projector_pending_[i]);
		if (close_projectors_)
			close_projectors_->setEnabled(bool(projectors_[0]) || bool(projectors_[1]) || bool(program_projector_));
		if (program_projector_button_)
			program_projector_button_->setEnabled(!user_id_.isEmpty() && !applying_ && bool(program_));
	}
	void observe_current_media()
	{
		if (!tearing_down_ && !user_id_.isEmpty())
			observe_state(applying_ ? "connecting" : (watching_.isEmpty() ? "authenticated" : "graph-applied"));
	}
	void close_projector(std::size_t index)
	{
		auto retired = std::move(projectors_[index]);
		if (retired && retired->window) {
			remember_projector_placement(QString("fixed-%1").arg(index + 1), retired->window);
			retired->window->close(); // OBS removes its own projector-list entry.
		}
		retired.reset();
		update_projector_controls();
	}
	void clear_main_media()
	{
		save_->setEnabled(false);
		watching_ = {};
		watching_versions_ = {};
		watching_scene_id_.clear();
		watching_scene_fingerprint_.clear();
		watching_studio_revision_ = -1;
		if (!obs_initialized())
			return;
		// Main Preview must blank without editing a graph still presented by a
		// fixed projector. The empty scene has no endpoint or media source.
		if (!tearing_down_) {
			if (!blank_scene_)
				blank_scene_ = obs_scene_create("WebOBS locked preview");
			if (blank_scene_ && !obs_source_removed(obs_scene_get_source(blank_scene_)))
				(void)select_monitor(blank_scene_);
		}
		wall_.reset();
	}
	void select_frontend_transition(const QString &kind, int duration_ms)
	{
		obs_frontend_source_list list{};
		obs_frontend_get_transitions(&list);
		const char *wanted = kind == "fade" ? "fade_transition" : "cut_transition";
		obs_source_t *chosen = nullptr;
		for (std::size_t i = 0; i < list.sources.num; ++i) {
			if (list.sources.array[i] && QString::fromUtf8(obs_source_get_unversioned_id(list.sources.array[i])) == wanted) {
				chosen = list.sources.array[i];
				break;
			}
		}
		if (chosen) obs_frontend_set_current_transition(chosen);
		obs_frontend_source_list_free(&list);
		obs_frontend_set_transition_duration(kind == "fade" ? std::clamp(duration_ms, 50, 10000) : 0);
	}

	void report_program(const QString &state, qint64 revision, const QString &scene_id,
		const QString &fingerprint, const QString &error = {})
	{
		if (user_id_.isEmpty() || revision < 0 || scene_id.isEmpty()) return;
		QJsonObject body{{"revision", revision}, {"sceneId", scene_id},
			{"fingerprint", fingerprint}, {"status", state}};
		if (!error.isEmpty()) body.insert("error", error);
		program_reported_revision_ = -1;
		request("/api/v1/native/studio/program", "POST", body,
			[this, revision](int code, const QJsonObject &) {
				if (code == 200) program_reported_revision_ = revision;
			});
	}

	void clear_program_media()
	{
		++program_generation_;
		program_sync_pending_ = false;
		program_apply_state_ = "idle";
		program_apply_error_.clear();
		program_apply_transient_ = false;
		program_apply_attempts_ = 0;
		program_scene_id_.clear();
		program_fingerprint_.clear();
		program_studio_revision_ = -1;
		program_reported_revision_ = -1;
		program_target_revision_ = -1;
		program_target_scene_id_.clear();
		program_target_fingerprint_.clear();
		if (!obs_initialized()) {
			program_.reset();
			update_projector_controls();
			return;
		}
		// Logout and teardown must remove protected Program pixels immediately,
		// never through a fade that leaves the previous scene visible. Cancel an
		// in-flight transition first because the frontend refuses a new one while
		// the previous fade is still active.
		if (!tearing_down_ && blank_scene_ && !obs_source_removed(obs_scene_get_source(blank_scene_))) {
			if (obs_source_t *output = obs_get_output_source(0)) {
				obs_transition_set(output, obs_scene_get_source(blank_scene_));
				obs_source_release(output);
			}
			select_frontend_transition("cut", 0);
			obs_frontend_set_current_scene(obs_scene_get_source(blank_scene_));
		}
		program_.reset();
		update_projector_controls();
	}

	// A Program TAKE must never latch permanently on a refusal that OBS itself can
	// settle out of (an in-flight fade, a canvas that is still busy, a graph that has
	// to be rebuilt). Those are retried a bounded number of times by the sync timer.
	// Structural refusals stay permanent so a real defect is not hidden behind retries.
	static constexpr int program_apply_attempt_limit = 4;
	static bool program_apply_is_transient(const QString &error)
	{
		static const char *const prefixes[] = {"program-canvas-busy", "program-transition-not-observed",
			"program-graph-create-failed", "program-apply-failed", "scene-canvas-not-applied",
			"scene-source-modified", "scene-create-failed", "scene-item-create-failed",
			"scene-audio-item-create-failed", "scene-audio-mixer", "scene-audio-meter-unavailable"};
		return std::any_of(std::begin(prefixes), std::end(prefixes),
			[&error](const char *prefix) { return error.startsWith(QLatin1String(prefix)); });
	}

	void fail_program(qint64 revision, const QString &scene_id, const QString &fingerprint,
		const QString &error)
	{
		const bool same_target = program_apply_state_ == "failed" &&
			program_target_scene_id_ == scene_id && program_target_fingerprint_ == fingerprint;
		program_apply_attempts_ = same_target ? program_apply_attempts_ + 1 : 1;
		program_apply_transient_ = program_apply_is_transient(error);
		program_target_revision_ = revision;
		program_target_scene_id_ = scene_id;
		program_target_fingerprint_ = fingerprint;
		program_apply_state_ = "failed";
		// Gates and the support bundle can only read this state file, so the
		// concrete bounded reason has to live here as well.
		program_apply_error_ = error.isEmpty() ? QStringLiteral("program-apply-failed") : error.left(96);
		report_program("failed", revision, scene_id, fingerprint, error);
		observe_current_media();
	}

	bool apply_program_graph(const SceneDocument &document, const std::vector<ProductCamera> &cameras,
		const QJsonObject &video, const QString &scene_id, qint64 studio_revision,
		const QString &fingerprint, const QString &transition_kind, int duration_ms, std::string &error)
	{
		obs_video_info actual{};
		const bool same_video = obs_get_video_info(&actual) &&
			actual.base_width == unsigned(video.value("width").toInt()) &&
			actual.base_height == unsigned(video.value("height").toInt()) &&
			actual.output_width == actual.base_width && actual.output_height == actual.base_height &&
			actual.fps_den != 0 && std::uint64_t(actual.fps_num) ==
			std::uint64_t(video.value("fps").toInt()) * actual.fps_den;
		if (!same_video) {
			if (wall_ || projectors_[0] || projectors_[1]) {
				error = "program-canvas-busy";
				return false;
			}
			program_.reset();
			if (!apply_product_video_config(video.value("width").toInt(), video.value("height").toInt(),
				video.value("fps").toInt(), error))
				return false;
		}
		auto candidate = create_product_scene(source_pool_, user_id_.toStdString(), document, cameras, error);
		if (!candidate || !candidate->scene) {
			if (error.empty()) error = "program-graph-create-failed";
			return false;
		}
		// A new TAKE must not be silently dropped because an older fade is still
		// running. Settle the active output on the last confirmed Program first,
		// then select the newly requested transition.
		if (obs_source_t *output = obs_get_output_source(0)) {
			obs_source_t *settle = program_ && program_->scene ?
				obs_scene_get_source(program_->scene) : obs_scene_get_source(blank_scene_);
			if (settle) obs_transition_set(output, settle);
			obs_source_release(output);
		}
		select_frontend_transition(transition_kind, duration_ms);
		obs_frontend_set_current_scene(obs_scene_get_source(candidate->scene));
		auto *selected = obs_frontend_get_current_scene();
		const bool matched = selected == obs_scene_get_source(candidate->scene);
		obs_source_release(selected);
		if (!matched) {
			error = "program-transition-not-observed";
			return false;
		}
		// The outgoing scene remains referenced by OBS for the fade duration.
		auto retired = std::move(program_);
		program_ = std::move(candidate);
		program_scene_id_ = scene_id;
		program_fingerprint_ = fingerprint;
		program_apply_error_.clear();
		program_apply_transient_ = false;
		program_apply_attempts_ = 0;
		program_studio_revision_ = studio_revision;
		program_target_revision_ = studio_revision;
		program_target_scene_id_ = scene_id;
		program_target_fingerprint_ = fingerprint;
		program_apply_state_ = "applied";
		report_program("applied", studio_revision, scene_id, fingerprint);
		update_projector_controls();
		observe_current_media();
		if (retired) {
			if (transition_kind == "fade" && duration_ms > 0) {
				// OBS keeps both sides of a completed fade in its transition source.
				// Settle on the confirmed Program and release the outgoing graph in
				// one deferred step so its decoders actually retire after the fade.
				QTimer::singleShot(duration_ms + 250, this,
					[this, retired = std::move(retired), scene_id, fingerprint]() mutable {
					if (program_scene_id_ == scene_id && program_fingerprint_ == fingerprint && program_) {
						if (obs_source_t *output = obs_get_output_source(0)) {
							obs_transition_set(output, obs_scene_get_source(program_->scene));
							obs_source_release(output);
						}
					}
					retired.reset();
					if (program_scene_id_ == scene_id && program_fingerprint_ == fingerprint) {
						refresh_video_health();
						// The visible state is written by observe_state(). Do not
						// leave the previous graph's source count in that snapshot
						// after the transition has actually released it.
						settlement_elapsed_.start();
						settlement_.start(50);
					}
				});
			} else {
				// A cut is complete as soon as the frontend selects the new scene,
				// but the transition still owns both sides until it is settled.
				// Collapse it immediately so the previous Program graph (and any
				// source variant unique to it) is released after the cut.
				if (obs_source_t *output = obs_get_output_source(0)) {
					obs_transition_set(output, obs_scene_get_source(program_->scene));
					obs_source_release(output);
				}
				retired.reset();
				refresh_video_health();
				settlement_elapsed_.start();
				settlement_.start(50);
			}
		}
		return true;
	}

	void sync_program()
	{
		if (user_id_.isEmpty() || applying_ || program_sync_pending_ || tearing_down_) return;
		program_sync_pending_ = true;
		const auto generation = program_generation_;
		request("/api/v1/native/studio", "GET", {}, [this, generation](int code, const QJsonObject &body) {
			program_sync_pending_ = false;
			if (generation != program_generation_ || user_id_.isEmpty() || tearing_down_) return;
			if (code == 401 || code == 403) {
				locked(tr("会话或场景权限已失效，Program 已锁定。"), "program-session-refused", code);
				return;
			}
			if (code != 200) return;
			const auto revision = body.value("revision").toInteger(-1);
			const auto scene_id = body.value("programSceneId").toString();
			const auto fingerprint = body.value("programFingerprint").toString();
			const bool supported = body.value("programSupported").toBool();
			if (revision < 0 || scene_id.isEmpty()) return;
			if (body.value("programEmpty").toBool()) {
				if (!program_scene_id_.isEmpty() || program_) {
					clear_program_media();
					observe_current_media();
				}
				return;
			}
			if (!supported || !QRegularExpression("^[a-f0-9]{64}$").match(fingerprint).hasMatch()) {
				if (program_target_revision_ != revision || program_target_scene_id_ != scene_id ||
					program_apply_state_ != "failed") {
					fail_program(revision, scene_id, fingerprint, "program-source-unsupported");
				}
				return;
			}
			if (scene_id == program_target_scene_id_ && fingerprint == program_target_fingerprint_ &&
				program_apply_state_ == "failed" &&
				(!program_apply_transient_ || program_apply_attempts_ >= program_apply_attempt_limit))
				return;
			if (!program_scene_id_.isEmpty() && scene_id == program_scene_id_ &&
				fingerprint == program_fingerprint_ && program_apply_state_ == "applied") {
				if (program_studio_revision_ != revision || program_reported_revision_ != revision) {
					program_studio_revision_ = revision;
					report_program("applied", revision, scene_id, fingerprint);
					observe_current_media();
				}
				return;
			}
			program_target_revision_ = revision;
			program_target_scene_id_ = scene_id;
			program_target_fingerprint_ = fingerprint;
			program_apply_state_ = "pending";
			observe_current_media();
			request("/api/v1/native/scenes/resolve", "POST",
				{{"sceneId", scene_id}, {"fingerprint", fingerprint}},
				[this, generation, revision, scene_id, fingerprint, body](int resolve_code, const QJsonObject &resolved) {
				if (generation != program_generation_ || user_id_.isEmpty() || tearing_down_) return;
				const auto scene_revision = resolved.value("studioRevision").toInteger(revision);
				if (resolve_code != 200 || !resolved.value("scene").isObject() ||
					resolved.value("sceneFingerprint").toString() != fingerprint ||
					scene_revision < 0) {
					fail_program(revision, scene_id, fingerprint, "program-scene-unavailable");
					return;
				}
				request("/api/v1/native/scenes/authorize", "POST",
					{{"sceneId", scene_id}, {"fingerprint", fingerprint}},
					[this, generation, revision, scene_id, fingerprint, body, resolved, scene_revision]
					(int authorize_code, const QJsonObject &authorization) {
					if (generation != program_generation_ || user_id_.isEmpty() || tearing_down_) return;
					if (authorize_code != 200 ||
						authorization.value("sceneFingerprint").toString() != fingerprint ||
						authorization.value("cameraVersions") != resolved.value("cameraVersions")) {
						fail_program(revision, scene_id, fingerprint, "program-authorization-rejected");
						return;
					}
					const auto authorized_revision = authorization.value("studioRevision").toInteger(scene_revision);
					const auto bytes = QJsonDocument(resolved.value("scene").toObject()).toJson(QJsonDocument::Compact);
					auto parsed = parse_scene_json(std::string_view(bytes.constData(), std::size_t(bytes.size())));
					const auto bindings = resolved.value("cameras").toArray();
					if (!parsed.ok() || parsed.document->sources.size() != std::size_t(bindings.size())) {
						fail_program(revision, scene_id, fingerprint, "program-scene-invalid");
						return;
					}
					std::vector<ProductCamera> cameras;
					for (int i = 0; i < bindings.size(); ++i) {
						auto &source = parsed.document->sources[std::size_t(i)];
						const auto binding = bindings[i].toObject();
						if (source.kind != "camera" || source.camera_id != binding.value("cameraId").toString().toStdString() ||
							source.profile_id != binding.value("profileId").toString().toStdString()) {
							fail_program(revision, scene_id, fingerprint, "program-binding-mismatch");
							return;
						}
						ProductCamera camera;
						camera.id = source.camera_id;
						camera.profile_id = source.profile_id;
						camera.name = "WebOBS Program " + source.id;
						camera.url = binding.value("url").toString().toStdString();
						camera.transport = binding.value("transport").toString().toStdString();
						const auto requested_hardware = source.hardware_decode == "auto" ?
							binding.value("hardwareDecode").toString().toStdString() : source.hardware_decode;
						if (requested_hardware != "auto" && requested_hardware != "on" && requested_hardware != "off") {
							fail_program(revision, scene_id, fingerprint, "program-decode-invalid");
							return;
						}
						if (requested_hardware != "auto") camera.hardware_decode = requested_hardware == "on";
						source.hardware_decode = requested_hardware;
						source.transport = camera.transport;
						cameras.push_back(std::move(camera));
					}
					const auto transition = body.value("transition").toObject();
					const auto kind = transition.value("kind").toString() == "fade" ? "fade" : "cut";
					const int duration = std::clamp(int(transition.value("durationMs").toInt(0)), 0, 10000);
					std::string error;
					if (!apply_program_graph(*parsed.document, cameras, authorization.value("video").toObject(),
						scene_id, authorized_revision, fingerprint, QString::fromLatin1(kind), duration, error))
						fail_program(revision, scene_id, fingerprint,
							error.empty() ? QStringLiteral("program-apply-failed") : QString::fromStdString(error));
				}, 12000);
			}, 12000);
		});
	}

	void clear_media()
	{
		if (stats_window_) stats_window_->close();
		stats_window_.clear();
		if (program_projector_) {
			program_projector_->close();
			program_projector_.clear();
		}
		clear_program_media();
		clear_main_media();
		projector_pending_.fill(false);
		for (std::size_t i = 0; i < projectors_.size(); ++i) close_projector(i);
		input_health_.clear();
		if (!tearing_down_) refresh_video_health();
	}
	void open_management_page(const QString &fragment)
	{
		if (user_id_.isEmpty()) {
			status_->setText(tr("请先登录后再打开管理页面。"));
			return;
		}
		auto url = origin_;
		QUrlQuery query;
		query.addQueryItem("native-management", "1");
		url.setQuery(query);
		url.setFragment(fragment);
		QDesktopServices::openUrl(url);
	}

	void open_stats()
	{
		if (user_id_.isEmpty()) return;
		request("/api/v1/native/auth/session", "GET", {}, [this](int code, const QJsonObject &) {
			if (code != 200) {
				if (renewal_transient(code)) {
					status_->setText(tr("本机会话核验暂不可用，请稍后重试。"));
					return;
				}
				locked(tr("会话已失效，请重新登录。"), code == 401 ? "session-rejected" : "session-check-refused", code);
				return;
			}
			if (!QMetaObject::invokeMethod(frontend_, "on_stats_triggered", Qt::DirectConnection)) {
				status_->setText(tr("无法打开原生统计窗口。"));
				return;
			}
			QWidget *found = nullptr;
			for (auto *widget : QApplication::allWidgets()) {
				if (!widget->isWindow() || QString::fromLatin1(widget->metaObject()->className()) != "OBSBasicStats") continue;
				if (found) {
					status_->setText(tr("原生统计窗口身份不唯一，请退出后重试。"));
					return;
				}
				found = widget;
			}
			if (!found) {
				status_->setText(tr("未找到原生统计窗口。"));
				return;
			}
			if (stats_window_ != found) {
				stats_window_ = found;
				found->setWindowTitle(tr("WebOBS · OBS 宿主统计（仅宿主进程）"));
				connect(found, &QObject::destroyed, this, [this] { observe_current_media(); });
			}
			observe_current_media();
		});
	}
	void toggle_projector_fullscreen(QWidget *window)
	{
		if (window->isFullScreen()) {
			QMetaObject::invokeMethod(window, "OpenWindowedProjector", Qt::DirectConnection);
			return;
		}
		const auto screens = QGuiApplication::screens();
		if (screens.isEmpty()) return;
		const int monitor = (std::max)(0, int(screens.indexOf(window->screen())));
		// Invoke the pinned projector's existing monitor action, including its
		// native saved-monitor/geometry/cursor behavior. No new renderer is used.
		QAction action(this);
		action.setProperty("monitor", monitor);
		QObject::connect(&action, SIGNAL(triggered(bool)), window, SLOT(OpenFullScreenProjector()));
		action.trigger();
	}
	void remember_projector_placement(const QString &role, QWidget *window)
	{
		if (user_id_.isEmpty() || !window || !window->screen()) return;
		const auto rect = window->isFullScreen() ? window->normalGeometry() : window->geometry();
		if (rect.isEmpty()) return;
		const auto placement = QJsonObject{{"x", rect.x()}, {"y", rect.y()},
			{"width", rect.width()}, {"height", rect.height()},
			{"screen", window->screen()->name().left(128)}, {"fullscreen", window->isFullScreen()}};
		if (projector_placements_.value(role).toObject() == placement) return;
		projector_placements_[role] = placement;
		placement_save_.start(500); // Debounce resize/move; no idle polling or per-pixel writes.
	}
	void remember_open_projector_placements()
	{
		// Win32 moves do not always produce a Qt Move event for OBS projector
		// windows. Piggyback on the existing heartbeat/state observation as a
		// bounded safety net; identical geometry never schedules another write.
		for (std::size_t i = 0; i < projectors_.size(); ++i)
			if (projectors_[i] && projectors_[i]->window)
				remember_projector_placement(QString("fixed-%1").arg(i + 1), projectors_[i]->window);
		if (program_projector_)
			remember_projector_placement("program", program_projector_);
	}
	void save_projector_placements()
	{
		placement_save_.stop();
		if (user_id_.isEmpty() || projector_placements_.isEmpty()) return;
		QFile previous(workspace_path());
		if (previous.size() > 16384 || !previous.open(QIODevice::ReadOnly)) return;
		auto workspace = QJsonDocument::fromJson(previous.readAll()).object();
		previous.close();
		if (workspace.value("schema").toInt() != 1 && workspace.value("schema").toInt() != 2) return;
		workspace["projectorPlacements"] = projector_placements_;
		QSaveFile output(workspace_path());
		const auto bytes = QJsonDocument(workspace).toJson();
		if (!output.open(QIODevice::WriteOnly) || output.write(bytes) != bytes.size() || !output.commit())
			status_->setText(tr("投影位置保存失败，原布局已保留。"));
	}
	void restore_projector_placement(const QString &role, QWidget *window)
	{
		const auto saved = projector_placements_.value(role).toObject();
		if (saved.isEmpty() || !window) return;
		QScreen *target = window->screen();
		bool same_screen = false;
		for (auto *screen : QGuiApplication::screens()) {
			if (screen->name() == saved.value("screen").toString()) {
				target = screen;
				same_screen = true;
				break;
			}
		}
		if (!target) return;
		const auto rect = projector_window_rect(saved, target->availableGeometry());
		if (rect.isEmpty()) return;
		window->setScreen(target);
		window->setGeometry(rect);
		// A missing screen falls back to a visible window, never unexpected
		// fullscreen takeover on another display. OBS still owns fullscreen.
		if (same_screen && saved.value("fullscreen").toBool() && !window->isFullScreen())
			toggle_projector_fullscreen(window);
	}
	void open_program_projector()
	{
		if (user_id_.isEmpty() || !program_ || program_projector_) {
			status_->setText(tr("TAKE 后存在已确认的 Program 时才能打开 Program 投影。"));
			return;
		}
		std::set<QWidget *> previous;
		for (auto *widget : QApplication::allWidgets())
			if (QString::fromLatin1(widget->metaObject()->className()) == "OBSProjector") previous.insert(widget);
		obs_frontend_open_projector("StudioProgram", -1, "", "");
		QWidget *opened = nullptr;
		for (auto *widget : QApplication::allWidgets()) {
			if (QString::fromLatin1(widget->metaObject()->className()) == "OBSProjector" && !previous.contains(widget)) {
				if (opened) {
					widget->close();
					opened->close();
					status_->setText(tr("Program 投影窗口身份不唯一，请重试。"));
					return;
				}
				opened = widget;
			}
		}
		if (!opened) {
			status_->setText(tr("OBS 未能打开 Program 投影窗口。"));
			return;
		}
		program_projector_ = opened;
		opened->installEventFilter(this);
		opened->setWindowTitle(tr("WebOBS Program 投影 · F11 全屏"));
		restore_projector_placement("program", opened);
		connect(opened, &QObject::destroyed, this, [this] {
			program_projector_.clear();
			observe_current_media();
		});
		observe_current_media();
	}

	void close_program_projector()
	{
		if (program_projector_) {
			remember_projector_placement("program", program_projector_);
			program_projector_->close();
		}
		program_projector_.clear();
		observe_current_media();
	}

	void open_projector(std::size_t index)
	{
		if (index >= projectors_.size() || projector_pending_[index] || applying_ || !wall_ || user_id_.isEmpty())
			return;
		const auto main_generation = main_generation_;
		const std::weak_ptr<ProductSceneGraph> graph_reference = wall_;
		const auto cameras = watching_;
		const auto versions = watching_versions_;
		const auto scene_id = watching_scene_id_;
		const auto fingerprint = watching_scene_fingerprint_;
		const bool scene = !scene_id.isEmpty();
		projector_pending_[index] = true;
		update_projector_controls();
		const QJsonObject renewal = scene ? QJsonObject{{"sceneId", scene_id}, {"fingerprint", fingerprint}} :
			QJsonObject{{"cameras", cameras}};
		request(scene ? "/api/v1/native/scenes/authorize" : "/api/v1/native/cameras/authorize", "POST", renewal,
			[this, index, main_generation, graph_reference, cameras, versions, scene_id, fingerprint, scene]
			(int code, const QJsonObject &body) {
			projector_pending_[index] = false;
			update_projector_controls();
			const auto graph = graph_reference.lock();
			if (!graph || main_generation != main_generation_ || wall_ != graph || applying_) return;
			if (code != 200) {
				// A busy authority declines this projector opening only; the already
				// authorized wall keeps its current authorization.
				if (renewal_transient(code)) {
					++transient_renewals_;
					last_lock_code_ = code;
					status_->setText(tr("本机授权服务繁忙，投影暂未打开，请稍后重试。"));
					return;
				}
				locked(tr("投影观看权限或配置已失效，请重新登录。"),
					code == 401 ? "projector-session-rejected" : "projector-refused", code);
				return;
			}
			if (body.value("cameraVersions").toObject() != versions ||
			    (scene && (body.value("sceneFingerprint").toString() != fingerprint ||
				body.value("studioRevision").toInteger(-1) < 0))) {
				locked(tr("投影观看权限或配置已失效，请重新登录。"), "projector-precondition-changed", code);
				return;
			}
			std::set<QWidget *> previous;
			for (auto *widget : QApplication::allWidgets())
				if (QString::fromLatin1(widget->metaObject()->className()) == "OBSProjector") previous.insert(widget);
			obs_frontend_open_projector("Scene", -1, "", obs_source_get_name(obs_scene_get_source(graph->scene)));
			QWidget *opened = nullptr;
			for (auto *widget : QApplication::allWidgets()) {
				if (QString::fromLatin1(widget->metaObject()->className()) == "OBSProjector" && !previous.contains(widget)) {
					if (opened) {
						widget->close();
						opened->close();
						status_->setText(tr("投影窗口身份不唯一，请重试。"));
						return;
					}
					opened = widget;
				}
			}
			if (!opened) {
				status_->setText(tr("OBS 未能打开投影窗口，请重试。"));
				return;
			}
			auto view = std::make_unique<ProjectorView>();
			view->id = ++next_projector_id_;
			view->window = opened;
			view->graph = graph;
			view->cameras = cameras;
			view->versions = versions;
			view->scene_id = scene_id;
			view->scene_fingerprint = fingerprint;
			view->studio_revision = scene ? body.value("studioRevision").toInteger(-1) : -1;
			const auto id = view->id;
			opened->installEventFilter(this);
			opened->setWindowTitle(tr("WebOBS 固定场景投影 %1 · F11 全屏").arg(index + 1));
			connect(opened, &QObject::destroyed, this, [this, index, id] {
				if (projectors_[index] && projectors_[index]->id == id) {
					projectors_[index].reset();
					update_projector_controls();
					observe_current_media();
				}
			});
			close_projector(index);
			projectors_[index] = std::move(view);
			restore_projector_placement(QString("fixed-%1").arg(index + 1), opened);
			update_projector_controls();
			observe_current_media();
		});
	}
	void renew_projectors()
	{
		if (user_id_.isEmpty()) return;
		for (std::size_t i = 0; i < projectors_.size(); ++i) {
			if (!projectors_[i] || !projectors_[i]->window || projectors_[i]->heartbeat_pending) continue;
			auto &view = *projectors_[i];
			view.heartbeat_pending = true;
			const auto id = view.id;
			const bool scene = !view.scene_id.isEmpty();
			const QJsonObject renewal = scene ?
				QJsonObject{{"sceneId", view.scene_id}, {"fingerprint", view.scene_fingerprint}} :
				QJsonObject{{"cameras", view.cameras}};
			request(scene ? "/api/v1/native/scenes/authorize" : "/api/v1/native/cameras/authorize", "POST", renewal,
				[this, i, id, scene](int code, const QJsonObject &body) {
				if (!projectors_[i] || projectors_[i]->id != id) return;
				auto &current = *projectors_[i];
				current.heartbeat_pending = false;
				if (code != 200) {
					if (tolerate_transient_renewal(code))
						return;
					locked(tr("投影会话、摄像机权限或配置已失效，请重新登录。"),
						code == 401 ? "projector-session-rejected" : "projector-renew-refused", code);
					return;
				}
				transient_renewals_ = 0;
				if (body.value("cameraVersions").toObject() != current.versions ||
				    (scene && (body.value("sceneFingerprint").toString() != current.scene_fingerprint ||
					body.value("studioRevision").toInteger(-1) < 0)))
					locked(tr("投影会话、摄像机权限或配置已失效，请重新登录。"), "projector-precondition-changed", code);
				else if (scene && body.value("studioRevision").toInteger(-1) != current.studio_revision) {
					current.studio_revision = body.value("studioRevision").toInteger(-1);
					observe_current_media();
				}
			}, 6000);
		}
	}

	// A renewal the local authority did not answer, because it is busy or briefly
	// unavailable, is not a revoked session. Two consecutive retries keep the wall
	// playing; a third unanswered renewal fails closed. An explicit refusal, a
	// changed device version or a changed Scene fingerprint still locks at once.
	static bool renewal_transient(int code)
	{
		return code == 0 || code == 408 || code == 429 || code == 500 || code == 502 || code == 503;
	}

	bool tolerate_transient_renewal(int code)
	{
		if (!renewal_transient(code))
			return false;
		++transient_renewals_;
		last_lock_code_ = code;
		if (transient_renewals_ < 3) {
			last_lock_ = QStringLiteral("renew-retrying");
			status_->setText(tr("本机授权服务繁忙，正在重试续期。"));
			return true;
		}
		last_lock_ = QStringLiteral("renew-unavailable");
		return false;
	}

	void locked(const QString &message, const char *category = "unspecified", int code = 0)
	{
		last_lock_ = QString::fromLatin1(category);
		last_lock_code_ = code;
		transient_renewals_ = 0;
		// Save only this account's window preferences before protected views
		// retire. Geometry never authorizes media or reopens a projector.
		for (std::size_t i = 0; i < projectors_.size(); ++i)
			if (projectors_[i]) remember_projector_placement(QString("fixed-%1").arg(i + 1), projectors_[i]->window);
		remember_projector_placement("program", program_projector_);
		save_projector_placements();
		projector_placements_ = {};
		if (client_) client_->reset_session();
		++main_generation_;
		retirement_elapsed_.start();
		heartbeat_.stop();
		program_sync_.stop();
		settlement_.stop();
		retirement_.stop();
		heartbeat_pending_ = false;
		applying_ = false;
		user_id_.clear();
		if (program_output_) program_output_->shutdown();
		clear_media();
		login_->setEnabled(true);
		for (auto *button : {watch_, save_, logout_, refresh_, scene_watch_, stats_button_, program_projector_button_,
			     record_program_, stream_program_, support_bundle_})
			if (button) button->setEnabled(false);
		slot_count_->setEnabled(false);
		camera_choices_->clear();
		for (auto *slot : slots_) slot->setEnabled(false);
		scenes_->clear();
		scenes_->setEnabled(false);
		status_->setText(message);
		if (media_source_count() == 0) {
			last_retirement_ms_ = retirement_elapsed_.elapsed();
			observe_state("locked");
		} else {
			// Do not publish a settled zero-source state or permit a new login
			// before the actual deferred references have left this process.
			login_->setEnabled(false);
			create_account_->setEnabled(false);
			observe_state("locking");
			retirement_.start(50);
		}
	}

	QString workspace_path() const
	{
		const auto name = ("workspace-" + user_id_ + ".json").toUtf8();
		char *path = obs_module_config_path(name.constData());
		const QString result = QString::fromUtf8(path ? path : "");
		bfree(path);
		return result;
	}

	QJsonArray selection() const
	{
		QJsonArray selected;
		for (auto *slot : slots_) {
			const auto item = slot->currentData().toJsonObject();
			if (item.isEmpty())
				return {};
			selected.append(item);
		}
		return selected;
	}

	void resize_slots(int count, const QJsonArray &selected = {})
	{
		if (count < 1 || count > int(maximum_quick_wall_slots)) return;
		while (camera_form_->rowCount()) camera_form_->removeRow(0);
		slots_.clear();
		for (int i = 0; i < count; ++i) {
			auto *slot = new QComboBox(this);
			slot->setObjectName(QString("webobsCameraSlot%1").arg(i + 1));
			slot->setAccessibleName(tr("画面 %1").arg(i + 1));
			// Share metadata across selectors instead of copying the whole
			// camera catalog up to 64 times. Authorization is still fresh at watch.
			slot->setModel(camera_choices_);
			const int match = i < selected.size() ? slot->findData(selected[i].toObject()) : 0;
			slot->setCurrentIndex(match > 0 ? match : 0);
			slot->setEnabled(!user_id_.isEmpty() && !applying_);
			camera_form_->addRow(tr("画面 %1").arg(i + 1), slot);
			slots_.push_back(slot);
		}
	}

	void refresh_registration()
	{
		request("/api/v1/auth/setup", "GET", {}, [this](int code, const QJsonObject &body) {
			create_account_->setEnabled(code == 200 && body.value("registrationOpen").toBool() &&
				user_id_.isEmpty() && login_->isEnabled());
		});
	}

	void login(const QJsonObject &credentials)
	{
		login_->setEnabled(false);
		create_account_->setEnabled(false);
		request("/api/v1/native/auth/login", "POST", credentials, [this](int code, const QJsonObject &body) {
			const auto id = body.value("userId").toString();
			if (code != 200 || !QRegularExpression("^[a-f0-9]{32}$").match(id).hasMatch()) {
				locked(tr("登录失败，请核对账号和本机服务状态。"));
				refresh_registration();
				return;
			}
			user_id_ = id;
			transient_renewals_ = 0;
			last_lock_ = QStringLiteral("none");
			last_lock_code_ = 0;
			QFile workspace_file(workspace_path());
			if (workspace_file.size() <= 16384 && workspace_file.open(QIODevice::ReadOnly)) {
				const auto saved = QJsonDocument::fromJson(workspace_file.readAll()).object()
					.value("projectorPlacements").toObject();
				for (const auto &role : {QString("fixed-1"), QString("fixed-2"), QString("program")})
					if (saved.value(role).isObject()) projector_placements_[role] = saved.value(role);
			}
			observe_state("authenticated");
			for (auto *button : {watch_, logout_, refresh_, scene_watch_, stats_button_, record_program_, stream_program_,
				     support_bundle_})
				button->setEnabled(true);
			status_->setText(tr("已登录，正在读取授权设备目录…"));
			heartbeat_last_ms_ = 0;
			heartbeat_.start(int(heartbeat_interval_ms));
			program_sync_.start(1000);
			sync_program();
			refresh_catalog(true);
		}, 12000);
	}

	void refresh_catalog(bool restore)
	{
		request("/api/v1/native/cameras", "GET", {}, [this, restore](int code, const QJsonObject &body) {
			if (code != 200 || !body.value("cameras").isArray()) {
				locked(tr("无法核验摄像机权限，请重新登录。"));
				return;
			}
			QJsonArray saved_selection;
			for (auto *slot : slots_) saved_selection.append(slot->currentData().toJsonObject());
			camera_choices_->clear();
			auto *placeholder = new QStandardItem(tr("选择摄像机与 Profile"));
			placeholder->setData(QJsonObject{}, Qt::UserRole);
			placeholder->setFlags(Qt::ItemIsEnabled | Qt::ItemIsSelectable);
			camera_choices_->appendRow(placeholder);
			for (const auto camera_value : body.value("cameras").toArray()) {
				const auto camera = camera_value.toObject();
				if (!camera.value("enabled").toBool())
					continue;
				for (const auto profile_value : camera.value("profiles").toArray()) {
					const auto profile = profile_value.toObject();
					if (!profile.value("enabled").toBool())
						continue;
					auto *choice = new QStandardItem(camera.value("name").toString() + " / " + profile.value("name").toString());
					choice->setData(QJsonObject{{"cameraId", camera.value("id")}, {"profileId", profile.value("id")}}, Qt::UserRole);
					choice->setFlags(Qt::ItemIsEnabled | Qt::ItemIsSelectable);
					camera_choices_->appendRow(choice);
				}
			}
			QString restore_scene;
			int count = restore ? 5 : slot_count_->value();
			if (restore) {
				QFile file(workspace_path());
				if (file.size() <= 16384 && file.open(QIODevice::ReadOnly)) {
					const auto workspace = QJsonDocument::fromJson(file.readAll()).object();
					if (workspace.value("schema").toInt() == 2)
						restore_scene = workspace.value("sceneId").toString();
					else {
						const auto saved = workspace.value("cameras").toArray();
						if (!saved.isEmpty() && saved.size() <= int(maximum_quick_wall_slots)) {
							count = int(saved.size());
							saved_selection = saved;
						}
					}
				}
			}
			{
				const QSignalBlocker blocker(slot_count_);
				slot_count_->setValue(count);
			}
			resize_slots(count, saved_selection);
			slot_count_->setEnabled(!applying_);
			observe_state(watching_.isEmpty() ? "authenticated" : "graph-applied");
			if (restore && restore_scene.isEmpty() && selection().size() == count) watch();
			refresh_scenes(restore_scene);
		}, 12000);
	}

	void refresh_scenes(const QString &restore_id = {})
	{
		request("/api/v1/native/scenes", "GET", {}, [this, restore_id](int code, const QJsonObject &body) {
			if (code != 200 || !body.value("scenes").isArray() || body.value("revision").toInteger(-1) < 0)
				return;
			scenes_->clear();
			scenes_->addItem(tr("选择已保存的 Studio 场景"), QJsonObject{});
			int restored = 0;
			for (const auto value : body.value("scenes").toArray()) {
				const auto scene = value.toObject();
				scenes_->addItem(scene.value("name").toString(),
					QJsonObject{{"sceneId", scene.value("id")}, {"revision", body.value("revision")},
						{"fingerprint", scene.value("fingerprint")}});
				if (scene.value("id").toString() == restore_id)
					restored = scenes_->count() - 1;
			}
			scenes_->setEnabled(!applying_);
			observe_state(applying_ ? "connecting" : (watching_.isEmpty() ? "authenticated" : "graph-applied"));
			if (restored > 0) {
				scenes_->setCurrentIndex(restored);
				watch_scene();
			}
		});
	}

	void begin_connecting()
	{
		++main_generation_;
		settlement_.stop();
		save_->setEnabled(false);
		// Keep the current authorized graph alive while resolving its successor.
		// The heartbeat continues renewing this exact graph during preparation.
		applying_ = true;
		update_projector_controls();
		observe_state("connecting");
		for (auto *button : {watch_, refresh_, scene_watch_}) button->setEnabled(false);
		scenes_->setEnabled(false);
		slot_count_->setEnabled(false);
		for (auto *slot : slots_) slot->setEnabled(false);
		status_->setText(tr("正在核验权限并连接摄像机…"));
	}

	void apply_graph(const SceneDocument &document, const std::vector<ProductCamera> &cameras,
		const QJsonArray &selected, const QJsonObject &versions, const QJsonObject &video,
		const QString &scene_id = {}, qint64 studio_revision = -1, const QString &fingerprint = {})
	{
		std::string error;
		obs_video_info actual{};
		const bool same_video = obs_get_video_info(&actual) &&
			actual.base_width == unsigned(video.value("width").toInt()) &&
			actual.base_height == unsigned(video.value("height").toInt()) &&
			actual.output_width == actual.base_width && actual.output_height == actual.base_height &&
			actual.fps_den != 0 && std::uint64_t(actual.fps_num) ==
			std::uint64_t(video.value("fps").toInt()) * actual.fps_den;
		if (!same_video && (projectors_[0] || projectors_[1])) {
			applying_ = false;
			save_->setEnabled(wall_ && !watching_.isEmpty());
			for (auto *button : {watch_, refresh_, scene_watch_}) button->setEnabled(true);
			scenes_->setEnabled(true);
			slot_count_->setEnabled(true);
			for (auto *slot : slots_) slot->setEnabled(true);
			update_projector_controls();
			status_->setText(tr("请先关闭固定投影，再更改主画面的画布或帧率。"));
			observe_current_media();
			return;
		}
		if (!same_video) {
			clear_main_media();
			if (!apply_product_video_config(video.value("width").toInt(), video.value("height").toInt(),
				video.value("fps").toInt(), error)) {
				locked(tr("无法应用项目画布或帧率，请检查视频设置。"));
				return;
			}
		}
		// Build before releasing the previous graph, so compatible owned sources
		// retain their decoder and socket across a same-canvas layout change.
		auto candidate = create_product_scene(source_pool_, user_id_.toStdString(), document, cameras, error);
		applying_ = false;
		for (auto *button : {watch_, refresh_, scene_watch_}) button->setEnabled(true);
		scenes_->setEnabled(true);
		slot_count_->setEnabled(true);
		for (auto *slot : slots_) slot->setEnabled(true);
		if (!candidate || !candidate->scene) {
			clear_main_media();
			update_projector_controls();
			status_->setText(tr("原生画面创建失败；部分来源、音轨或资产仍需接入。"));
			observe_state("graph-failed");
			return;
		}
		if (!select_monitor(candidate->scene)) {
			candidate.reset();
			locked(tr("原生 Preview 不可用，请退出后重新打开。"));
			return;
		}
		wall_ = std::move(candidate);
		refresh_renderer();
		watching_ = selected;
		watching_versions_ = versions;
		watching_scene_id_ = scene_id;
		watching_scene_fingerprint_ = fingerprint;
		watching_studio_revision_ = studio_revision;
		save_->setEnabled(true);
		update_projector_controls();
		observe_state("graph-applied");
		status_->setText(tr("原生场景已创建，视频状态见下方。"));
		refresh_video_health();
		// Observe bounded deferred retirement without hiding removed inputs from
		// accounting or delaying the actual scene switch.
		if (media_source_count() != int(owned_media_source_count())) {
			settlement_elapsed_.start();
			settlement_.start(50);
		}
	}

	void watch_scene()
	{
		const auto choice = scenes_->currentData().toJsonObject();
		const auto id = choice.value("sceneId").toString();
		const auto revision = choice.value("revision").toInteger(-1);
		const auto expected_fingerprint = choice.value("fingerprint").toString();
		const bool by_content = QRegularExpression("^[a-f0-9]{64}$").match(expected_fingerprint).hasMatch();
		const QJsonObject wanted = by_content ? QJsonObject{{"sceneId", id}, {"fingerprint", expected_fingerprint}} :
			QJsonObject{{"sceneId", id}, {"revision", revision}};
		if (id.isEmpty() || revision < 0 || user_id_.isEmpty() || applying_) return;
		begin_connecting();
		request("/api/v1/native/scenes/resolve", "POST", wanted,
			[this, wanted, id, revision, expected_fingerprint, by_content](int code, const QJsonObject &body) {
			const auto fingerprint = body.value("sceneFingerprint").toString();
			if (code != 200 || body.value("studioRevision").toInteger(-1) < 0 ||
			    (!by_content && body.value("studioRevision").toInteger(-1) != revision) ||
			    (by_content && fingerprint != expected_fingerprint) || !body.value("scene").isObject() ||
			    !QRegularExpression("^[a-f0-9]{64}$").match(fingerprint).hasMatch()) {
				locked(tr("场景不可用或已变更，请登录后刷新；部分业务来源仍需接入。"));
				return;
			}
			request("/api/v1/native/scenes/authorize", "POST", wanted,
				[this, id, revision, by_content, fingerprint, body](int status, const QJsonObject &authorization) {
				if (status != 200 || authorization.value("studioRevision").toInteger(-1) < 0 ||
				    (!by_content && authorization.value("studioRevision").toInteger(-1) != revision) ||
				    authorization.value("sceneFingerprint").toString() != fingerprint ||
				    authorization.value("cameraVersions") != body.value("cameraVersions")) {
					locked(tr("场景或摄像机权限已变更，请重新登录。"));
					return;
				}
				const auto bytes = QJsonDocument(body.value("scene").toObject()).toJson(QJsonDocument::Compact);
				auto parsed = parse_scene_json(std::string_view(bytes.constData(), std::size_t(bytes.size())));
				const auto resolved = body.value("cameras").toArray();
				if (!parsed.ok() || parsed.document->sources.size() != std::size_t(resolved.size())) {
					locked(tr("场景资料无效，请检查已保存的布局。"));
					return;
				}
				std::vector<ProductCamera> cameras;
				QJsonArray selected;
				for (int i = 0; i < resolved.size(); ++i) {
					auto &source = parsed.document->sources[std::size_t(i)];
					const auto binding = resolved[i].toObject();
					if (source.kind != "camera" || source.camera_id != binding.value("cameraId").toString().toStdString() ||
					    source.profile_id != binding.value("profileId").toString().toStdString()) {
						locked(tr("场景来源身份不匹配，请重新登录。"));
						return;
					}
					ProductCamera camera;
					camera.id = source.camera_id;
					camera.profile_id = source.profile_id;
					camera.name = "WebOBS " + source.id;
					camera.url = binding.value("url").toString().toStdString();
					camera.transport = binding.value("transport").toString().toStdString();
					const auto requested_hardware = source.hardware_decode == "auto" ?
						binding.value("hardwareDecode").toString().toStdString() : source.hardware_decode;
					if (requested_hardware != "auto" && requested_hardware != "on" && requested_hardware != "off") {
						locked(tr("场景解码配置无效。"));
						return;
					}
					if (requested_hardware != "auto") camera.hardware_decode = requested_hardware == "on";
					source.hardware_decode = requested_hardware;
					source.transport = camera.transport;
					cameras.push_back(std::move(camera));
					selected.append(QJsonObject{{"cameraId", binding.value("cameraId")}, {"profileId", binding.value("profileId")}});
				}
				apply_graph(*parsed.document, cameras, selected, body.value("cameraVersions").toObject(),
					authorization.value("video").toObject(), id, authorization.value("studioRevision").toInteger(-1), fingerprint);
			}, 12000);
		}, 12000);
	}

	void watch()
	{
		const QJsonArray selected = selection();
		if (selected.size() != qsizetype(slots_.size()) || selected.isEmpty() || user_id_.isEmpty() || applying_) {
			status_->setText(tr("请为每个画面选择摄像机 Profile。"));
			observe_state("selection-incomplete");
			return;
		}
		begin_connecting();
		request("/api/v1/native/cameras/resolve", "POST", {{"cameras", selected}},
			[this, selected](int code, const QJsonObject &body) {
			if (code != 200 || body.value("cameras").toArray().size() != selected.size()) {
				locked(tr("摄像机授权或连接资料不可用，请重新登录。"));
				return;
			}
			const auto resolved = body.value("cameras").toArray();
			const auto versions = body.value("cameraVersions").toObject();
			std::set<QString> camera_ids;
			for (const auto value : selected)
				camera_ids.insert(value.toObject().value("cameraId").toString());
			if (std::size_t(versions.size()) != camera_ids.size()) {
				locked(tr("设备配置版本不可用，请重新登录。"));
				return;
			}
			// Reauthorize after resolution and immediately before OBS graph writes.
			request("/api/v1/native/cameras/authorize", "POST", {{"cameras", selected}},
				[this, selected, resolved, versions](int status, const QJsonObject &authorization) {
				if (status != 200) {
					locked(tr("观看权限已失效，请重新登录。"));
					return;
				}
				if (authorization.value("cameraVersions").toObject() != versions) {
					locked(tr("设备配置已变更，请重新连接。"));
					return;
				}
				const auto video = authorization.value("video").toObject();
				std::vector<ProductCamera> cameras(std::size_t(selected.size()));
				SceneDocument document;
				document.canvas.width = video.value("width").toInt();
				document.canvas.height = video.value("height").toInt();
				const auto tiles = quick_wall_layout(unsigned(document.canvas.width), unsigned(document.canvas.height), unsigned(selected.size()));
				if (tiles.size() != std::size_t(selected.size())) {
					locked(tr("画布不足以容纳所选路数，请修复画布设置。"));
					return;
				}
				for (int i = 0; i < selected.size(); ++i) {
					const auto item = resolved[i].toObject();
					const auto wanted = selected[i].toObject();
					if (item.value("cameraId") != wanted.value("cameraId") ||
					    item.value("profileId") != wanted.value("profileId")) {
						locked(tr("摄像机身份不匹配，请重新登录。"));
						return;
					}
					cameras[i].id = wanted.value("cameraId").toString().toStdString();
					cameras[i].profile_id = wanted.value("profileId").toString().toStdString();
					cameras[i].name = "WebOBS " + std::to_string(i + 1);
					cameras[i].url = item.value("url").toString().toStdString();
					cameras[i].transport = item.value("transport").toString().toStdString();
					const auto hardware = item.value("hardwareDecode").toString();
					if (hardware != "auto" && hardware != "on" && hardware != "off") {
						locked(tr("设备解码配置无效，请在设备库中修复。"));
						return;
					}
					if (hardware != "auto")
						cameras[i].hardware_decode = hardware == "on";
					SceneSource source;
					source.id = "slot-" + std::to_string(i + 1);
					source.kind = "camera";
					source.name = cameras[i].name;
					source.camera_id = cameras[i].id;
					source.profile_id = cameras[i].profile_id;
					source.transport = cameras[i].transport;
					source.hardware_decode = hardware.toStdString();
					// Preserve the existing monitor's continuous inactive-source policy.
					source.shutdown_when_hidden = false;
					document.sources.push_back(source);
					SceneItem scene_item;
					scene_item.id = source.id;
					scene_item.source_id = source.id;
					scene_item.x = int(tiles[i].x);
					scene_item.y = int(tiles[i].y);
					scene_item.width = int(tiles[i].width);
					scene_item.height = int(tiles[i].height);
					scene_item.z_index = i;
					document.items.push_back(scene_item);
				}
				apply_graph(document, cameras, selected, versions, video);
			}, 12000);
		}, 12000);
	}

	void closeEvent(QCloseEvent *event) override
	{
		if (!quitting_ && tray_ && program_output_) {
			const auto value = program_output_->status();
			if (value.recording || value.streaming) {
				hide();
				tray_->showMessage(tr("WebOBS Wall"),
					tr("Program 录像或推流仍在运行。使用托盘图标恢复窗口或停止输出后退出。"),
					QSystemTrayIcon::Information, 5000);
				event->ignore();
				return;
			}
		}
		locked(tr("正在退出…"));
		frontend_->close();
		event->accept();
	}
	bool eventFilter(QObject *object, QEvent *event) override
	{
		if (event->type() == QEvent::Move || event->type() == QEvent::Resize ||
		    event->type() == QEvent::WindowStateChange || event->type() == QEvent::Close) {
			if (program_projector_ && object == program_projector_.data())
				remember_projector_placement("program", program_projector_);
			for (std::size_t i = 0; i < projectors_.size(); ++i)
				if (projectors_[i] && object == projectors_[i]->window.data())
					remember_projector_placement(QString("fixed-%1").arg(i + 1), projectors_[i]->window);
		}
		if (program_projector_ && object == program_projector_.data()) {
			if (event->type() == QEvent::WindowStateChange)
				QTimer::singleShot(0, this, [this] { observe_current_media(); });
			if (event->type() == QEvent::KeyPress && static_cast<QKeyEvent *>(event)->key() == Qt::Key_F11) {
				if (!static_cast<QKeyEvent *>(event)->isAutoRepeat()) toggle_projector_fullscreen(program_projector_);
				observe_current_media();
				return true;
			}
			if (event->type() == QEvent::MouseButtonDblClick &&
			    static_cast<QMouseEvent *>(event)->button() == Qt::LeftButton) {
				toggle_projector_fullscreen(program_projector_);
				observe_current_media();
				return true;
			}
		}
		for (const auto &view : projectors_) {
			if (!view || object != view->window.data()) continue;
			if (event->type() == QEvent::WindowStateChange)
				QTimer::singleShot(0, this, [this] { observe_current_media(); });
			if (event->type() == QEvent::KeyPress && static_cast<QKeyEvent *>(event)->key() == Qt::Key_F11) {
				if (!static_cast<QKeyEvent *>(event)->isAutoRepeat()) toggle_projector_fullscreen(view->window);
				observe_current_media();
				return true;
			}
			if (event->type() == QEvent::MouseButtonDblClick &&
			    static_cast<QMouseEvent *>(event)->button() == Qt::LeftButton) {
				toggle_projector_fullscreen(view->window);
				observe_current_media();
				return true;
			}
		}
		if (object == preview_) {
			switch (event->type()) {
			case QEvent::MouseButtonPress:
			case QEvent::MouseButtonRelease:
			case QEvent::MouseButtonDblClick:
			case QEvent::MouseMove:
			case QEvent::Wheel:
			case QEvent::ContextMenu:
			case QEvent::KeyPress:
			case QEvent::KeyRelease:
			case QEvent::ShortcutOverride:
			case QEvent::DragEnter:
			case QEvent::DragMove:
			case QEvent::DragLeave:
			case QEvent::Drop:
			case QEvent::TouchBegin:
			case QEvent::TouchUpdate:
			case QEvent::TouchEnd:
				event->accept();
				return true;
			default:
				break;
			}
		}
		return QWidget::eventFilter(object, event);
	}

public:
	void observe_visible_window()
	{
		if (user_id_.isEmpty()) observe_state("locked");
		else observe_current_media();
	}
	explicit ProductWindow(QWidget *frontend) : QWidget(frontend, Qt::Window), frontend_(frontend)
	{
		// Initialize OBS's real Preview/Program separation while no protected
		// source exists. The product restore guard already refused collection I/O.
		obs_frontend_set_preview_program_mode(false);
		blank_scene_ = obs_scene_create("WebOBS locked preview");
		if (blank_scene_)
			obs_frontend_set_current_scene(obs_scene_get_source(blank_scene_));
		obs_frontend_set_preview_program_mode(true);
		idle_program_uuid_ = program_state().value("sceneUuid").toString();
		const bool preview_delivery = qEnvironmentVariable("WEBOBS_NATIVE_PREVIEW") == "true";
		const QString product_version = qEnvironmentVariable("WEBOBS_NATIVE_PRODUCT_VERSION");
		setWindowTitle(preview_delivery ? tr("WebOBS Wall v4.5 · 原生监看预览版") :
			(product_version.isEmpty() ? tr("WebOBS Wall") : tr("WebOBS Wall %1").arg(product_version)));
		setObjectName("webobsProductWindow");
		resize(1280, 800);
		auto *body = new QHBoxLayout(this);
		auto *controls = new QWidget(this);
		controls->setMinimumWidth(280);
		controls->setMaximumWidth(360);
		auto *layout = new QVBoxLayout(controls);
		if (preview_delivery) {
			auto *notice = new QLabel(tr("v4.5 预览版：原生监看、账号、场景与投影。录像/NVR、旧数据导入和自动更新尚未提供。"), controls);
			notice->setWordWrap(true);
			layout->addWidget(notice);
		}
		layout->setContentsMargins(0, 0, 0, 0);
		auto *sidebar = new QScrollArea(this);
		sidebar->setWidgetResizable(true);
		sidebar->setHorizontalScrollBarPolicy(Qt::ScrollBarAlwaysOff);
		sidebar->setMinimumWidth(300);
		sidebar->setMaximumWidth(380);
		sidebar->setWidget(controls);
		body->addWidget(sidebar);
		status_ = new QLabel(tr("登录 WebOBS 后选择已有摄像机。"), this);
		status_->setWordWrap(true);
		layout->addWidget(status_);
		health_clock_.start();
		video_health_ = new QLabel(tr("视频输入：未监看"), this);
		video_health_->setObjectName("webobsVideoHealth");
		video_health_->setWordWrap(true);
		video_health_->setToolTip(tr("只检查 OBS 媒体源是否交付新视频帧；不代表最终画面、硬解或独显验证。低于每六秒一帧的来源可能显示停滞。"));
		layout->addWidget(video_health_);
		audio_health_ = new QLabel(tr("音频混音：无（空选择或未配置）"), this);
		audio_health_->setObjectName("webobsAudioHealth");
		audio_health_->setWordWrap(true);
		audio_health_->setToolTip(tr("显示原生逐轨混音源数量与 OBS 电平峰值；不把静音、无音频轨或监听关闭误报为成功。"));
		layout->addWidget(audio_health_);
		renderer_label_ = new QLabel(this);
		renderer_label_->setObjectName("webobsRendererDevice");
		renderer_label_->setWordWrap(true);
		renderer_label_->setToolTip(tr("显示 OBS 实际使用的画面渲染适配器；不代表摄像机解码使用相同显卡或已启用硬解。"));
		layout->addWidget(renderer_label_);
		refresh_renderer();
		auto *form = new QFormLayout;
		username_ = new QLineEdit(this);
		username_->setObjectName("webobsUsername");
		username_->setAccessibleName(tr("账号"));
		username_->setMaxLength(64);
		password_ = new QLineEdit(this);
		password_->setObjectName("webobsPassword");
		password_->setAccessibleName(tr("密码"));
		password_->setMaxLength(128);
		password_->setEchoMode(QLineEdit::Password);
		form->addRow(tr("账号"), username_);
		form->addRow(tr("密码"), password_);
		layout->addLayout(form);
		login_ = new QPushButton(tr("登录"), this);
		login_->setObjectName("webobsLogin");
		layout->addWidget(login_);
		create_account_ = new QPushButton(tr("创建首个管理员账号"), this);
		create_account_->setEnabled(false);
		create_account_->setObjectName("webobsCreateAccount");
		layout->addWidget(create_account_);
		slot_count_ = new QSpinBox(this);
		slot_count_->setRange(1, int(maximum_quick_wall_slots));
		slot_count_->setValue(5);
		slot_count_->setKeyboardTracking(false);
		slot_count_->setToolTip(tr("选择要配置的路数，再点击“开始原生监看”应用。"));
		slot_count_->setObjectName("webobsCameraCount");
		slot_count_->setAccessibleName(tr("监看路数"));
		auto *count_form = new QFormLayout;
		count_form->addRow(tr("监看路数"), slot_count_);
		layout->addLayout(count_form);
		camera_choices_ = new QStandardItemModel(this);
		camera_form_ = new QFormLayout;
		layout->addLayout(camera_form_);
		resize_slots(5);
		connect(slot_count_, &QSpinBox::valueChanged, this, [this](int count) {
			QJsonArray selected;
			for (auto *slot : slots_) selected.append(slot->currentData().toJsonObject());
			resize_slots(count, selected);
			observe_current_media();
		});
		watch_ = new QPushButton(tr("开始原生监看"), this);
		save_ = new QPushButton(tr("保存布局"), this);
		save_->setToolTip(tr("保存当前布局和投影窗口位置；打开投影时恢复其屏幕、大小和全屏偏好。"));
		logout_ = new QPushButton(tr("退出账号"), this);
		refresh_ = new QPushButton(tr("刷新设备目录"), this);
		watch_->setObjectName("webobsWatch");
		save_->setObjectName("webobsSaveLayout");
		logout_->setObjectName("webobsLogout");
		refresh_->setObjectName("webobsRefreshCatalog");
		for (auto *button : {watch_, save_, refresh_, logout_})
			layout->addWidget(button);
		scenes_ = new QComboBox(this);
		scenes_->setObjectName("webobsStudioScene");
		scenes_->setAccessibleName(tr("已保存的 Studio 场景"));
		scene_watch_ = new QPushButton(tr("监看所选 Studio 场景"), this);
		scene_watch_->setObjectName("webobsWatchScene");
		layout->addWidget(scenes_);
		layout->addWidget(scene_watch_);
		auto *projector_row = new QHBoxLayout;
		for (std::size_t i = 0; i < projector_buttons_.size(); ++i) {
			projector_buttons_[i] = new QPushButton(tr("固定场景投影 %1").arg(i + 1), this);
			projector_buttons_[i]->setObjectName(QString("webobsFixedProjector%1").arg(i + 1));
			projector_row->addWidget(projector_buttons_[i]);
			connect(projector_buttons_[i], &QPushButton::clicked, this, [this, i] { open_projector(i); });
		}
		layout->addLayout(projector_row);
		close_projectors_ = new QPushButton(tr("关闭固定投影"), this);
		close_projectors_->setObjectName("webobsCloseProjectors");
		layout->addWidget(close_projectors_);
		connect(close_projectors_, &QPushButton::clicked, this, [this] {
			for (std::size_t i = 0; i < projectors_.size(); ++i) close_projector(i);
			close_program_projector();
		});
		program_projector_button_ = new QPushButton(tr("打开 Program 投影"), this);
		program_projector_button_->setObjectName("webobsProgramProjector");
		program_projector_button_->setToolTip(tr("显示 OBS 真实 Program 输出；TAKE 确认后才可用。"));
		layout->addWidget(program_projector_button_);
		connect(program_projector_button_, &QPushButton::clicked, this, [this] { open_program_projector(); });
		if (!preview_delivery) {
			program_output_ = std::make_unique<ProductProgramOutput>(
				qEnvironmentVariable("WEBOBS_NATIVE_PROFILE_ROOT"));
			record_program_ = new QPushButton(tr("录制 Program"), this);
			record_program_->setObjectName("webobsRecordProgram");
			record_program_->setToolTip(tr("由同一个 OBS 宿主把实际 Program 画面和混音录制为 MP4；无任务时不启动编码器。"));
			layout->addWidget(record_program_);
			connect(record_program_, &QPushButton::clicked, this, [this] { toggle_recording(); });
			stream_program_ = new QPushButton(tr("推流 Program"), this);
			stream_program_->setObjectName("webobsStreamProgram");
			stream_program_->setToolTip(tr("按需启动本机 MediaMTX，以 RTMP 接收 Program 并对外提供 RTSP/WHEP；停止后释放推流进程。"));
			layout->addWidget(stream_program_);
			connect(stream_program_, &QPushButton::clicked, this, [this] { toggle_streaming(); });
			output_health_ = new QLabel(tr("Program 输出：空闲"), this);
			output_health_->setObjectName("webobsOutputHealth");
			output_health_->setWordWrap(true);
			layout->addWidget(output_health_);
			support_bundle_ = new QPushButton(tr("生成支持包"), this);
			support_bundle_->setObjectName("webobsSupportBundle");
			support_bundle_->setToolTip(tr("导出有界脱敏状态、计数和 OBS 标记统计；不包含摄像机地址、令牌、日志正文或媒体。"));
			layout->addWidget(support_bundle_);
			connect(support_bundle_, &QPushButton::clicked, this, [this] { generate_support_bundle(); });
			if (QSystemTrayIcon::isSystemTrayAvailable()) {
				tray_ = new QSystemTrayIcon(windowIcon(), this);
				auto *menu = new QMenu(this);
				auto *show = menu->addAction(tr("显示 WebOBS Wall"));
				connect(show, &QAction::triggered, this, [this] {
					showNormal();
					raise();
					activateWindow();
				});
				auto *quit = menu->addAction(tr("停止 Program 输出并退出"));
				connect(quit, &QAction::triggered, this, [this] {
					quitting_ = true;
					if (program_output_) program_output_->shutdown();
					locked(tr("正在退出…"));
					frontend_->close();
				});
				tray_->setContextMenu(menu);
				tray_->setToolTip(tr("WebOBS Wall：Program 输出在后台运行"));
				connect(tray_, &QSystemTrayIcon::activated, this,
					[this](QSystemTrayIcon::ActivationReason reason) {
						if (reason == QSystemTrayIcon::Trigger) {
							showNormal();
							raise();
							activateWindow();
						}
					});
				tray_->show();
			}
		}
		auto *manage = new QPushButton(tr("设备与来源管理"), this);
		manage->setObjectName("webobsManageDevices");
		layout->addWidget(manage);
		for (const auto &[text, fragment, object] : std::array<std::tuple<const char *, const char *, const char *>, 9>{{
				{"音频与监听", "/audio", "webobsManageAudio"},
				{"分析策略", "/analytics", "webobsManageAnalytics"},
				{"事件与通知", "/events", "webobsManageEvents"},
				{"录像与回放", "/archive", "webobsManageArchive"},
				{"录像与存储", "/storage", "webobsManageStorage"},
				{"网站来源", "/go2rtc", "webobsManageGo2rtc"},
				{"账号与权限", "/admin", "webobsManageAdmin"},
				{"我的账号", "/account", "webobsManageAccount"},
				{"系统设置", "/settings", "webobsManageSettings"}}}) {
			auto *button = new QPushButton(tr(text), this);
			button->setObjectName(QString::fromLatin1(object));
			layout->addWidget(button);
			connect(button, &QPushButton::clicked, this,
				[this, fragment = QString::fromLatin1(fragment)] { open_management_page(fragment); });
		}
		stats_button_ = new QPushButton(tr("OBS 宿主统计"), this);
		stats_button_->setObjectName("webobsHostStats");
		stats_button_->setToolTip(tr("查看 OBS 原有 FPS、渲染延迟和掉帧。CPU、内存仅统计宿主进程。"));
		layout->addWidget(stats_button_);
		connect(stats_button_, &QPushButton::clicked, this, [this] { open_stats(); });
		layout->addStretch(1);
		for (auto *widget : frontend->findChildren<QWidget *>("preview")) {
			if (QString::fromLatin1(widget->metaObject()->className()) == "OBSBasicPreview") {
				preview_ = widget;
				widget->setFocusPolicy(Qt::NoFocus);
				widget->setAcceptDrops(false);
				widget->installEventFilter(this);
				widget->setMinimumSize(320, 180);
				widget->setParent(this);
				body->addWidget(widget, 1);
				widget->show();
				break;
			}
		}
		origin_ = QUrl(qEnvironmentVariable("WEBOBS_NATIVE_CONTROL_ORIGIN"));
		host_secret_ = qgetenv("WEBOBS_NATIVE_HOST_TOKEN");
		connect(&retirement_, &QTimer::timeout, this, [this] {
			if (media_source_count() == 0) {
				retirement_.stop();
				last_retirement_ms_ = retirement_elapsed_.elapsed();
				login_->setEnabled(true);
				observe_state("locked");
				refresh_registration();
			} else if (retirement_elapsed_.elapsed() >= 2000) {
				retirement_.stop();
				last_retirement_ms_ = retirement_elapsed_.elapsed();
				status_->setText(tr("摄像机已停止显示，但资源尚未完全释放，请退出后重开。"));
				observe_state("cleanup-failed");
			}
		});
		connect(&settlement_, &QTimer::timeout, this, [this] {
			if (media_source_count() == int(owned_media_source_count())) {
				settlement_.stop();
				observe_current_media();
			} else if (settlement_elapsed_.elapsed() >= 2000) {
				locked(tr("旧视频输入未能及时释放，请退出后重试。"));
			} else {
				observe_current_media();
			}
		});
		locked(tr("请登录已有 WebOBS 账号。"));
		if (!blank_scene_ || idle_program_uuid_.isEmpty() || !obs_frontend_preview_program_mode_active()) {
			status_->setText(tr("无法初始化 OBS Preview/Program，请退出后重新打开。"));
			login_->setEnabled(false);
			manage->setEnabled(false);
			return;
		}
		if (origin_.scheme() != "http" || origin_.host() != "127.0.0.1" || origin_.port() < 1 ||
		    !origin_.userInfo().isEmpty() || !origin_.path().isEmpty() || origin_.hasQuery() || origin_.hasFragment() ||
		    !QRegularExpression("^[a-f0-9]{64}$").match(QString::fromLatin1(host_secret_)).hasMatch()) {
			status_->setText(tr("本机产品服务连接失败，请从 WebOBS Wall 启动入口重试。"));
			login_->setEnabled(false);
			manage->setEnabled(false);
			return;
		}
		client_ = std::make_unique<ProductHttpClient>(origin_, host_secret_, this);
		connect(login_, &QPushButton::clicked, this, [this] {
			const QJsonObject credentials{{"username", username_->text()}, {"password", password_->text()}};
			password_->clear();
			login(credentials);
		});
		refresh_registration();
		connect(create_account_, &QPushButton::clicked, this, [this] {
			const QJsonObject credentials{{"username", username_->text()}, {"password", password_->text()}};
			password_->clear();
			create_account_->setEnabled(false);
			login_->setEnabled(false);
			request("/api/v1/auth/setup", "POST", credentials, [this, credentials](int code, const QJsonObject &) {
				if (code == 201)
					login(credentials);
				else {
					locked(tr("创建账号失败，请检查账号格式和密码要求后重试。"));
					refresh_registration();
				}
			}, 12000);
		});
		connect(password_, &QLineEdit::returnPressed, login_, &QPushButton::click);
		connect(watch_, &QPushButton::clicked, this, [this] { watch(); });
		connect(scene_watch_, &QPushButton::clicked, this, [this] { watch_scene(); });
		connect(refresh_, &QPushButton::clicked, this, [this] { refresh_catalog(false); });
		connect(save_, &QPushButton::clicked, this, [this] {
			if (watching_.isEmpty() || applying_ || user_id_.isEmpty()) {
				status_->setText(tr("请先连接要保存的摄像机。"));
				return;
			}
			QSaveFile file(workspace_path());
			QJsonObject workspace = watching_scene_id_.isEmpty() ?
				QJsonObject{{"schema", 1}, {"cameras", watching_}} :
				QJsonObject{{"schema", 2}, {"sceneId", watching_scene_id_}};
			if (!projector_placements_.isEmpty()) workspace["projectorPlacements"] = projector_placements_;
			const auto bytes = QJsonDocument(workspace).toJson();
			if (!QDir().mkpath(QFileInfo(file.fileName()).absolutePath()) ||
			    !file.open(QIODevice::WriteOnly) || file.write(bytes) != bytes.size() || !file.commit())
				status_->setText(tr("布局保存失败，已有布局已保留。"));
			else
				status_->setText(tr("布局已保存，重新登录后恢复。"));
		});
		connect(logout_, &QPushButton::clicked, this, [this] {
			request("/api/v1/native/auth/logout", "POST", {}, [](int, const QJsonObject &) {});
			locked(tr("已退出账号。"));
		});
		connect(manage, &QPushButton::clicked, this, [this] { open_management_page("/devices"); });
		connect(&program_sync_, &QTimer::timeout, this, [this] { sync_program(); });
		placement_save_.setSingleShot(true);
		connect(&placement_save_, &QTimer::timeout, this, [this] {
			save_projector_placements();
			observe_current_media();
		});
		connect(&heartbeat_, &QTimer::timeout, this, [this] {
			const qint64 now_ms = QDateTime::currentMSecsSinceEpoch();
			if (heartbeat_last_ms_ > 0) {
				const qint64 lag = now_ms - heartbeat_last_ms_ - heartbeat_interval_ms;
				// Only a late tick of a continuously running timer says something about the
				// UI thread; a gap across a logout or a stopped timer does not.
				if (lag > 250 && lag < 60000) {
					ui_stall_last_ms_ = lag;
					ui_stall_at_ms_ = now_ms;
					if (lag > ui_stall_max_ms_)
						ui_stall_max_ms_ = lag;
				}
			}
			heartbeat_last_ms_ = now_ms;
			remember_open_projector_placements();
			refresh_video_health();
			refresh_output_health();
			renew_projectors(); // Remains active while the main view resolves another scene.
			if (heartbeat_pending_ || user_id_.isEmpty())
				return;
			heartbeat_pending_ = true;
			const std::weak_ptr<ProductSceneGraph> renewed_graph = wall_;
			const bool active = !watching_.isEmpty();
			const bool scene_active = active && !watching_scene_id_.isEmpty();
			const QString path = scene_active ? "/api/v1/native/scenes/authorize" :
				(active ? "/api/v1/native/cameras/authorize" : "/api/v1/native/auth/session");
			const QJsonObject renewal = scene_active ?
				QJsonObject{{"sceneId", watching_scene_id_}, {"fingerprint", watching_scene_fingerprint_}} :
				QJsonObject{{"cameras", watching_}};
			// The authority answers this through the account/registry services, which can
			// be busy while Program output runs; the server enforces its own budget.
			request(path, active ? "POST" : "GET", renewal, [this, active, scene_active, renewed_graph](int code, const QJsonObject &body) {
				heartbeat_pending_ = false;
				// A finished renewal of the old graph cannot revoke a newer graph.
				// A graph retained during preparation MUST still enforce its result.
				if ((active && renewed_graph.expired()) || renewed_graph.lock() != wall_) return;
				if (code != 200) {
					if (tolerate_transient_renewal(code))
						return;
					locked(tr("会话或摄像机权限已失效，请重新登录。"),
						code == 401 ? "session-rejected" : "renew-refused", code);
					return;
				}
				transient_renewals_ = 0;
				if (active && body.value("cameraVersions").toObject() != watching_versions_)
					locked(tr("设备配置已变更，请重新登录后连接。"), "camera-versions-changed", code);
				else if (scene_active && (body.value("sceneFingerprint").toString() != watching_scene_fingerprint_ ||
					body.value("studioRevision").toInteger(-1) < 0))
					locked(tr("场景已变更，请重新登录后连接。"), "scene-changed", code);
				else if (scene_active && body.value("studioRevision").toInteger(-1) != watching_studio_revision_) {
					watching_studio_revision_ = body.value("studioRevision").toInteger(-1);
					observe_current_media();
				}
			}, 6000);
		});
		render_probe_attach();
	}
	~ProductWindow() override
	{
		tearing_down_ = true;
		render_probe_detach();
		heartbeat_.stop();
		program_sync_.stop();
		settlement_.stop();
		retirement_.stop();
		client_.reset();
		if (tray_) {
			tray_->hide();
			tray_ = nullptr;
		}
		if (program_output_) {
			program_output_->shutdown();
			program_output_.reset();
		}
		clear_media();
		if (blank_scene_ && obs_initialized()) {
			obs_source_remove(obs_scene_get_source(blank_scene_));
			obs_scene_release(blank_scene_);
			blank_scene_ = nullptr;
		}
		// OBS retains its UI pointer through frontend teardown.
		if (preview_) {
			preview_->setParent(frontend_);
			preview_->hide();
		}
	}
};
} // namespace

void start_product_window()
{
	auto *frontend = static_cast<QWidget *>(obs_frontend_get_main_window());
	if (!frontend || !frontend->property("webobsProductFrontend").toBool())
		return;
	if (!product_window)
		product_window = new ProductWindow(frontend);
	// The raw frontend remains alive for OBS's lifecycle, while its editing and
	// application-shortcut entry points stay outside the product input surface.
	for (auto *action : frontend->findChildren<QAction *>()) {
		action->setEnabled(false);
		action->setShortcuts({});
	}
	frontend->hide();
	product_window->show();
	obs_frontend_set_preview_enabled(true);
	// Native handles can change during the first show/layout. Publish the
	// actual visible product root again instead of keeping a constructor HWND.
	QTimer::singleShot(0, product_window, [] {
		if (product_window) product_window->observe_visible_window();
	});
}

void stop_product_window()
{
	delete product_window.data();
	product_window = nullptr;
}
} // namespace webobs::native_host
