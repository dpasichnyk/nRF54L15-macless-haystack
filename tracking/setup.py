from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path
from typing import Literal

from tracking.bootstrap import bootstrap
from tracking.config import initialize
from tracking.crypto import load_tags
from tracking.http import HttpClient, HttpFailure

logger = logging.getLogger(__name__)

class Arguments(argparse.Namespace):
    command: Literal["init", "bootstrap"] = "init"
    state: str = ".tracking"
    keys: str = ""
    url: str = "http://127.0.0.1:8082"


def main() -> int:
    _ = os.umask(0o077)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Initialize the optional tracking stack without replacing secrets")
    _ = parser.add_argument("command", choices=("init", "bootstrap"))
    _ = parser.add_argument("--state", default=".tracking")
    _ = parser.add_argument("--keys", required=True)
    _ = parser.add_argument("--url", default="http://127.0.0.1:8082")
    args = parser.parse_args(namespace=Arguments())
    try:
        state, keys = Path(args.state).resolve(), Path(args.keys).resolve()
        match args.command:
            case "init":
                initialize(state, keys)
                print(f"Tracking state ready: {state}")
            case "bootstrap":
                bootstrap(HttpClient(args.url, timeout=5), state, load_tags(keys.read_bytes()))
                print(f"Tracking UI ready: {args.url}; credentials: {state / 'admin.json'}")
        return 0
    except (OSError, ValueError, HttpFailure) as error:
        logger.error("Tracking setup failed: %s", error)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
