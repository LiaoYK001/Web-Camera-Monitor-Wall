FROM ubuntu:24.04 AS downloader

ARG DEBIAN_FRONTEND=noninteractive
ARG MEDIAMTX_VERSION=1.18.2
ARG MEDIAMTX_LINUX_AMD64_SHA256=73ed27c292e05ceb4990dcb34531f01872dfff5374b7515c45a202e0abf47706
ARG TARGETARCH

RUN test "$TARGETARCH" = "amd64" \
    && apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl \
    && rm -rf /var/lib/apt/lists/* \
    && archive="mediamtx_v${MEDIAMTX_VERSION}_linux_amd64.tar.gz" \
    && curl --fail --location --retry 3 --retry-all-errors \
        --output "/tmp/${archive}" \
        "https://github.com/bluenviron/mediamtx/releases/download/v${MEDIAMTX_VERSION}/${archive}" \
    && echo "${MEDIAMTX_LINUX_AMD64_SHA256}  /tmp/${archive}" | sha256sum --check \
    && mkdir /opt/mediamtx \
    && tar -xzf "/tmp/${archive}" -C /opt/mediamtx

FROM ubuntu:24.04

COPY --from=downloader /opt/mediamtx/mediamtx /usr/local/bin/mediamtx
COPY --from=downloader /opt/mediamtx/mediamtx.yml /etc/mediamtx.yml
COPY --from=downloader /opt/mediamtx/LICENSE /usr/share/licenses/mediamtx/LICENSE

ENTRYPOINT ["/usr/local/bin/mediamtx", "/etc/mediamtx.yml"]
