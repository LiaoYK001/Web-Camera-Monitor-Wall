#include "product_window.hpp"
#include "product_bootstrap.hpp"
#include "product_http_client.hpp"
#include "product_scene.hpp"
#include "layout.hpp"
#include "wall.hpp"

#include <obs-frontend-api.h>
#include <obs-module.h>
#include <QAction>
#include <QApplication>
#include <QCloseEvent>
#include <QComboBox>
#include <QCoreApplication>
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
#include <QMouseEvent>
#include <QPointer>
#include <QPushButton>
#include <QRegularExpression>
#include <QSaveFile>
#include <QScreen>
#include <QScrollArea>
#include <QTimer>
#include <QUrl>
#include <QVBoxLayout>
#include <QWidget>

#include <algorithm>
#include <array>
#include <functional>
#include <memory>
#include <map>
#include <set>

namespace webobs::native_host {
namespace {
class ProductWindow;
QPointer<ProductWindow> product_window;

class ProductWindow final : public QWidget {
	QWidget *frontend_;
	QWidget *preview_ = nullptr;
	std::unique_ptr<ProductHttpClient> client_;
	QTimer heartbeat_;
	QTimer retirement_;
	QElapsedTimer retirement_elapsed_;
	QUrl origin_;
	QByteArray host_secret_;
	QLineEdit *username_, *password_;
	QLabel *status_;
	QLabel *video_health_;
	QElapsedTimer health_clock_;
	struct InputHealth { std::int64_t serial = 0; qint64 changed_ms = 0; bool sampled = false, advanced = false; };
	std::map<std::string, InputHealth> input_health_;
	QPushButton *login_, *create_account_, *watch_, *save_, *logout_, *refresh_, *scene_watch_;
	QComboBox *scenes_ = nullptr;
	std::array<QComboBox *, 5> slots_{};
	ProductSourcePool source_pool_;
	std::shared_ptr<ProductSceneGraph> wall_;
	obs_scene_t *blank_scene_ = nullptr;
	bool tearing_down_ = false;
	struct ProjectorView {
		quint64 id = 0;
		QPointer<QWidget> window;
		std::shared_ptr<ProductSceneGraph> graph;
		QJsonArray cameras;
		QJsonObject versions;
		QString scene_id;
		qint64 studio_revision = -1;
		bool heartbeat_pending = false;
	};
	std::array<std::unique_ptr<ProjectorView>, 2> projectors_;
	std::array<QPushButton *, 2> projector_buttons_{};
	QPushButton *close_projectors_ = nullptr;
	std::array<bool, 2> projector_pending_{};
	quint64 next_projector_id_ = 0;
	QJsonArray watching_;
	QJsonObject watching_versions_;
	QString watching_scene_id_;
	qint64 watching_studio_revision_ = -1;
	QString user_id_;
	quint64 main_generation_ = 0;
	bool heartbeat_pending_ = false;
	bool applying_ = false;
	qint64 last_retirement_ms_ = 0;

