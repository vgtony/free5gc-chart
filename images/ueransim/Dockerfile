# syntax=docker/dockerfile:1
FROM ubuntu:24.04 AS builder

ARG UERANSIM_VERSION=v3.3.0
ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       build-essential ca-certificates cmake git libsctp-dev \
    && git clone --branch "${UERANSIM_VERSION}" --depth 1 \
       https://github.com/aligungr/UERANSIM.git /src/ueransim \
    && cmake -S /src/ueransim -B /src/ueransim/build-release \
       -DCMAKE_BUILD_TYPE=Release \
    && cmake --build /src/ueransim/build-release --parallel "$(nproc)"

FROM ubuntu:24.04

ARG UERANSIM_VERSION=v3.3.0
LABEL org.opencontainers.image.source="https://github.com/aligungr/UERANSIM" \
      org.opencontainers.image.version="${UERANSIM_VERSION}"

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       ca-certificates curl iproute2 iputils-ping libsctp1 lksctp-tools mawk \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /ueransim/build /ueransim/config

COPY --from=builder /src/ueransim/build-release/nr-gnb /ueransim/build/nr-gnb
COPY --from=builder /src/ueransim/build-release/nr-ue /ueransim/build/nr-ue
COPY --from=builder /src/ueransim/build-release/nr-cli /ueransim/build/nr-cli
COPY --from=builder /src/ueransim/LICENSE /licenses/UERANSIM-LICENSE

WORKDIR /ueransim
