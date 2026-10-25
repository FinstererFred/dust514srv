# Offline service (catma_service/, Python 2.7): runs CCP's offline CREST handlers from the client's own
# Python modules with the real CATMA database. Neither is in the image or the repository; both are
# mounted (DUST_EXTRACTED = unpacked PYTHON.SDAT/COMMON.SDAT, DUST_VAULT = the game's VAULT folder).
FROM python:2.7-slim

ENV DUST_EXTRACTED=/data/extracted \
    DUST_VAULT=/data/vault \
    PYTHONUNBUFFERED=1
WORKDIR /srv/dust/catma_service
# -O so the original .pyo files are used
ENTRYPOINT ["python", "-O", "offline_service.py"]
