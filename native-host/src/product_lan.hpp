#pragma once

#include <QByteArray>
#include <QJsonObject>
#include <QNetworkAccessManager>
#include <QSet>
#include <QUrl>
#include <functional>

namespace webobs::native_host {
// The product supervisor's loopback-only LAN sharing switch.
//
// The window uses this to open or close the private HTTPS/Web entry that other
// machines on the account owner's network use. It never talks to a camera, a
// media port or an upstream host: the endpoint must be an absolute
// http://127.0.0.1:<port>/lan address supplied by the supervisor, and every
// request carries this boot's host token. Replies are bounded status receipts,
// not account credentials.
class ProductLanSwitch final : public QObject {
public:
	using Reply = std::function<void(int, const QJsonObject &)>;
	static constexpr qint64 response_limit = 32768;
	ProductLanSwitch(QUrl endpoint, QByteArray host_secret, QObject *parent = nullptr);
	~ProductLanSwitch() override;
	// False when the supervisor supplied no switch or supplied an unsafe one;
	// every request then reports code 0 without touching the network.
	[[nodiscard]] bool usable() const noexcept { return configured_; }
	void request(const QByteArray &method, const QJsonObject &body, Reply callback, int timeout_ms = 4000);
private:
	QNetworkAccessManager network_;
	QUrl endpoint_;
	QByteArray host_secret_;
	bool configured_ = false;
	QSet<QNetworkReply *> pending_;
};
} // namespace webobs::native_host
