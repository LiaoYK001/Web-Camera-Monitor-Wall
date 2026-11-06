#include "config_backup.hpp"
#include "native_ui_gate.hpp"
#include "product_bootstrap.hpp"
#include "ownership_store.hpp"
#include "renderer_device.hpp"
#include "wall.hpp"
#ifdef WEBOBS_NATIVE_PIXEL_TEST
#include "pixel_test.hpp"
#endif

#include <obs-module.h>
#include <obs-frontend-api.h>
#include <QComboBox>
#include <QCoreApplication>
#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QFormLayout>
#include <QGuiApplication>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QRegularExpression>
#include <QTimer>
#include <QLabel>
#include <QMessageBox>
#include <QPointer>
#include <QPushButton>
#include <QVBoxLayout>
#include <QWidget>

#include <array>
#include <cstring>

OBS_DECLARE_MODULE()
OBS_MODULE_USE_DEFAULT_LOCALE("webobs-native-host", "en-US")
MODULE_EXPORT const char *obs_module_description(void)
{
	return "WebOBS native frontend development prototype (not a product migration)";
}

namespace {
constexpr const char *dock_id = "webobs-native-host";
QPointer<QWidget> dock;
bool frontend_alive = false;

QJsonObject renderer_receipt()
{
	const auto device = webobs::native_host::observe_renderer_device();
	QJsonObject value{{"available", device.available}, {"hardwareDecodeVerified", false}};
	if (!device.available)
		return value;
	value.insert("api", QStringLiteral("d3d11"));
	// Same high:low LUID representation as the private PDH GPU diagnostic.
	value.insert("adapterLuid", QStringLiteral("%1:%2").arg(device.luid_high, 8, 16, QLatin1Char('0'))
		.arg(device.luid_low, 8, 16, QLatin1Char('0')));
	value.insert("vendorId", int(device.vendor_id));
	value.insert("deviceId", int(device.device_id));
	value.insert("software", device.software);
	value.insert("dedicatedVideoMemoryCapacityBytes", double(device.dedicated_video_memory));
	return value;
}

// Development-only load receipt. No arbitrary output path, camera/source settings,
// URL or user configuration is serialized. The external smoke runner owns the
// entirely new portable tree and checks normal process exit and private isolation.
void write_wall_receipt(const QJsonObject &object)
{
	char *path = obs_module_config_path("wall-bootstrap.json");
	if (!path)
		return;
	QFile receipt(QString::fromUtf8(path));
	bfree(path);
	if (receipt.open(QIODevice::WriteOnly | QIODevice::Truncate))
		receipt.write(QJsonDocument(object).toJson());
}

void bootstrap_configured_wall()
{
	char *config_path = obs_module_config_path("wall.json");
	if (!config_path)
		return;
	const QString path = QString::fromUtf8(config_path);
	bfree(config_path);
	QFile file(path);
	if (!file.exists())
		return;
	QJsonObject receipt{{"schema", 1}, {"scope", "existing-sources-only"}, {"ok", false}};
	const auto fail = [&receipt](const char *code) {
		receipt.insert("error", QString::fromLatin1(code));
		write_wall_receipt(receipt);
	};
	if (!file.open(QIODevice::ReadOnly) || file.size() > 4096) {
		fail("config-unreadable");
		return;
	}
	const auto document = QJsonDocument::fromJson(file.readAll());
	if (!document.isObject()) {
		fail("config-invalid-json");
		return;
	}
	const auto object = document.object();
	const auto sources = object.value("sources").toArray();
	if (object.value("schema").toInt() != 1 || sources.size() != 5) {
		fail("config-schema");
		return;
	}
	const QRegularExpression uuid("^[0-9a-fA-F]{8}-([0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}$");
	std::array<std::string, 5> uuids;
	for (int i = 0; i < 5; ++i) {
		const QString value = sources.at(i).toString();
		if (!uuid.match(value).hasMatch()) {
			fail("config-uuid");
			return;
		}
		uuids[std::size_t(i)] = value.toStdString();
	}
	auto resolved = webobs::native_host::ensure_five_tile_wall(uuids, "WebOBS Native Wall");
	receipt.insert("reused", resolved.reused);
	receipt.insert("items", 5);
	if (!resolved.scene) {
		receipt.insert("error", resolved.error.empty() ? QStringLiteral("wall-unavailable")
							       : QString::fromStdString(resolved.error));
		write_wall_receipt(receipt);
		return;
	}
	obs_scene_release(resolved.scene);
	receipt.insert("ok", true);
	write_wall_receipt(receipt);
}

void write_product_receipt(const QJsonObject &object)
{
	char *path = obs_module_config_path("product-bootstrap.json");
	if (!path)
		return;
	QFile receipt(QString::fromUtf8(path));
	bfree(path);
	if (receipt.open(QIODevice::WriteOnly | QIODevice::Truncate))
		receipt.write(QJsonDocument(object).toJson());
}

// Provenance persistence: records ONLY sources created by this bootstrap
// (reused sources never yield an entry). The stored ledger is a local claim
// record inside the module's private config directory — not an authorization
// grant, not a secret, and no durability/rename-atomicity strength is claimed
// (see ownership_store.hpp). Failures are surfaced as receipt fields without
// failing the wall itself.
void record_product_ownership(const std::array<webobs::native_host::ProductCamera, 5> &cameras,
                              const webobs::native_host::ProductWallResult &product,
                              QJsonObject &receipt)
{
	char *path = obs_module_config_path("source-ownership.json");
	if (!path)
		return;
	const QString file = QString::fromUtf8(path);
	bfree(path);
	const auto loaded = webobs::native_host::load_ownership_store(file.toStdString());
	if (loaded.status == webobs::native_host::OwnershipStoreStatus::invalid_ledger) {
		receipt.insert("ownershipLedger", QStringLiteral("ledger-invalid"));
		return;
	}
	if (loaded.status == webobs::native_host::OwnershipStoreStatus::io_error) {
		receipt.insert("ownershipLedger", QStringLiteral("store-io-error"));
		return;
	}
	auto entries = loaded.entries;
	for (std::size_t i = 0; i < cameras.size(); ++i) {
		if (!product.created_here[i])
			continue;
		if (webobs::native_host::record_created_source(entries, cameras[i].id, product.uuids[i]) !=
		    webobs::native_host::OwnershipStatus::success) {
			receipt.insert("ownershipLedger", QStringLiteral("record-conflict"));
			return;
		}
	}
	if (entries.empty()) // nothing created and no prior ledger: persist nothing
		return;
	if (webobs::native_host::save_ownership_store(file.toStdString(), entries) !=
	    webobs::native_host::OwnershipStoreStatus::success)
		receipt.insert("ownershipLedger", QStringLiteral("store-io-error"));
	else
		receipt.insert("ownershipEntries", static_cast<int>(entries.size()));
}

void bootstrap_product_cameras()
{
	char *config_path = obs_module_config_path("product.json");
	if (!config_path)
		return;
	const QString path = QString::fromUtf8(config_path);
	bfree(config_path);
	QFile file(path);
	if (!file.exists())
		return;
	QJsonObject receipt{{"schema", 1}, {"scope", "product-cameras"}, {"ok", false}};
	receipt.insert("renderer", renderer_receipt());
	const auto fail = [&receipt](const char *code) {
		receipt.insert("error", QString::fromLatin1(code));
		write_product_receipt(receipt);
	};
	if (!file.open(QIODevice::ReadOnly) || file.size() > 16384) {
		fail("config-unreadable");
		return;
	}
	const auto document = QJsonDocument::fromJson(file.readAll());
	if (!document.isObject()) {
		fail("config-invalid-json");
		return;
	}
	const auto object = document.object();
	const auto cameras_json = object.value("cameras").toArray();
	if (object.value("schema").toInt() != 1 || cameras_json.size() != 5) {
		fail("config-schema");
		return;
	}
	const QRegularExpression id_pattern("^[A-Za-z0-9_.-]{1,64}$");
	const QRegularExpression url_pattern("^(rtsp|rtsps|http|https)://");
	std::array<webobs::native_host::ProductCamera, 5> cameras{};
	for (int i = 0; i < 5; ++i) {
		const auto camera = cameras_json.at(i).toObject();
		const QString id = camera.value("id").toString();
		const QString name = camera.value("name").toString();
		const QString url = camera.value("url").toString();
		const auto hardware_decode = camera.value("hardwareDecode");
		if (!id_pattern.match(id).hasMatch() || name.isEmpty() || name.size() > 128 ||
		    name.contains('\n') || name.contains('\r') || url.size() > 2048 ||
		    !camera.value("url").isString() || !url_pattern.match(url).hasMatch() ||
		    (!hardware_decode.isUndefined() && !hardware_decode.isBool())) {
			fail("config-camera");
			return;
		}
		cameras[std::size_t(i)] = {id.toStdString(), name.toStdString(), url.toStdString(),
					   hardware_decode.isUndefined() ? std::nullopt :
					   std::optional<bool>(hardware_decode.toBool())};
	}
	bool canvas_applied = false;
	const auto canvas_value = object.value("canvas");
	if (canvas_value.isObject()) {
		const auto canvas = canvas_value.toObject();
		std::string error;
		if (!webobs::native_host::apply_product_video_config(canvas.value("width").toInt(0),
								     canvas.value("height").toInt(0),
								     canvas.value("fps").toInt(0), error)) {
			receipt.insert("error", QString::fromStdString(error.empty() ? "video-config" : error));
			write_product_receipt(receipt);
			return;
		}
		canvas_applied = true;
		obs_video_info actual{};
		if (!obs_get_video_info(&actual)) {
			fail("video-config-unavailable");
			return;
		}
		receipt.insert("videoInfo", QJsonObject{{"baseWidth", int(actual.base_width)},
			{"baseHeight", int(actual.base_height)}, {"outputWidth", int(actual.output_width)},
			{"outputHeight", int(actual.output_height)}, {"fpsNumerator", int(actual.fps_num)},
			{"fpsDenominator", int(actual.fps_den)}});
	}
	auto product = webobs::native_host::create_product_five_camera_wall(cameras, "WebOBS Native Wall");
	receipt.insert("created", product.created);
	receipt.insert("reused", product.reused);
	receipt.insert("sceneReused", product.scene_reused);
	receipt.insert("canvasApplied", canvas_applied);
	receipt.insert("items", 5);
	if (!product.error.empty() || !product.scene) {
		receipt.insert("error",
			       QString::fromStdString(product.error.empty() ? "wall-unavailable" : product.error));
		product.release();
		write_product_receipt(receipt);
		return;
	}
	record_product_ownership(cameras, product, receipt);
	int hardware_requests = 0;
	bool requests_available = true;
	for (auto *source : product.sources) {
		auto *settings = obs_source_get_settings(source);
		if (!settings) {
			requests_available = false;
			break;
		}
		hardware_requests += obs_data_get_bool(settings, "hw_decode") ? 1 : 0;
		obs_data_release(settings);
	}
	// Stored requests only: OBS chooses the decoder and may fall back. Neither
	// this count nor the renderer device verifies per-camera hardware decoding.
	if (requests_available)
		receipt.insert("hardwareDecodeRequestedSources", hardware_requests);
	product.release();
	receipt.insert("ok", true);
	write_product_receipt(receipt);
}

void bootstrap_product_configuration()
{
	char *path = obs_module_config_path("product.json");
	const bool present = path && QFileInfo(QString::fromUtf8(path)).exists();
	if (path)
		bfree(path);
	if (present)
		bootstrap_product_cameras();
	else
		bootstrap_configured_wall();
}

void frontend_event(enum obs_frontend_event event, void *)
{
#ifdef WEBOBS_NATIVE_PIXEL_TEST
	const bool pixel_test_handled = webobs::native_host::pixel_test_event(event);
#else
	const bool pixel_test_handled = false;
#endif
	if (event == OBS_FRONTEND_EVENT_EXIT) {
		frontend_alive = false;
		return;
	}
	if (pixel_test_handled || event != OBS_FRONTEND_EVENT_FINISHED_LOADING)
		return;
	webobs::native_host::backup_config_for_upgrade_if_needed();
	bootstrap_product_configuration();
	const QString token = qEnvironmentVariable("WEBOBS_NATIVE_SMOKE_TOKEN");
	if (!QRegularExpression("^[0-9a-f]{32}$").match(token).hasMatch())
		return;

	const QDir bin(QCoreApplication::applicationDirPath());
	const QString root = QDir::cleanPath(bin.absoluteFilePath("../.."));
	const QString profile = QFileInfo(root + "/config/obs-studio").canonicalFilePath();
	char *module_config = obs_module_config_path("");
	const QString actual_module_config = module_config ? QDir::cleanPath(QFileInfo(QString::fromUtf8(module_config)).absoluteFilePath()) : QString{};
	bfree(module_config);
	QFile manifest_file(root + "/webobs-native-prototype.json");
	if (profile.isEmpty() || actual_module_config.compare(profile + "/plugin_config/webobs-native-host", Qt::CaseInsensitive) != 0 ||
	    !manifest_file.open(QIODevice::ReadOnly))
		return;
	const auto manifest = QJsonDocument::fromJson(manifest_file.readAll()).object();
	if (manifest.value("obsCommit").toString() != "fb4d98bf88fae5fc85cb11fc57f7c5e309282194" ||
	    !manifest.contains("defaultProduct") || manifest.value("defaultProduct").toBool(true))
		return;
	const QString receipt_name = qEnvironmentVariable("WEBOBS_NATIVE_SMOKE_RECEIPT", "native-smoke.json");
	if (!QRegularExpression("^[A-Za-z0-9._-]{1,80}\\.json$").match(receipt_name).hasMatch())
		return;
	QFile receipt(profile + "/" + receipt_name);
	if (!receipt.open(QIODevice::WriteOnly | QIODevice::NewOnly))
		return;
	const QJsonObject result{{"schema", 1}, {"token", token},
	                         {"obsVersion", QString::fromUtf8(obs_get_version_string())},
	                         {"qtVersion", QString::fromLatin1(qVersion())},
	                         {"qtPlatform", QGuiApplication::platformName()},
	                         {"profile", profile}, {"moduleConfig", actual_module_config},
	                         {"dockLoaded", !dock.isNull()},
	                         {"mediaSourceRegistered", (obs_get_source_output_flags("ffmpeg_source") & OBS_SOURCE_VIDEO) != 0},
	                         {"finishedLoading", true}, {"mediaQualified", false}};
	const QByteArray bytes = QJsonDocument(result).toJson();
	if (receipt.write(bytes) != bytes.size())
		return;
	receipt.close();
	// Let native OBS closeEvent/save/teardown run; never bypass via QApplication::quit.
	auto *main_window = static_cast<QWidget *>(obs_frontend_get_main_window());
	if (main_window)
		QTimer::singleShot(0, main_window, [main_window] { main_window->close(); });
}

class WallDock final : public QWidget {
	std::array<QComboBox *, 5> slots_{};

