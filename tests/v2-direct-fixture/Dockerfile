FROM ubuntu:24.04@sha256:561618e2c15bf2397621dd04f96926663a3b5616c189cf7e38db7e82f5c538ea

RUN apt-get -o Acquire::Retries=5 update \
    && apt-get -o Acquire::Retries=5 install -y --no-install-recommends \
        ca-certificates ffmpeg libsodium23 python3 \
    && rm -rf /var/lib/apt/lists/*

COPY v2/client_control_service.py /fixture/client_control_service.py
COPY tests/v2-direct-fixture/probe.py /fixture/probe.py

ENTRYPOINT ["python3", "/fixture/probe.py"]
