from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import sqlite3
import time
from pathlib import Path
from threading import Event
from types import FrameType
from typing import Literal

from tracking.crypto import load_tags
from tracking.http import HttpClient, HttpFailure
from tracking.service import Collector
from tracking.store import Store
from tracking.traccar import Traccar, load_credentials

logger = logging.getLogger(__name__)

class Arguments(argparse.Namespace):
    command: Literal["run", "once", "status", "health", "backup", "replay"] = "run"
    output: str | None = None


def main() -> int:
    _ = os.umask(0o077)
    parser = argparse.ArgumentParser(description="Collect and retain Find My reports for Traccar")
    _ = parser.add_argument("command", choices=("run", "once", "status", "health", "backup", "replay"))
    _ = parser.add_argument("output", nargs="?")
    args = parser.parse_args(namespace=Arguments())
    if args.output is not None and args.command != "backup":
        parser.error("only backup accepts an output path")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    database = Path(os.environ.get("TRACKING_DATABASE", "/data/reports.sqlite3"))
    try:
        poll = int(os.environ.get("TRACKING_POLL_SECONDS", "60"))
        if not 30 <= poll <= 3600:
            raise ValueError("TRACKING_POLL_SECONDS must be between 30 and 3600")
        if args.command not in ("run", "once") and not database.is_file():
            raise ValueError("Collector database does not exist yet")
        with Store(database) as store:
            match args.command:
                case "status":
                    print(json.dumps(store.status(), sort_keys=True))
                    return 0
                case "health":
                    progress = store.status()["last_progress"]
                    return 0 if progress and 0 <= time.time() - progress < max(180, poll * 3) else 1
                case "backup":
                    if not args.output:
                        raise ValueError("backup requires an output path")
                    store.backup(Path(args.output))
                    return 0
                case "run" | "once" | "replay":
                    tags = load_tags(Path(os.environ.get("TRACKING_KEYS_FILE", "/run/secrets/devices.json")).read_bytes())
                    if args.command == "replay":
                        print(json.dumps({"requeued": store.requeue(tuple(tag.unique_id for tag in tags))}))
                        return 0
            credentials = load_credentials(Path(os.environ.get("TRACKING_AUTH_FILE", "/run/secrets/collector.json")))
            collector = Collector(
                store,
                HttpClient(os.environ.get("TRACKING_ENDPOINT_URL", "http://endpoint:6176"), timeout=60),
                Traccar(
                    HttpClient(os.environ.get("TRACKING_API_URL", "http://traccar:8082")),
                    HttpClient(os.environ.get("TRACKING_INGEST_URL", "http://traccar:5055")),
                    credentials,
                ),
            )
            stop = Event()

            def shutdown(_signal: int, _frame: FrameType | None) -> None:
                stop.set()

            _ = signal.signal(signal.SIGTERM, shutdown)
            _ = signal.signal(signal.SIGINT, shutdown)
            if args.command == "once":
                return 0 if collector.cycle(tags, stop) else 1
            collector.run(tags, stop, poll)
        return 0
    except (OSError, ValueError, HttpFailure, sqlite3.Error) as error:
        logger.error("Collector stopped: %s", error)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
