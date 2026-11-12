#pragma once

#include "product_media.hpp"
#include "webobs/scene_document.hpp"
#include <memory>
#include <vector>

namespace webobs::native_host {
struct ProductSceneSource;
class ProductSceneGraph;

// Main-thread only. Entries are owned by graphs, never by a global OBS name.
// The immutable account boundary is retained until all old graphs are gone.
class ProductSourcePool {
	std::string owner_;
	std::vector<std::weak_ptr<ProductSceneSource>> entries_;
	std::shared_ptr<ProductSceneSource> acquire(const std::string &owner, const SceneSource &configuration,
		const ProductCamera &camera, std::string &error);
	friend std::unique_ptr<ProductSceneGraph> create_product_scene(
		ProductSourcePool &, const std::string &, const SceneDocument &,
		const std::vector<ProductCamera> &, std::string &);
public:
	ProductSourcePool() = default;
	ProductSourcePool(const ProductSourcePool &) = delete;
	ProductSourcePool &operator=(const ProductSourcePool &) = delete;
};

class ProductSceneGraph {
	std::vector<std::shared_ptr<ProductSceneSource>> sources_;
public:
	obs_scene_t *scene = nullptr;
	// One UUID per document source, in document order; repeats are deliberate.
	std::vector<std::string> uuids;
	ProductSceneGraph() = default;
	ProductSceneGraph(const ProductSceneGraph &) = delete;
	ProductSceneGraph &operator=(const ProductSceneGraph &) = delete;
	~ProductSceneGraph();
	friend std::unique_ptr<ProductSceneGraph> create_product_scene(
		ProductSourcePool &, const std::string &, const SceneDocument &,
		const std::vector<ProductCamera> &, std::string &);
};

// Resolved bindings must come from the authenticated product authority. Every
// document source is checked against its exact binding before any source I/O.
// No authorization is granted by this renderer. Unsupported business-source
// kinds/audio routing/assets fail explicitly until their resolvers are wired.
std::unique_ptr<ProductSceneGraph> create_product_scene(ProductSourcePool &pool,
	const std::string &owner, const SceneDocument &document,
	const std::vector<ProductCamera> &bindings, std::string &error);
} // namespace webobs::native_host
