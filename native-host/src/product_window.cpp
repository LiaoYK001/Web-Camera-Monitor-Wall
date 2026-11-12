#include "product_window.hpp"
#include "product_bootstrap.hpp"
#include "product_scene.hpp"
#include "layout.hpp"
#include "wall.hpp"

#include <obs-frontend-api.h>
#include <obs-module.h>
#include <QAction>
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
#include <QNetworkAccessManager>
#include <QNetworkCookieJar>
#include <QNetworkProxy>
#include <QNetworkReply>
#include <QPointer>
#include <QPushButton>
#include <QRegularExpression>
#include <QSaveFile>
#include <QTimer>
#include <QUrl>
#include <QVBoxLayout>
#include <QWidget>

#include <array>
#include <functional>
#include <memory>
#include <set>

namespace webobs::native_host {
namespace {
class ProductWindow;
QPointer<ProductWindow> product_window;

class ProductWindow final : public QWidget {
	// One bounded Studio document plus its separately authorized private bindings.
	static constexpr qint64 response_limit = 2 * maximum_scene_json_bytes;
	QWidget *frontend_;
	QWidget *preview_ = nullptr;
	QNetworkAccessManager network_;
	QTimer heartbeat_;
	QTimer retirement_;
	QElapsedTimer retirement_elapsed_;
	QUrl origin_;
	QByteArray host_secret_;
	QLineEdit *username_, *password_;
	QLabel *status_;
	QPushButton *login_, *create_account_, *watch_, *save_, *logout_, *refresh_, *scene_watch_;
	QComboBox *scenes_ = nullptr;
	std::array<QComboBox *, 5> slots_{};
	ProductSourcePool source_pool_;
	std::unique_ptr<ProductSceneGraph> wall_;
	QJsonArray watching_;
	QJsonObject watching_versions_;
	QString watching_scene_id_;
	qint64 watching_studio_revision_ = -1;
	QString user_id_;
	quint64 generation_ = 0;
	bool heartbeat_pending_ = false;
	bool applying_ = false;
	qint64 last_retirement_ms_ = 0;

	using Reply = std::function<void(int, const QJsonObject &)>;
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
		const auto generation = generation_;
		QUrl url = origin_;
		url.setPath(path);
		QNetworkRequest message(url);
		message.setRawHeader("Origin", origin_.toString(QUrl::RemovePath).toUtf8());
		message.setRawHeader("X-WebOBS-Native-Host", host_secret_);
		message.setHeader(QNetworkRequest::ContentTypeHeader, "application/json");
		message.setAttribute(QNetworkRequest::RedirectPolicyAttribute, QNetworkRequest::ManualRedirectPolicy);
		message.setTransferTimeout(timeout_ms);
		QNetworkReply *reply = method == "GET" ? network_.get(message) :
			network_.post(message, QJsonDocument(body).toJson(QJsonDocument::Compact));
		reply->setReadBufferSize(response_limit);
		auto *deadline = new QTimer(reply);
		deadline->setSingleShot(true);
		connect(deadline, &QTimer::timeout, reply, &QNetworkReply::abort);
		deadline->start(timeout_ms);
		auto bytes = std::make_shared<QByteArray>();
		connect(reply, &QNetworkReply::readyRead, this, [reply, bytes] {
			if (reply->bytesAvailable() > response_limit - bytes->size()) {
				reply->abort();
				return;
			}
			bytes->append(reply->readAll());
		});
		connect(reply, &QNetworkReply::finished, this, [this, reply, bytes, deadline, generation, callback] {
			deadline->stop();
			const int code = reply->attribute(QNetworkRequest::HttpStatusCodeAttribute).toInt();
			const auto document = QJsonDocument::fromJson(*bytes);
			const bool valid = reply->error() == QNetworkReply::NoError && document.isObject();
			reply->deleteLater();
			if (generation == generation_)
				callback(valid ? code : (code >= 400 ? code : 0), document.object());
		});
	}

	void clear_media()
	{
		watching_ = {};
		watching_versions_ = {};
		watching_scene_id_.clear();
		watching_studio_revision_ = -1;
		if (!obs_initialized())
			return;
		// Graph teardown detaches pictures first and retires only its last-owned
		// media entries. Other authorized graphs can retain shared sources.
		wall_.reset();
	}

	void locked(const QString &message)
	{
		++generation_;
		retirement_elapsed_.start();
		heartbeat_.stop();
		retirement_.stop();
		heartbeat_pending_ = false;
		applying_ = false;
		clear_media();
		user_id_.clear();
		network_.setCookieJar(new QNetworkCookieJar(&network_));
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
			for (auto *button : {watch_, save_, logout_, refresh_, scene_watch_})
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
		++generation_;
		heartbeat_pending_ = false;
		clear_media();
		applying_ = true;
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
		clear_media();
		std::string error;
		if (!apply_product_video_config(video.value("width").toInt(), video.value("height").toInt(),
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
			clear_media();
			status_->setText(tr("原生画面创建失败；部分来源、音轨或资产仍需接入。"));
			observe_state("graph-failed");
			return;
		}
		select_wall(wall_->scene);
		watching_ = selected;
		watching_versions_ = versions;
		watching_scene_id_ = scene_id;
		watching_studio_revision_ = studio_revision;
		observe_state("graph-applied");
		status_->setText(tr("原生监看已连接。"));
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
	explicit ProductWindow(QWidget *frontend) : QWidget(frontend, Qt::Window), frontend_(frontend), network_(this)
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
		body->addWidget(controls);
		status_ = new QLabel(tr("登录 WebOBS 后选择已有摄像机。"), this);
		layout->addWidget(status_);
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
		network_.setProxy(QNetworkProxy::NoProxy);
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
			if (heartbeat_pending_ || applying_ || user_id_.isEmpty())
				return;
			heartbeat_pending_ = true;
			const bool active = !watching_.isEmpty();
			const bool scene_active = active && !watching_scene_id_.isEmpty();
			const QString path = scene_active ? "/api/v1/native/scenes/authorize" :
				(active ? "/api/v1/native/cameras/authorize" : "/api/v1/native/auth/session");
			const QJsonObject renewal = scene_active ?
				QJsonObject{{"sceneId", watching_scene_id_}, {"revision", watching_studio_revision_}} :
				QJsonObject{{"cameras", watching_}};
			request(path, active ? "POST" : "GET", renewal, [this, active, scene_active](int code, const QJsonObject &body) {
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
		clear_media();
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
