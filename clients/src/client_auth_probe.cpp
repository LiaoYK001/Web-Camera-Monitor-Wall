#include "webobs/client/client_auth_probe.hpp"

#include "webobs/client/client_controller.hpp"

#include <QGuiApplication>
#include <QJsonDocument>
#include <QJsonObject>
#include <QTextStream>
#include <QTimer>
#include <QUrl>

namespace webobs::client {

int run_client_auth_probe(QGuiApplication &application, const QString &control_url,
                          const QString &camera_id, const QString &profile_id,
                          bool offline_after_ready, QString &error)
{
    const QUrl server(control_url);
    const bool loopback_http = server.scheme() == QStringLiteral("http") &&
        (server.host() == QStringLiteral("127.0.0.1") ||
         server.host() == QStringLiteral("localhost"));
    if (!server.isValid() || server.userInfo().size() > 0 || server.hasFragment() ||
        server.hasQuery() || (server.scheme() != QStringLiteral("https") && !loopback_http) ||
        control_url.size() > 2048 || camera_id.isEmpty() || camera_id.size() > 64 ||
        profile_id.isEmpty() || profile_id.size() > 64) {
        error = QStringLiteral("authorization probe inputs are invalid");
        return 2;
    }
    ClientController controller;
    controller.setServerUrl(control_url);
    bool pairing_reported = false;
    bool playback_ready = false;
    bool stream_started = false;
    bool finishing = false;
    int result = 4;
    const auto write_document = [](const QJsonObject &document) {
        QTextStream output(stdout);
        output << QJsonDocument(document).toJson(QJsonDocument::Compact) << Qt::endl;
    };
    QObject::connect(&controller, &ClientController::enrollmentChanged, &application, [&] {
        if (pairing_reported || controller.pairingCode().isEmpty())
            return;
        pairing_reported = true;
        write_document(QJsonObject{
            {QStringLiteral("result"), QStringLiteral("pairing-required")},
            {QStringLiteral("pairingCode"), controller.pairingCode()},
            {QStringLiteral("storageBackend"), controller.storageBackend()},
            {QStringLiteral("temporaryIdentity"), controller.temporaryIdentity()}});
    });
    QObject::connect(&controller, &ClientController::bootstrapChanged, &application, [&] {
        if (!stream_started && !controller.cameras().isEmpty() &&
            controller.state() == QStringLiteral("ready")) {
            stream_started = true;
            controller.startCamera(camera_id, profile_id, QStringLiteral("true-direct-only"));
        }
    });
    QObject::connect(controller.focusStreams(), &StreamSessionModel::directResult, &application,
        [&](const QString &, bool reachable, const QString &) {
            if (!reachable || playback_ready)
                return;
            playback_ready = true;
            write_document(QJsonObject{
                {QStringLiteral("result"), QStringLiteral("authorization-playback-ready")},
                {QStringLiteral("streamCount"), controller.focusStreams()->count()}});
            if (offline_after_ready)
                controller.setServerUrl(QStringLiteral("https://127.0.0.1:1"));
        });
    QObject::connect(&controller, &ClientController::stateChanged, &application, [&] {
        const QString state = controller.state();
        if (finishing || (state != QStringLiteral("revoked") &&
                          state != QStringLiteral("grant-expired")))
            return;
        finishing = true;
        QTimer::singleShot(0, &application, [&, state] {
            const int streams = controller.focusStreams()->count();
            write_document(QJsonObject{
                {QStringLiteral("result"), QStringLiteral("authorization-stopped")},
                {QStringLiteral("state"), state},
                {QStringLiteral("streamCount"), streams}});
            result = playback_ready && streams == 0 ? 0 : 4;
            controller.revokeLocalIdentity();
            application.quit();
        });
    });
    QObject::connect(&controller, &ClientController::userError, &application,
        [](const QString &) { qWarning("authorization probe operation failed safely"); });
    QTimer::singleShot(150'000, &application, [&] {
        if (!finishing) {
            finishing = true;
            controller.stopAll();
            controller.revokeLocalIdentity();
            application.quit();
        }
    });
    controller.enroll(QStringLiteral("Android authorization gate"));
    application.exec();
    return result;
}

}
