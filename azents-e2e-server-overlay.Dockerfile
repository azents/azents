ARG BASE_IMAGE=azents-server:e2e-base-snapshot
FROM ${BASE_IMAGE}

ARG ROOT_DIR=/app

RUN rm -rf "${ROOT_DIR}/python/apps/azents"
COPY python/apps/azents/ "${ROOT_DIR}/python/apps/azents/"

WORKDIR "${ROOT_DIR}/python/apps/azents"
