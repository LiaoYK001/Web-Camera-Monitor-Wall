#pragma once

#include <QByteArray>
#include <QString>

namespace webobs::client {

class SecureStore {
public:
    SecureStore();
    [[nodiscard]] bool persistent_available() const;
    [[nodiscard]] QString backend() const;
    bool save(const QByteArray &value, QString &error);
    QByteArray load(QString &error) const;
    bool clear(QString &error);

private:
    bool persistent_available_ = false;
    QString backend_ = QStringLiteral("memory-only");
    QByteArray temporary_value_;
};

}