	void refresh()
	{
		std::array<QString, 5> selected;
		for (std::size_t i = 0; i < slots_.size(); ++i) {
			selected[i] = slots_[i]->currentData().toString();
			slots_[i]->clear();
			slots_[i]->addItem(tr("Select an existing Media Source"), QString{});
		}
		obs_enum_sources([](void *opaque, obs_source_t *source) {
			auto *self = static_cast<WallDock *>(opaque);
			const char *id = obs_source_get_unversioned_id(source);
			if (id && std::strcmp(id, "ffmpeg_source") == 0 && !obs_source_removed(source)) {
				// Display only names, never the URL/settings which may contain credentials.
				for (auto *slot : self->slots_)
					slot->addItem(QString::fromUtf8(obs_source_get_name(source)),
					              QString::fromUtf8(obs_source_get_uuid(source)));
			}
			return true;
		}, this);
		for (std::size_t i = 0; i < slots_.size(); ++i) {
			const int index = slots_[i]->findData(selected[i]);
			slots_[i]->setCurrentIndex(index < 0 ? 0 : index);
		}
	}

	void create_wall()
	{
		// Fail closed: the dock mutation requires an operator authorization
		// decision, and no control layer produces one for the plugin yet. The
		// other entry points (refresh, projector, bootstrap) stay documented
		// bypasses; see docs/native-control-auth.md.
		const auto gate = webobs::native_host::evaluate_ui_action(
			webobs::native_host::UiActionKind::dock_create_wall, webobs::native_host::UiAuthorizationState{});
		if (gate != webobs::native_host::UiGateStatus::allowed) {
			QMessageBox::warning(this, tr("WebOBS Native Prototype"),
			                     tr("Creating a wall from the dock requires an operator authorization "
			                        "decision, which is not connected to this prototype yet. The action "
			                        "was refused."));
			return;
		}
		std::array<std::string, 5> uuids;
		for (std::size_t i = 0; i < slots_.size(); ++i)
			uuids[i] = slots_[i]->currentData().toString().toStdString();
		auto result = webobs::native_host::create_five_tile_wall(uuids);
		if (!result.scene) {
			QMessageBox::warning(this, tr("WebOBS Native Prototype"),
			                     QString::fromStdString(result.error));
			return;
		}
		webobs::native_host::select_wall(result.scene);
		obs_scene_release(result.scene);
	}

public:
	WallDock()
	{
		auto *layout = new QVBoxLayout(this);
		auto *notice = new QLabel(tr("Development prototype — no product login or migration.\n"
		                            "Use a separate writable portable bundle. Add RTSP inputs with OBS Media Source\n"
		                            "properties first. Existing sources/decoders and their native settings are reused.\n"
		                            "Studio mode sends the new scene to Preview; TAKE remains manual."), this);
		notice->setWordWrap(true);
		layout->addWidget(notice);
		auto *form = new QFormLayout;
		for (std::size_t i = 0; i < slots_.size(); ++i) {
			slots_[i] = new QComboBox(this);
			form->addRow(tr("Tile %1").arg(static_cast<int>(i + 1)), slots_[i]);
		}
		layout->addLayout(form);
		auto *refresh_button = new QPushButton(tr("Refresh existing Media Sources"), this);
		auto *create_button = new QPushButton(tr("Create a new five-tile scene"), this);
		auto *projector_button = new QPushButton(tr("Open native Program projector"), this);
		layout->addWidget(refresh_button);
		layout->addWidget(create_button);
		layout->addWidget(projector_button);
		layout->addStretch();
		connect(refresh_button, &QPushButton::clicked, this, [this] { refresh(); });
		connect(create_button, &QPushButton::clicked, this, [this] { create_wall(); });
		connect(projector_button, &QPushButton::clicked, this, [] {
			obs_frontend_open_projector("StudioProgram", -1, nullptr, nullptr);
		});
		refresh();
	}
};
} // namespace

bool obs_module_load(void)
{
	return true;
}

void obs_module_post_load(void)
{
	auto *widget = new WallDock;
	if (!obs_frontend_add_dock_by_id(dock_id, "WebOBS Native Prototype", widget)) {
		delete widget;
		return;
	}
	dock = widget;
	frontend_alive = true;
	obs_frontend_add_event_callback(frontend_event, nullptr);
}

void obs_module_unload(void)
{
	// The frontend API is destroyed after EVENT_EXIT, before libobs unloads us.
	if (frontend_alive) {
		obs_frontend_remove_event_callback(frontend_event, nullptr);
		if (dock)
			obs_frontend_remove_dock(dock_id);
	}
	frontend_alive = false;
	dock = nullptr;
}
