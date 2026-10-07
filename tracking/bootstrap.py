from __future__ import annotations

import secrets
import time
from pathlib import Path

from deploy.report_fetch import JsonValue
from tracking.crypto import Tag
from tracking.http import HttpClient, HttpFailure
from tracking.traccar import Credentials, load_credentials


def _record(value: JsonValue) -> dict[str, JsonValue]:
    if not isinstance(value, dict):
        raise HttpFailure("Unexpected Traccar response")
    return value


def _records(value: JsonValue) -> list[dict[str, JsonValue]]:
    if not isinstance(value, list):
        raise HttpFailure("Unexpected Traccar list response")
    return [_record(item) for item in value]


def _identifier(record: dict[str, JsonValue]) -> int:
    value = record.get("id")
    if type(value) is not int or value <= 0:
        raise ValueError("Traccar returned an invalid object id")
    return value


def _login(api: HttpClient, credentials: Credentials) -> dict[str, JsonValue]:
    _ = api.form("api/session", {"email": credentials.email, "password": credentials.password})
    return _record(api.json("GET", "api/session"))


def bootstrap(api: HttpClient, state: Path, tags: tuple[Tag, ...]) -> None:
    for attempt in range(30):
        try:
            server = _record(api.json("GET", "api/server"))
            break
        except HttpFailure:
            if attempt == 29:
                raise
            time.sleep(2)
    else:
        raise HttpFailure("Traccar did not become ready")
    owner = load_credentials(state / "admin.json")
    collector = load_credentials(state / "collector.json")
    if server.get("newServer") is True:
        if (state / "initialized").exists():
            raise ValueError("Traccar database is empty but tracking was initialized; restore the database backup")
        _ = api.json("POST", "api/users", {
            "name": "Owner", "email": owner.email, "password": owner.password,
        })
    user = _login(api, owner)
    if user.get("administrator") is not True:
        raise ValueError("Saved owner credentials are not a Traccar administrator")
    server = _record(api.json("GET", "api/server"))
    if server.get("registration") is not False:
        server["registration"] = False
        _ = api.json("PUT", "api/server", server)
    users = _records(api.json("GET", "api/users"))
    service = next((item for item in users if item.get("email") == collector.email), None)
    if service is None:
        service = _record(api.json("POST", "api/users", {
            "name": "Report collector", "email": collector.email, "password": collector.password,
            "readonly": True, "deviceReadonly": True,
        }))
    if service.get("administrator") is True or service.get("readonly") is not True:
        raise ValueError("Collector account must be non-administrator and read-only")
    service_id = _identifier(service)
    devices = _records(api.json("GET", "api/devices?all=true"))
    linked = {
        _identifier(item) for item in _records(api.json("GET", f"api/devices?userId={service_id}"))
    }
    for tag in tags:
        matches: list[dict[str, JsonValue]] = []
        for item in devices:
            attributes = item.get("attributes")
            if isinstance(attributes, dict) and attributes.get("findmytagid") == tag.unique_id:
                matches.append(item)
        if len(matches) > 1:
            raise ValueError("Multiple Traccar devices are assigned to the same tag")
        device = matches[0] if matches else None
        if device is None:
            device = _record(api.json("POST", "api/devices", {
                "name": tag.name, "uniqueId": secrets.token_hex(24), "category": "default",
                "attributes": {"findmytagid": tag.unique_id},
            }))
        device_id = _identifier(device)
        if device_id not in linked:
            _ = api.json("POST", "api/permissions", {"userId": service_id, "deviceId": device_id})
    reader = _login(api, collector)
    if reader.get("administrator") is True or reader.get("readonly") is not True:
        raise ValueError("Collector login does not have the expected restricted role")
    visible: set[str] = set()
    for item in _records(api.json("GET", "api/devices")):
        attributes = item.get("attributes")
        if isinstance(attributes, dict):
            tag_id = attributes.get("findmytagid")
            if isinstance(tag_id, str):
                visible.add(tag_id)
    if not all(tag.unique_id in visible for tag in tags):
        raise ValueError("Collector cannot access every configured tag")
    _ = (state / "initialized").write_text("1\n")
