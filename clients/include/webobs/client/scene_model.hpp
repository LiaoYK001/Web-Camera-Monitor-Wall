#pragma once

#include <QAbstractListModel>
#include <QJsonObject>

namespace webobs::client {

class SceneModel final : public QAbstractListModel {
    Q_OBJECT
    Q_PROPERTY(QString sceneId READ sceneId NOTIFY sceneChanged)
    Q_PROPERTY(QString sceneName READ sceneName NOTIFY sceneChanged)
    Q_PROPERTY(int canvasWidth READ canvasWidth NOTIFY sceneChanged)
    Q_PROPERTY(int canvasHeight READ canvasHeight NOTIFY sceneChanged)

public:
    enum Role {
        ItemIdRole = Qt::UserRole + 1, SourceIdRole, CameraIdRole, ProfileIdRole,
        KindRole, NameRole, XRole, YRole, WidthRole, HeightRole, RotationRole,
        OpacityRole, VisibleRole, LockedRole, ZRole, ScaleModeRole, TextRole, ColorRole,
        FilePathRole,
    };
    Q_ENUM(Role)

    explicit SceneModel(QObject *parent = nullptr);
    int rowCount(const QModelIndex &parent = {}) const override;
    QVariant data(const QModelIndex &index, int role) const override;
    bool setData(const QModelIndex &index, const QVariant &value, int role) override;
    Qt::ItemFlags flags(const QModelIndex &index) const override;
    QHash<int, QByteArray> roleNames() const override;

    QString sceneId() const;
    QString sceneName() const;
    int canvasWidth() const;
    int canvasHeight() const;
    Q_INVOKABLE bool load(const QJsonObject &scene);
    Q_INVOKABLE bool saveLocal(const QString &path);
    Q_INVOKABLE void moveItem(int row, qreal x, qreal y);
    Q_INVOKABLE void resizeItem(int row, qreal width, qreal height);
    Q_INVOKABLE void setItemVisible(int row, bool visible);
    Q_INVOKABLE void setItemLocked(int row, bool locked);
    QJsonObject toJson() const;

signals:
    void sceneChanged();
    void errorOccurred(const QString &message);

private:
    struct Item {
        QString id;
        QString source_id;
        QString camera_id;
        QString profile_id;
        QString kind;
        QString name;
        QString text;
        QString color = QStringLiteral("#000000");
        QString file_path;
        qreal x = 0;
        qreal y = 0;
        qreal width = 320;
        qreal height = 180;
        qreal rotation = 0;
        qreal opacity = 1;
        bool visible = true;
        bool locked = false;
        int z = 0;
        QString scale_mode = QStringLiteral("contain");
    };
    QString id_ = QStringLiteral("local-monitor");
    QString name_ = QStringLiteral("Local Monitor");
    qint64 revision_ = 0;
    int canvas_width_ = 1920;
    int canvas_height_ = 1080;
    QList<Item> items_;
};

}
