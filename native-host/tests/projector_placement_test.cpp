#include "projector_placement.hpp"
#include <iostream>
#include <stdexcept>

using namespace webobs::native_host;
void require(bool value) { if (!value) throw std::runtime_error("projector placement constraint failed"); }
int main()
{
	const QJsonObject saved{{"x", -2800}, {"y", 180}, {"width", 1280}, {"height", 720}};
	const QRect second(-3200, 0, 1920, 1080), primary(0, 0, 1366, 728);
	require(projector_window_rect(saved, second) == QRect(-2800, 180, 1280, 720));
	const auto moved = projector_window_rect(saved, primary);
	require(primary.contains(moved) && moved.width() == 1280 && moved.x() == 0);
	require(projector_window_rect(saved, QRect(50, 50, 120, 60)) == QRect(50, 50, 120, 60));
	require(projector_window_rect({}, primary).isEmpty());
	auto malformed = saved;
	malformed["width"] = 1000000000;
	require(projector_window_rect(malformed, primary).isEmpty());
	malformed["width"] = 1280;
	malformed["x"] = "not-a-coordinate";
	require(projector_window_rect(malformed, primary).isEmpty());
	require(projector_window_rect(saved, {}).isEmpty());
	std::cout << "PASS logical-coordinate restore, removed display fallback and bounded saved geometry\n";
}
