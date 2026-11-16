#include "layout.hpp"
#include <cassert>
#include <cstdint>
#include <iostream>
#include <limits>
using namespace webobs::native_host;

int main()
{
	for (const auto dimensions : {std::array<std::uint32_t, 2>{1920, 1080}, {1921, 1081}, {17, 19},
		{std::numeric_limits<std::uint32_t>::max(), std::numeric_limits<std::uint32_t>::max()}}) {
		const auto [width, height] = dimensions;
		for (std::uint32_t count = 1; count <= maximum_quick_wall_slots; ++count) {
			const auto tiles = quick_wall_layout(width, height, count);
			assert(tiles.size() == count);
			std::uint64_t area = 0;
			for (std::size_t i = 0; i < tiles.size(); ++i) {
				const auto a = tiles[i];
				assert(a.width && a.height);
				assert(std::uint64_t(a.x) + a.width <= width && std::uint64_t(a.y) + a.height <= height);
				area += std::uint64_t(a.width) * a.height;
				for (std::size_t j = 0; j < i; ++j) {
					const auto b = tiles[j];
					assert(std::uint64_t(a.x) + a.width <= b.x || std::uint64_t(b.x) + b.width <= a.x ||
						std::uint64_t(a.y) + a.height <= b.y || std::uint64_t(b.y) + b.height <= a.y);
				}
			}
			assert(area <= std::uint64_t(width) * height);
			for (std::uint32_t side = 1; side <= 8; ++side)
				if (side * side == count) assert(area == std::uint64_t(width) * height);
		}
		const auto old = five_tile_layout(width, height);
		const auto current = quick_wall_layout(width, height, 5);
		for (std::size_t i = 0; i < old.size(); ++i)
			assert(old[i].x == current[i].x && old[i].y == current[i].y &&
				old[i].width == current[i].width && old[i].height == current[i].height);
	}
	assert(quick_wall_layout(1, 1, 1).front().width == 1);
	assert(quick_wall_layout(0, 1080, 5).empty());
	assert(quick_wall_layout(1920, 0, 5).empty());
	assert(quick_wall_layout(1920, 1080, 0).empty());
	assert(quick_wall_layout(1920, 1080, 65).empty());
	assert(quick_wall_layout(1, 1, 64).empty());
	std::cout << "PASS 1-64 layouts, odd/full-uint32 bounds, no overlap, full-square coverage, five-slot compatibility\n";
}
