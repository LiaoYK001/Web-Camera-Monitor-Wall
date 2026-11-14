// Real Qt HTTP/event-loop regression with disposable loopback fixtures.
// This is transport evidence, not account, camera or renderer qualification.
#include "product_http_client.hpp"
#include <QCoreApplication>
#include <QElapsedTimer>
#include <QEventLoop>
#include <QHostAddress>
#include <QPointer>
#include <QTcpServer>
#include <QTcpSocket>
#include <QTimer>
#include <iostream>
#include <memory>
#include <stdexcept>

namespace {
using webobs::native_host::ProductHttpClient;
const QByteArray secret(64, 'a'), token_a(64, 'b'), token_b(64, 'c');
void require(bool value, const char *message) { if (!value) throw std::runtime_error(message); }
QByteArray cookie(const QByteArray &token)
{
	return "webobs_session=" + token + "; Path=/; HttpOnly; SameSite=Strict; Max-Age=3600";
}
void pause(int ms)
{
	QEventLoop loop;
	QTimer::singleShot(ms, &loop, &QEventLoop::quit);
	loop.exec();
}
struct Fixture {
	QTcpServer server;
	QByteArray next_login = cookie(token_a), expected = "webobs_session=" + token_a;
	bool inject_session_cookie = false, failed = false;
	int next_login_delay = 0, login_requests = 0;
	QString redirect;
	Fixture()
	{
		require(server.listen(QHostAddress::LocalHost, 0), "fixture listen failed");
		QObject::connect(&server, &QTcpServer::newConnection, &server, [this] {
			while (auto *socket = server.nextPendingConnection()) {
				auto bytes = std::make_shared<QByteArray>();
				QObject::connect(socket, &QTcpSocket::disconnected, socket, &QObject::deleteLater);
				QObject::connect(socket, &QTcpSocket::readyRead, &server, [this, socket, bytes] {
					bytes->append(socket->readAll());
					if (bytes->size() > 16384) { failed = true; socket->disconnectFromHost(); return; }
					const auto end = bytes->indexOf("\r\n\r\n");
					if (end < 0) return;
					const auto lines = bytes->left(end).split('\n');
					const auto first = lines.front().trimmed().split(' ');
					if (first.size() != 3) { failed = true; socket->disconnectFromHost(); return; }
					QByteArray seen_cookie, seen_secret;
					int length = 0;
					for (const auto &line : lines) {
						const auto field = line.left(line.indexOf(':')).toLower();
						const auto value = line.mid(line.indexOf(':') + 1).trimmed();
						if (field == "cookie") seen_cookie = value;
						if (field == "x-webobs-native-host") seen_secret = value;
						if (field == "content-length") length = value.toInt();
					}
					if (bytes->size() < end + 4 + length) return;
					QObject::disconnect(socket, &QTcpSocket::readyRead, &server, nullptr);
					if (seen_secret != secret) { failed = true; socket->disconnectFromHost(); return; }
					const auto path = first[1];
					QByteArray body = "{}", headers;
					int status = 200, delay = 0;
					if (path.endsWith("/auth/login")) {
						headers = "Set-Cookie: " + next_login + "\r\n";
						delay = next_login_delay;
						next_login_delay = 0;
						++login_requests;
					}
					else if (path.endsWith("/auth/logout")) {
						headers = "Set-Cookie: webobs_session=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0\r\n";
						delay = 200;
					} else if (path.endsWith("/auth/session")) {
						body = QByteArray("{\"present\":") + (seen_cookie.isEmpty() ? "false" : "true") +
							",\"matches\":" + (seen_cookie == expected ? "true" : "false") + '}';
						if (inject_session_cookie) headers = "Set-Cookie: " + cookie(QByteArray(64, 'd')) + "\r\n";
					} else if (path.endsWith("/stall")) return;
					else if (path.endsWith("/oversized"))
						body = "{\"data\":\"" + QByteArray(ProductHttpClient::response_limit + 1, 'x') + "\"}";
					else if (path.endsWith("/redirect")) {
						status = 302;
						headers = "Location: " + redirect.toUtf8() + "\r\n";
					}
					const auto response = "HTTP/1.1 " + QByteArray::number(status) + " Fixture\r\nConnection: close\r\n"
						"Content-Type: application/json\r\nContent-Length: " + QByteArray::number(body.size()) + "\r\n" + headers + "\r\n" + body;
					const QPointer<QTcpSocket> retained = socket;
					QTimer::singleShot(delay, &server, [retained, response] {
						if (retained) { retained->write(response); retained->disconnectFromHost(); }
					});
				});
			}
		});
	}
	QUrl origin() const { return QUrl("http://127.0.0.1:" + QString::number(server.serverPort())); }
};
struct Result { int code = -1; QJsonObject body; bool done = false; };
Result call(ProductHttpClient &client, const QString &path, const QByteArray &method = "GET", int timeout = 1000)
{
	auto result = std::make_shared<Result>();
	QEventLoop loop;
	const QPointer<QEventLoop> retained = &loop;
	client.request(path, method, {}, [result, retained](int code, const auto &body) {
		result->code = code; result->body = body; result->done = true;
		if (retained) retained->quit();
	}, timeout);
	QTimer::singleShot(2000, &loop, &QEventLoop::quit);
	if (!result->done) loop.exec();
	require(result->done, "bounded request did not settle");
	return *result;
}
void exercise()
{
	Fixture fixture;
	ProductHttpClient client(fixture.origin(), secret);
	require(call(client, "/api/v1/native/auth/login", "POST").code == 200, "first login cookie rejected");
	require(call(client, "/api/v1/native/auth/session").body.value("matches").toBool(), "bound cookie not sent");
	bool stale_callback = false;
	client.request("/api/v1/native/auth/logout", "POST", {}, [&](int, const auto &) { stale_callback = true; });
	client.reset_session();
	fixture.next_login = cookie(token_b);
	fixture.expected = "webobs_session=" + token_b;
	require(call(client, "/api/v1/native/auth/login", "POST").code == 200, "second login cookie rejected");
	pause(350);
	require(!stale_callback, "retired request callback crossed session generation");
	require(call(client, "/api/v1/native/auth/session").body.value("matches").toBool(), "late logout changed newer cookie");
	fixture.next_login = cookie(token_a);
	fixture.next_login_delay = 200;
	const int previous_logins = fixture.login_requests;
	bool old_login_callback = false;
	client.request("/api/v1/native/auth/login", "POST", {}, [&](int, const auto &) { old_login_callback = true; });
	for (int i = 0; i < 50 && fixture.login_requests == previous_logins; ++i) pause(10);
	require(fixture.login_requests == previous_logins + 1, "delayed login fixture did not receive the old request");
	fixture.next_login = cookie(token_b);
	require(call(client, "/api/v1/native/auth/login", "POST").code == 200, "new login during delayed old response failed");
	pause(250);
	require(!old_login_callback && call(client, "/api/v1/native/auth/session").body.value("matches").toBool(),
		"late older login crossed the current account generation");
	fixture.inject_session_cookie = true;
	require(call(client, "/api/v1/native/auth/session").code == 200, "session fixture failed");
	fixture.inject_session_cookie = false;
	require(call(client, "/api/v1/native/auth/session").body.value("matches").toBool(), "non-login reply changed cookie");
	QTcpServer destination;
	require(destination.listen(QHostAddress::LocalHost, 0), "redirect destination failed");
	int redirected = 0;
	QObject::connect(&destination, &QTcpServer::newConnection, &destination, [&] { ++redirected; });
	fixture.redirect = "http://127.0.0.1:" + QString::number(destination.serverPort()) + "/credential-receiver";
	require(call(client, "/api/v1/native/redirect").code == 302, "redirect not returned as a non-followed response");
	pause(30);
	require(redirected == 0, "redirect forwarded private request credentials");
	fixture.next_login = "webobs_session=invalid; Path=/; HttpOnly";
	require(call(client, "/api/v1/native/auth/login", "POST").code == 0, "malformed session token accepted");
	require(!call(client, "/api/v1/native/auth/session").body.value("present").toBool(), "failed login retained old cookie");
	QElapsedTimer elapsed;
	elapsed.start();
	require(call(client, "/api/v1/native/stall", "GET", 60).code == 0 && elapsed.elapsed() < 1500, "deadline did not bound request");
	require(call(client, "/api/v1/native/oversized").code == 0, "oversized response accepted");
	int capacity_callbacks = 0;
	{
		ProductHttpClient pending(fixture.origin(), secret);
		for (int i = 0; i < 17; ++i)
			pending.request("/api/v1/native/stall", "GET", {}, [&](int, const auto &) { ++capacity_callbacks; }, 1000);
		require(capacity_callbacks == 1, "pending request bound missing");
	}
	pause(30);
	require(capacity_callbacks == 1 && !fixture.failed, "client cleanup or fixture protocol failed");
	ProductHttpClient invalid(QUrl("http://untrusted.invalid"), secret);
	require(call(invalid, "/api/v1/native/auth/login", "POST").code == 0, "non-loopback origin accepted");
}
} // namespace

int main(int argc, char **argv)
{
	QCoreApplication application(argc, argv);
	try {
		exercise();
		std::cout << "PASS real Qt HTTP: session generations/cookies, no redirects, bounds, deadline and destruction. No media qualification.\n";
		return 0;
	} catch (const std::exception &error) {
		std::cerr << "FAIL Qt HTTP fixture: " << error.what() << '\n';
		return 1;
	}
}
