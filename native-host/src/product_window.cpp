#include "product_window.hpp"
#include "product_bootstrap.hpp"
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

namespace webobs::native_host {
namespace {
class ProductWindow;
QPointer<ProductWindow> product_window;

class ProductWindow final : public QWidget {
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
	QPushButton *login_, *create_account_, *watch_, *save_, *logout_, *refresh_;
	std::array<QComboBox *, 5> slots_{};
	ProductWallResult wall_;
	QJsonArray watching_;
	QJsonObject watching_versions_;
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
		for (auto *slot : slots_)
			selection_indices.append(slot ? slot->currentIndex() : -1);
		for (int i = 0; i < watching_.size(); ++i) {
			auto binding = watching_[i].toObject();
			binding.insert("sourceUuid", QString::fromStdString(wall_.uuids[std::size_t(i)]));
			bindings.append(binding);
		}
		QJsonObject state{{"schema", 1}, {"phase", QString::fromLatin1(phase)},
			{"pid", QString::number(QCoreApplication::applicationPid())},
			{"catalogItems", slots_[0] && slots_[0]->count() > 0 ? slots_[0]->count() - 1 : 0},
			{"selectionIndices", selection_indices},
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
		reply->setReadBufferSize(256 * 1024);
		auto *deadline = new QTimer(reply);
		deadline->setSingleShot(true);
		connect(deadline, &QTimer::timeout, reply, &QNetworkReply::abort);
		deadline->start(timeout_ms);
		auto bytes = std::make_shared<QByteArray>();
		connect(reply, &QNetworkReply::readyRead, this, [reply, bytes] {
			if (reply->bytesAvailable() > 256 * 1024 - bytes->size()) {
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
		if (!obs_initialized())
			return;
		// Detach protected pictures from the active scene immediately. Frontend
		// source-tree references and OBS's destruction queue may retire later.
		if (wall_.scene)
			obs_scene_enum_items(wall_.scene, [](obs_scene_t *, obs_sceneitem_t *item, void *) {
				obs_sceneitem_set_visible(item, false);
				obs_sceneitem_remove(item);
				return true;
			}, nullptr);
		// Clear the inputs before releasing graph references, including references
		// retained temporarily by the frontend. Credentials stay out of disk state.
		for (auto *source : wall_.sources) {
			if (!source)
				continue;
			auto *empty = obs_data_create();
			obs_data_set_bool(empty, "is_local_file", false);
			obs_data_set_string(empty, "input", "");
			obs_data_set_string(empty, "local_file", "");
			obs_source_update(source, empty);
			obs_data_release(empty);
			obs_source_remove(source);
		}
		if (wall_.scene)
			obs_source_remove(obs_scene_get_source(wall_.scene));
		wall_.release();
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
		for (auto *button : {watch_, save_, logout_, refresh_})
			button->setEnabled(false);
		for (auto *slot : slots_) {
			slot->clear();
			slot->setEnabled(false);
		}
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
			for (auto *button : {watch_, save_, logout_, refresh_})
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
			if (restore) {
				QFile file(workspace_path());
				if (file.size() <= 16384 && file.open(QIODevice::ReadOnly)) {
					const auto saved = QJsonDocument::fromJson(file.readAll()).object().value("cameras").toArray();
					if (saved.size() == 5)
						for (int i = 0; i < 5; ++i) {
							const int index = slots_[i]->findData(saved[i].toObject());
							slots_[i]->setCurrentIndex(index > 0 ? index : 0);
						}
				}
				if (selection().size() == 5)
					watch();
			}
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
		++generation_;
		heartbeat_pending_ = false;
		clear_media();
		applying_ = true;
		observe_state("connecting");
		watch_->setEnabled(false);
		refresh_->setEnabled(false);
		for (auto *slot : slots_)
			slot->setEnabled(false);
		status_->setText(tr("正在核验权限并连接摄像机…"));
		request("/api/v1/native/cameras/resolve", "POST", {{"cameras", selected}},
			[this, selected](int code, const QJsonObject &body) {
			if (code != 200 || body.value("cameras").toArray().size() != 5) {
				locked(tr("摄像机授权或连接资料不可用，请重新登录。"));
				return;
			}
			const auto resolved = body.value("cameras").toArray();
			const auto versions = body.value("cameraVersions").toObject();
			if (versions.size() != 5) {
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
				clear_media();
				const auto video = authorization.value("video").toObject();
				std::string video_error;
				if (!apply_product_video_config(video.value("width").toInt(), video.value("height").toInt(),
					video.value("fps").toInt(), video_error)) {
					locked(tr("无法应用项目画布或帧率，请检查视频设置。"));
					return;
				}
				std::array<ProductCamera, 5> cameras;
				for (int i = 0; i < 5; ++i) {
					const auto item = resolved[i].toObject();
					const auto wanted = selected[i].toObject();
					if (item.value("cameraId") != wanted.value("cameraId") ||
					    item.value("profileId") != wanted.value("profileId")) {
						locked(tr("摄像机身份不匹配，请重新登录。"));
						return;
					}
					cameras[i].id = wanted.value("cameraId").toString().toStdString();
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
				}
				wall_ = create_product_five_camera_wall(cameras, "WebOBS Wall");
				applying_ = false;
				watch_->setEnabled(true);
				refresh_->setEnabled(true);
				for (auto *slot : slots_)
					slot->setEnabled(true);
				if (!wall_.scene || !wall_.error.empty()) {
					clear_media();
					status_->setText(tr("原生画面创建失败，请检查设备配置后重试。"));
					observe_state("graph-failed");
					return;
				}
				select_wall(wall_.scene);
				watching_ = selected;
				watching_versions_ = versions;
				observe_state("graph-applied");
				status_->setText(tr("原生监看已连接。"));
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
		connect(refresh_, &QPushButton::clicked, this, [this] { refresh_catalog(false); });
		connect(save_, &QPushButton::clicked, this, [this] {
			if (watching_.size() != 5 || applying_) {
				status_->setText(tr("请先连接要保存的摄像机。"));
				return;
			}
			QSaveFile file(workspace_path());
			const auto bytes = QJsonDocument(QJsonObject{{"schema", 1}, {"cameras", watching_}}).toJson();
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
			request(active ? "/api/v1/native/cameras/authorize" : "/api/v1/native/auth/session",
				active ? "POST" : "GET", {{"cameras", watching_}}, [this, active](int code, const QJsonObject &body) {
				heartbeat_pending_ = false;
				if (code != 200)
					locked(tr("会话或摄像机权限已失效，请重新登录。"));
				else if (active && body.value("cameraVersions").toObject() != watching_versions_)
					locked(tr("设备配置已变更，请重新登录后连接。"));
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
