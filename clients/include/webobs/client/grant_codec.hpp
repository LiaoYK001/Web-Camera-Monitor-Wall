#pragma once

#include <QByteArray>
#include <QJsonObject>
#include <QString>
#include <QVariantList>

namespace webobs::client {

struct DeviceIdentity {
    DeviceIdentity() = default;
    ~DeviceIdentity();
    DeviceIdentity(const DeviceIdentity &) = delete;
    DeviceIdentity &operator=(const DeviceIdentity &) = delete;
    DeviceIdentity(DeviceIdentity &&other) noexcept;
    DeviceIdentity &operator=(DeviceIdentity &&other) noexcept;

    QByteArray signing_public_key;
    QByteArray signing_secret_key;
    QByteArray encryption_public_key;
    QByteArray encryption_secret_key;
    QByteArray enrollment_nonce;
    QString device_token;
    QByteArray server_signing_public_key;
    QByteArray latest_grant_bundle;
    QByteArray latest_shared_scenes;
    qint64 bootstrap_revision = 0;
    QString control_server_url;

    [[nodiscard]] bool valid() const;
    [[nodiscard]] QByteArray serialize() const;
    void clear_sensitive() noexcept;
    static DeviceIdentity deserialize(const QByteArray &value, QString &error);
};

struct GrantDocument {
    QString client_id;
    qint64 issued_at = 0;
    qint64 expires_at = 0;
    qint64 revision = 0;
    QVariantList cameras;
};

class GrantCodec {
public:
    static bool initialize(QString &error);
    static DeviceIdentity create_identity(QString &error);
    static QJsonObject enrollment_request(const QString &name, const QString &platform,
                                          const DeviceIdentity &identity, QString &error);
    static GrantDocument open_bundle(const QJsonObject &bundle, DeviceIdentity &identity,
                                     QString &error);
};

}
