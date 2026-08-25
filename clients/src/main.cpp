#include "webobs/client/client_controller.hpp"
#include "webobs/client/batch_probe.hpp"
#include "webobs/client/grant_codec.hpp"
#include "webobs/client/media_pipeline.hpp"

#include <QGuiApplication>
#include <QCommandLineOption>
#include <QCommandLineParser>
#include <QCoreApplication>
#include <QDir>
#include <QJsonDocument>
#include <QJsonObject>
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
            QByteArrayView(argv[index]) == QByteArrayView("--probe-manifest") ||
            QByteArrayView(argv[index]) == QByteArrayView("--verify-runtime"))
            probe_requested = true;
    if (probe_requested && qEnvironmentVariableIsEmpty("QT_QPA_PLATFORM"))
        qputenv("QT_QPA_PLATFORM", "offscreen");
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
    parser.addOption({QStringLiteral("probe-manifest"),
                      QStringLiteral("Run multiple production media pipelines in one process"),
                      QStringLiteral("absolute-json-path")});
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
    if (parser.isSet(QStringLiteral("probe-endpoint")) &&
        parser.isSet(QStringLiteral("probe-manifest"))) {
        qCritical("choose one bounded probe mode");
        return 2;
    }
    if (parser.isSet(QStringLiteral("verify-runtime"))) {
        QStringList required{QStringLiteral("rtspsrc"), QStringLiteral("uridecodebin3"),
            QStringLiteral("decodebin3"), QStringLiteral("qml6glsink"),
            QStringLiteral("whepclientsrc"), QStringLiteral("rtph264depay"),
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
#if defined(Q_OS_WIN)
        required << QStringLiteral("d3d11h264dec") << QStringLiteral("d3d11h265dec");
#elif defined(Q_OS_LINUX)
        required << QStringLiteral("vah264dec") << QStringLiteral("vah265dec");
#endif
        QStringList missing;
        for (const QString &name : required) {
            GstElementFactory *factory = gst_element_factory_find(name.toUtf8().constData());
            if (factory)
                gst_object_unref(factory);
            else
                missing << name;
        }
        if (!missing.isEmpty()) {
            qCritical("self-contained runtime is missing required media elements: %s",
                      qPrintable(missing.join(',')));
            return 2;
        }
        qInfo().noquote() << QJsonDocument(QJsonObject{
            {QStringLiteral("result"), QStringLiteral("passed")},
            {QStringLiteral("gstreamer"), QString::fromLatin1(gst_version_string())},
            {QStringLiteral("requiredElements"), required.size()}}).toJson(QJsonDocument::Compact);
        return 0;
    }
    if (parser.isSet(QStringLiteral("probe-manifest"))) {
        const int result = webobs::client::run_batch_probe(
            application, parser.value(QStringLiteral("probe-manifest")), error);
        if (result != 0 && !error.isEmpty())
            qCritical("batch protocol probe failed safely: %s", qPrintable(error.left(128)));
        return result;
    }
    if (parser.isSet(QStringLiteral("probe-endpoint"))) {
        const QString adapter = parser.value(QStringLiteral("probe-adapter")).toLower();
        const QString codec = parser.value(QStringLiteral("probe-codec")).toLower();
        bool duration_ok = false;
        const int duration = parser.value(QStringLiteral("probe-seconds")).toInt(&duration_ok);
        const QUrl url(parser.value(QStringLiteral("probe-endpoint")));
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
