#!/bin/sh
# First start: default configs and a self-signed certificate (RPCS3 does not check it) into the volume.
set -e
for f in /opt/rpcn/defaults/*.cfg; do
    [ -e "$(basename "$f")" ] || cp "$f" .
done
[ -e cert.pem ] && [ -e key.pem ] || /opt/rpcn/rpcn --cert-gen
exec /opt/rpcn/rpcn
