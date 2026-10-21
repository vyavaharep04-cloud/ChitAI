"""Start the local server: `python -m chitai.api` (binds 127.0.0.1 only)."""

from __future__ import annotations

import argparse

import uvicorn

from .server import create_app


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m chitai.api", description="ChitAI local web server")
    parser.add_argument("--port", type=int, default=8000, help="port to listen on (default 8000)")
    args = parser.parse_args(argv)
    # Loopback only. LAN access is a later, explicit opt-in.
    uvicorn.run(create_app(), host="127.0.0.1", port=args.port, log_level="info")


if __name__ == "__main__":
    main()