	using Reply = std::function<void(int, const QJsonObject &)>;
	void refresh_video_health()
	{
		std::map<std::string, ProductVideoProgress> inputs;
		auto collect = [&](const std::shared_ptr<ProductSceneGraph> &graph) {
			if (graph) for (const auto &input : graph->video_progress()) inputs.emplace(input.uuid, input);
		};
		collect(wall_);
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
	void observe_state(const char *phase)
	{
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
			{"pid", QString::number(QCoreApplication::applicationPid())},
			{"catalogItems", slots_[0] && slots_[0]->count() > 0 ? slots_[0]->count() - 1 : 0},
			{"selectionIndices", selection_indices},
			{"sceneId", watching_scene_id_}, {"studioRevision", watching_studio_revision_},
			{"studioChoices", studio_choices},
			{"mainGeneration", qint64(main_generation_)},
			{"sessionBound", !user_id_.isEmpty()}, {"mediaSources", media_sources}, {"bindings", bindings},
			{"videoAvailable", video_available}, {"hardwareDecodeVerified", false}};
		state.insert("previewLocked", preview_ && preview_->property("webobsPreviewLocked").toBool());
		state.insert("restoreGuardHits", frontend_->property("webobsRestoreGuardHits").toInt());
		state.insert("refusedCollection", frontend_->property("webobsRefusedCollection").toString());
		state.insert("lastRetirementMs", last_retirement_ms_);
		if (preview_)
			state.insert("windows", QJsonArray{QJsonObject{{"role", "main-preview"},
				{"qtClass", QString::fromLatin1(preview_->metaObject()->className())},
				{"hwnd", QString::number(quintptr(preview_->winId()), 16)},
				{"rootHwnd", QString::number(quintptr(window()->winId()), 16)}}});
		QJsonArray projector_states;
		auto windows = state.value("windows").toArray();
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
				{"studioRevision", view.studio_revision}, {"bindings", view_bindings},
				{"fullscreen", view.window->isFullScreen()}});
			const auto role = view.window->isFullScreen() ? "fixed-scene-fullscreen-%1" : "fixed-scene-%1";
			windows.append(QJsonObject{{"role", QString::fromLatin1(role).arg(i + 1)},
				{"qtClass", QString::fromLatin1(view.window->metaObject()->className())},
				{"hwnd", QString::number(quintptr(view.window->winId()), 16)},
				{"rootHwnd", QString::number(quintptr(view.window->winId()), 16)}});
		}
		state.insert("windows", windows);
		state.insert("projectors", projector_states);
		if (video_available)
			state.insert("videoInfo", QJsonObject{{"baseWidth", int(video.base_width)},
				{"baseHeight", int(video.base_height)}, {"outputWidth", int(video.output_width)},
				{"outputHeight", int(video.output_height)}, {"fpsNumerator", int(video.fps_num)},
				{"fpsDenominator", int(video.fps_den)}});
		char *path = obs_module_config_path("product-state.json");
		QSaveFile file(QString::fromUtf8(path ? path : ""));
		bfree(path);
		const auto encoded = QJsonDocument(state).toJson();
		if (!QDir().mkpath(QFileInfo(file.fileName()).absolutePath()) || !file.open(QIODevice::WriteOnly) ||
		    file.write(encoded) != encoded.size() || !file.commit())
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
			close_projectors_->setEnabled(bool(projectors_[0]) || bool(projectors_[1]));
	}
	void observe_current_media()
	{
		if (!tearing_down_ && !user_id_.isEmpty())
			observe_state(applying_ ? "connecting" : (watching_.isEmpty() ? "authenticated" : "graph-applied"));
	}
	void close_projector(std::size_t index)
	{
		auto retired = std::move(projectors_[index]);
		if (retired && retired->window)
			retired->window->close(); // OBS removes its own projector-list entry.
		retired.reset();
		update_projector_controls();
	}
	void clear_main_media()
	{
		save_->setEnabled(false);
		watching_ = {};
		watching_versions_ = {};
		watching_scene_id_.clear();
		watching_studio_revision_ = -1;
		if (!obs_initialized())
			return;
		// Main Preview must blank without editing a graph still presented by a
		// fixed projector. The empty scene has no endpoint or media source.
		if (!tearing_down_) {
			if (!blank_scene_)
				blank_scene_ = obs_scene_create("WebOBS locked preview");
			if (blank_scene_ && !obs_source_removed(obs_scene_get_source(blank_scene_)))
				select_wall(blank_scene_);
		}
		wall_.reset();
	}
	void clear_media()
	{
		clear_main_media();
		projector_pending_.fill(false);
		for (std::size_t i = 0; i < projectors_.size(); ++i) close_projector(i);
		input_health_.clear();
		if (!tearing_down_) refresh_video_health();
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
	void open_projector(std::size_t index)
	{
		if (index >= projectors_.size() || projector_pending_[index] || applying_ || !wall_ || user_id_.isEmpty())
			return;
		const auto main_generation = main_generation_;
		const std::weak_ptr<ProductSceneGraph> graph_reference = wall_;
		const auto cameras = watching_;
		const auto versions = watching_versions_;
		const auto scene_id = watching_scene_id_;
		const auto revision = watching_studio_revision_;
		const bool scene = !scene_id.isEmpty();
		projector_pending_[index] = true;
		update_projector_controls();
		const QJsonObject renewal = scene ? QJsonObject{{"sceneId", scene_id}, {"revision", revision}} :
			QJsonObject{{"cameras", cameras}};
		request(scene ? "/api/v1/native/scenes/authorize" : "/api/v1/native/cameras/authorize", "POST", renewal,
			[this, index, main_generation, graph_reference, cameras, versions, scene_id, revision, scene]
			(int code, const QJsonObject &body) {
			projector_pending_[index] = false;
			update_projector_controls();
			const auto graph = graph_reference.lock();
			if (!graph || main_generation != main_generation_ || wall_ != graph || applying_) return;
			if (code != 200 || body.value("cameraVersions").toObject() != versions ||
			    (scene && body.value("studioRevision").toInteger(-1) != revision)) {
				locked(tr("投影观看权限或配置已失效，请重新登录。"));
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
			view->studio_revision = revision;
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
				QJsonObject{{"sceneId", view.scene_id}, {"revision", view.studio_revision}} :
				QJsonObject{{"cameras", view.cameras}};
			request(scene ? "/api/v1/native/scenes/authorize" : "/api/v1/native/cameras/authorize", "POST", renewal,
				[this, i, id, scene](int code, const QJsonObject &body) {
				if (!projectors_[i] || projectors_[i]->id != id) return;
				auto &current = *projectors_[i];
				current.heartbeat_pending = false;
				if (code != 200 || body.value("cameraVersions").toObject() != current.versions ||
				    (scene && body.value("studioRevision").toInteger(-1) != current.studio_revision))
					locked(tr("投影会话、摄像机权限或配置已失效，请重新登录。"));
			});
		}
	}

	void locked(const QString &message)
	{
		if (client_) client_->reset_session();
		++main_generation_;
		retirement_elapsed_.start();
		heartbeat_.stop();
		retirement_.stop();
		heartbeat_pending_ = false;
		applying_ = false;
		user_id_.clear();
		clear_media();
		login_->setEnabled(true);
		for (auto *button : {watch_, save_, logout_, refresh_, scene_watch_})
			button->setEnabled(false);
		for (auto *slot : slots_) {
			slot->clear();
			slot->setEnabled(false);
		}
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
			observe_state("authenticated");
			for (auto *button : {watch_, logout_, refresh_, scene_watch_})
				button->setEnabled(true);
			status_->setText(tr("已登录，正在读取授权设备目录…"));
			heartbeat_.start(2000);
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
			for (auto *slot : slots_) {
				slot->clear();
				slot->addItem(tr("选择摄像机与 Profile"), QJsonObject{});
				for (const auto camera_value : body.value("cameras").toArray()) {
					const auto camera = camera_value.toObject();
					if (!camera.value("enabled").toBool())
						continue;
					for (const auto profile_value : camera.value("profiles").toArray()) {
						const auto profile = profile_value.toObject();
						if (!profile.value("enabled").toBool())
							continue;
						slot->addItem(camera.value("name").toString() + " / " + profile.value("name").toString(),
							QJsonObject{{"cameraId", camera.value("id")}, {"profileId", profile.value("id")}});
					}
				}
				slot->setEnabled(true);
			}
			observe_state(watching_.isEmpty() ? "authenticated" : "graph-applied");
			QString restore_scene;
			if (restore) {
				QFile file(workspace_path());
				if (file.size() <= 16384 && file.open(QIODevice::ReadOnly)) {
					const auto workspace = QJsonDocument::fromJson(file.readAll()).object();
					if (workspace.value("schema").toInt() == 2)
						restore_scene = workspace.value("sceneId").toString();
					else {
						const auto saved = workspace.value("cameras").toArray();
						if (saved.size() == 5)
							for (int i = 0; i < 5; ++i) {
								const int index = slots_[i]->findData(saved[i].toObject());
								slots_[i]->setCurrentIndex(index > 0 ? index : 0);
							}
					}
				}
				if (restore_scene.isEmpty() && selection().size() == 5)
					watch();
			}
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
					QJsonObject{{"sceneId", scene.value("id")}, {"revision", body.value("revision")}});
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
		heartbeat_pending_ = false;
		clear_main_media();
		applying_ = true;
		update_projector_controls();
		observe_state("connecting");
		for (auto *button : {watch_, refresh_, scene_watch_}) button->setEnabled(false);
		scenes_->setEnabled(false);
		for (auto *slot : slots_) slot->setEnabled(false);
		status_->setText(tr("正在核验权限并连接摄像机…"));
	}

	void apply_graph(const SceneDocument &document, const std::vector<ProductCamera> &cameras,
		const QJsonArray &selected, const QJsonObject &versions, const QJsonObject &video,
		const QString &scene_id = {}, qint64 studio_revision = -1)
	{
		clear_main_media();
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
			for (auto *button : {watch_, refresh_, scene_watch_}) button->setEnabled(true);
			scenes_->setEnabled(true);
			for (auto *slot : slots_) slot->setEnabled(true);
			update_projector_controls();
			status_->setText(tr("请先关闭固定投影，再更改主画面的画布或帧率。"));
			observe_current_media();
			return;
		}
		if (!same_video && !apply_product_video_config(video.value("width").toInt(), video.value("height").toInt(),
			video.value("fps").toInt(), error)) {
			locked(tr("无法应用项目画布或帧率，请检查视频设置。"));
			return;
		}
		wall_ = create_product_scene(source_pool_, user_id_.toStdString(), document, cameras, error);
		applying_ = false;
		for (auto *button : {watch_, refresh_, scene_watch_}) button->setEnabled(true);
		scenes_->setEnabled(true);
		for (auto *slot : slots_) slot->setEnabled(true);
		if (!wall_ || !wall_->scene) {
			clear_main_media();
			update_projector_controls();
			status_->setText(tr("原生画面创建失败；部分来源、音轨或资产仍需接入。"));
			observe_state("graph-failed");
			return;
		}
		select_wall(wall_->scene);
		watching_ = selected;
		watching_versions_ = versions;
		watching_scene_id_ = scene_id;
		watching_studio_revision_ = studio_revision;
		save_->setEnabled(true);
		update_projector_controls();
		observe_state("graph-applied");
		status_->setText(tr("原生场景已创建，视频状态见下方。"));
		refresh_video_health();
	}

	void watch_scene()
	{
		const auto wanted = scenes_->currentData().toJsonObject();
		const auto id = wanted.value("sceneId").toString();
		const auto revision = wanted.value("revision").toInteger(-1);
		if (id.isEmpty() || revision < 0 || user_id_.isEmpty() || applying_) return;
		begin_connecting();
		request("/api/v1/native/scenes/resolve", "POST", wanted,
			[this, wanted, id, revision](int code, const QJsonObject &body) {
			if (code != 200 || body.value("studioRevision").toInteger(-1) != revision || !body.value("scene").isObject()) {
				locked(tr("场景不可用或已变更，请登录后刷新；部分业务来源仍需接入。"));
				return;
			}
			request("/api/v1/native/scenes/authorize", "POST", wanted,
				[this, id, revision, body](int status, const QJsonObject &authorization) {
				if (status != 200 || authorization.value("studioRevision").toInteger(-1) != revision ||
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
					authorization.value("video").toObject(), id, revision);
			}, 12000);
		}, 12000);
	}

	void watch()
	{
		const QJsonArray selected = selection();
		if (selected.size() != 5 || user_id_.isEmpty() || applying_) {
			status_->setText(tr("请选择五个摄像机 Profile。"));
			observe_state("selection-incomplete");
			return;
		}
		begin_connecting();
		request("/api/v1/native/cameras/resolve", "POST", {{"cameras", selected}},
			[this, selected](int code, const QJsonObject &body) {
			if (code != 200 || body.value("cameras").toArray().size() != 5) {
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
				std::vector<ProductCamera> cameras(5);
				SceneDocument document;
				document.canvas.width = video.value("width").toInt();
				document.canvas.height = video.value("height").toInt();
				const auto tiles = five_tile_layout(unsigned(document.canvas.width), unsigned(document.canvas.height));
				for (int i = 0; i < 5; ++i) {
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
		locked(tr("正在退出…"));
		frontend_->close();
		event->accept();
	}
	bool eventFilter(QObject *object, QEvent *event) override
	{
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
	explicit ProductWindow(QWidget *frontend) : QWidget(frontend, Qt::Window), frontend_(frontend)
	{
		setWindowTitle("WebOBS Wall");
		setObjectName("webobsProductWindow");
		resize(1280, 800);
		auto *body = new QHBoxLayout(this);
		auto *controls = new QWidget(this);
		controls->setMinimumWidth(280);
		controls->setMaximumWidth(360);
		auto *layout = new QVBoxLayout(controls);
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
		auto *cameras = new QFormLayout;
		for (std::size_t i = 0; i < slots_.size(); ++i) {
			slots_[i] = new QComboBox(this);
			slots_[i]->setObjectName(QString("webobsCameraSlot%1").arg(i + 1));
			slots_[i]->setAccessibleName(tr("画面 %1").arg(i + 1));
			cameras->addRow(tr("画面 %1").arg(i + 1), slots_[i]);
		}
		layout->addLayout(cameras);
		watch_ = new QPushButton(tr("开始原生监看"), this);
		save_ = new QPushButton(tr("保存布局"), this);
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
			observe_current_media();
		});
		auto *manage = new QPushButton(tr("打开设备与系统管理"), this);
		layout->addWidget(manage);
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
		locked(tr("请登录已有 WebOBS 账号。"));
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
			const QJsonObject workspace = watching_scene_id_.isEmpty() ?
				QJsonObject{{"schema", 1}, {"cameras", watching_}} :
				QJsonObject{{"schema", 2}, {"sceneId", watching_scene_id_}};
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
		connect(manage, &QPushButton::clicked, this, [this] {
			auto url = origin_;
			url.setFragment("/devices");
			QDesktopServices::openUrl(url);
		});
		connect(&heartbeat_, &QTimer::timeout, this, [this] {
			refresh_video_health();
			renew_projectors(); // Remains active while the main view resolves another scene.
			if (heartbeat_pending_ || applying_ || user_id_.isEmpty())
				return;
			heartbeat_pending_ = true;
			const auto main_generation = main_generation_;
			const bool active = !watching_.isEmpty();
			const bool scene_active = active && !watching_scene_id_.isEmpty();
			const QString path = scene_active ? "/api/v1/native/scenes/authorize" :
				(active ? "/api/v1/native/cameras/authorize" : "/api/v1/native/auth/session");
			const QJsonObject renewal = scene_active ?
				QJsonObject{{"sceneId", watching_scene_id_}, {"revision", watching_studio_revision_}} :
				QJsonObject{{"cameras", watching_}};
			request(path, active ? "POST" : "GET", renewal, [this, active, scene_active, main_generation](int code, const QJsonObject &body) {
				if (main_generation != main_generation_) return;
				heartbeat_pending_ = false;
				if (code != 200)
					locked(tr("会话或摄像机权限已失效，请重新登录。"));
				else if (active && body.value("cameraVersions").toObject() != watching_versions_)
					locked(tr("设备配置已变更，请重新登录后连接。"));
				else if (scene_active && body.value("studioRevision").toInteger(-1) != watching_studio_revision_)
					locked(tr("场景已变更，请重新登录后连接。"));
			});
		});
	}
	~ProductWindow() override
	{
		tearing_down_ = true;
		heartbeat_.stop();
		retirement_.stop();
		client_.reset();
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
	obs_frontend_set_preview_program_mode(false);
	obs_frontend_set_preview_enabled(true);
}

void stop_product_window()
{
	delete product_window.data();
	product_window = nullptr;
}
} // namespace webobs::native_host
