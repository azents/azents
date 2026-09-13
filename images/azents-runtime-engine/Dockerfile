FROM docker:29.8.0-dind@sha256:5efed980cba3fc126cf54e21a5a6ff8849d05b6e0623d6e7612f48e9cd6cd17e

LABEL io.azents.docker.api-version="1.55"
LABEL io.azents.docker.engine-version="29.7.2"
LABEL io.azents.runtime-engine.storage="ephemeral"

RUN addgroup -g 1000 azents-runner

ENTRYPOINT ["dockerd"]
