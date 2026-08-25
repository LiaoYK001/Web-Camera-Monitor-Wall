#pragma once

#include <QString>

namespace webobs::client {

// Returns only lan, vpn, or wan. Public DNS names are conservatively WAN;
// merely having a VPN interface never upgrades an unrelated public target.
QString classify_network(const QString &endpoint);

}
