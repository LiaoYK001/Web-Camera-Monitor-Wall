#include "webobs/client/grant_codec.hpp"

#include <QCborArray>
#include <QCborMap>
#include <QCborParserError>
#include <QCborValue>
#include <QCryptographicHash>
#include <QJsonDocument>
#include <QRandomGenerator>
#include <sodium.h>

#include <algorithm>
#include <array>

namespace webobs::client {
namespace {

QString b64url(const QByteArray &value)
{
    return QString::fromLatin1(value.toBase64(QByteArray::Base64UrlEncoding |
                                               QByteArray::OmitTrailingEquals));
}

QByteArray from_b64url(const QJsonValue &value, qsizetype expected, QString &error)
{
    if (!value.isString() || value.toString().size() > 4096) {
        error = QStringLiteral("grant contains an invalid base64url field");
        return {};
    }
    const QByteArray result = QByteArray::fromBase64(value.toString().toLatin1(),
        QByteArray::Base64UrlEncoding | QByteArray::AbortOnBase64DecodingErrors);
    if (result.size() != expected) {
        error = QStringLiteral("grant contains an invalid key or ciphertext length");
        return {};
    }
    return result;
}

QByteArray cbor_head(quint8 major, quint64 value)
{
    QByteArray result;
    if (value < 24) {
        result.append(static_cast<char>((major << 5) | value));
    } else if (value <= 0xff) {
        result.append(static_cast<char>((major << 5) | 24));
        result.append(static_cast<char>(value));
    } else if (value <= 0xffff) {
        result.append(static_cast<char>((major << 5) | 25));
        result.append(static_cast<char>(value >> 8));
        result.append(static_cast<char>(value));
    } else {
        result.append(static_cast<char>((major << 5) | 26));
        for (int shift = 24; shift >= 0; shift -= 8)
            result.append(static_cast<char>(value >> shift));
    }
    return result;
}

QByteArray cbor_bytes(const QByteArray &value)
{
    return cbor_head(2, static_cast<quint64>(value.size())) + value;
}

QByteArray cbor_text(const QString &value)
{
    const QByteArray encoded = value.toUtf8();
    return cbor_head(3, static_cast<quint64>(encoded.size())) + encoded;
}

QByteArray canonical_enrollment(const QString &name, const QString &platform,
                                const DeviceIdentity &identity)
{
    std::array<std::pair<QByteArray, QByteArray>, 6> items{{
        {cbor_text(QStringLiteral("purpose")), cbor_text(QStringLiteral("webobs-client-enrollment-v1"))},
        {cbor_text(QStringLiteral("name")), cbor_text(name)},
        {cbor_text(QStringLiteral("platform")), cbor_text(platform)},
        {cbor_text(QStringLiteral("signingPublicKey")), cbor_bytes(identity.signing_public_key)},
        {cbor_text(QStringLiteral("encryptionPublicKey")), cbor_bytes(identity.encryption_public_key)},
        {cbor_text(QStringLiteral("nonce")), cbor_bytes(identity.enrollment_nonce)},
    }};
    std::sort(items.begin(), items.end(), [](const auto &left, const auto &right) {
        return left.first.size() == right.first.size() ? left.first < right.first :
                                                        left.first.size() < right.first.size();
    });
    QByteArray result = cbor_head(5, items.size());
    for (const auto &[key, value] : items)
        result += key + value;
    return result;
}

bool secure_sizes(const DeviceIdentity &identity)
{
    return identity.signing_public_key.size() == crypto_sign_PUBLICKEYBYTES &&
           identity.signing_secret_key.size() == crypto_sign_SECRETKEYBYTES &&
           identity.encryption_public_key.size() == crypto_box_PUBLICKEYBYTES &&
           identity.encryption_secret_key.size() == crypto_box_SECRETKEYBYTES &&
           identity.enrollment_nonce.size() == 32;
}

}

bool DeviceIdentity::valid() const
{
    return secure_sizes(*this) && !device_token.isEmpty();
}

QByteArray DeviceIdentity::serialize() const
{
    QCborMap value;
    value.insert(QStringLiteral("format"), QStringLiteral("webobs-device-identity-v1"));
    value.insert(QStringLiteral("signingPublic"), signing_public_key);
    value.insert(QStringLiteral("signingSecret"), signing_secret_key);
    value.insert(QStringLiteral("encryptionPublic"), encryption_public_key);
    value.insert(QStringLiteral("encryptionSecret"), encryption_secret_key);
    value.insert(QStringLiteral("enrollmentNonce"), enrollment_nonce);
    value.insert(QStringLiteral("deviceToken"), device_token);
    value.insert(QStringLiteral("serverSigningPublic"), server_signing_public_key);
    value.insert(QStringLiteral("latestGrantBundle"), latest_grant_bundle);
    value.insert(QStringLiteral("latestSharedScenes"), latest_shared_scenes);
    value.insert(QStringLiteral("bootstrapRevision"), bootstrap_revision);
    value.insert(QStringLiteral("controlServerUrl"), control_server_url);
    return QCborValue(value).toCbor(QCborValue::SortKeysInMaps);
}

DeviceIdentity DeviceIdentity::deserialize(const QByteArray &value, QString &error)
{
    QCborParserError parser_error;
    const QCborValue decoded = QCborValue::fromCbor(value, &parser_error);
    if (parser_error.error != QCborError::NoError || !decoded.isMap()) {
        error = QStringLiteral("stored device identity is invalid");
        return {};
    }
    const QCborMap map = decoded.toMap();
    if (map.value(QStringLiteral("format")).toString() != QStringLiteral("webobs-device-identity-v1")) {
        error = QStringLiteral("stored device identity format is unsupported");
        return {};
    }
    DeviceIdentity result;
    result.signing_public_key = map.value(QStringLiteral("signingPublic")).toByteArray();
    result.signing_secret_key = map.value(QStringLiteral("signingSecret")).toByteArray();
    result.encryption_public_key = map.value(QStringLiteral("encryptionPublic")).toByteArray();
    result.encryption_secret_key = map.value(QStringLiteral("encryptionSecret")).toByteArray();
    result.enrollment_nonce = map.value(QStringLiteral("enrollmentNonce")).toByteArray();
    result.device_token = map.value(QStringLiteral("deviceToken")).toString();
    result.server_signing_public_key = map.value(QStringLiteral("serverSigningPublic")).toByteArray();
    result.latest_grant_bundle = map.value(QStringLiteral("latestGrantBundle")).toByteArray();
    result.latest_shared_scenes = map.value(QStringLiteral("latestSharedScenes")).toByteArray();
    result.bootstrap_revision = map.value(QStringLiteral("bootstrapRevision")).toInteger();
    result.control_server_url = map.value(QStringLiteral("controlServerUrl")).toString();
    if (result.latest_grant_bundle.size() > 1024 * 1024 ||
        result.latest_shared_scenes.size() > 1024 * 1024 ||
        result.bootstrap_revision < 0 || result.control_server_url.size() > 2048) {
        error = QStringLiteral("stored device identity exceeds safety limits");
        return {};
    }
    if (!result.valid()) {
        error = QStringLiteral("stored device identity has invalid key material");
        sodium_memzero(result.signing_secret_key.data(), result.signing_secret_key.size());
        sodium_memzero(result.encryption_secret_key.data(), result.encryption_secret_key.size());
        return {};
    }
    return result;
}

bool GrantCodec::initialize(QString &error)
{
    if (sodium_init() < 0) {
        error = QStringLiteral("libsodium initialization failed");
        return false;
    }
#if WEBOBS_LOCKED_RUNTIME
    if (QString::fromLatin1(sodium_version_string()) != QStringLiteral(WEBOBS_SODIUM_VERSION)) {
        error = QStringLiteral("libsodium runtime version does not match the locked build");
        return false;
    }
#endif
    return true;
}

DeviceIdentity GrantCodec::create_identity(QString &error)
{
    DeviceIdentity result;
    result.signing_public_key.resize(crypto_sign_PUBLICKEYBYTES);
    result.signing_secret_key.resize(crypto_sign_SECRETKEYBYTES);
    result.encryption_public_key.resize(crypto_box_PUBLICKEYBYTES);
    result.encryption_secret_key.resize(crypto_box_SECRETKEYBYTES);
    result.enrollment_nonce.resize(32);
    if (crypto_sign_keypair(reinterpret_cast<unsigned char *>(result.signing_public_key.data()),
                            reinterpret_cast<unsigned char *>(result.signing_secret_key.data())) != 0 ||
        crypto_box_keypair(reinterpret_cast<unsigned char *>(result.encryption_public_key.data()),
                           reinterpret_cast<unsigned char *>(result.encryption_secret_key.data())) != 0) {
        error = QStringLiteral("device key generation failed");
        return {};
    }
    randombytes_buf(result.enrollment_nonce.data(), static_cast<size_t>(result.enrollment_nonce.size()));
    return result;
}

QJsonObject GrantCodec::enrollment_request(const QString &name, const QString &platform,
                                           const DeviceIdentity &identity, QString &error)
{
    if (!secure_sizes(identity) || name.trimmed().isEmpty()) {
        error = QStringLiteral("device enrollment input is invalid");
        return {};
    }
    const QByteArray proof = canonical_enrollment(name.trimmed(), platform, identity);
    QByteArray signature(crypto_sign_BYTES, Qt::Uninitialized);
    unsigned long long length = 0;
    if (crypto_sign_detached(reinterpret_cast<unsigned char *>(signature.data()), &length,
            reinterpret_cast<const unsigned char *>(proof.constData()), proof.size(),
            reinterpret_cast<const unsigned char *>(identity.signing_secret_key.constData())) != 0 ||
        length != crypto_sign_BYTES) {
        error = QStringLiteral("device enrollment signing failed");
        return {};
    }
    return {
        {QStringLiteral("name"), name.trimmed()}, {QStringLiteral("platform"), platform},
        {QStringLiteral("signingPublicKey"), b64url(identity.signing_public_key)},
        {QStringLiteral("encryptionPublicKey"), b64url(identity.encryption_public_key)},
        {QStringLiteral("enrollmentNonce"), b64url(identity.enrollment_nonce)},
        {QStringLiteral("signature"), b64url(signature)},
    };
}

GrantDocument GrantCodec::open_bundle(const QJsonObject &bundle, DeviceIdentity &identity,
                                      QString &error)
{
    if (bundle.value("format").toString() != QStringLiteral("webobs-client-grant+cbor-sealed-v1") ||
        bundle.value("contractVersion").toInt() != 1) {
        error = QStringLiteral("grant bundle format is unsupported");
        return {};
    }
    const QByteArray server_key = from_b64url(bundle.value("serverSigningPublicKey"),
                                               crypto_sign_PUBLICKEYBYTES, error);
    if (!error.isEmpty())
        return {};
    if (!identity.server_signing_public_key.isEmpty() &&
        sodium_compare(reinterpret_cast<const unsigned char *>(identity.server_signing_public_key.constData()),
                       reinterpret_cast<const unsigned char *>(server_key.constData()), server_key.size()) != 0) {
        error = QStringLiteral("server grant signing key changed; re-enrollment is required");
        return {};
    }
    const QJsonValue ciphertext_value = bundle.value("ciphertext");
    if (!ciphertext_value.isString() || ciphertext_value.toString().size() > 1024 * 1024) {
        error = QStringLiteral("grant ciphertext is invalid");
        return {};
    }
    const QByteArray ciphertext = QByteArray::fromBase64(ciphertext_value.toString().toLatin1(),
        QByteArray::Base64UrlEncoding | QByteArray::AbortOnBase64DecodingErrors);
    if (ciphertext.size() <= crypto_box_SEALBYTES + crypto_sign_BYTES) {
        error = QStringLiteral("grant ciphertext is truncated");
        return {};
    }
    QByteArray plaintext(ciphertext.size() - crypto_box_SEALBYTES, Qt::Uninitialized);
    if (crypto_box_seal_open(reinterpret_cast<unsigned char *>(plaintext.data()),
            reinterpret_cast<const unsigned char *>(ciphertext.constData()), ciphertext.size(),
            reinterpret_cast<const unsigned char *>(identity.encryption_public_key.constData()),
            reinterpret_cast<const unsigned char *>(identity.encryption_secret_key.constData())) != 0) {
        error = QStringLiteral("grant cannot be decrypted by this device");
        return {};
    }
    const QByteArray signature = plaintext.first(crypto_sign_BYTES);
    const QByteArray encoded = plaintext.sliced(crypto_sign_BYTES);
    if (crypto_sign_verify_detached(reinterpret_cast<const unsigned char *>(signature.constData()),
            reinterpret_cast<const unsigned char *>(encoded.constData()), encoded.size(),
            reinterpret_cast<const unsigned char *>(server_key.constData())) != 0) {
        sodium_memzero(plaintext.data(), plaintext.size());
        error = QStringLiteral("grant signature is invalid");
        return {};
    }
    QCborParserError parser_error;
    const QCborValue value = QCborValue::fromCbor(encoded, &parser_error);
    if (parser_error.error != QCborError::NoError || !value.isMap()) {
        sodium_memzero(plaintext.data(), plaintext.size());
        error = QStringLiteral("grant CBOR is invalid");
        return {};
    }
    const QCborMap map = value.toMap();
    GrantDocument result;
    result.client_id = map.value(QStringLiteral("clientId")).toString();
    result.issued_at = map.value(QStringLiteral("issuedAt")).toInteger();
    result.expires_at = map.value(QStringLiteral("expiresAt")).toInteger();
    result.revision = map.value(QStringLiteral("revision")).toInteger();
    result.cameras = map.value(QStringLiteral("cameras")).toArray().toVariantList();
    identity.server_signing_public_key = server_key;
    if (result.client_id.isEmpty() || result.expires_at <= result.issued_at) {
        sodium_memzero(plaintext.data(), plaintext.size());
        error = QStringLiteral("grant document is incomplete");
        return {};
    }
    identity.latest_grant_bundle = QJsonDocument(bundle).toJson(QJsonDocument::Compact);
    sodium_memzero(plaintext.data(), plaintext.size());
    return result;
}

}
