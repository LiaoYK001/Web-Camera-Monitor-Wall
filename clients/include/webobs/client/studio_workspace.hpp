#pragma once

#include "webobs/client/scene_model.hpp"

#include <QJsonArray>
#include <QHash>
#include <QObject>
#include <QSet>
#include <QVariantList>

namespace webobs::client {

class StudioWorkspace final : public QObject {
    Q_OBJECT
    Q_PROPERTY(SceneModel* preview READ preview CONSTANT)
    Q_PROPERTY(SceneModel* program READ program CONSTANT)
    Q_PROPERTY(QVariantList scenes READ scenes NOTIFY collectionChanged)
    Q_PROPERTY(QString previewSceneId READ previewSceneId NOTIFY collectionChanged)
    Q_PROPERTY(QString programSceneId READ programSceneId NOTIFY collectionChanged)
    Q_PROPERTY(QString transitionKind READ transitionKind NOTIFY collectionChanged)
    Q_PROPERTY(int transitionDurationMs READ transitionDurationMs NOTIFY collectionChanged)

public:
    explicit StudioWorkspace(QObject *parent = nullptr);
    SceneModel *preview();
    SceneModel *program();
    QVariantList scenes() const;
    QString previewSceneId() const;
    QString programSceneId() const;
    QString transitionKind() const;
    int transitionDurationMs() const;

    bool load(const QJsonArray &scenes);
    Q_INVOKABLE bool addScene(const QString &name);
    Q_INVOKABLE bool removeScene(const QString &sceneId);
    Q_INVOKABLE bool selectPreview(const QString &sceneId);
    Q_INVOKABLE bool take(const QString &kind, int durationMs);
    Q_INVOKABLE bool saveLocal(const QString &absolutePath);
    Q_INVOKABLE bool loadLocal(const QString &absolutePath);
    Q_INVOKABLE SceneModel *sceneModel(const QString &sceneId);
    QJsonObject toJson();

signals:
    void collectionChanged();
    void errorOccurred(const QString &message);
    void transitionStarted(const QString &kind, int durationMs);

private:
    int find_scene(const QString &id) const;
    void snapshot_preview();
    bool validate(QString &error) const;
    bool visit_nested(const QString &scene_id, int depth, QSet<QString> &stack,
                      QString &error) const;

    SceneModel preview_;
    SceneModel program_;
    QJsonArray scenes_;
    QString preview_scene_id_;
    QString program_scene_id_;
    QString transition_kind_ = QStringLiteral("cut");
    int transition_duration_ms_ = 300;
    qint64 revision_ = 0;
    QHash<QString, SceneModel *> nested_models_;
};

}
