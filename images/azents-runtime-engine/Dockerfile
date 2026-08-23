FROM docker:29.7.2-dind@sha256:12e683a161823b2a839aeea999b9d960e6e1f9a97b1679ad6b441982e2d9cf07

LABEL io.azents.docker.api-version="1.55"
LABEL io.azents.docker.engine-version="29.7.2"
LABEL io.azents.runtime-engine.storage="ephemeral"

RUN addgroup -g 1000 azents-runner

ENTRYPOINT ["dockerd"]
