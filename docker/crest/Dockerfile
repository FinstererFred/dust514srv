# CREST server (dust_server/, Python 3). Only the runtime: the repository is mounted at /srv/dust, so
# dust_server/fake_battle.json and dev_commands.json stay editable and logs land in dust_server/logs/.
FROM python:3.13-slim

RUN apt-get update && apt-get install -y --no-install-recommends openssl \
    && rm -rf /var/lib/apt/lists/*

COPY docker/crest/entrypoint.sh /usr/local/bin/dust-crest
RUN chmod +x /usr/local/bin/dust-crest

ENV CREST_PORTS=80,443,8080
WORKDIR /srv/dust/dust_server
ENTRYPOINT ["/usr/local/bin/dust-crest"]
