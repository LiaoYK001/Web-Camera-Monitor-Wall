// Product-owned integration; upstream OBS remains unmodified.
#pragma once

#include <array>
#include <cstdint>
#include <vector>

namespace webobs::native_host {
struct Tile {
	std::uint32_t x, y, width, height;
};

inline constexpr std::uint32_t maximum_quick_wall_slots = 64;

inline Tile grid_tile(std::uint32_t width, std::uint32_t height, std::uint32_t index,
	std::uint32_t columns, std::uint32_t rows)
{
	const auto col = index % columns, row = index / columns;
	const auto x = static_cast<std::uint32_t>(std::uint64_t(width) * col / columns);
	const auto right = static_cast<std::uint32_t>(std::uint64_t(width) * (col + 1) / columns);
	const auto y = static_cast<std::uint32_t>(std::uint64_t(height) * row / rows);
	const auto bottom = static_cast<std::uint32_t>(std::uint64_t(height) * (row + 1) / rows);
	return {x, y, right - x, bottom - y};
}

// A bounded quick-wall grid. Reject canvases too small to give every cell
// positive dimensions; callers must never create zero-sized scene items.
inline std::vector<Tile> quick_wall_layout(std::uint32_t width, std::uint32_t height, std::uint32_t count)
{
	if (!count || count > maximum_quick_wall_slots) return {};
	std::uint32_t columns = 1;
	while (columns * columns < count) ++columns;
	const auto rows = (count + columns - 1) / columns;
	if (width < columns || height < rows) return {};
	std::vector<Tile> result;
	result.reserve(count);
	for (std::uint32_t i = 0; i < count; ++i)
		result.push_back(grid_tile(width, height, i, columns, rows));
	return result;
}

// Integer boundaries cover an odd-sized canvas without cumulative rounding.
// The sixth cell is deliberately empty; no pixels are stretched across cells.
inline std::array<Tile, 5> five_tile_layout(std::uint32_t width, std::uint32_t height)
{
	std::array<Tile, 5> result{};
	for (std::uint32_t i = 0; i < result.size(); ++i) {
		result[i] = grid_tile(width, height, i, 3, 2);
	}
	return result;
}
} // namespace webobs::native_host
