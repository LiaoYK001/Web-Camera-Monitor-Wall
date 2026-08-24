#include "webobs/client/studio_workspace.hpp"

#include <QFile>
#include <QFileInfo>
#include <QJsonDocument>
#include <QSaveFile>
#include <QSet>
#include <QUuid>

namespace webobs::client {

StudioWorkspace::StudioWorkspace(QObject *parent) : QObject(parent)
{
    connect(&preview_, &SceneModel::errorOccurred, this, &StudioWorkspace::errorOccurred);
    connect(&program_, &SceneModel::errorOccurred, this, &StudioWorkspace::errorOccurred);
}

SceneModel *StudioWorkspace::preview() { return &preview_; }
SceneModel *StudioWorkspace::program() { return &program_; }
QString StudioWorkspace::previewSceneId() const { return preview_scene_id_; }
QString StudioWorkspace::programSceneId() const { return program_scene_id_; }
QString StudioWorkspace::transitionKind() const { return transition_kind_; }
int StudioWorkspace::transitionDurationMs() const { return transition_duration_ms_; }

QVariantList StudioWorkspace::scenes() const
{
    QVariantList result;
    for (const QJsonValue &value : scenes_) {
        const QJsonObject scene = value.toObject();
        result.append(QVariantMap{{QStringLiteral("sceneId"), scene.value("id").toString()},
                                  {QStringLiteral("name"), scene.value("name").toString()}});
    }
    return result;
}

int StudioWorkspace::find_scene(const QString &id) const
{
    for (int index = 0; index < scenes_.size(); ++index)
        if (scenes_.at(index).toObject().value("id").toString() == id)
            return index;
    return -1;
}

void StudioWorkspace::snapshot_preview()
{
    const int index = find_scene(preview_scene_id_);
    if (index >= 0)
        scenes_.replace(index, preview_.toJson());
}

bool StudioWorkspace::load(const QJsonArray &scenes)
{
    if (scenes.isEmpty() || scenes.size() > 64) {
        emit errorOccurred(QStringLiteral("Studio collection must contain between one and 64 scenes"));
        return false;
    }
    QSet<QString> ids;
    int width = 0;
    int height = 0;
    for (const QJsonValue &value : scenes) {
        if (!value.isObject())
            return false;
        SceneModel validator;
        if (!validator.load(value.toObject()))
            return false;
        if (ids.contains(validator.sceneId()) || validator.sceneId().isEmpty())
            return false;
        ids.insert(validator.sceneId());
        if (width == 0) {
            width = validator.canvasWidth();
            height = validator.canvasHeight();
        } else if (width != validator.canvasWidth() || height != validator.canvasHeight()) {
            emit errorOccurred(QStringLiteral("All Studio scenes must share one canvas size"));
            return false;
        }
    }
    qDeleteAll(nested_models_);
    nested_models_.clear();
    scenes_ = scenes;
    preview_scene_id_ = scenes_.first().toObject().value("id").toString();
    program_scene_id_ = preview_scene_id_;
    if (!preview_.load(scenes_.first().toObject()) || !program_.load(scenes_.first().toObject()))
        return false;
    QString error;
    if (!validate(error)) {
        emit errorOccurred(error);
        scenes_ = {};
        return false;
    }
    emit collectionChanged();
    return true;
}

SceneModel *StudioWorkspace::sceneModel(const QString &scene_id)
{
    if (scene_id == preview_scene_id_)
        return &preview_;
    if (scene_id == program_scene_id_)
        return &program_;
    const int index = find_scene(scene_id);
    if (index < 0)
        return nullptr;
    SceneModel *model = nested_models_.value(scene_id, nullptr);
    if (!model) {
        model = new SceneModel(this);
        connect(model, &SceneModel::errorOccurred, this, &StudioWorkspace::errorOccurred);
        nested_models_.insert(scene_id, model);
    }
    if (!model->load(scenes_.at(index).toObject()))
        return nullptr;
    return model;
}

bool StudioWorkspace::addScene(const QString &name)
{
    if (scenes_.size() >= 64 || name.trimmed().isEmpty() || name.size() > 128)
        return false;
    snapshot_preview();
    const QString id = QStringLiteral("local-%1").arg(
        QUuid::createUuid().toString(QUuid::WithoutBraces));
    const int width = scenes_.isEmpty() ? 1920 :
        scenes_.first().toObject().value("canvas").toObject().value("width").toInt(1920);
    const int height = scenes_.isEmpty() ? 1080 :
        scenes_.first().toObject().value("canvas").toObject().value("height").toInt(1080);
    QJsonObject scene{{"schemaVersion", 5}, {"revision", 0}, {"id", id},
        {"name", name.trimmed()},
        {"canvas", QJsonObject{{"width", width}, {"height", height},
                                {"backgroundColor", "#000000"}}},
        {"sources", QJsonArray{}}, {"items", QJsonArray{}}};
    scenes_.append(scene);
    preview_scene_id_ = id;
    preview_.load(scene);
    emit collectionChanged();
    return true;
}

bool StudioWorkspace::removeScene(const QString &scene_id)
{
    snapshot_preview();
    const int index = find_scene(scene_id);
    if (index < 0 || scenes_.size() <= 1)
        return false;
    scenes_.removeAt(index);
    if (preview_scene_id_ == scene_id) {
        preview_scene_id_ = scenes_.first().toObject().value("id").toString();
        preview_.load(scenes_.first().toObject());
    }
    if (program_scene_id_ == scene_id) {
        program_scene_id_ = preview_scene_id_;
        program_.load(preview_.toJson());
    }
    emit collectionChanged();
    return true;
}

bool StudioWorkspace::selectPreview(const QString &scene_id)
{
    if (scene_id == preview_scene_id_)
        return true;
    snapshot_preview();
    const int index = find_scene(scene_id);
    if (index < 0 || !preview_.load(scenes_.at(index).toObject()))
        return false;
    preview_scene_id_ = scene_id;
    emit collectionChanged();
    return true;
}

bool StudioWorkspace::visit_nested(const QString &scene_id, int depth, QSet<QString> &stack,
                                   QString &error) const
{
    if (depth > 2) {
        error = QStringLiteral("Nested scenes are limited to two levels");
        return false;
    }
    if (stack.contains(scene_id)) {
        error = QStringLiteral("Nested scenes must not contain a cycle");
        return false;
    }
    const int index = find_scene(scene_id);
    if (index < 0) {
        error = QStringLiteral("Nested source references a missing scene");
        return false;
    }
    stack.insert(scene_id);
    const QJsonObject scene = scenes_.at(index).toObject();
    for (const QJsonValue &value : scene.value("sources").toArray()) {
        const QJsonObject source = value.toObject();
        if (source.value("kind").toString() == QStringLiteral("nested") &&
            !visit_nested(source.value("sceneId").toString(), depth + 1, stack, error)) {
            stack.remove(scene_id);
            return false;
        }
    }
    stack.remove(scene_id);
    return true;
}

bool StudioWorkspace::validate(QString &error) const
{
    if (scenes_.isEmpty() || scenes_.size() > 64)
        return false;
    for (const QJsonValue &value : scenes_) {
        QSet<QString> stack;
        if (!visit_nested(value.toObject().value("id").toString(), 0, stack, error))
            return false;
    }
    return true;
}

bool StudioWorkspace::take(const QString &kind, int duration_ms)
{
    if (!QStringList{QStringLiteral("cut"), QStringLiteral("fade")}.contains(kind) ||
        duration_ms < 0 || duration_ms > 10'000)
        return false;
    snapshot_preview();
    QString error;
    if (!validate(error)) {
        emit errorOccurred(error);
        return false;
    }
    transition_kind_ = kind;
    transition_duration_ms_ = kind == QStringLiteral("cut") ? 0 : duration_ms;
    if (!program_.load(preview_.toJson()))
        return false;
    program_scene_id_ = preview_scene_id_;
    ++revision_;
    emit transitionStarted(transition_kind_, transition_duration_ms_);
    emit collectionChanged();
    return true;
}

QJsonObject StudioWorkspace::toJson()
{
    snapshot_preview();
    return {{"schemaVersion", 1}, {"revision", revision_},
            {"programSceneId", program_scene_id_}, {"previewSceneId", preview_scene_id_},
            {"transition", QJsonObject{{"kind", transition_kind_},
                                        {"durationMs", transition_duration_ms_}}},
            {"scenes", scenes_}};
}

bool StudioWorkspace::saveLocal(const QString &absolute_path)
{
    if (!QFileInfo(absolute_path).isAbsolute())
        return false;
    snapshot_preview();
    QString error;
    if (!validate(error)) {
        emit errorOccurred(error);
        return false;
    }
    QSaveFile file(absolute_path);
    const QByteArray encoded = QJsonDocument(toJson()).toJson(QJsonDocument::Indented);
    if (!file.open(QIODevice::WriteOnly) || file.write(encoded) != encoded.size() || !file.commit()) {
        emit errorOccurred(QStringLiteral("Local Studio collection could not be saved"));
        return false;
    }
    return true;
}

bool StudioWorkspace::loadLocal(const QString &absolute_path)
{
    if (!QFileInfo(absolute_path).isAbsolute())
        return false;
    QFile file(absolute_path);
    if (!file.open(QIODevice::ReadOnly) || file.size() > 1024 * 1024)
        return false;
    QJsonParseError parse_error;
    const QJsonDocument document = QJsonDocument::fromJson(file.readAll(), &parse_error);
    if (parse_error.error != QJsonParseError::NoError || !document.isObject())
        return false;
    const QJsonObject collection = document.object();
    if (collection.value("schemaVersion").toInt() != 1 || !load(collection.value("scenes").toArray()))
        return false;
    const QString preview_id = collection.value("previewSceneId").toString();
    const QString program_id = collection.value("programSceneId").toString();
    if (!selectPreview(preview_id) || find_scene(program_id) < 0)
        return false;
    program_scene_id_ = program_id;
    program_.load(scenes_.at(find_scene(program_id)).toObject());
    const QJsonObject transition = collection.value("transition").toObject();
    transition_kind_ = transition.value("kind").toString(QStringLiteral("cut"));
    transition_duration_ms_ = transition.value("durationMs").toInt(300);
    revision_ = collection.value("revision").toInteger();
    emit collectionChanged();
    return true;
}

}
