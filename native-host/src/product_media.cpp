#include "product_media.hpp"
#include <cstring>
namespace webobs::native_host {
namespace {
bool starts_with(const std::string &value, const char *prefix)
{
	return value.compare(0, std::strlen(prefix), prefix) == 0;
}

} // namespace
bool valid_product_camera(const ProductCamera &camera, std::string &error)
{
	if (camera.id.empty() || camera.id.size() > 64)
		return error = "camera-id-invalid", false;
	for (const char c : camera.id)
		if (!((c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9') || c == '-' ||
		      c == '_' || c == '.'))
			return error = "camera-id-invalid", false;
	if (camera.name.empty() || camera.name.size() > 128 || camera.name.find_first_of("\r\n") != std::string::npos)
		return error = "camera-name-invalid", false;
	if (camera.profile_id.empty() || camera.profile_id.size() > 64)
		return error = "camera-profile-invalid", false;
	for (const char c : camera.profile_id)
		if (!((c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9') || c == '-' ||
		      c == '_' || c == '.'))
			return error = "camera-profile-invalid", false;
	if (camera.url.empty() || camera.url.size() > 2048 || camera.url.find_first_of("\r\n") != std::string::npos ||
	    camera.url.find('\0') != std::string::npos)
		return error = "camera-url-invalid", false;
	if (!starts_with(camera.url, "rtsp://") && !starts_with(camera.url, "rtsps://") &&
	    !starts_with(camera.url, "http://") && !starts_with(camera.url, "https://"))
		return error = "camera-url-invalid", false;
	if (camera.transport != "auto" && camera.transport != "tcp" && camera.transport != "udp" &&
	    camera.transport != "udp_multicast")
		return error = "camera-transport-invalid", false;
	return true;
}

obs_source_t *create_product_camera_source(const ProductCamera &camera, bool close_when_inactive,
	bool restart_when_active)
{
	auto *settings = obs_data_create();
	obs_data_set_bool(settings, "is_local_file", false);
	obs_data_set_string(settings, "input", camera.url.c_str());
	if (camera.transport != "auto")
		obs_data_set_string(settings, "ffmpeg_options", ("rtsp_transport=" + camera.transport).c_str());
	obs_data_set_bool(settings, "looping", false);
	obs_data_set_bool(settings, "hw_decode", camera.hardware_decode.value_or(true));
	obs_data_set_bool(settings, "restart_on_activate", restart_when_active);
	obs_data_set_bool(settings, "close_when_inactive", close_when_inactive);
	obs_data_set_int(settings, "reconnect_delay_sec", 10);
	obs_data_set_int(settings, "buffering_mb", 2);
	auto *source = obs_source_create("ffmpeg_source", camera.name.c_str(), settings, nullptr);
	obs_data_release(settings);
	return source;
}

} // namespace webobs::native_host
