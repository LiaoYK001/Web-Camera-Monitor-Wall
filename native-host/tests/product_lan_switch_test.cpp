// Real Qt HTTP/event-loop regression for the supervisor's LAN sharing switch.
// This is transport and fail-closed evidence only: no Caddy, certificate,
// camera, LAN interface or installed product is involved.
#include "product_lan.hpp"
#include <QCoreApplication>
#include <QEventLoop>
#include <QHostAddress>
#include <QTcpServer>
#include <QTcpSocket>
#include <QTimer>
#include <iostream>
#include <memory>
#include <stdexcept>

namespace {
using webobs::native_host::ProductLanSwitch;
const QByteArray secret(64, 'a');
void require(bool value, const char *message) { if (!value) throw std::runtime_error(message); }

struct Fixture {
	// The listener is heap-owned so a test can close it: destroying QTcpServer releases the
	// listening socket on every Qt 6 version, which is what the dead-switch case needs.
	std::unique_ptr<QTcpServer> server = std::make_unique<QTcpServer>();
	QByteArray requests;
	int connections = 0, responses = 0, next_code = 200;
	QByteArray next_body = R"({"enabled":false,"port":18443,"urls":[],"running":false,"pendingRestart":false})";
	bool oversized = false, send_json = true, failed = false;
	Fixture()
	{
		require(server->listen(QHostAddress::LocalHost, 0), "fixture listen failed");
		QObject::connect(server.get(), &QTcpServer::newConnection, server.get(), [this] {
			while (server) {
				auto *socket = server->nextPendingConnection();
				if (!socket) break;
				++connections;
				auto bytes = std::make_shared<QByteArray>();
				QObject::connect(socket, &QTcpSocket::disconnected, socket, &QObject::deleteLater);
				QObject::connect(socket, &QTcpSocket::readyRead, server.get(), [this, socket, bytes] {
					bytes->append(socket->readAll());
					const auto end = bytes->indexOf("\r\n\r\n");
					if (end < 0) return;
					requests.append(bytes->left(end));
					if (requests.contains("Cookie:")) { failed = true; socket->disconnectFromHost(); return; }
					QByteArray body;
					if (!oversized && send_json) body = next_body;
					const QByteArray head = "HTTP/1.1 " + QByteArray::number(oversized ? 200 : next_code) +
						" OK\r\nContent-Type: application/json\r\n";
					const QByteArray payload = oversized
						? QByteArray("HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n\r\n") +
						  QByteArray(ProductLanSwitch::response_limit + 4096, 'x')
						: head + "Content-Length: " + QByteArray::number(body.size()) +
						  "\r\nConnection: close\r\n\r\n" + body;
					socket->write(payload);
					socket->disconnectFromHost();
					++responses;
				});
			}
		});
	}
	void close() { server.reset(); }
	int port() const { return server ? server->serverPort() : 0; }
};

QUrl endpoint(int port)
{
	return QUrl(QString("http://127.0.0.1:%1/lan").arg(port));
}

int exchange(Fixture &fixture, ProductLanSwitch &client, const QByteArray &method, const QJsonObject &body,
		const char *label)
{
	fixture.requests.clear();
	fixture.responses = 0;
	bool answered = false;
	int code = -1;
	client.request(method, body, [&answered, &code](int result, const QJsonObject &) {
		code = result;
		answered = true;
	});
	QEventLoop loop;
	QTimer poll;
	QObject::connect(&poll, &QTimer::timeout, &loop, [&loop, &answered] {
		if (answered)
			loop.quit();
	});
	poll.start(20);
	// The client's own deadline aborts the reply at 4 s, so 6 s of event loop is enough to
	// distinguish "answered slowly" from "Qt dispatched nothing" on a loaded CI host.
	QTimer::singleShot(6000, &loop, &QEventLoop::quit);
	loop.exec();
	poll.stop();
	if (!answered) {
		// Connections reached the listener and it replied, but no client callback arrived:
		// the Qt HTTP path is at fault. Zero connections means the OS never delivered the
		// loopback connection. Naming the side keeps the next run actionable.
		std::cerr << "no LAN switch answer for " << label << ": connections=" << fixture.connections
		          << " responses=" << fixture.responses << '\n';
		throw std::runtime_error("the LAN switch never answered");
	}
	return code;
}
} // namespace

