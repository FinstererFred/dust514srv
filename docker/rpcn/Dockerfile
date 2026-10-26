# RPCN (RPCS3's PSN replacement) for the battle host: the host signs in here, players keep their own RPCN
# (e.g. the official np.rpcs3.net), the game connection does not go through RPCN.
# Build context is the repository root:  docker build -f docker/rpcn/Dockerfile -t dust514-rpcn .

FROM rust:1.91-bookworm AS build

# The version of research/rpcn/rpcn.exe that our local tests used
ARG RPCN_COMMIT=7a3c3c480d54d7b51a7a231655c778821097ee4e

RUN apt-get update && apt-get install -y --no-install-recommends protobuf-compiler \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /src/rpcn
RUN git init -q . \
    && git remote add origin https://github.com/RipleyTom/rpcn.git \
    && git fetch -q --depth 1 origin "${RPCN_COMMIT}" \
    && git checkout -q FETCH_HEAD \
    && cargo build --release \
    && mkdir -p /opt/rpcn/defaults \
    && cp target/release/rpcn /opt/rpcn/ \
    && cp servers.cfg server_redirs.cfg scoreboards.cfg /opt/rpcn/defaults/


FROM debian:bookworm-slim

COPY --from=build /opt/rpcn /opt/rpcn
COPY docker/rpcn/rpcn.cfg /opt/rpcn/defaults/rpcn.cfg
COPY docker/rpcn/entrypoint.sh /usr/local/bin/dust-rpcn
RUN chmod +x /usr/local/bin/dust-rpcn

# RPCN reads its config, certificate and database from the working directory
WORKDIR /data
VOLUME /data
ENTRYPOINT ["/usr/local/bin/dust-rpcn"]
