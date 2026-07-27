FROM docker:28.5.2-dind@sha256:2a232a42256f70d78e3cc5d2b5d6b3276710a0de0596c145f627ecfae90282ac

LABEL io.azents.docker.api-version="1.51"
LABEL io.azents.docker.engine-version="28.5.2"
LABEL io.azents.runtime-engine.storage="ephemeral"

RUN addgroup -g 1000 azents-runner

ENTRYPOINT ["dockerd"]
