# syntax=docker/dockerfile:1

FROM docker:29-cli AS dockercli

FROM python:3.14-slim

RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

COPY --from=dockercli /usr/local/bin/docker /usr/local/bin/docker
COPY --from=dockercli /usr/local/libexec/docker/cli-plugins /usr/local/libexec/docker/cli-plugins

WORKDIR /app
COPY pyproject.toml ./
COPY openbench ./openbench
RUN pip install --no-cache-dir .

ENTRYPOINT ["openbench"]
