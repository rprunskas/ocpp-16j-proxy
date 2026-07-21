# OCPP 1.6J Proxy for Home Assistant

This directory is a self-contained Home Assistant app/add-on repository. It
contains a copy of the proxy application; the original project files outside
this directory are not used or modified by the add-on.

The add-on listens for OCPP 1.6J charge points on TCP port `9000` and proxies
each connection to `wss://ocpp.circlelink.app` by default. A charger connecting
as `/CP-001` is sent upstream as `wss://ocpp.circlelink.app/CP-001`.

## Requirements

- Home Assistant OS on an `amd64` or `aarch64` machine.
- The Home Assistant host must be reachable from the charger's LAN.
- The host needs outbound internet and DNS access for the upstream `wss://`
  connection.

Home Assistant Container doesn't support apps/add-ons. For that installation
type, run the original proxy as a separate container instead.

## Install locally on Home Assistant OS

1. Install and start either the **Samba share** or **Advanced SSH & Web
   Terminal** app so you can access the Home Assistant `/addons` directory.
2. Copy the entire `ocpp-16j-proxy` directory from this repository to:

   ```text
   /addons/ocpp-16j-proxy
   ```

   The resulting path must contain `config.yaml`, `Dockerfile`, and
   `run_addon.py` directly inside it.
3. In Home Assistant, open **Settings → Apps → App store**.
4. Open the top-right menu and select **Check for updates**. Refresh the page if
   necessary.
5. Under **Local apps**, open **OCPP 1.6J Proxy** and select **Install**. The
   first build can take several minutes because it downloads the Python image
   and dependencies.
6. Open the app's **Configuration** tab. The default upstream URL is already:

   ```text
   wss://ocpp.circlelink.app
   ```

7. Open the **Network** section and confirm container port `9000/tcp` is mapped
   to host port `9000`.
8. Select **Start**, enable **Start on boot**, and inspect the **Logs** tab. A
   successful start includes a `proxy_started` JSON event.
9. Configure the charger with the Home Assistant host's LAN IP and its charger
   ID, for example:

   ```text
   ws://192.168.0.26:9000/CP-001
   ```

   Replace the IP and `CP-001` with the actual values. The charger must request
   the WebSocket subprotocol `ocpp1.6`.

## Install from a Git repository

To make the add-on installable as a custom repository:

1. Create a Git repository whose root contains this directory's
   `repository.yaml`, `README.md`, and `ocpp-16j-proxy/` folder. In other words,
   publish the **contents** of `home-assistant-addon`, not its parent project.
2. In Home Assistant, open **Settings → Apps → App store → ⋮ → Repositories**.
3. Add the Git repository URL and select **Add**.
4. Find **OCPP 1.6J Proxy** in the app store, install it, configure it, and start
   it.

## Configuration

| Option | Default | Description |
| --- | --- | --- |
| `upstream_url` | `wss://ocpp.circlelink.app` | Central-system URL. `{charge_point_id}` is supported; otherwise the charger path is appended. |
| `log_level` | `INFO` | Proxy log verbosity. |
| `max_message_size` | `1048576` | Maximum WebSocket message size in bytes. |
| `ping_interval` | `20` | WebSocket ping interval in seconds. |
| `ping_timeout` | `20` | WebSocket ping timeout in seconds. |
| `open_timeout` | `10` | Upstream connection timeout in seconds. |
| `forward_authorization` | `true` | Forward the charger's `Authorization` header upstream. |
| `upstream_authorization` | unset | Optional fixed upstream `Authorization` value, replacing the charger value. |

The host port can be changed separately in the app's **Network** section. If it
is changed to `9100`, for example, chargers must connect to port `9100`.

## Troubleshooting

- **No `proxy_started` log:** check the app build and startup logs.
- **Charger cannot connect:** verify the Home Assistant LAN IP, port mapping,
  firewall, Wi-Fi client isolation, charger ID path, and `ocpp1.6` subprotocol.
- **`upstream_connection_failed`:** verify internet access, DNS, system time,
  upstream URL, and credentials.
- **Connection rejected for missing identity:** include the charger ID in the
  URL path, such as `/CP-001`.

