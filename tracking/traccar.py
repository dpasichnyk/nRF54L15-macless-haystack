from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

from deploy.report_fetch import JSON_LOADS, JsonValue
from tracking.http import HttpClient, HttpFailure
from tracking.store import Pending


@dataclass(frozen=True, slots=True)
class Credentials:
    email: str
    password: str = field(repr=False)


class CredentialsError(ValueError):
    pass


def load_credentials(path: Path) -> Credentials:
    data = JSON_LOADS(path.read_bytes())
    if not isinstance(data, dict):
        raise CredentialsError("Invalid local Traccar credentials file")
    email, password = data.get("email"), data.get("password")
    if not isinstance(email, str) or not email or not isinstance(password, str) or not password:
        raise CredentialsError("Traccar credentials require email and password")
    return Credentials(email, password)


class Traccar:
    def __init__(self, api: HttpClient, ingest: HttpClient, credentials: Credentials) -> None:
        self.api: HttpClient = api
        self.ingest: HttpClient = ingest
        self.credentials: Credentials = credentials
        self._logged_in: bool = False
        self._devices: dict[str, tuple[int, str]] = {}

    def _get(self, path: str) -> JsonValue:
        for attempt in range(2):
            if not self._logged_in:
                _ = self.api.form("api/session", {
                    "email": self.credentials.email, "password": self.credentials.password,
                })
                self._logged_in = True
            try:
                return self.api.json("GET", path)
            except HttpFailure as error:
                if error.status != 401 or attempt:
                    raise
                self._logged_in = False
        raise HttpFailure("Traccar session could not be established")

    def _device(self, tag_id: str) -> tuple[int, str]:
        if tag_id not in self._devices:
            data = self._get("api/devices")
            if not isinstance(data, list):
                raise HttpFailure("Invalid Traccar devices response")
            for device in data:
                if not isinstance(device, dict):
                    raise HttpFailure("Invalid Traccar device")
                unique_id, device_id, attributes = device.get("uniqueId"), device.get("id"), device.get("attributes")
                if isinstance(unique_id, str) and type(device_id) is int and isinstance(attributes, dict):
                    logical_id = attributes.get("findmytagid")
                    if isinstance(logical_id, str):
                        existing = self._devices.get(logical_id)
                        if existing is not None and existing != (device_id, unique_id):
                            raise HttpFailure("Multiple Traccar devices match the tag")
                        self._devices[logical_id] = (device_id, unique_id)
        if tag_id not in self._devices:
            raise HttpFailure("Tag is not registered or not shared with the collector")
        return self._devices[tag_id]

    def _stored(self, item: Pending) -> bool:
        timestamp = item.position.timestamp
        query = urlencode({
            "deviceId": self._device(item.tag_id)[0],
            "from": datetime.fromtimestamp(timestamp - 1, timezone.utc).isoformat(),
            "to": datetime.fromtimestamp(timestamp + 1, timezone.utc).isoformat(),
        })
        data = self._get(f"api/positions?{query}")
        if not isinstance(data, list):
            raise HttpFailure("Invalid Traccar positions response")
        for position in data:
            if not isinstance(position, dict):
                raise HttpFailure("Invalid Traccar position")
            attributes = position.get("attributes")
            if isinstance(attributes, dict) and attributes.get("findmyreportid") in (
                item.source_id, f"sha256:{item.source_id}",
            ):
                return True
        return False

    def deliver(self, item: Pending) -> bool:
        if self._stored(item):
            return True
        position = item.position
        _ = self.ingest.form("", {
            "id": self._device(item.tag_id)[1], "lat": str(position.latitude), "lon": str(position.longitude),
            "timestamp": str(position.timestamp), "accuracy": str(position.accuracy),
            "findmyreportid": f"sha256:{item.source_id}", "findmyconfidence": str(position.confidence),
            "findmystatus": str(position.status),
        })
        for delay in (0.0, 0.1, 0.3, 0.6):
            if delay:
                time.sleep(delay)
            if self._stored(item):
                return True
        return False
