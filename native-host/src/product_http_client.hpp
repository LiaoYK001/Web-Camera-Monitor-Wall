#pragma once

#include <QJsonObject>
#include <QNetworkAccessManager>
#include <QSet>
#include <QUrl>
#include <functional>

namespace webobs::native_host {
// One product session and one fixed loopback origin. No media/renderer code.
class ProductHttpClient final : public QObject {
public:
	using Reply = std::function<void(int, const QJsonObject &)>;
	static constexpr qint64 response_limit = 2 * 1024 * 1024;
	ProductHttpClient(QUrl origin, QByteArray host_secret, QObject *parent = nullptr);
	~ProductHttpClient() override;
	void reset_session();
	void request(const QString &path, const QByteArray &method, const QJsonObject &body, Reply callback,
		int timeout_ms = 2000);
private:
	QNetworkAccessManager network_;
	QUrl origin_;
	QByteArray host_secret_;
	QByteArray session_cookie_;
	quint64 generation_ = 0;
	QSet<QNetworkReply *> pending_;
	bool configured_ = false;
};
} // namespace webobs::native_host
