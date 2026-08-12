FROM ubuntu:24.04

ARG DEBIAN_FRONTEND=noninteractive
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*
RUN apt-get -o Acquire::Retries=5 -o Acquire::http::Timeout=30 -o Acquire::https::Timeout=30 update \
    && apt-get -o Acquire::Retries=5 -o Acquire::http::Timeout=30 -o Acquire::https::Timeout=30 install -y --no-install-recommends curl jq \
    && rm -rf /var/lib/apt/lists/*

COPY tests/rtsp-fixture/publish.sh /usr/local/bin/publish-test-stream
COPY tests/rtsp-fixture/publish-hevc.sh /usr/local/bin/publish-hevc-stream
COPY tests/rtsp-fixture/probe.sh /usr/local/bin/probe-recording
COPY tests/rtsp-fixture/m1-real-control.sh /usr/local/bin/run-m1-real-control
RUN chmod 0755 \
        /usr/local/bin/publish-test-stream \
        /usr/local/bin/publish-hevc-stream \
        /usr/local/bin/probe-recording \
        /usr/local/bin/run-m1-real-control