int main(int argc, char **argv)
{
	QCoreApplication app(argc, argv);
	try {
		Fixture fixture;
		// Fail closed on every address that is not this boot's loopback switch.
		for (const auto &unsafe : {QUrl("http://127.0.0.1/lan"), QUrl("https://127.0.0.1:18443/lan"),
			QUrl("http://localhost:18443/lan"), QUrl("http://127.0.0.1:18443/"),
			QUrl("http://127.0.0.1:18443/lan?token=x"), QUrl("http://10.0.0.8:18443/lan"),
			QUrl("http://a@127.0.0.1:18443/lan")}) {
			ProductLanSwitch refusal(unsafe, secret);
			require(!refusal.usable(), "unsafe LAN endpoint was accepted");
			int code = -1;
			refusal.request("GET", {}, [&code](int result, const QJsonObject &) { code = result; });
			require(code == 0, "unsafe LAN endpoint still attempted a request");
		}
		// Prove the loopback listener is reachable through the OS socket API before blaming
		// the Qt HTTP client: a failed probe names an OS/firewall problem, a passed probe with
		// a stalled reply names the Qt network path on this build.
		QTcpSocket probe;
		probe.connectToHost("127.0.0.1", fixture.port());
		require(probe.waitForConnected(3000), "the loopback fixture socket could not connect");
		probe.write("GET /lan HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n");
		require(probe.waitForBytesWritten(3000), "the LAN probe request was not written");
		// The fixture replies from its readyRead signal, so the reply needs the event loop;
		// a blocking waitForReadyRead would prove nothing about the OS socket path.
		QEventLoop probe_loop;
		QTimer probe_poll;
		QObject::connect(&probe_poll, &QTimer::timeout, &probe_loop, [&probe, &probe_loop] {
			if (probe.bytesAvailable() > 0)
				probe_loop.quit();
		});
		probe_poll.start(20);
		QTimer::singleShot(3000, &probe_loop, &QEventLoop::quit);
		probe_loop.exec();
		probe_poll.stop();
		require(probe.readAll().startsWith("HTTP/1.1 200"), "the loopback fixture never answered the raw probe");
		probe.disconnectFromHost();

		ProductLanSwitch short_secret(endpoint(fixture.port()), QByteArray(63, 'a'));
		require(!short_secret.usable(), "a malformed host token was accepted");

		ProductLanSwitch client(endpoint(fixture.port()), secret);
		require(client.usable(), "the loopback LAN switch was refused");
		require(exchange(fixture, client, "GET", {}, "status-read") == 200, "LAN status read failed");
		require(fixture.requests.contains("GET /lan HTTP/1.1"), "LAN status is not a plain GET");
		// Qt canonicalizes raw header names (X-Webobs-Native-Token) and HTTP names are
		// case-insensitive, so the fixture compares the whole header block lowercased.
		const QByteArray lowered = fixture.requests.toLower();
		require(lowered.contains("x-webobs-native-token: " + QByteArray(secret).toLower()),
			"host token was not supplied");
		require(lowered.contains("origin: http://127.0.0.1:"), "the LAN switch request has no own origin");
		require(!lowered.contains("cookie:"), "the LAN switch request carried a session cookie");

		fixture.next_body = R"({"enabled":true,"port":18443,"urls":["https://192.168.1.9:18443"],
			"running":false,"pendingRestart":true})";
		require(exchange(fixture, client, "POST", QJsonObject{{"enabled", true}, {"port", 18443}}, "toggle-on") == 200,
			"LAN share toggle failed");
		require(fixture.requests.contains("POST /lan HTTP/1.1"), "LAN toggle is not a POST");
		// Qt canonicalizes header names differently across versions, so the JSON body
		// declaration is matched the same case-insensitive way as the token.
		require(fixture.requests.toLower().contains("content-type: application/json"),
			"toggle has no JSON content type");

		fixture.next_code = 401;
		fixture.next_body = R"({"error":"unauthorized"})";
		require(exchange(fixture, client, "POST", QJsonObject{{"enabled", false}, {"port", 18443}}, "refused-status") == 401,
			"an unauthenticated LAN toggle was not reported");

		// A 200 whose body is not a JSON object is unreadable: report 0 so the window
		// keeps the last receipt instead of inventing a state.
		fixture.next_code = 200;
		fixture.send_json = false;
		require(exchange(fixture, client, "POST", QJsonObject{{"enabled", true}, {"port", 18443}}, "unreadable-body") == 0,
			"an unreadable LAN reply was reported as a usable state");

		// A server error is reported even when the body is an HTML error page.
		fixture.next_code = 500;
		fixture.send_json = true;
		fixture.next_body = QByteArray("<html>not json</html>");
		require(exchange(fixture, client, "POST", QJsonObject{{"enabled", false}, {"port", 18443}}, "server-error") == 500,
			"a failing LAN switch was reported as silent instead of refused");

		fixture.oversized = true;
		fixture.next_code = 200;
		require(exchange(fixture, client, "GET", {}, "oversized-reply") == 0, "an oversized LAN reply was accepted");

		// A dead switch reports 0 so the window keeps the last known receipt.
		Fixture dead;
		ProductLanSwitch alone(endpoint(dead.port()), secret);
		dead.close();
		require(exchange(dead, alone, "GET", {}, "dead-switch") == 0, "a closed LAN switch was reported as a status code");
	} catch (const std::exception &error) {
		std::cerr << "FAIL native LAN switch: " << error.what() << '\n';
		return 1;
	}
	std::cout << "PASS native LAN switch: unsafe endpoints, token, toggle, unreadable and oversized replies\n";
	return 0;
}
