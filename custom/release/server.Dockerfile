# Omnigent server image for a release of the patch series.
#
# Installs the release's own wheels (the same bytes hosts install, web UI
# bundled) with every dependency pinned by constraints.txt, which is exported
# from the build's uv.lock. Upstream's deploy/docker/Dockerfile resolves
# dependencies afresh with an editable install instead, so its image can pick
# up versions the lock never tested. The runtime matches upstream's `runtime`
# target: same entrypoint, port, artifact volume and health check.
#
# Build context: the folder release/build.sh writes (release/ and image/).
#   docker build -f image/server.Dockerfile --platform linux/amd64 .

ARG PYTHON_VERSION=3.12
ARG UV_VERSION=0.13.4

FROM ghcr.io/astral-sh/uv:${UV_VERSION} AS uv

FROM python:${PYTHON_VERSION}-slim AS builder
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_NO_CACHE=1 UV_PYTHON_DOWNLOADS=never
RUN --mount=type=bind,source=release,target=/release \
    uv venv /opt/venv \
 && uv pip install --python /opt/venv/bin/python --no-build \
      --constraint /release/constraints.txt --find-links /release \
      "omnigent[postgres] @ file://$(ls /release/omnigent-[0-9]*.whl)"

FROM python:${PYTHON_VERSION}-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:${PATH}"

# curl + ca-certificates only: the health check and outbound HTTPS.
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl ca-certificates \
 && rm -rf /var/lib/apt/lists/*

COPY --from=builder /opt/venv /opt/venv
COPY image/entrypoint.py /app/entrypoint.py

WORKDIR /app
RUN mkdir -p /data/artifacts

ENV PORT=8000 \
    HOST=0.0.0.0 \
    ARTIFACT_DIR=/data/artifacts

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS "http://127.0.0.1:${PORT}/health" || exit 1

CMD ["python", "/app/entrypoint.py"]
