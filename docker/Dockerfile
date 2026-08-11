FROM node:24.14.0-bookworm-slim@sha256:d8e448a56fc63242f70026718378bd4b00f8c82e78d20eefb199224a4d8e33d8 AS web-builder

WORKDIR /src/web
RUN corepack enable \
    && attempt=1 \
    && until corepack prepare pnpm@11.16.0 --activate; do \
        if [ "$attempt" -ge 5 ]; then exit 1; fi; \
        attempt=$((attempt + 1)); \
        sleep 5; \
    done
COPY web/package.json web/pnpm-lock.yaml ./
RUN pnpm config set fetch-retries 5 \
    && pnpm install --frozen-lockfile --ignore-scripts
COPY web/ ./
RUN pnpm run build

FROM ubuntu:24.04 AS mediamtx-downloader

ARG DEBIAN_FRONTEND=noninteractive
ARG MEDIAMTX_VERSION=1.18.2
ARG MEDIAMTX_LINUX_AMD64_SHA256=73ed27c292e05ceb4990dcb34531f01872dfff5374b7515c45a202e0abf47706
ARG TARGETARCH

RUN test "$TARGETARCH" = "amd64" \
    && apt-get -o Acquire::Retries=5 -o Acquire::http::Timeout=30 -o Acquire::https::Timeout=30 update \
    && apt-get -o Acquire::Retries=5 -o Acquire::http::Timeout=30 -o Acquire::https::Timeout=30 install -y --no-install-recommends \
        ca-certificates \
        curl \
    && rm -rf /var/lib/apt/lists/* \
    && archive="mediamtx_v${MEDIAMTX_VERSION}_linux_amd64.tar.gz" \
    && curl --fail --location --retry 5 --retry-all-errors \
        --output "/tmp/${archive}" \
        "https://github.com/bluenviron/mediamtx/releases/download/v${MEDIAMTX_VERSION}/${archive}" \
    && echo "${MEDIAMTX_LINUX_AMD64_SHA256}  /tmp/${archive}" | sha256sum --check \
    && mkdir -p /opt/mediamtx \
    && tar -xzf "/tmp/${archive}" -C /opt/mediamtx mediamtx LICENSE

FROM ubuntu:24.04 AS datachannel-builder

ARG DEBIAN_FRONTEND=noninteractive
ARG LIBDATACHANNEL_VERSION=0.21.0
ARG LIBDATACHANNEL_COMMIT=9d5c46b8f506943727104d766e5dad0693c5a223
ARG TARGETARCH

RUN test "$TARGETARCH" = "amd64" \
    && apt-get -o Acquire::Retries=5 -o Acquire::http::Timeout=30 -o Acquire::https::Timeout=30 update \
    && attempt=1 \
    && until apt-get -o Acquire::Retries=5 -o Acquire::http::Timeout=30 -o Acquire::https::Timeout=30 install -y --no-install-recommends \
        build-essential \
        ca-certificates \
        cmake \
        git \
        libssl-dev \
        ninja-build; do \
        if [ "$attempt" -ge 5 ]; then exit 1; fi; \
        attempt=$((attempt + 1)); \
        sleep 5; \
        apt-get -o Acquire::Retries=5 -o Acquire::http::Timeout=30 -o Acquire::https::Timeout=30 update; \
    done \
    && rm -rf /var/lib/apt/lists/*

RUN git init /src/libdatachannel \
    && git -C /src/libdatachannel remote add origin https://github.com/paullouisageneau/libdatachannel.git \
    && git -C /src/libdatachannel fetch --depth 1 origin "$LIBDATACHANNEL_COMMIT" \
    && git -C /src/libdatachannel checkout --detach FETCH_HEAD \
    && test "$(git -C /src/libdatachannel rev-parse HEAD)" = "$LIBDATACHANNEL_COMMIT"

RUN attempt=1 \
    && until git -C /src/libdatachannel submodule update --init --recursive --depth 1; do \
        if [ "$attempt" -ge 5 ]; then exit 1; fi; \
        attempt=$((attempt + 1)); \
        sleep 5; \
    done

RUN cmake -S /src/libdatachannel -B /build/libdatachannel -G Ninja \
        -DCMAKE_BUILD_TYPE=Release \
        -DCMAKE_INSTALL_PREFIX=/opt/obs \
        -DCMAKE_PREFIX_PATH=/opt/obs \
        -DCMAKE_POLICY_VERSION_MINIMUM=3.5 \
        -DBUILD_SHARED_LIBS=ON \
        -DUSE_MBEDTLS=OFF \
        -DNO_WEBSOCKET=ON \
        -DNO_TESTS=ON \
        -DNO_EXAMPLES=ON \
    && cmake --build /build/libdatachannel --parallel \
    && cmake --install /build/libdatachannel --strip \
    && mkdir -p /opt/obs/share/licenses/libdatachannel \
    && cp /src/libdatachannel/LICENSE /opt/obs/share/licenses/libdatachannel/LICENSE \
    && printf '%s\n' "$LIBDATACHANNEL_VERSION" > /opt/obs/share/libdatachannel-version

FROM ubuntu:24.04 AS obs-builder

ARG DEBIAN_FRONTEND=noninteractive
ARG OBS_VERSION=32.1.2
ARG TARGETARCH

RUN test "$TARGETARCH" = "amd64"

RUN apt-get -o Acquire::Retries=5 -o Acquire::http::Timeout=30 -o Acquire::https::Timeout=30 update \
    && apt-get -o Acquire::Retries=5 -o Acquire::http::Timeout=30 -o Acquire::https::Timeout=30 install -y --no-install-recommends \
        build-essential \
        ca-certificates \
        cmake \
        extra-cmake-modules \
        libavcodec-dev \
        libavdevice-dev \
        libavfilter-dev \
        libavformat-dev \
        libavutil-dev \
        libboost-dev \
        libcurl4-openssl-dev \
        libdrm-dev \
        libegl1-mesa-dev \
        libgl1-mesa-dev \
        libglvnd-dev \
        libjansson-dev \
        libmbedtls-dev \
        libpci-dev \
        libsimde-dev \
        libswresample-dev \
        libswscale-dev \
        libva-dev \
        libx11-dev \
        libx11-xcb-dev \
        libx264-dev \
        libxcb-composite0-dev \
        libxcb-randr0-dev \
        libxcb-shm0-dev \
        libxcb-xfixes0-dev \
        libxcb-xinerama0-dev \
        libxcb1-dev \
        libxinerama-dev \
        ninja-build \
        pkg-config \
        uthash-dev \
        uuid-dev \
        zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /src/obs
COPY obs/obs-studio/ ./
COPY --from=datachannel-builder /opt/obs /opt/obs

# OBS 32.1.2's Linux obs-ffmpeg VAAPI source still references its HEVC
# capability helper when ENABLE_HEVC=OFF. Keep the core type support enabled;
# M0 only builds/configures obs_x264 and never selects an HEVC encoder.
RUN cmake -S /src/obs -B /build/obs -G Ninja \
        -DCMAKE_BUILD_TYPE=Release \
        -DCMAKE_INSTALL_PREFIX=/opt/obs \
        -DCMAKE_INSTALL_LIBDIR=lib \
        -DCMAKE_PREFIX_PATH=/opt/obs \
        -DOBS_VERSION_OVERRIDE=${OBS_VERSION} \
        -DENABLE_UI=OFF \
        -DENABLE_FRONTEND=OFF \
        -DENABLE_SCRIPTING=OFF \
        -DENABLE_HEVC=ON \
        -DENABLE_BROWSER=OFF \
        -DENABLE_WEBSOCKET=OFF \
        -DENABLE_WEBRTC=ON \
        -DENABLE_AJA=OFF \
        -DENABLE_DECKLINK=OFF \
        -DENABLE_ALSA=OFF \
        -DENABLE_PIPEWIRE=OFF \
        -DENABLE_PULSEAUDIO=OFF \
        -DENABLE_WAYLAND=OFF \
        -DENABLE_V4L2=OFF \
        -DENABLE_NVENC=OFF \
        -DENABLE_QSV11=OFF \
        -DENABLE_VLC=OFF \
        -DENABLE_VST=OFF \
        -DENABLE_FREETYPE=OFF \
        -DENABLE_LIBFDK=OFF \
        -DENABLE_SPEEXDSP=OFF \
        -DENABLE_RNNOISE=OFF \
        -DENABLE_NEW_MPEGTS_OUTPUT=OFF \
    && cmake --build /build/obs --parallel --target \
        libobs \
        libobs-opengl \
        obs-ffmpeg \
        obs-x264 \
        obs-webrtc \
        obs-ffmpeg-mux \
    && cmake -E copy_directory /build/obs/rundir/Release /opt/obs \
    && ln -sf libobs-opengl.so.30 /opt/obs/lib/libobs-opengl.so

FROM obs-builder AS core-builder

WORKDIR /src/webobs
COPY CMakeLists.txt ./
COPY core/ ./core/

RUN cmake -S /src/webobs -B /build/webobs -G Ninja \
        -DCMAKE_BUILD_TYPE=Release \
        -DCMAKE_INSTALL_PREFIX=/opt/obs \
        -DWEBOBS_OBS_SOURCE_DIR=/src/obs \
        -DWEBOBS_OBS_BUILD_DIR=/build/obs \
        -DWEBOBS_OBS_PREFIX=/opt/obs \
        -DWEBOBS_BUILD_TESTS=ON \
    && cmake --build /build/webobs --parallel \
    && ctest --test-dir /build/webobs --output-on-failure \
    && cmake --install /build/webobs \
    && LD_LIBRARY_PATH=/opt/obs/lib /opt/obs/bin/webobsd --version \
    && ldd /opt/obs/bin/webobsd \
    && ldd /opt/obs/lib/libobs-opengl.so.30 \
    && ldd /opt/obs/lib/obs-plugins/obs-ffmpeg.so \
    && ldd /opt/obs/lib/obs-plugins/obs-x264.so \
    && ldd /opt/obs/lib/obs-plugins/obs-webrtc.so \
    && ldd /opt/obs/lib/libdatachannel.so

FROM ubuntu:24.04 AS runtime

ARG DEBIAN_FRONTEND=noninteractive

RUN apt-get -o Acquire::Retries=5 -o Acquire::http::Timeout=30 -o Acquire::https::Timeout=30 update \
    && apt-get -o Acquire::Retries=5 -o Acquire::http::Timeout=30 -o Acquire::https::Timeout=30 install -y --no-install-recommends \
        ca-certificates \
        ffmpeg \
        libcurl4t64 \
        libdrm2 \
        libegl1 \
        libegl-mesa0 \
        libgl1-mesa-dri \
        libjansson4 \
        libpci3 \
        libuuid1 \
        libva2 \
        libx11-6 \
        libx11-xcb1 \
        libx264-164 \
        libxcb-composite0 \
        libxcb-randr0 \
        libxcb-shm0 \
        libxcb-xfixes0 \
        libxcb-xinerama0 \
        libxcb1 \
        libxinerama1 \
        tini \
        x11-utils \
        xvfb \
    && rm -rf /var/lib/apt/lists/*

COPY --from=core-builder /opt/obs /opt/obs
COPY --from=web-builder /src/web/dist /opt/webobs/ui
COPY --from=mediamtx-downloader /opt/mediamtx/mediamtx /opt/webobs/bin/mediamtx
COPY --from=mediamtx-downloader /opt/mediamtx/LICENSE /usr/share/licenses/mediamtx/LICENSE
COPY docker/entrypoint.sh /opt/webobs/entrypoint.sh
COPY gateway/mediamtx.yml /opt/webobs/etc/mediamtx.yml
COPY LICENSE /usr/share/licenses/webobs/LICENSE
COPY obs/obs-studio/COPYING /usr/share/licenses/webobs/OBS-COPYING

ENV LD_LIBRARY_PATH=/opt/obs/lib \
    DISPLAY=:99 \
    EGL_PLATFORM=x11 \
    LIBGL_ALWAYS_SOFTWARE=1 \
    GALLIUM_DRIVER=llvmpipe

RUN mkdir -p /config/obs /config/webobs /recordings \
    && chmod 0700 /config/webobs \
    && chmod 0755 /opt/webobs/entrypoint.sh /opt/webobs/bin/mediamtx \
    && /opt/webobs/bin/mediamtx --version \
    && LD_LIBRARY_PATH=/opt/obs/lib /opt/obs/bin/webobsd --version \
    && ldd /opt/obs/bin/webobsd > /tmp/webobs-ldd.txt \
    && ldd /opt/obs/lib/libobs-opengl.so.30 >> /tmp/webobs-ldd.txt \
    && ldd /opt/obs/lib/obs-plugins/obs-ffmpeg.so >> /tmp/webobs-ldd.txt \
    && ldd /opt/obs/lib/obs-plugins/obs-x264.so >> /tmp/webobs-ldd.txt \
    && ldd /opt/obs/lib/obs-plugins/obs-webrtc.so >> /tmp/webobs-ldd.txt \
    && ldd /opt/obs/lib/libdatachannel.so >> /tmp/webobs-ldd.txt \
    && ldd /opt/obs/bin/obs-ffmpeg-mux >> /tmp/webobs-ldd.txt \
    && if grep "not found" /tmp/webobs-ldd.txt; then exit 1; fi \
    && rm /tmp/webobs-ldd.txt

WORKDIR /opt/obs
VOLUME ["/config/webobs", "/recordings"]
EXPOSE 8080 8189/udp

LABEL org.opencontainers.image.title="Web Camera Monitor Wall" \
      org.opencontainers.image.description="Headless libobs multi-source monitor wall and local control plane" \
      org.opencontainers.image.licenses="GPL-2.0-or-later" \
      org.opencontainers.image.source="https://github.com/LiaoYK001/Web-Camera-Monitor-Wall" \
      org.opencontainers.image.version="0.1.0"

ENTRYPOINT ["/usr/bin/tini", "--", "/opt/webobs/entrypoint.sh"]
