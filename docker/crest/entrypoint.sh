#!/bin/sh
# Starts the CREST server; creates the self-signed dev certificate for port 443 on the first run.
set -e
certs=/srv/dust/dust_server/certs
if [ ! -f "$certs/server.crt" ]; then
    mkdir -p "$certs"
    openssl req -x509 -newkey rsa:2048 -nodes -keyout "$certs/server.key" -out "$certs/server.crt" \
        -days 3650 -subj /CN=crest.eveonline.com
fi
exec python -u listen_server.py --ports "$CREST_PORTS" "$@"
