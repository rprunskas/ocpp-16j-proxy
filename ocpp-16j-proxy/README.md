# OCPP 1.6J Proxy

Transparent OCPP 1.6J WebSocket proxy for Home Assistant OS.

- Accepts chargers on host TCP port `9000` by default.
- Proxies them to `wss://ocpp.circlelink.app` by default.
- Preserves the charger identity from the WebSocket URL path.
- Requires the `ocpp1.6` subprotocol on both connections.
- Logs correlated OCPP requests, results, errors, and latency as JSON.
- Forwards charger authorization or accepts a fixed upstream authorization
  value.

See the **Documentation** tab after installation for configuration details.

