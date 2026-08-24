#include "webobs/client/client_controller.hpp"
#include "webobs/client/grant_codec.hpp"
#include "webobs/client/media_pipeline.hpp"

#include <QGuiApplication>
#include <QQmlApplicationEngine>
#include <QQmlContext>
#include <QUrl>

int main(int argc, char *argv[])
{
    QGuiApplication application(argc, argv);
    application.setApplicationName(QStringLiteral("WebObs Native"));
    application.setOrganizationName(QStringLiteral("WebObs"));
    application.setApplicationVersion(QStringLiteral(WEBOBS_CLIENT_VERSION));

    QString error;
    if (!webobs::client::GrantCodec::initialize(error) ||
        !webobs::client::MediaPipeline::initialize(error)) {
        qCritical("%s", qPrintable(error));
        return 2;
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
