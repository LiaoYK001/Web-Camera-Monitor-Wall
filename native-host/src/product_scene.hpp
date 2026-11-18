#pragma once

#include "product_media.hpp"
#include "webobs/scene_document.hpp"
#include <memory>
#include <vector>

namespace webobs::native_host {
struct ProductSceneSource;
class ProductSceneGraph;
struct ProductVideoProgress {
	std::string uuid;
	bool available = false;
	std::int64_t serial = 0; // Opaque delivered-video callback serial, never a rendering/hardware claim.
};
struct ProductAudioProgress {
	std::string source_id;
	bool available = false;
	float peak_dbfs = -120.0f;
};

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
	// Owned audio-mix source UUIDs, one per source with explicit nonempty audio.
	std::vector<std::string> audio_uuids;
	ProductSceneGraph() = default;
	ProductSceneGraph(const ProductSceneGraph &) = delete;
	ProductSceneGraph &operator=(const ProductSceneGraph &) = delete;
	~ProductSceneGraph();
	std::vector<ProductVideoProgress> video_progress() const;
	std::vector<ProductAudioProgress> audio_progress() const;
	friend std::unique_ptr<ProductSceneGraph> create_product_scene(
		ProductSourcePool &, const std::string &, const SceneDocument &,
		const std::vector<ProductCamera> &, std::string &);
};

// Resolved bindings must come from the authenticated product authority. Every
// document source is checked against its exact binding before any source I/O.
// No authorization is granted by this renderer. Unsupported business-source
// kinds and assets fail explicitly until their resolvers are wired. Explicit
// empty audioInputs keep video but silence audio. In the product build,
// nonempty audioInputs use a bounded audio-only FFmpeg mixer feeding one owned
// OBS source; the video source remains the direct RTSP source.
std::unique_ptr<ProductSceneGraph> create_product_scene(ProductSourcePool &pool,
	const std::string &owner, const SceneDocument &document,
	const std::vector<ProductCamera> &bindings, std::string &error);
} // namespace webobs::native_host
