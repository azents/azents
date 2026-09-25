FROM docker:29.8.1-dind@sha256:3f3c01aaaebf7cce837356b688b7c059a4749f10bd7660dec7c58fc454a283f0

LABEL io.azents.docker.api-version="1.56"
LABEL io.azents.docker.engine-version="29.8.0"
LABEL io.azents.runtime-engine.storage="ephemeral"

RUN addgroup -g 1000 azents-runner

ENTRYPOINT ["dockerd"]
