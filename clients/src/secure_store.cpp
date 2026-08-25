#include "webobs/client/secure_store.hpp"

#include <QByteArray>
#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QSaveFile>
#include <QStandardPaths>

#include <sodium.h>

#if defined(WEBOBS_SECURE_STORE_DPAPI)
#include <windows.h>
#include <dpapi.h>
#elif defined(WEBOBS_SECURE_STORE_LIBSECRET)
#pragma push_macro("signals")
#undef signals
#include <libsecret/secret.h>
#pragma pop_macro("signals")
#elif defined(WEBOBS_SECURE_STORE_ANDROID)
#include <QJniObject>
#endif

namespace webobs::client {
namespace {

#if defined(WEBOBS_SECURE_STORE_LIBSECRET)
const SecretSchema identity_schema = [] {
    SecretSchema schema{};
    schema.name = "org.webobs.Native.Identity";
    schema.flags = SECRET_SCHEMA_NONE;
    schema.attributes[0] = {"account", SECRET_SCHEMA_ATTRIBUTE_STRING};
    schema.attributes[1] = {nullptr, SECRET_SCHEMA_ATTRIBUTE_STRING};
    return schema;
}();
#endif

}

SecureStore::SecureStore()
{
#if defined(WEBOBS_SECURE_STORE_DPAPI)
    persistent_available_ = true;
    backend_ = QStringLiteral("windows-dpapi");
#elif defined(WEBOBS_SECURE_STORE_LIBSECRET)
    GError *error = nullptr;
    SecretService *service = secret_service_get_sync(SECRET_SERVICE_NONE, nullptr, &error);
    persistent_available_ = service != nullptr;
    if (service)
        g_object_unref(service);
    if (error)
        g_error_free(error);
    backend_ = persistent_available_ ? QStringLiteral("linux-secret-service") :
                                      QStringLiteral("memory-only");
#elif defined(WEBOBS_SECURE_STORE_ANDROID)
    persistent_available_ = QJniObject::callStaticMethod<jboolean>(
        "org/webobs/nativeclient/KeyStoreBridge", "available", "()Z");
    backend_ = persistent_available_ ? QStringLiteral("android-keystore") :
                                      QStringLiteral("memory-only");
#endif
}

SecureStore::~SecureStore()
{
    if (!temporary_value_.isEmpty())
        sodium_memzero(temporary_value_.data(), static_cast<size_t>(temporary_value_.size()));
}

bool SecureStore::persistent_available() const
{
    return persistent_available_;
}

QString SecureStore::backend() const
{
    return backend_;
}

bool SecureStore::save(const QByteArray &value, QString &error)
{
    if (!persistent_available_) {
        if (!temporary_value_.isEmpty())
            sodium_memzero(temporary_value_.data(), static_cast<size_t>(temporary_value_.size()));
        temporary_value_ = value;
        error = QStringLiteral("secure storage unavailable; identity is temporary and will not be persisted");
        return true;
    }
#if defined(WEBOBS_SECURE_STORE_DPAPI)
    DATA_BLOB input{static_cast<DWORD>(value.size()),
                    reinterpret_cast<BYTE *>(const_cast<char *>(value.constData()))};
    DATA_BLOB output{};
    if (!CryptProtectData(&input, L"WebObs Native Device Identity", nullptr, nullptr, nullptr,
                          CRYPTPROTECT_UI_FORBIDDEN, &output)) {
        error = QStringLiteral("DPAPI could not protect the device identity");
        return false;
    }
    const QByteArray protected_value(reinterpret_cast<const char *>(output.pbData), output.cbData);
    LocalFree(output.pbData);
    const QString root = QStandardPaths::writableLocation(QStandardPaths::AppLocalDataLocation);
    if (root.isEmpty() || !QFileInfo(root).isAbsolute()) {
        error = QStringLiteral("DPAPI identity directory is unavailable");
        return false;
    }
    const QString path = QDir(root).filePath(QStringLiteral("device-identity.dpapi"));
    if (!QDir().mkpath(QFileInfo(path).absolutePath())) {
        error = QStringLiteral("DPAPI identity directory could not be created");
        return false;
    }
    QSaveFile file(path);
    if (!file.open(QIODevice::WriteOnly | QIODevice::Truncate) ||
        file.write(protected_value) != protected_value.size() || !file.commit()) {
        error = QStringLiteral("DPAPI identity file could not be written");
        return false;
    }
    return true;
#elif defined(WEBOBS_SECURE_STORE_LIBSECRET)
    GError *native_error = nullptr;
    const QByteArray encoded = value.toBase64();
    const bool saved = secret_password_store_sync(&identity_schema, SECRET_COLLECTION_DEFAULT,
        "WebObs Native Device Identity", encoded.constData(), nullptr, &native_error,
        "account", "default", nullptr);
    if (!saved) {
        error = QStringLiteral("Secret Service could not store the device identity");
        if (native_error)
            g_error_free(native_error);
    }
    return saved;
#elif defined(WEBOBS_SECURE_STORE_ANDROID)
    const QJniObject encoded = QJniObject::fromString(QString::fromLatin1(value.toBase64()));
    const bool saved = QJniObject::callStaticMethod<jboolean>(
        "org/webobs/nativeclient/KeyStoreBridge", "save", "(Ljava/lang/String;)Z",
        encoded.object<jstring>());
    if (!saved)
        error = QStringLiteral("Android Keystore could not store the device identity");
    return saved;
#else
    Q_UNUSED(value)
    error = QStringLiteral("secure storage backend was not compiled");
    return false;
#endif
}

QByteArray SecureStore::load(QString &error) const
{
    if (!persistent_available_)
        return temporary_value_;
#if defined(WEBOBS_SECURE_STORE_DPAPI)
    const QString root = QStandardPaths::writableLocation(QStandardPaths::AppLocalDataLocation);
    if (root.isEmpty() || !QFileInfo(root).isAbsolute()) {
        error = QStringLiteral("DPAPI identity directory is unavailable");
        return {};
    }
    const QString path = QDir(root).filePath(QStringLiteral("device-identity.dpapi"));
    QFile file(path);
    if (!file.exists())
        return {};
    if (!file.open(QIODevice::ReadOnly) || file.size() > 1024 * 1024) {
        error = QStringLiteral("DPAPI identity file could not be read");
        return {};
    }
    QByteArray protected_value = file.readAll();
    DATA_BLOB input{static_cast<DWORD>(protected_value.size()),
                    reinterpret_cast<BYTE *>(protected_value.data())};
    DATA_BLOB output{};
    if (!CryptUnprotectData(&input, nullptr, nullptr, nullptr, nullptr,
                            CRYPTPROTECT_UI_FORBIDDEN, &output)) {
        error = QStringLiteral("DPAPI could not unprotect the device identity");
        return {};
    }
    const QByteArray result(reinterpret_cast<const char *>(output.pbData), output.cbData);
    LocalFree(output.pbData);
    return result;
#elif defined(WEBOBS_SECURE_STORE_LIBSECRET)
    GError *native_error = nullptr;
    gchar *value = secret_password_lookup_sync(&identity_schema, nullptr, &native_error,
                                                "account", "default", nullptr);
    if (!value) {
        if (native_error) {
            error = QStringLiteral("Secret Service could not load the device identity");
            g_error_free(native_error);
        }
        return {};
    }
    const QByteArray result = QByteArray::fromBase64(value);
    secret_password_free(value);
    return result;
#elif defined(WEBOBS_SECURE_STORE_ANDROID)
    const QJniObject value = QJniObject::callStaticObjectMethod(
        "org/webobs/nativeclient/KeyStoreBridge", "load", "()Ljava/lang/String;");
    if (!value.isValid())
        return {};
    return QByteArray::fromBase64(value.toString().toLatin1());
#else
    Q_UNUSED(error)
    return {};
#endif
}

bool SecureStore::clear(QString &error)
{
    if (!temporary_value_.isEmpty())
        sodium_memzero(temporary_value_.data(), static_cast<size_t>(temporary_value_.size()));
    temporary_value_.clear();
    if (!persistent_available_)
        return true;
#if defined(WEBOBS_SECURE_STORE_DPAPI)
    const QString root = QStandardPaths::writableLocation(QStandardPaths::AppLocalDataLocation);
    if (root.isEmpty() || !QFileInfo(root).isAbsolute()) {
        error = QStringLiteral("DPAPI identity directory is unavailable");
        return false;
    }
    const QString path = QDir(root).filePath(QStringLiteral("device-identity.dpapi"));
    if (QFile::exists(path) && !QFile::remove(path)) {
        error = QStringLiteral("DPAPI identity file could not be removed");
        return false;
    }
    return true;
#elif defined(WEBOBS_SECURE_STORE_LIBSECRET)
    GError *native_error = nullptr;
    const bool cleared = secret_password_clear_sync(&identity_schema, nullptr, &native_error,
                                                     "account", "default", nullptr);
    if (!cleared && native_error) {
        error = QStringLiteral("Secret Service could not remove the device identity");
        g_error_free(native_error);
    }
    return cleared;
#elif defined(WEBOBS_SECURE_STORE_ANDROID)
    const bool cleared = QJniObject::callStaticMethod<jboolean>(
        "org/webobs/nativeclient/KeyStoreBridge", "clear", "()Z");
    if (!cleared)
        error = QStringLiteral("Android Keystore identity could not be removed");
    return cleared;
#else
    Q_UNUSED(error)
    return true;
#endif
}

}
