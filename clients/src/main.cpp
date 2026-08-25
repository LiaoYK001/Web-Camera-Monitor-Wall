#include "webobs/client/client_controller.hpp"
#include "webobs/client/client_auth_probe.hpp"
#include "webobs/client/batch_probe.hpp"
#include "webobs/client/grant_codec.hpp"
#include "webobs/client/media_pipeline.hpp"

#include <QGuiApplication>
#include <QHash>
#include <QCommandLineOption>
#include <QCommandLineParser>
#include <QCoreApplication>
#include <QDir>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QRegularExpression>
#include <QSet>
#include <QStringList>
#include <QQmlApplicationEngine>
#include <QQmlContext>
#include <QTimer>
#include <QFileInfo>
#include <QUrl>

int main(int argc, char *argv[])
{
    bool probe_requested = false;
    for (int index = 1; index < argc; ++index)
        if (QByteArrayView(argv[index]) == QByteArrayView("--probe-endpoint") ||
            QByteArrayView(argv[index]) == QByteArrayView("--probe-endpoint-env") ||
            QByteArrayView(argv[index]) == QByteArrayView("--probe-manifest") ||
            QByteArrayView(argv[index]) == QByteArrayView("--probe-background-release") ||
            QByteArrayView(argv[index]) == QByteArrayView("--probe-client-auth") ||
            QByteArrayView(argv[index]) == QByteArrayView("--probe-foreground-resume") ||
            QByteArrayView(argv[index]) == QByteArrayView("--probe-reconnect") ||
            QByteArrayView(argv[index]) == QByteArrayView("--verify-runtime"))
            probe_requested = true;
#if !defined(Q_OS_ANDROID)
    if (probe_requested && qEnvironmentVariableIsEmpty("QT_QPA_PLATFORM"))
        qputenv("QT_QPA_PLATFORM", "offscreen");
#endif
    QGuiApplication application(argc, argv);
    application.setApplicationName(QStringLiteral("WebObs Native"));
    application.setOrganizationName(QStringLiteral("WebObs"));
    application.setApplicationVersion(QStringLiteral(WEBOBS_CLIENT_VERSION));

#if defined(Q_OS_WIN)
    const QDir application_directory(QCoreApplication::applicationDirPath());
    const QString bundled_plugins = application_directory.absoluteFilePath(
        QStringLiteral("../lib/gstreamer-1.0"));
    const QString bundled_scanner = application_directory.absoluteFilePath(
        QStringLiteral("../libexec/gstreamer-1.0/gst-plugin-scanner.exe"));
    if (QFileInfo::exists(bundled_plugins) && QFileInfo::exists(bundled_scanner)) {
        qputenv("GST_PLUGIN_SYSTEM_PATH_1_0", QByteArray{});
        qputenv("GST_PLUGIN_PATH_1_0", QDir::toNativeSeparators(bundled_plugins).toUtf8());
        qputenv("GST_PLUGIN_SCANNER_1_0", QDir::toNativeSeparators(bundled_scanner).toUtf8());
    }
#endif

    QString error;
    if (!webobs::client::GrantCodec::initialize(error) ||
        !webobs::client::MediaPipeline::initialize(error)) {
        qCritical("%s", qPrintable(error));
        return 2;
    }

    QCommandLineParser parser;
    parser.setApplicationDescription(QStringLiteral("WebObs Native True Direct client"));
    parser.addHelpOption();
    parser.addVersionOption();
    parser.addOption({QStringLiteral("verify-runtime"),
                      QStringLiteral("Verify the self-contained desktop media runtime")});
    parser.addOption({QStringLiteral("probe-endpoint"), QStringLiteral("Run the production media pipeline without QML"),
                      QStringLiteral("url")});
    parser.addOption({QStringLiteral("probe-endpoint-env"),
                      QStringLiteral("Read the private probe endpoint from a named WEBOBS_* environment variable"),
                      QStringLiteral("name")});
    parser.addOption({QStringLiteral("probe-manifest"),
                      QStringLiteral("Run multiple production media pipelines in one process"),
                      QStringLiteral("absolute-json-path")});
    parser.addOption({QStringLiteral("probe-background-release"),
                      QStringLiteral("Stop all probe pipelines when Android enters background")});
    parser.addOption({QStringLiteral("probe-foreground-resume"),
                      QStringLiteral("Restart a released Android batch when it returns foreground")});
    parser.addOption({QStringLiteral("probe-reconnect"),
                      QStringLiteral("Retry previously ready batch streams after a bounded outage")});
    parser.addOption({QStringLiteral("probe-client-auth"),
                      QStringLiteral("Exercise enrollment, encrypted authorization and stop policy")});
    parser.addOption({QStringLiteral("probe-auth-offline"),
                      QStringLiteral("Disconnect the control plane after authorized playback starts")});
    parser.addOption({QStringLiteral("probe-control-url"),
                      QStringLiteral("HTTPS control URL for the authorization probe"),
                      QStringLiteral("url")});
    parser.addOption({QStringLiteral("probe-camera-id"),
                      QStringLiteral("Granted Camera ID for the authorization probe"),
                      QStringLiteral("id")});
    parser.addOption({QStringLiteral("probe-profile-id"),
                      QStringLiteral("Granted Profile ID for the authorization probe"),
                      QStringLiteral("id")});
    parser.addOption({QStringLiteral("probe-adapter"), QStringLiteral("rtsp, mjpeg, hls, or whep"),
                      QStringLiteral("adapter")});
    parser.addOption({QStringLiteral("probe-codec"), QStringLiteral("h264, h265, or mjpeg"),
                      QStringLiteral("codec")});
    parser.addOption({QStringLiteral("probe-seconds"), QStringLiteral("Playback evidence duration (1-7200)"),
                      QStringLiteral("seconds"), QStringLiteral("8")});
    parser.addOption({QStringLiteral("probe-record-mkv"),
                      QStringLiteral("Also exercise the production RTSP stream-copy recorder"),
                      QStringLiteral("absolute-path")});
    parser.process(application);
    if (parser.isSet(QStringLiteral("probe-foreground-resume")) &&
        !parser.isSet(QStringLiteral("probe-background-release"))) {
        qCritical("foreground resume probe requires background release mode");
        return 2;
    }
    const bool endpoint_argument = parser.isSet(QStringLiteral("probe-endpoint"));
    const bool endpoint_environment = parser.isSet(QStringLiteral("probe-endpoint-env"));
    if ((endpoint_argument && endpoint_environment) ||
        ((endpoint_argument || endpoint_environment) && parser.isSet(QStringLiteral("probe-manifest")))) {
        qCritical("choose one bounded probe mode");
        return 2;
    }
    if (parser.isSet(QStringLiteral("verify-runtime"))) {
        QStringList required{QStringLiteral("rtspsrc"), QStringLiteral("uridecodebin3"),
            QStringLiteral("decodebin3"), QStringLiteral("qml6glsink"),
            QStringLiteral("whepclientsrc"), QStringLiteral("whepsrc"),
            QStringLiteral("rtph264depay"),
            QStringLiteral("rtph265depay"), QStringLiteral("h264parse"),
            QStringLiteral("h265parse"), QStringLiteral("matroskamux"),
            QStringLiteral("matroskademux"), QStringLiteral("mp4mux"),
            QStringLiteral("videoconvert"), QStringLiteral("identity"),
            QStringLiteral("fakesink"), QStringLiteral("filesink"),
            QStringLiteral("audioconvert"), QStringLiteral("audioresample"),
            QStringLiteral("volume"), QStringLiteral("souphttpsrc"),
            QStringLiteral("hlsdemux2"), QStringLiteral("jpegdec"),
            QStringLiteral("avdec_h264"), QStringLiteral("avdec_h265"),
            QStringLiteral("webrtcbin"), QStringLiteral("nicesrc"),
            QStringLiteral("dtlssrtpdec"), QStringLiteral("dtlssrtpenc"),
            QStringLiteral("rtpbin"), QStringLiteral("opusdec"),
            QStringLiteral("alawdec"), QStringLiteral("mulawdec"),
            QStringLiteral("avdec_aac")};
        QStringList missing;
        QJsonObject plugin_versions;
        for (const QString &name : required) {
            GstElementFactory *factory = gst_element_factory_find(name.toUtf8().constData());
            if (factory) {
                const gchar *plugin_name = gst_plugin_feature_get_plugin_name(
                    GST_PLUGIN_FEATURE(factory));
                GstPlugin *plugin = plugin_name ? gst_registry_find_plugin(
                    gst_registry_get(), plugin_name) : nullptr;
                if (plugin) {
                    plugin_versions.insert(QString::fromLatin1(plugin_name),
                        QString::fromLatin1(gst_plugin_get_version(plugin)));
                    gst_object_unref(plugin);
                }
                gst_object_unref(factory);
            } else {
                missing << name;
            }
        }
        if (!missing.isEmpty()) {
            qCritical("self-contained runtime is missing required media elements: %s",
                      qPrintable(missing.join(',')));
            return 2;
        }
#if WEBOBS_LOCKED_RUNTIME
        const QHash<QString, QString> locked_plugin_versions{
            {QStringLiteral("rtspsrc"), QStringLiteral("1.28.6")},
            {QStringLiteral("uridecodebin3"), QStringLiteral("1.28.6")},
            {QStringLiteral("qml6glsink"), QStringLiteral("1.28.6")},
            {QStringLiteral("hlsdemux2"), QStringLiteral("1.28.6")},
            {QStringLiteral("avdec_h264"), QStringLiteral("1.28.6")},
            {QStringLiteral("whepclientsrc"), QStringLiteral("0.15.3")},
            {QStringLiteral("whepsrc"), QStringLiteral("0.15.3")},
        };
        QStringList mismatched;
        for (auto expected = locked_plugin_versions.cbegin();
             expected != locked_plugin_versions.cend(); ++expected) {
            GstElementFactory *factory = gst_element_factory_find(expected.key().toUtf8().constData());
            const gchar *plugin_name = factory ? gst_plugin_feature_get_plugin_name(
                GST_PLUGIN_FEATURE(factory)) : nullptr;
            GstPlugin *plugin = plugin_name ? gst_registry_find_plugin(
                gst_registry_get(), plugin_name) : nullptr;
            const QString actual = plugin ? QString::fromLatin1(gst_plugin_get_version(plugin)) : QString{};
            const bool exact_rs_commit = (expected.key() == QStringLiteral("whepclientsrc") ||
                expected.key() == QStringLiteral("whepsrc")) &&
                actual == QStringLiteral("0.15.3-75e46c3a+");
            if (actual != expected.value() && !exact_rs_commit)
                mismatched << QStringLiteral("%1=%2").arg(expected.key(), actual.isEmpty() ?
                    QStringLiteral("missing") : actual);
            if (plugin)
                gst_object_unref(plugin);
            if (factory)
                gst_object_unref(factory);
        }
        if (!mismatched.isEmpty()) {
            qCritical("self-contained runtime has unlocked plug-in versions: %s",
                      qPrintable(mismatched.join(',')));
            return 2;
        }
#endif
        QStringList hardware_decoders;
#if defined(Q_OS_WIN)
        const QStringList hardware_candidates{QStringLiteral("d3d11h264dec"),
                                              QStringLiteral("d3d11h265dec")};
#elif defined(Q_OS_ANDROID)
        const QStringList hardware_candidates{QStringLiteral("android-mediacodec")};
#elif defined(Q_OS_LINUX)
        const QStringList hardware_candidates{QStringLiteral("vah264dec"),
                                              QStringLiteral("vah265dec")};
#else
        const QStringList hardware_candidates;
#endif
        for (const QString &name : hardware_candidates) {
#if defined(Q_OS_ANDROID)
            Q_UNUSED(name)
            GstRegistry *registry = gst_registry_get();
            GList *features = gst_registry_get_feature_list(registry, GST_TYPE_ELEMENT_FACTORY);
            for (GList *entry = features; entry; entry = entry->next) {
                auto *factory = GST_ELEMENT_FACTORY(entry->data);
                const QString factory_name = QString::fromUtf8(
                    gst_plugin_feature_get_name(GST_PLUGIN_FEATURE(factory))).toLower();
                const QString klass = QString::fromUtf8(
                    gst_element_factory_get_metadata(factory, GST_ELEMENT_METADATA_KLASS)).toLower();
                if (klass.contains(QStringLiteral("decoder/video")) &&
                    (factory_name.contains(QStringLiteral("amc")) ||
                     factory_name.contains(QStringLiteral("mediacodec")))) {
                    hardware_decoders << factory_name;
                    break;
                }
            }
            gst_plugin_feature_list_free(features);
#else
            GstElementFactory *factory = gst_element_factory_find(name.toUtf8().constData());
            if (factory) {
                hardware_decoders << name;
                gst_object_unref(factory);
            }
#endif
        }
        qInfo().noquote() << QJsonDocument(QJsonObject{
            {QStringLiteral("result"), QStringLiteral("passed")},
            {QStringLiteral("gstreamer"), QString::fromLatin1(gst_version_string())},
            {QStringLiteral("hardwareDecodeReady"),
             hardware_decoders.size() >= hardware_candidates.size()},
            {QStringLiteral("hardwareDecoders"),
             QJsonArray::fromStringList(hardware_decoders)},
            {QStringLiteral("pluginVersions"), plugin_versions},
            {QStringLiteral("requiredElements"), required.size()}}).toJson(QJsonDocument::Compact);
        return 0;
    }
    if (parser.isSet(QStringLiteral("probe-client-auth"))) {
        const int result = webobs::client::run_client_auth_probe(
            application, parser.value(QStringLiteral("probe-control-url")),
            parser.value(QStringLiteral("probe-camera-id")),
            parser.value(QStringLiteral("probe-profile-id")),
            parser.isSet(QStringLiteral("probe-auth-offline")), error);
        if (result != 0 && !error.isEmpty())
            qCritical("authorization probe failed safely: %s", qPrintable(error.left(128)));
        return result;
    }
    if (parser.isSet(QStringLiteral("probe-manifest"))) {
        const int result = webobs::client::run_batch_probe(
            application, parser.value(QStringLiteral("probe-manifest")), error,
            parser.isSet(QStringLiteral("probe-background-release")),
            parser.isSet(QStringLiteral("probe-reconnect")),
            parser.isSet(QStringLiteral("probe-foreground-resume")));
        if (result != 0 && !error.isEmpty())
            qCritical("batch protocol probe failed safely: %s", qPrintable(error.left(128)));
        return result;
    }
    if (endpoint_argument || endpoint_environment) {
        const QString adapter = parser.value(QStringLiteral("probe-adapter")).toLower();
        const QString codec = parser.value(QStringLiteral("probe-codec")).toLower();
        bool duration_ok = false;
        const int duration = parser.value(QStringLiteral("probe-seconds")).toInt(&duration_ok);
        const QString endpoint_environment_name = parser.value(QStringLiteral("probe-endpoint-env"));
        if (endpoint_environment && !QRegularExpression(
                QStringLiteral(R"(^WEBOBS_[A-Z0-9_]{1,56}$)"))
                .match(endpoint_environment_name).hasMatch()) {
            qCritical("private probe endpoint environment name is invalid");
            return 2;
        }
        const QString raw_endpoint = endpoint_environment ?
            qEnvironmentVariable(endpoint_environment_name.toUtf8().constData()) :
            parser.value(QStringLiteral("probe-endpoint"));
        const QUrl url(raw_endpoint);
        const QString record_path = parser.value(QStringLiteral("probe-record-mkv"));
        const QFileInfo record_target(record_path);
        const QSet<QString> adapters{QStringLiteral("rtsp"), QStringLiteral("mjpeg"),
                                     QStringLiteral("hls"), QStringLiteral("whep")};
        const QSet<QString> codecs{QStringLiteral("h264"), QStringLiteral("h265"),
                                   QStringLiteral("mjpeg")};
        if (!adapters.contains(adapter) || !codecs.contains(codec) || !duration_ok ||
            duration < 1 || duration > 7200 || !url.isValid() || url.host().isEmpty()) {
            qCritical("invalid bounded protocol probe arguments");
            return 2;
        }
        if (!record_path.isEmpty() && (!record_target.isAbsolute() || record_target.exists() ||
            record_target.suffix().compare(QStringLiteral("mkv"), Qt::CaseInsensitive) != 0 ||
            !record_target.dir().exists())) {
            qCritical("invalid bounded protocol recording target");
            return 2;
        }
        webobs::client::MediaEndpoint endpoint;
        endpoint.adapter = adapter;
        endpoint.endpoint = url.toString();
        endpoint.video_codec = codec;
        endpoint.username = qEnvironmentVariable("WEBOBS_PROBE_USERNAME");
        endpoint.password = qEnvironmentVariable("WEBOBS_PROBE_PASSWORD");
        webobs::client::MediaPipeline pipeline;
        int result = 4;
        QObject::connect(&pipeline, &webobs::client::MediaPipeline::directReady, &application,
            [&application, &pipeline, duration, record_path, &result] {
                if (!record_path.isEmpty()) {
                    QString recording_error;
                    if (!pipeline.start_recording(record_path, recording_error)) {
                        qCritical("protocol recorder failed safely: %s",
                                  qPrintable(recording_error.left(128)));
                        result = 4;
                        application.quit();
                        return;
                    }
                }
                QTimer::singleShot(duration * 1000, &application,
                    [&application, &pipeline, duration, &result] {
                    pipeline.stopRecording();
                    const QJsonObject evidence{{QStringLiteral("result"), QStringLiteral("passed")},
                        {QStringLiteral("decoder"), pipeline.decoder()},
                        {QStringLiteral("hardwareDecode"), pipeline.hardwareDecode()},
                        {QStringLiteral("fallbackReason"), pipeline.fallbackReason()},
                        {QStringLiteral("framesDecoded"), static_cast<qint64>(pipeline.framesDecoded())},
                        {QStringLiteral("framesDropped"), static_cast<qint64>(pipeline.framesDropped())},
                        {QStringLiteral("fps"), pipeline.currentFps()},
                        {QStringLiteral("width"), pipeline.videoWidth()},
                        {QStringLiteral("height"), pipeline.videoHeight()},
                        {QStringLiteral("visualSamples"), static_cast<qint64>(pipeline.visualSamples())},
                        {QStringLiteral("blackSamples"), static_cast<qint64>(pipeline.blackSamples())},
                        {QStringLiteral("pipelineRestarts"), static_cast<qint64>(pipeline.pipelineRestarts())}};
                    if (pipeline.framesDecoded() < static_cast<quint64>(duration)) {
                        result = 4;
                    } else {
                        qInfo().noquote() << QJsonDocument(evidence).toJson(QJsonDocument::Compact);
                        result = 0;
                    }
                    pipeline.stop();
                    application.quit();
                });
            });
        QObject::connect(&pipeline, &webobs::client::MediaPipeline::directFailed, &application,
            [&application, &result](const QString &reason) {
                qCritical("protocol probe failed safely: %s", qPrintable(reason.left(128)));
                result = 4;
                application.quit();
            });
        if (!pipeline.start(endpoint, error)) {
            qCritical("protocol probe could not start: %s", qPrintable(error.left(128)));
            return 4;
        }
        QTimer::singleShot((duration + 5) * 1000, &application, [&application, &result] {
            result = 4;
            application.quit();
        });
        application.exec();
        return result;
    }

    webobs::client::ClientController controller;
    QQmlApplicationEngine engine;
    engine.rootContext()->setContextProperty(QStringLiteral("clientController"), &controller);
    QObject::connect(&engine, &QQmlApplicationEngine::objectCreationFailed,
                     &application, [] { QCoreApplication::exit(3); }, Qt::QueuedConnection);
#if QT_VERSION >= QT_VERSION_CHECK(6, 5, 0)
    engine.loadFromModule(QStringLiteral("WebObs.Native"), QStringLiteral("Main"));
#else
    engine.load(QUrl(QStringLiteral("qrc:/qt/qml/WebObs/Native/qml/Main.qml")));
#endif
    return application.exec();
}
