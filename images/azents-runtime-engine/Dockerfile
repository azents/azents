FROM docker:29.8.2-dind@sha256:1e08cdb63405ca788aea94ef35b792d1e299607c667d33d7bcbcae1fd2611ced

LABEL io.azents.docker.api-version="1.56"
LABEL io.azents.docker.engine-version="29.8.1"
LABEL io.azents.runtime-engine.storage="ephemeral"

RUN addgroup -g 1000 azents-runner

ENTRYPOINT ["dockerd"]
