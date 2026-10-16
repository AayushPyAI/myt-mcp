"""Entry point. Run: .venv/bin/python server.py  ->  http://<HOST>:<PORT>/mcp/<MCP_SECRET>"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import uvicorn
from dotenv import load_dotenv

from myt_mcp.app import create_http_app, create_server
from myt_mcp.config import ConfigError, Settings


def main() -> None:
    load_dotenv(Path(__file__).with_name(".env"))
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    # httpx logs every request URL at INFO; keep URLs (and any key in them) out of the logs.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    try:
        settings = Settings.from_env()
        app = create_http_app(settings, create_server(settings))
    except ConfigError as e:
        sys.exit(f"Config error: {e}")
    uvicorn.run(app, host=settings.host, port=settings.port)


if __name__ == "__main__":
    main()
