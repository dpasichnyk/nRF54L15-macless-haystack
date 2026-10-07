from __future__ import annotations

import json
import logging
import time
from threading import Event

from tracking.crypto import ReportError, Tag, decrypt_report, parse_reports
from tracking.http import HttpClient, HttpFailure
from tracking.store import Store
from tracking.traccar import Traccar

logger = logging.getLogger(__name__)


class Collector:
    def __init__(self, store: Store, endpoint: HttpClient, traccar: Traccar) -> None:
        self.store: Store = store
        self.endpoint: HttpClient = endpoint
        self.traccar: Traccar = traccar

    def cycle(self, tags: tuple[Tag, ...], stop: Event) -> bool:
        inserted = rejected = delivered = 0
        healthy = True
        for tag in tags:
            if stop.is_set():
                break
            try:
                body = self.endpoint.json("POST", body={
                    "ids": [key.report_id for key in tag.keys], "days": 7,
                })
                reports = parse_reports(json.dumps(body, allow_nan=False).encode(), tag)
            except (HttpFailure, ValueError) as error:
                logger.warning("Report collection failed tag=%s reason=%s", tag.unique_id, error)
                healthy = False
                self.store.progress(int(time.time()))
                continue
            keys = {key.report_id: key for key in tag.keys}
            for report in reports:
                if self.store.contains(report):
                    continue
                try:
                    result = decrypt_report(report, keys[report.key_id], int(time.time()))
                except ReportError as error:
                    _ = self.store.add(report, error)
                    rejected += 1
                else:
                    inserted += self.store.add(report, result)
            self.store.progress(int(time.time()))

        for pending in self.store.pending(tuple(tag.unique_id for tag in tags)):
            if stop.is_set():
                break
            try:
                stored = self.traccar.deliver(pending)
            except HttpFailure as error:
                logger.warning("Position delivery deferred tag=%s reason=%s", pending.tag_id, error)
                healthy = False
                break
            if not stored:
                logger.warning("Position storage not confirmed tag=%s; keeping pending", pending.tag_id)
                healthy = False
                break
            self.store.mark_delivered(pending, int(time.time()))
            delivered += 1
            self.store.progress(int(time.time()))
        self.store.progress(int(time.time()))
        if inserted or rejected or delivered:
            logger.log(logging.WARNING if rejected else logging.INFO,
                       "Collection complete new=%d rejected=%d delivered=%d", inserted, rejected, delivered)
        return healthy

    def run(self, tags: tuple[Tag, ...], stop: Event, poll_seconds: int) -> None:
        delay = poll_seconds
        while not stop.is_set():
            started = time.monotonic()
            healthy = self.cycle(tags, stop)
            delay = poll_seconds if healthy else min(delay * 2, max(poll_seconds, 300))
            _ = stop.wait(max(0.0, delay - (time.monotonic() - started)))
