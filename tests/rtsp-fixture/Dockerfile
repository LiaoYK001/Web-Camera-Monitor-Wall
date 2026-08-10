FROM ubuntu:24.04

ARG DEBIAN_FRONTEND=noninteractive
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY tests/rtsp-fixture/publish.sh /usr/local/bin/publish-test-stream
COPY tests/rtsp-fixture/probe.sh /usr/local/bin/probe-recording
RUN chmod 0755 /usr/local/bin/publish-test-stream /usr/local/bin/probe-recording
