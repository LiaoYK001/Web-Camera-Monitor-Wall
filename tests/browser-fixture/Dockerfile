FROM ubuntu:24.04

ARG DEBIAN_FRONTEND=noninteractive
RUN apt-get -o Acquire::Retries=5 update \
    && apt-get -o Acquire::Retries=5 install -y --no-install-recommends python3 \
    && rm -rf /var/lib/apt/lists/*

COPY tests/browser-fixture/index.html /srv/browser-fixture/index.html

USER 65534:65534
EXPOSE 8080
ENTRYPOINT ["python3", "-m", "http.server", "8080", "--bind", "0.0.0.0", "--directory", "/srv/browser-fixture"]
