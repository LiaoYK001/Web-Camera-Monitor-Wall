#include "webobs/client/scene_model.hpp"

#include <QJsonArray>
#include <QJsonDocument>
#include <QSaveFile>
#include <QSet>
#include <QtMath>

#include <algorithm>

namespace webobs::client {

SceneModel::SceneModel(QObject *parent) : QAbstractListModel(parent) {}

int SceneModel::rowCount(const QModelIndex &parent) const
{
    return parent.isValid() ? 0 : items_.size();
}

QVariant SceneModel::data(const QModelIndex &index, int role) const
{
    if (!index.isValid() || index.row() < 0 || index.row() >= items_.size())
        return {};
    const Item &item = items_.at(index.row());
    switch (role) {
    case ItemIdRole: return item.id;
    case SourceIdRole: return item.source_id;
    case CameraIdRole: return item.camera_id;
    case ProfileIdRole: return item.profile_id;
    case KindRole: return item.kind;
    case NameRole: return item.name;
    case XRole: return item.x;
    case YRole: return item.y;
    case WidthRole: return item.width;
    case HeightRole: return item.height;
    case RotationRole: return item.rotation;
    case OpacityRole: return item.opacity;
    case VisibleRole: return item.visible;
    case LockedRole: return item.locked;
    case ZRole: return item.z;
    case ScaleModeRole: return item.scale_mode;
    case TextRole: return item.text;
    case ColorRole: return item.color;
    case FilePathRole: return item.file_path;
    default: return {};
    }
}

bool SceneModel::setData(const QModelIndex &index, const QVariant &value, int role)
{
    if (!index.isValid() || index.row() < 0 || index.row() >= items_.size())
        return false;
    Item &item = items_[index.row()];
    if (item.locked && role != LockedRole && role != VisibleRole)
        return false;
    switch (role) {
    case XRole: item.x = std::clamp(value.toReal(), -32768.0, 32768.0); break;
    case YRole: item.y = std::clamp(value.toReal(), -32768.0, 32768.0); break;
    case WidthRole: item.width = std::clamp(value.toReal(), 1.0, 32768.0); break;
    case HeightRole: item.height = std::clamp(value.toReal(), 1.0, 32768.0); break;
    case RotationRole: item.rotation = std::clamp(value.toReal(), -360.0, 360.0); break;
    case OpacityRole: item.opacity = std::clamp(value.toReal(), 0.0, 1.0); break;
    case VisibleRole: item.visible = value.toBool(); break;
    case LockedRole: item.locked = value.toBool(); break;
    case ZRole: item.z = value.toInt(); break;
    case ScaleModeRole:
        if (!QStringList{"contain", "cover", "stretch"}.contains(value.toString())) return false;
        item.scale_mode = value.toString(); break;
    default: return false;
    }
    emit dataChanged(index, index, {role});
    return true;
}

Qt::ItemFlags SceneModel::flags(const QModelIndex &index) const
{
    return QAbstractListModel::flags(index) | Qt::ItemIsEditable;
}

QHash<int, QByteArray> SceneModel::roleNames() const
{
    return {{ItemIdRole, "itemId"}, {SourceIdRole, "sourceId"}, {CameraIdRole, "cameraId"},
            {ProfileIdRole, "profileId"}, {KindRole, "kind"}, {NameRole, "name"},
            {XRole, "sceneX"}, {YRole, "sceneY"}, {WidthRole, "sceneWidth"},
            {HeightRole, "sceneHeight"}, {RotationRole, "sceneRotation"},
            {OpacityRole, "sceneOpacity"}, {VisibleRole, "sceneVisible"},
            {LockedRole, "sceneLocked"}, {ZRole, "sceneZ"},
            {ScaleModeRole, "scaleMode"}, {TextRole, "sourceText"}, {ColorRole, "sourceColor"},
            {FilePathRole, "sourceFilePath"}};
}

bool SceneModel::load(const QJsonObject &scene)
{
    const QJsonObject canvas = scene.value("canvas").toObject();
    const QJsonArray sources = scene.value("sources").toArray();
    const QJsonArray items = scene.value("items").toArray();
    if (items.size() > 256 || sources.size() > 64 || canvas.value("width").toInt() < 16 ||
        canvas.value("height").toInt() < 16) {
        emit errorOccurred(QStringLiteral("Scene exceeds the local safety limits"));
        return false;
    }
    QHash<QString, QJsonObject> source_by_id;
    for (const QJsonValue &value : sources) {
        const QJsonObject source = value.toObject();
        const QString source_id = source.value("id").toString();
        if (source_id.isEmpty() || source_by_id.contains(source_id)) {
            emit errorOccurred(QStringLiteral("Scene contains an invalid or duplicate source ID"));
            return false;
        }
        source_by_id.insert(source_id, source);
    }
    QList<Item> next;
    for (const QJsonValue &value : items) {
        const QJsonObject object = value.toObject();
        const QJsonObject source = source_by_id.value(object.value("sourceId").toString());
        Item item;
        item.id = object.value("id").toString();
        item.source_id = object.value("sourceId").toString();
        item.camera_id = source.value("cameraId").toString();
        item.profile_id = source.value("profileId").toString();
        item.kind = source.value("kind").toString();
        item.name = source.value("name").toString();
        item.text = source.value("text").toString();
        item.color = source.value("color").toString(QStringLiteral("#000000"));
        item.file_path = source.value("filePath").toString();
        item.x = object.value("x").toDouble(); item.y = object.value("y").toDouble();
        item.width = object.value("width").toDouble(320); item.height = object.value("height").toDouble(180);
        item.rotation = object.value("rotation").toDouble();
        item.opacity = object.value("opacity").toDouble(1);
        item.visible = object.value("visible").toBool(true);
        item.locked = object.value("locked").toBool(false);
        item.z = object.value("zIndex").toInt();
        item.scale_mode = object.value("scaleMode").toString(QStringLiteral("contain"));
        if (item.id.isEmpty() || item.source_id.isEmpty() ||
            (item.kind == QStringLiteral("camera") && (item.camera_id.isEmpty() || item.profile_id.isEmpty()))) {
            emit errorOccurred(QStringLiteral("Scene references an invalid stable Camera/Profile ID"));
            return false;
        }
        next.push_back(item);
    }
    beginResetModel();
    items_ = std::move(next);
    id_ = scene.value("id").toString(QStringLiteral("local-monitor"));
    name_ = scene.value("name").toString(QStringLiteral("Local Monitor"));
    revision_ = scene.value("revision").toInteger();
    canvas_width_ = canvas.value("width").toInt(1920);
    canvas_height_ = canvas.value("height").toInt(1080);
    endResetModel();
    emit sceneChanged();
    return true;
}

QJsonObject SceneModel::toJson() const
{
    QJsonArray sources;
    QJsonArray items;
    QSet<QString> serialized_sources;
    for (const Item &item : items_) {
        QJsonObject source{{"id", item.source_id}, {"kind", item.kind}, {"name", item.name},
            {"muted", true}, {"volume", 1}, {"syncOffsetMs", 0}, {"monitoring", "off"},
            {"audioTrack", 1}, {"filters", QJsonArray{}}};
        if (item.kind == QStringLiteral("camera")) {
            source.insert("cameraId", item.camera_id);
            source.insert("profileId", item.profile_id);
            source.insert("hardwareDecode", "auto");
        } else if (item.kind == QStringLiteral("text")) {
            source.insert("text", item.text);
            source.insert("color", item.color);
        } else if (item.kind == QStringLiteral("color")) {
            source.insert("color", item.color);
        } else if (item.kind == QStringLiteral("image")) {
            source.insert("filePath", item.file_path);
        }
        if (!serialized_sources.contains(item.source_id)) {
            sources.append(source);
            serialized_sources.insert(item.source_id);
        }
        items.append(QJsonObject{{"id", item.id}, {"sourceId", item.source_id},
            {"x", qRound(item.x)}, {"y", qRound(item.y)}, {"width", qRound(item.width)},
            {"height", qRound(item.height)},
            {"rotation", item.rotation}, {"opacity", item.opacity}, {"visible", item.visible},
            {"locked", item.locked}, {"zIndex", item.z}, {"scaleMode", item.scale_mode},
            {"crop", QJsonObject{{"top", 0}, {"right", 0}, {"bottom", 0}, {"left", 0}}},
            {"blendMode", "normal"}});
    }
    return {{"schemaVersion", 5}, {"revision", revision_}, {"id", id_}, {"name", name_},
            {"canvas", QJsonObject{{"width", canvas_width_}, {"height", canvas_height_},
                                    {"backgroundColor", "#000000"}}},
            {"sources", sources}, {"items", items}};
}

bool SceneModel::saveLocal(const QString &path)
{
    QSaveFile file(path);
    if (!file.open(QIODevice::WriteOnly) ||
        file.write(QJsonDocument(toJson()).toJson(QJsonDocument::Indented)) < 0 || !file.commit()) {
        emit errorOccurred(QStringLiteral("Local-only Scene could not be saved"));
        return false;
    }
    return true;
}

void SceneModel::moveItem(int row, qreal x, qreal y)
{
    setData(index(row), x, XRole); setData(index(row), y, YRole);
}
void SceneModel::resizeItem(int row, qreal width, qreal height)
{
    setData(index(row), width, WidthRole); setData(index(row), height, HeightRole);
}
void SceneModel::setItemVisible(int row, bool visible) { setData(index(row), visible, VisibleRole); }
void SceneModel::setItemLocked(int row, bool locked) { setData(index(row), locked, LockedRole); }
QString SceneModel::sceneId() const { return id_; }
QString SceneModel::sceneName() const { return name_; }
int SceneModel::canvasWidth() const { return canvas_width_; }
int SceneModel::canvasHeight() const { return canvas_height_; }

}
