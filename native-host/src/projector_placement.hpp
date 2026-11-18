#pragma once

#include <QJsonObject>
#include <QRect>
#include <algorithm>

namespace webobs::native_host {
// Qt logical coordinates, not raw device pixels. Re-clamp at open time so an
// unplugged monitor cannot strand the projector outside the visible desktop.
inline QRect projector_window_rect(const QJsonObject &saved, const QRect &available)
{
	if (available.isEmpty()) return {};
	const auto x = saved.value("x").toInteger(-100001);
	const auto y = saved.value("y").toInteger(-100001);
	const auto width = saved.value("width").toInteger(0);
	const auto height = saved.value("height").toInteger(0);
	if (x < -100000 || x > 100000 || y < -100000 || y > 100000 ||
	    width < 1 || width > 16384 || height < 1 || height > 16384) return {};
	const auto w = std::clamp(int(width), (std::min)(160, available.width()), available.width());
	const auto h = std::clamp(int(height), (std::min)(90, available.height()), available.height());
	return {std::clamp(int(x), available.left(), available.right() - w + 1),
		std::clamp(int(y), available.top(), available.bottom() - h + 1), w, h};
}
} // namespace webobs::native_host
