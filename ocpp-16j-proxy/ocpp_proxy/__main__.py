from __future__ import annotations

import argparse
import asyncio

from .proxy import OcppProxy, ProxyConfig, configure_logging


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Transparent OCPP 1.6J WebSocket proxy"
    )
    parser.add_argument(
        "--upstream",
        help=(
            "Central-system WebSocket URL. May contain {charge_point_id}; "
            "otherwise the incoming path is appended."
        ),
    )
    parser.add_argument("--host", help="Listening host (default: environment or 0.0.0.0)")
    parser.add_argument("--port", type=int, help="Listening port")
    parser.add_argument(
        "--log-level",
        choices=("DEBUG", "INFO", "WARNING", "ERROR"),
        help="Log level",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        config = ProxyConfig.from_env(
            upstream_url=args.upstream,
            listen_host=args.host,
            listen_port=args.port,
            log_level=args.log_level,
        )
    except ValueError as exc:
        raise SystemExit(f"Configuration error: {exc}") from exc

    configure_logging(config.log_level)
    try:
        asyncio.run(OcppProxy(config).run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
