#include "webobs/client/application_lifecycle.hpp"
#include "webobs/client/scene_model.hpp"
#include "webobs/client/stream_session_model.hpp"
#include "webobs/client/studio_workspace.hpp"

#include <QDateTime>
#include <QJsonArray>
#include <QJsonObject>
#include <QtTest>

using webobs::client::MediaEndpoint;
using webobs::client::should_suspend_for_application_state;
using webobs::client::SceneModel;
using webobs::client::StreamSessionModel;
using webobs::client::StudioWorkspace;

namespace {

MediaEndpoint fixture_endpoint(int index)
{
    MediaEndpoint endpoint;
    endpoint.adapter = QStringLiteral("rtsp");
    endpoint.endpoint = QStringLiteral("rtsp://camera-%1.invalid/live").arg(index);
    endpoint.video_codec = QStringLiteral("h264");
    return endpoint;
}

QJsonObject fixture_scene()
{
    return {{"schemaVersion", 5}, {"revision", 1}, {"id", "local-grid"},
        {"name", "Local grid"},
        {"canvas", QJsonObject{{"width", 1920}, {"height", 1080},
                                {"backgroundColor", "#000000"}}},
        {"sources", QJsonArray{QJsonObject{{"id", "camera-source"}, {"kind", "camera"},
            {"name", "Fixture camera"}, {"cameraId", "camera-fixture"},
            {"profileId", "sub"}}}},
        {"items", QJsonArray{
            QJsonObject{{"id", "item-a"}, {"sourceId", "camera-source"}, {"x", 0}, {"y", 0},
                        {"width", 960}, {"height", 1080}, {"zIndex", 0}},
            QJsonObject{{"id", "item-b"}, {"sourceId", "camera-source"}, {"x", 960}, {"y", 0},
                        {"width", 960}, {"height", 1080}, {"zIndex", 1}},
        }}};
}

}

class ClientModelTests final : public QObject {
    Q_OBJECT

private slots:
    void application_lifecycle_distinguishes_desktop_focus_from_suspend()
    {
        QVERIFY(!should_suspend_for_application_state(
            Qt::ApplicationInactive, false));
        QVERIFY(!should_suspend_for_application_state(
            Qt::ApplicationHidden, false));
        QVERIFY(should_suspend_for_application_state(
            Qt::ApplicationSuspended, false));
        QVERIFY(should_suspend_for_application_state(
            Qt::ApplicationInactive, true));
        QVERIFY(should_suspend_for_application_state(
            Qt::ApplicationHidden, true));
        QVERIFY(!should_suspend_for_application_state(
            Qt::ApplicationActive, true));
    }

    void grid_capacity_and_duplicate_camera_are_bounded()
    {
        StreamSessionModel model(16, false);
        QString error;
        for (int index = 0; index < 16; ++index) {
            const QString id = model.prepare(QStringLiteral("camera-%1").arg(index),
                QStringLiteral("sub"), QStringLiteral("Camera %1").arg(index),
                QStringLiteral("auto"), fixture_endpoint(index), error);
            QVERIFY2(!id.isEmpty(), qPrintable(error));
        }
        QCOMPARE(model.count(), 16);
        const QString rejected = model.prepare(QStringLiteral("camera-overflow"),
            QStringLiteral("sub"), QStringLiteral("Overflow"), QStringLiteral("auto"),
            fixture_endpoint(99), error);
        QVERIFY(rejected.isEmpty());
        QVERIFY(error.contains(QStringLiteral("capacity")));

        StreamSessionModel duplicate_model(16, false);
        error.clear();
        const QString first = duplicate_model.prepare(QStringLiteral("camera-a"), QStringLiteral("sub"),
            QStringLiteral("Camera A"), QStringLiteral("auto"), fixture_endpoint(1), error);
        const QString duplicate = duplicate_model.prepare(QStringLiteral("camera-a"), QStringLiteral("main"),
            QStringLiteral("Camera A"), QStringLiteral("auto"), fixture_endpoint(2), error);
        QCOMPARE(duplicate, first);
        QCOMPARE(duplicate_model.count(), 1);
    }

    void focus_replacement_keeps_one_independent_session()
    {
        StreamSessionModel model(1, true);
        QString error;
        const QString first = model.prepare(QStringLiteral("camera-a"), QStringLiteral("main"),
            QStringLiteral("Camera A"), QStringLiteral("auto"), fixture_endpoint(1), error);
        QVERIFY(!first.isEmpty());
        const QString second = model.prepare(QStringLiteral("camera-b"), QStringLiteral("main"),
            QStringLiteral("Camera B"), QStringLiteral("auto"), fixture_endpoint(2), error);
        QVERIFY(!second.isEmpty());
        QVERIFY(second != first);
        QCOMPARE(model.count(), 1);
        const auto context = model.context(second);
        QVERIFY(context.has_value());
        QCOMPARE(context->camera_id, QStringLiteral("camera-b"));
        QCOMPARE(context->profile_id, QStringLiteral("main"));
    }

