from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

OPTIONS_PATH = Path("/data/options.json")

DEFAULTS: dict[str, Any] = {
    "upstream_url": "wss://ocpp.circlelink.app",
    "log_level": "INFO",
    "max_message_size": 1_048_576,
    "ping_interval": 20.0,
    "ping_timeout": 20.0,
    "open_timeout": 10.0,
    "forward_authorization": True,
}

ENVIRONMENT_OPTIONS = {
    "upstream_url": "OCPP_UPSTREAM_URL",
    "log_level": "OCPP_LOG_LEVEL",
    "max_message_size": "OCPP_MAX_MESSAGE_SIZE",
    "ping_interval": "OCPP_PING_INTERVAL",
    "ping_timeout": "OCPP_PING_TIMEOUT",
    "open_timeout": "OCPP_OPEN_TIMEOUT",
    "forward_authorization": "OCPP_FORWARD_AUTHORIZATION",
    "upstream_authorization": "OCPP_UPSTREAM_AUTHORIZATION",
}


def load_options(path: Path = OPTIONS_PATH) -> dict[str, Any]:
    try:
        configured = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SystemExit(f"Home Assistant options file not found: {path}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"Unable to read Home Assistant options: {exc}") from exc

    if not isinstance(configured, dict):
        raise SystemExit("Home Assistant options must contain a JSON object")
    return {**DEFAULTS, **configured}


def configure_environment(options: dict[str, Any]) -> None:
    os.environ["OCPP_LISTEN_HOST"] = "0.0.0.0"
    os.environ["OCPP_LISTEN_PORT"] = "9000"

    for option, environment_name in ENVIRONMENT_OPTIONS.items():
        value = options.get(option)
        if value is None or value == "":
            os.environ.pop(environment_name, None)
            continue
        if isinstance(value, bool):
            serialized = "true" if value else "false"
        else:
            serialized = str(value)
        os.environ[environment_name] = serialized


def main() -> None:
    configure_environment(load_options())

    # Import after setting environment variables so the copied application uses
    # the values configured in the Home Assistant UI.
    from ocpp_proxy.__main__ import main as proxy_main

    proxy_main()


if __name__ == "__main__":
    main()

