// Product-owned integration; upstream OBS remains unmodified.
#pragma once

#include <array>
#include <cstdint>

namespace webobs::native_host {
struct Tile {
	std::uint32_t x, y, width, height;
};

// Integer boundaries cover an odd-sized canvas without cumulative rounding.
// The sixth cell is deliberately empty; no pixels are stretched across cells.
inline std::array<Tile, 5> five_tile_layout(std::uint32_t width, std::uint32_t height)
{
	std::array<Tile, 5> result{};
	for (std::uint32_t i = 0; i < result.size(); ++i) {
		const auto col = i % 3;
		const auto row = i / 3;
		const auto x = static_cast<std::uint32_t>(std::uint64_t(width) * col / 3);
		const auto right = static_cast<std::uint32_t>(std::uint64_t(width) * (col + 1) / 3);
		const auto y = static_cast<std::uint32_t>(std::uint64_t(height) * row / 2);
		const auto bottom = static_cast<std::uint32_t>(std::uint64_t(height) * (row + 1) / 2);
		result[i] = {x, y, right - x, bottom - y};
	}
	return result;
}
} // namespace webobs::native_host
