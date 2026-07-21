FROM python:3.13-alpine

ARG BUILD_VERSION="0.1.0"
ARG BUILD_ARCH="unknown"

LABEL \
    io.hass.version="${BUILD_VERSION}" \
    io.hass.type="app" \
    io.hass.arch="${BUILD_ARCH}"

ENV PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apk add --no-cache ca-certificates

COPY requirements.txt ./
RUN python -m pip install --requirement requirements.txt

COPY ocpp_proxy ./ocpp_proxy
COPY run_addon.py ./

EXPOSE 9000

CMD ["python", "/app/run_addon.py"]

