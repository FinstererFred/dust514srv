# Battle host: RPCS3 built from source with our patches (rpcs3_patches/), run headless with the Null renderer.
# Build context is the repository root:  docker build -f docker/host/Dockerfile -t dust514-host .
# No game files, firmware or accounts in the image; those come from the data volume (see docker/README.md).

FROM ubuntu:26.04 AS build

# RPCS3 master of 2026-10-29 (v0.0.43-20416), the last commit before the RSX core rework removed GSRender.cpp, which our
# null-renderer patch targets. Master since 2026-10-31 (fab15ea, suspected) hangs DUST 514 at its first flip with every
# renderer ("RSX queue appears to be stuck"), see NOTES.md
ARG RPCS3_COMMIT=b19cedaaff84abc12afc6a27b58a16d370d55156
ARG BUILD_JOBS=0

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential cmake ninja-build git ca-certificates python3 pkg-config \
        llvm-dev clang \
        qt6-base-dev qt6-base-private-dev qt6-multimedia-dev qt6-svg-dev libxkbcommon-dev libxkbcommon-x11-dev libx11-dev \
        libasound2-dev libpulse-dev libopenal-dev libglew-dev libgl-dev libegl-dev \
        zlib1g-dev libzstd-dev libedit-dev libudev-dev libcurl4-openssl-dev \
        libavcodec-dev libavformat-dev libavutil-dev libswscale-dev libswresample-dev \
    # Ubuntu's LLVM CMake package references Polly, which lives in a version-specific package
    && llvm_ver=$(apt-cache depends llvm-dev | grep -oP 'llvm-\K[0-9]+(?=-dev)' | head -n1) \
    && apt-get install -y --no-install-recommends "libpolly-${llvm_ver}-dev" \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /src/rpcs3
RUN git init -q . \
    && git remote add origin https://github.com/RPCS3/rpcs3.git \
    && git fetch -q --depth 1 origin "${RPCS3_COMMIT}" \
    && git checkout -q FETCH_HEAD \
    # LLVM comes from the distribution (BUILD_LLVM=OFF); its submodule alone is several GB
    && git -c submodule."3rdparty/llvm/llvm".update=none submodule update -q --init --recursive --depth 1 --jobs 8

# Only the source patches; the game patches (*.yml) live in the data volume and must not trigger a rebuild
COPY rpcs3_patches/*.patch /src/patches/
RUN for p in /src/patches/*.patch; do git apply --verbose "$p"; done

# Null renderer only: no Vulkan, no audio or input backends a battle host never uses
RUN cmake -S . -B build -G Ninja \
        -DCMAKE_BUILD_TYPE=Release \
        -DCMAKE_INSTALL_PREFIX=/opt/rpcs3 \
        -DUSE_NATIVE_INSTRUCTIONS=OFF \
        -DUSE_LTO=OFF \
        -DBUILD_LLVM=OFF \
        -DUSE_VULKAN=OFF \
        -DUSE_FAUDIO=OFF \
        -DUSE_SDL=OFF \
        -DUSE_LIBEVDEV=OFF \
        -DUSE_GAMEMODE=OFF \
        -DUSE_DISCORD_RPC=OFF \
        -DUSE_SYSTEM_FFMPEG=ON \
    && cmake --build build $( [ "${BUILD_JOBS}" -gt 0 ] && echo "-j ${BUILD_JOBS}" ) \
    && cmake --install build

# Runtime packages = the packages that own the shared libraries rpcs3 links against
RUN ldd /opt/rpcs3/bin/rpcs3 | awk '/=> \//{print $3}' | xargs -r -n1 realpath \
        | xargs -r dpkg -S 2>/dev/null | cut -d: -f1 | sort -u > /opt/rpcs3/runtime-packages.txt \
    && cat /opt/rpcs3/runtime-packages.txt


FROM ubuntu:26.04

ENV DEBIAN_FRONTEND=noninteractive
COPY --from=build /opt/rpcs3 /opt/rpcs3
RUN apt-get update \
    && xargs -a /opt/rpcs3/runtime-packages.txt apt-get install -y --no-install-recommends \
    && apt-get install -y --no-install-recommends python3 ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# RPCS3 keeps config, dev_hdd0, dev_flash and patches under $XDG_CONFIG_HOME/rpcs3 and its log and
# PPU/SPU caches under $XDG_CACHE_HOME/rpcs3; both live on the /data volume
ENV XDG_CONFIG_HOME=/data/config \
    XDG_CACHE_HOME=/data/cache \
    QT_QPA_PLATFORM=offscreen \
    PATH=/opt/rpcs3/bin:$PATH

COPY docker/host/watchdog.py /usr/local/bin/dust-host-watchdog
RUN chmod +x /usr/local/bin/dust-host-watchdog

VOLUME /data
ENTRYPOINT ["/usr/local/bin/dust-host-watchdog"]
