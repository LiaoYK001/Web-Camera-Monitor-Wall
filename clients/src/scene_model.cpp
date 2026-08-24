#include "webobs/client/scene_model.hpp"

#include <QJsonArray>
#include <QJsonDocument>
#include <QFileInfo>
#include <QSaveFile>
#include <QSet>
#include <QUuid>
#include <QtMath>

#include <algorithm>
#include <cmath>

namespace webobs::client {
namespace {

bool valid_identifier(const QString &value)
{
    static const QRegularExpression expression(QStringLiteral("^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$"));
    return expression.match(value).hasMatch();
}

bool valid_asset_path(const QString &value)
{
    if ((!value.startsWith(QStringLiteral("/assets/")) &&
         !value.startsWith(QStringLiteral("/recordings/"))) || value.size() > 2048)
        return false;
    return !value.split(QLatin1Char('/')).contains(QStringLiteral(".."));
}

bool valid_filter(const QJsonValue &value)
{
    if (!value.isObject())
        return false;
    const QJsonObject object = value.toObject();
    static const QSet<QString> required{QStringLiteral("id"), QStringLiteral("kind"),
        QStringLiteral("enabled"), QStringLiteral("amount"), QStringLiteral("value")};
    static const QSet<QString> kinds{QStringLiteral("crop-pad"), QStringLiteral("opacity"),
        QStringLiteral("color-correction"), QStringLiteral("mask-blend"),
        QStringLiteral("lut"), QStringLiteral("scaling"), QStringLiteral("delay")};
    const QStringList keys = object.keys();
    if (QSet<QString>(keys.cbegin(), keys.cend()) != required ||
        !valid_identifier(object.value(QStringLiteral("id")).toString()) ||
        !kinds.contains(object.value(QStringLiteral("kind")).toString()) ||
        !object.value(QStringLiteral("enabled")).isBool() ||
        !object.value(QStringLiteral("amount")).isDouble() ||
        !std::isfinite(object.value(QStringLiteral("amount")).toDouble()) ||
        object.value(QStringLiteral("amount")).toDouble() < -10000 ||
        object.value(QStringLiteral("amount")).toDouble() > 10000 ||
        !object.value(QStringLiteral("value")).isString() ||
        object.value(QStringLiteral("value")).toString().toUtf8().size() > 4096)
        return false;
    const QString kind = object.value(QStringLiteral("kind")).toString();
    const QString parameter = object.value(QStringLiteral("value")).toString();
    if ((kind == QStringLiteral("lut") || kind == QStringLiteral("mask-blend")) &&
        !valid_asset_path(parameter))
        return false;
    if (kind == QStringLiteral("scaling")) {
        static const QRegularExpression resolution(QStringLiteral("^([0-9]{2,4})x([0-9]{2,4})$"));
        const QRegularExpressionMatch match = resolution.match(parameter);
        if (!match.hasMatch() || match.captured(1).toInt() < 16 || match.captured(1).toInt() > 8192 ||
            match.captured(2).toInt() < 16 || match.captured(2).toInt() > 8192)
            return false;
    }
    return true;
}

bool valid_filters(const QJsonArray &filters)
{
    if (filters.size() > 16)
        return false;
    QSet<QString> identifiers;
    for (const QJsonValue &value : filters) {
        if (!valid_filter(value))
            return false;
        const QString id = value.toObject().value(QStringLiteral("id")).toString();
        if (identifiers.contains(id))
            return false;
        identifiers.insert(id);
    }
    return true;
}

}

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
    case GroupIdRole: return item.group_id;
    case CropTopRole: return item.crop_top;
    case CropRightRole: return item.crop_right;
    case CropBottomRole: return item.crop_bottom;
    case CropLeftRole: return item.crop_left;
    case FiltersRole: return item.filters.toVariantList();
    case NestedSceneIdRole: return item.nested_scene_id;
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
            {FilePathRole, "sourceFilePath"}, {GroupIdRole, "groupId"},
            {CropTopRole, "cropTop"}, {CropRightRole, "cropRight"},
            {CropBottomRole, "cropBottom"}, {CropLeftRole, "cropLeft"},
            {FiltersRole, "sourceFilters"}, {NestedSceneIdRole, "nestedSceneId"}};
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
        item.nested_scene_id = source.value("sceneId").toString();
        item.filters = source.value("filters").toArray();
        item.x = object.value("x").toDouble(); item.y = object.value("y").toDouble();
        item.width = object.value("width").toDouble(320); item.height = object.value("height").toDouble(180);
        item.rotation = object.value("rotation").toDouble();
        item.opacity = object.value("opacity").toDouble(1);
        item.visible = object.value("visible").toBool(true);
        item.locked = object.value("locked").toBool(false);
        item.z = object.value("zIndex").toInt();
        item.scale_mode = object.value("scaleMode").toString(QStringLiteral("contain"));
        item.group_id = object.value("groupId").toString();
        const QJsonObject crop = object.value("crop").toObject();
        item.crop_top = crop.value("top").toInt();
        item.crop_right = crop.value("right").toInt();
        item.crop_bottom = crop.value("bottom").toInt();
        item.crop_left = crop.value("left").toInt();
        if (item.id.isEmpty() || item.source_id.isEmpty() ||
            !QStringList{QStringLiteral("camera"), QStringLiteral("text"), QStringLiteral("image"),
                         QStringLiteral("color"), QStringLiteral("nested")}.contains(item.kind) ||
            (item.kind == QStringLiteral("camera") && (item.camera_id.isEmpty() || item.profile_id.isEmpty())) ||
            (item.kind == QStringLiteral("nested") && item.nested_scene_id.isEmpty()) ||
            !valid_filters(item.filters) || item.crop_top < 0 || item.crop_right < 0 ||
            item.crop_bottom < 0 || item.crop_left < 0) {
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
        } else if (item.kind == QStringLiteral("nested")) {
            source.insert("sceneId", item.nested_scene_id);
        }
        source.insert("filters", item.filters);
        if (!serialized_sources.contains(item.source_id)) {
            sources.append(source);
            serialized_sources.insert(item.source_id);
        }
        items.append(QJsonObject{{"id", item.id}, {"sourceId", item.source_id},
            {"x", qRound(item.x)}, {"y", qRound(item.y)}, {"width", qRound(item.width)},
            {"height", qRound(item.height)},
            {"rotation", item.rotation}, {"opacity", item.opacity}, {"visible", item.visible},
            {"locked", item.locked}, {"zIndex", item.z}, {"scaleMode", item.scale_mode},
            {"groupId", item.group_id},
            {"crop", QJsonObject{{"top", item.crop_top}, {"right", item.crop_right},
                                  {"bottom", item.crop_bottom}, {"left", item.crop_left}}},
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
    if (row < 0 || row >= items_.size() || items_[row].locked)
        return;
    const qreal snapped_x = qRound(x / 10.0) * 10.0;
    const qreal snapped_y = qRound(y / 10.0) * 10.0;
    const qreal delta_x = snapped_x - items_[row].x;
    const qreal delta_y = snapped_y - items_[row].y;
    const QString group = items_[row].group_id;
    for (int candidate = 0; candidate < items_.size(); ++candidate) {
        if (candidate == row || (!group.isEmpty() && items_[candidate].group_id == group)) {
            setData(index(candidate), items_[candidate].x + delta_x, XRole);
            setData(index(candidate), items_[candidate].y + delta_y, YRole);
        }
    }
}
void SceneModel::resizeItem(int row, qreal width, qreal height)
{
    setData(index(row), width, WidthRole); setData(index(row), height, HeightRole);
}
void SceneModel::setItemVisible(int row, bool visible) { setData(index(row), visible, VisibleRole); }
void SceneModel::setItemLocked(int row, bool locked) { setData(index(row), locked, LockedRole); }
void SceneModel::setItemRotation(int row, qreal degrees) { setData(index(row), degrees, RotationRole); }
void SceneModel::setItemOpacity(int row, qreal opacity) { setData(index(row), opacity, OpacityRole); }
void SceneModel::setItemScaleMode(int row, const QString &mode) { setData(index(row), mode, ScaleModeRole); }

void SceneModel::setItemCrop(int row, int top, int right, int bottom, int left)
{
    if (row < 0 || row >= items_.size() || items_[row].locked ||
        std::min({top, right, bottom, left}) < 0 || std::max({top, right, bottom, left}) > 8192)
        return;
    Item &item = items_[row];
    item.crop_top = top; item.crop_right = right; item.crop_bottom = bottom; item.crop_left = left;
    emit dataChanged(index(row), index(row), {CropTopRole, CropRightRole, CropBottomRole, CropLeftRole});
}

void SceneModel::setItemGroup(int row, const QString &group_id)
{
    if (row < 0 || row >= items_.size() || group_id.size() > 64)
        return;
    items_[row].group_id = group_id;
    emit dataChanged(index(row), index(row), {GroupIdRole});
}

bool SceneModel::setItemFilters(int row, const QVariantList &filters)
{
    if (row < 0 || row >= items_.size() || items_[row].locked || filters.size() > 16)
        return false;
    const QJsonArray encoded = QJsonArray::fromVariantList(filters);
    if (!valid_filters(encoded))
        return false;
    items_[row].filters = encoded;
    emit dataChanged(index(row), index(row), {FiltersRole});
    return true;
}

void SceneModel::alignItem(int row, const QString &horizontal, const QString &vertical)
{
    if (row < 0 || row >= items_.size() || items_[row].locked)
        return;
    Item &item = items_[row];
    qreal x = item.x;
    qreal y = item.y;
    if (horizontal == QStringLiteral("left")) x = 0;
    else if (horizontal == QStringLiteral("center")) x = (canvas_width_ - item.width) / 2.0;
    else if (horizontal == QStringLiteral("right")) x = canvas_width_ - item.width;
    if (vertical == QStringLiteral("top")) y = 0;
    else if (vertical == QStringLiteral("center")) y = (canvas_height_ - item.height) / 2.0;
    else if (vertical == QStringLiteral("bottom")) y = canvas_height_ - item.height;
    moveItem(row, x, y);
}

bool SceneModel::valid_color(const QString &value)
{
    if (value.size() != 7 || value.front() != QLatin1Char('#'))
        return false;
    return std::all_of(value.begin() + 1, value.end(), [](QChar character) {
        const ushort code = character.unicode();
        return (code >= '0' && code <= '9') || (code >= 'a' && code <= 'f') ||
               (code >= 'A' && code <= 'F');
    });
}

bool SceneModel::add_item(Item item)
{
    if (items_.size() >= 256)
        return false;
    item.id = QUuid::createUuid().toString(QUuid::WithoutBraces);
    item.source_id = QUuid::createUuid().toString(QUuid::WithoutBraces);
    item.z = items_.size();
    const int row = items_.size();
    beginInsertRows({}, row, row);
    items_.push_back(std::move(item));
    endInsertRows();
    return true;
}

bool SceneModel::addCamera(const QString &camera_id, const QString &profile_id, const QString &name)
{
    if (camera_id.isEmpty() || profile_id.isEmpty()) return false;
    Item item; item.kind = QStringLiteral("camera"); item.camera_id = camera_id;
    item.profile_id = profile_id; item.name = name.left(128);
    return add_item(std::move(item));
}
bool SceneModel::addText(const QString &text)
{
    if (text.isEmpty() || text.size() > 4096) return false;
    Item item; item.kind = QStringLiteral("text"); item.name = QStringLiteral("Text"); item.text = text;
    return add_item(std::move(item));
}
bool SceneModel::addImage(const QString &absolute_path)
{
    if (!QFileInfo(absolute_path).isAbsolute()) return false;
    Item item; item.kind = QStringLiteral("image"); item.name = QFileInfo(absolute_path).fileName();
    item.file_path = absolute_path; return add_item(std::move(item));
}
bool SceneModel::addColor(const QString &color)
{
    if (!valid_color(color)) return false;
    Item item; item.kind = QStringLiteral("color"); item.name = QStringLiteral("Color"); item.color = color;
    return add_item(std::move(item));
}
bool SceneModel::addNested(const QString &scene_id, const QString &name)
{
    if (scene_id.isEmpty() || scene_id == id_) return false;
    Item item; item.kind = QStringLiteral("nested"); item.nested_scene_id = scene_id;
    item.name = name.left(128); return add_item(std::move(item));
}
void SceneModel::removeItem(int row)
{
    if (row < 0 || row >= items_.size() || items_[row].locked) return;
    beginRemoveRows({}, row, row); items_.removeAt(row); endRemoveRows();
    for (int index = row; index < items_.size(); ++index) items_[index].z = index;
    if (row < items_.size()) emit dataChanged(this->index(row), this->index(items_.size() - 1), {ZRole});
}
QString SceneModel::sceneId() const { return id_; }
QString SceneModel::sceneName() const { return name_; }
int SceneModel::canvasWidth() const { return canvas_width_; }
int SceneModel::canvasHeight() const { return canvas_height_; }

}
