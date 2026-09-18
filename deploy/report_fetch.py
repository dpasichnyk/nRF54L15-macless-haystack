from __future__ import annotations

import base64
import json
from collections import OrderedDict
from dataclasses import dataclass
from functools import partial
from typing import NoReturn, Protocol

MAX_REQUEST_BYTES = 64 * 1024
MAX_RESPONSE_BYTES = 4 * 1024 * 1024
APPLE_EPOCH = 978307200
CACHE_SECONDS = 30

type JsonValue = dict[str, JsonValue] | list[JsonValue] | str | int | float | bool | None


class JsonDecoder(Protocol):
    def __call__(self, s: bytes) -> JsonValue: ...


def _reject_constant(_value: str) -> NoReturn:
    raise ValueError("Non-finite JSON number")


JSON_LOADS: JsonDecoder = partial(json.loads, parse_constant=_reject_constant)


class InvalidRequest(ValueError):
    pass


class InvalidResponse(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ReportQuery:
    ids: tuple[str, ...]
    days: int


def parse_query(body: bytes) -> ReportQuery:
    if len(body) > MAX_REQUEST_BYTES:
        raise InvalidRequest("Request body exceeds 64 KiB")
    try:
        data = JSON_LOADS(body)
    except (ValueError, RecursionError) as error:
        raise InvalidRequest("Invalid JSON request") from error
    if not isinstance(data, dict):
        raise InvalidRequest("ids must be a list of SHA-256 hashes")
    ids = data.get("ids")
    if not isinstance(ids, list):
        raise InvalidRequest("ids must be a list of SHA-256 hashes")
    keys: set[str] = set()
    for key in ids:
        if not isinstance(key, str):
            raise InvalidRequest("Each id must be a base64 SHA-256 hash")
        try:
            decoded = base64.b64decode(key, validate=True)
        except ValueError as error:
            raise InvalidRequest("Each id must be a base64 SHA-256 hash") from error
        if len(decoded) != 32 or base64.b64encode(decoded).decode("ascii") != key:
            raise InvalidRequest("Each id must be a canonical base64 SHA-256 hash")
        keys.add(key)
    if not 1 <= len(keys) <= 50:
        raise InvalidRequest("Request must contain between 1 and 50 distinct ids")
    days = data.get("days", 7)
    if type(days) is not int or not 1 <= days <= 31:
        raise InvalidRequest("days must be an integer between 1 and 31")
    return ReportQuery(tuple(sorted(keys)), days)


def search_body(query: ReportQuery) -> dict[str, JsonValue]:
    return {"search": [{"startDate": 1, "ids": [key]} for key in query.ids]}


def filter_response(body: bytes, query: ReportQuery, now: float) -> dict[str, JsonValue]:
    if not body or len(body) > MAX_RESPONSE_BYTES:
        raise InvalidResponse("Upstream response is empty or exceeds 4 MiB")
    try:
        data = JSON_LOADS(body)
    except (ValueError, RecursionError) as error:
        raise InvalidResponse("Upstream returned invalid JSON") from error
    if not isinstance(data, dict) or data.get("statusCode") not in (200, "200"):
        raise InvalidResponse("Upstream reported an unsuccessful response")
    reports = data.get("results")
    if not isinstance(reports, list):
        raise InvalidResponse("Upstream results must be a list")
    seen: set[tuple[str, str]] = set()
    selected: list[tuple[int, dict[str, JsonValue]]] = []
    cutoff = now - query.days * 86400
    for report in reports:
        if not isinstance(report, dict):
            raise InvalidResponse("Upstream returned an invalid report")
        key, payload = report.get("id"), report.get("payload")
        if not isinstance(key, str) or key not in query.ids or not isinstance(payload, str):
            raise InvalidResponse("Upstream report has an unexpected id or payload")
        try:
            decoded = base64.b64decode(payload, validate=True)
        except ValueError as error:
            raise InvalidResponse("Upstream report payload is not base64") from error
        if len(decoded) < 4:
            raise InvalidResponse("Upstream report has no timestamp")
        timestamp = int.from_bytes(decoded[:4], "big") + APPLE_EPOCH
        identity = (key, payload)
        if timestamp > cutoff and identity not in seen:
            seen.add(identity)
            selected.append((timestamp, report))
    selected.sort(key=lambda item: item[0], reverse=True)
    data["results"] = [report for _, report in selected]
    return data


class ReportCache:
    def __init__(self) -> None:
        self._entries: OrderedDict[tuple[str, ...], tuple[float, bytes]] = OrderedDict()

    def get(self, query: ReportQuery, now: float) -> bytes | None:
        entry = self._entries.get(query.ids)
        if entry is None:
            return None
        expires, body = entry
        if now >= expires:
            del self._entries[query.ids]
            return None
        self._entries.move_to_end(query.ids)
        return body

    def put(self, query: ReportQuery, body: bytes, now: float) -> None:
        self._entries[query.ids] = (now + CACHE_SECONDS, body)
        self._entries.move_to_end(query.ids)
        while len(self._entries) > 4:
            _ = self._entries.popitem(last=False)
