# Chromium IWA RTSP/TCP experiment

This directory is deliberately outside the production Vite build. It is not precached, bundled into the OCI image as an IWA, signed, or released as `.swbn`.

The worker accepts one already-verified synthetic-lab Grant host/port, opens one Direct Socket, performs unauthenticated RTSP interleaved TCP, depacketizes H.264 single NAL/STAP-A/FU-A RTP and transfers decoded `VideoFrame` objects to the IWA UI. `lab-runtime.ts` owns one worker and renders each frame into a local Canvas while closing superseded frames. The embedding IWA must verify the signed Grant before calling the bridge; equality checks inside the worker are defense in depth, not Grant verification.

Production camera credentials, redirects, UDP, audio, H.265, multicast and arbitrary destinations are intentionally unsupported. Use Chrome IWA Dev Mode Proxy only.