    void studio_streams_allow_repeated_camera_items_without_sink_rebinding()
    {
        StreamSessionModel model(4, false, nullptr, true);
        QString error;
        const QString first = model.prepare(QStringLiteral("camera-a"), QStringLiteral("sub"),
            QStringLiteral("Camera A"), QStringLiteral("true-direct-only"), fixture_endpoint(1), error);
        const QString second = model.prepare(QStringLiteral("camera-a"), QStringLiteral("sub"),
            QStringLiteral("Camera A duplicate"), QStringLiteral("true-direct-only"),
            fixture_endpoint(1), error);
        QVERIFY(!first.isEmpty());
        QVERIFY(!second.isEmpty());
        QVERIFY(first != second);
        QCOMPARE(model.count(), 2);
    }

    void reconnect_backoff_stays_inside_ten_second_recovery_budget()
    {
        QCOMPARE(StreamSessionModel::reconnectDelayMs(0), 1000);
        QCOMPARE(StreamSessionModel::reconnectDelayMs(1), 2000);
        QCOMPARE(StreamSessionModel::reconnectDelayMs(2), 4000);
        QCOMPARE(StreamSessionModel::reconnectDelayMs(99), 4000);
    }

    void server_fallback_endpoint_is_bounded_and_released_with_session()
    {
        StreamSessionModel model(1, false);
        QSignalSpy releases(&model, &StreamSessionModel::fallbackReleaseRequested);
        QString error;
        const QString session = model.prepare(QStringLiteral("camera-a"), QStringLiteral("sub"),
            QStringLiteral("Camera A"), QStringLiteral("auto"), fixture_endpoint(1), error);
        QVERIFY(!session.isEmpty());
        MediaEndpoint fallback;
        fallback.adapter = QStringLiteral("whep");
        fallback.endpoint = QStringLiteral("https://monitor.invalid/api/v2/media-plans/") +
            QString(32, QLatin1Char('a')) + QStringLiteral("/whep");
        fallback.video_codec = QStringLiteral("h264");
        fallback.bearer_token = QString(64, QLatin1Char('b'));
        QVERIFY(model.activate_fallback(session, QString(32, QLatin1Char('a')),
                                        QDateTime::currentSecsSinceEpoch() + 300,
                                        fallback, error));
        const auto context = model.context(session);
        QVERIFY(context.has_value());
        QCOMPARE(context->adapter, QStringLiteral("whep"));
        QCOMPARE(context->endpoint, fallback.endpoint);
        model.remove(session);
        QCOMPARE(releases.count(), 1);
        QCOMPARE(releases.first().first().toString(), QString(32, QLatin1Char('a')));

        error.clear();
        const QString second = model.prepare(QStringLiteral("camera-b"), QStringLiteral("sub"),
            QStringLiteral("Camera B"), QStringLiteral("auto"), fixture_endpoint(2), error);
        QVERIFY(!model.activate_fallback(second, QStringLiteral("not-a-plan"),
                                         QDateTime::currentSecsSinceEpoch() + 300,
                                         fallback, error));
        QVERIFY(error.contains(QStringLiteral("contract")));

        error.clear();
        QVERIFY(!model.activate_fallback(second, QString(32, QLatin1Char('a')),
                                         QDateTime::currentSecsSinceEpoch() - 1,
                                         fallback, error));
    }

    void scene_round_trip_deduplicates_reused_sources()
    {
        SceneModel model;
        QVERIFY(model.load(fixture_scene()));
        QCOMPARE(model.rowCount(), 2);
        const QJsonObject encoded = model.toJson();
        QCOMPARE(encoded.value("sources").toArray().size(), 1);
        QCOMPARE(encoded.value("items").toArray().size(), 2);

        QJsonObject invalid = fixture_scene();
        QJsonArray sources = invalid.value("sources").toArray();
        sources.append(sources.first());
        invalid.insert("sources", sources);
        QVERIFY(!model.load(invalid));
    }

