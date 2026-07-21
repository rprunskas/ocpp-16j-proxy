# OCPP 1.6J Proxy configuration

The app listens on `0.0.0.0:9000` inside its container. Home Assistant maps
that listener to host port `9000` by default; the host port can be changed in
the app's **Network** section.

## Basic setup

The default central-system URL is:

```text
wss://ocpp.circlelink.app
```

With the defaults, configure a charger to connect to the Home Assistant host's
LAN IP and include its charger ID in the path:

```text
ws://192.168.0.26:9000/CP-001
```

This connection is proxied to:

```text
wss://ocpp.circlelink.app/CP-001
```

Replace the example IP and charger ID with the real values. The charger must
offer the `ocpp1.6` WebSocket subprotocol.

## Authentication

`forward_authorization` forwards the charger's incoming `Authorization` header
to the central system. If `upstream_authorization` is set, its value replaces
the incoming header. Do not include credentials directly in the URL unless the
central system explicitly requires that format.

## Logs

Open the app's **Logs** tab. Every OCPP CALL, CALLRESULT, and CALLERROR is logged
as JSON. Responses contain the correlated action and latency when their unique
ID matches a request seen on the same connection.

