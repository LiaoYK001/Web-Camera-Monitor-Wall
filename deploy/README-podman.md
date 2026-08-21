# Fedora + Podman deployment

This example targets a dedicated Fedora monitoring VM. It uses host networking so RTSP,
WebRTC and future ONVIF WS-Discovery can cross the intended VLANs without a large port map.
Only use host networking on a dedicated, firewalled host.

1. Install `podman`, `podman-compose`, `mesa-va-drivers`, `libva-utils` and the AMD firmware.
2. Create `/home/webobs/{webobs-config,assets,recordings,secrets}` as the deployment user.
3. Put the TLS certificate, private key and authentication values in the four files referenced
   by `compose.podman.example.yaml`; use mode `0600`. Never commit them.
4. Replace the documentation-only host names/address and pin the image to a release tag or,
   for strict production, `ghcr.io/...@sha256:<digest>`.
5. Confirm the render node before starting:

   ```bash
   vainfo --display drm --device /dev/dri/renderD128
   podman compose -f deploy/compose.podman.example.yaml config
   podman compose -f deploy/compose.podman.example.yaml up -d
   ```

SELinux volume labels use `:Z`. The application listens only on `127.0.0.1`; the bundled Caddy
process owns the external HTTPS port. The first browser visit shows an empty Camera Registry and
login page—no RTSP bootstrap value is required. Check `/api/v1/system/capabilities` after login;
`devicePresent` alone is not proof of VA-API readiness.