    void scene_editor_preserves_v5_transforms_groups_and_filters()
    {
        SceneModel model;
        QVERIFY(model.load(fixture_scene()));
        model.setItemGroup(0, QStringLiteral("doors"));
        model.setItemGroup(1, QStringLiteral("doors"));
        model.moveItem(0, 13, 27);
        QCOMPARE(model.data(model.index(0), SceneModel::XRole).toDouble(), 10.0);
        QCOMPARE(model.data(model.index(0), SceneModel::YRole).toDouble(), 30.0);
        QCOMPARE(model.data(model.index(1), SceneModel::XRole).toDouble(), 970.0);
        QCOMPARE(model.data(model.index(1), SceneModel::YRole).toDouble(), 30.0);
        model.setItemCrop(0, 1, 2, 3, 4);
        model.setItemRotation(0, 15);
        model.setItemOpacity(0, 0.75);
        QVERIFY(model.setItemFilters(0, QVariantList{
            QVariantMap{{QStringLiteral("id"), QStringLiteral("brightness")},
                        {QStringLiteral("kind"), QStringLiteral("color-correction")},
                        {QStringLiteral("enabled"), true}, {QStringLiteral("amount"), 0.1},
                        {QStringLiteral("value"), QString()}},
            QVariantMap{{QStringLiteral("id"), QStringLiteral("scale")},
                        {QStringLiteral("kind"), QStringLiteral("scaling")},
                        {QStringLiteral("enabled"), true}, {QStringLiteral("amount"), 1.0},
                        {QStringLiteral("value"), QStringLiteral("640x360")}},
        }));
        QVERIFY(!model.setItemFilters(0, QVariantList{
            QVariantMap{{QStringLiteral("id"), QStringLiteral("plugin")},
                        {QStringLiteral("kind"), QStringLiteral("arbitrary-plugin")},
                        {QStringLiteral("enabled"), true}, {QStringLiteral("amount"), 1.0},
                        {QStringLiteral("value"), QString()}},
        }));
        const QJsonObject encoded = model.toJson();
        const QJsonObject first_item = encoded.value("items").toArray().first().toObject();
        QCOMPARE(first_item.value("groupId").toString(), QStringLiteral("doors"));
        QCOMPARE(first_item.value("crop").toObject().value("left").toInt(), 4);
        QCOMPARE(encoded.value("sources").toArray().first().toObject()
                     .value("filters").toArray().size(), 2);
    }

    void scene_editor_adds_only_bounded_supported_sources()
    {
        SceneModel model;
        QVERIFY(model.load(fixture_scene()));
        QVERIFY(model.addCamera(QStringLiteral("camera-two"), QStringLiteral("main"),
                                QStringLiteral("Camera two")));
        QVERIFY(model.addText(QStringLiteral("Front door")));
        QVERIFY(model.addColor(QStringLiteral("#102030")));
        QVERIFY(model.addImage(QStringLiteral("/tmp/fixture.png")));
        QVERIFY(model.addNested(QStringLiteral("secondary"), QStringLiteral("Secondary")));
        QVERIFY(!model.addNested(model.sceneId(), QStringLiteral("Cycle")));
        QVERIFY(!model.addColor(QStringLiteral("red")));
        QVERIFY(!model.addImage(QStringLiteral("relative.png")));
        QCOMPARE(model.rowCount(), 7);
        const QJsonObject encoded = model.toJson();
        QCOMPARE(encoded.value("items").toArray().size(), 7);
    }

    void studio_preview_is_isolated_until_cut_or_fade()
    {
        QJsonObject first = fixture_scene();
        QJsonObject second = fixture_scene();
        second.insert(QStringLiteral("id"), QStringLiteral("local-secondary"));
        second.insert(QStringLiteral("name"), QStringLiteral("Secondary"));
        StudioWorkspace studio;
        QVERIFY(studio.load(QJsonArray{first, second}));
        QCOMPARE(studio.previewSceneId(), QStringLiteral("local-grid"));
        QCOMPARE(studio.programSceneId(), QStringLiteral("local-grid"));
        QCOMPARE(studio.preview()->rowCount(), 2);
        QCOMPARE(studio.program()->rowCount(), 2);
        QVERIFY(studio.preview()->addText(QStringLiteral("Preview only")));
        QCOMPARE(studio.preview()->rowCount(), 3);
        QCOMPARE(studio.program()->rowCount(), 2);
        QVERIFY(studio.take(QStringLiteral("fade"), 350));
        QCOMPARE(studio.program()->rowCount(), 3);
        QCOMPARE(studio.transitionKind(), QStringLiteral("fade"));
        QCOMPARE(studio.transitionDurationMs(), 350);
        QVERIFY(studio.selectPreview(QStringLiteral("local-secondary")));
        QCOMPARE(studio.program()->rowCount(), 3);
        QVERIFY(!studio.take(QStringLiteral("wipe"), 350));
    }

    void studio_rejects_missing_nested_scene_at_take()
    {
        StudioWorkspace studio;
        QVERIFY(studio.load(QJsonArray{fixture_scene()}));
        QVERIFY(studio.preview()->addNested(QStringLiteral("missing-scene"),
                                            QStringLiteral("Missing")));
        QVERIFY(!studio.take(QStringLiteral("cut"), 0));
        QCOMPARE(studio.program()->rowCount(), 2);
    }
};

QTEST_GUILESS_MAIN(ClientModelTests)
#include "client_model_tests.moc"
