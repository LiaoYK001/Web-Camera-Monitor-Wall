#include "wall.hpp"

#include <obs-module.h>
#include <obs-frontend-api.h>
#include <QComboBox>
#include <QCoreApplication>
#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QFormLayout>
#include <QGuiApplication>
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

// Development-only load receipt. No arbitrary output path, camera/source settings,
// URL or user configuration is serialized. The external smoke runner owns the
// entirely new portable tree and checks normal process exit and private isolation.
void frontend_event(enum obs_frontend_event event, void *)
{
	if (event == OBS_FRONTEND_EVENT_EXIT) {
		frontend_alive = false;
		return;
	}
	if (event != OBS_FRONTEND_EVENT_FINISHED_LOADING)
		return;
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
	QFile receipt(profile + "/native-smoke.json");
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
