# /// script
# requires-python = ">=3.12"
# ///
#
# ─── How to run ───
# 1. Install uv (if not installed):
#      curl -LsSf https://astral.sh/uv/install.sh | sh
# 2. Run directly (no venv, no pip install needed):
#      uv run scripts/wait_for_anisette.py
# ──────────────────

from __future__ import annotations

import json
import os
import sys
import time
from contextlib import closing
from dataclasses import dataclass
from http.client import HTTPConnection, HTTPException, HTTPSConnection
from typing import Final, Protocol, assert_never
from urllib.parse import urlsplit

DEFAULT_ANISETTE_URL: Final = "http://anisette:6969"
CONNECTION_TYPES: Final[dict[str, type[HTTPConnection]]] = {
    "http": HTTPConnection,
    "https": HTTPSConnection,
}
JSON_CONTENT_TYPE: Final = "application/json"
MAX_ATTEMPTS: Final = 12
REQUEST_TIMEOUT_SECONDS: Final = 5
RETRY_DELAY_SECONDS: Final = 1
URL_ENVIRONMENT_VARIABLE: Final = "ANISETTE_READY_URL"
MAX_RESPONSE_BYTES: Final = 64 * 1024

type JsonValue = dict[str, JsonValue] | list[JsonValue] | str | int | float | bool | None


class JsonLoader(Protocol):
    def __call__(self, s: bytes) -> JsonValue: ...


JSON_LOADS: JsonLoader = json.loads


@dataclass(frozen=True, slots=True)
class ProbeTarget:
    connection_type: type[HTTPConnection]
    host: str
    port: int | None
    path: str


@dataclass(frozen=True, slots=True)
class InvalidUrl:
    message: str


type ProbeTargetResult = ProbeTarget | InvalidUrl


def response_error(content_type: str | None, body: bytes) -> str | None:
    if content_type is None:
        return "response is not JSON"
    media_type, _, _ = content_type.partition(";")
    if media_type.strip().lower() != JSON_CONTENT_TYPE:
        return "response is not JSON"
    try:
        payload = JSON_LOADS(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        return f"invalid JSON response: {error}"

    match payload:
        case {
            "X-Apple-I-MD": str() as one_time_password,
            "X-Apple-I-MD-M": str() as machine_identifier,
        } if one_time_password and machine_identifier:
            return None
        case dict():
            return "response is missing required Anisette headers"
        case list() | str() | bool() | int() | float() | None:
            return "response is missing required Anisette headers"
    assert_never(payload)


def parse_probe_target(url: str) -> ProbeTargetResult:
    try:
        parsed_url = urlsplit(url)
        host = parsed_url.hostname
    except ValueError:
        return InvalidUrl("URL is malformed")

    try:
        port = parsed_url.port
    except ValueError:
        return InvalidUrl("URL has an invalid port")

    if host is None:
        return InvalidUrl("URL must include a host")

    connection_type = CONNECTION_TYPES.get(parsed_url.scheme)
    if connection_type is None:
        return InvalidUrl("URL must use HTTP or HTTPS")

    path = parsed_url.path or "/"
    if parsed_url.query:
        path = f"{path}?{parsed_url.query}"
    return ProbeTarget(connection_type, host, port, path)


def probe_target(target: ProbeTarget) -> str | None:
    try:
        connection = target.connection_type(
            target.host,
            target.port,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )

        with closing(connection):
            connection.request("GET", target.path)
            response = connection.getresponse()
            if response.status != 200:
                return f"HTTP {response.status}"
            body = response.read(MAX_RESPONSE_BYTES + 1)
            if len(body) > MAX_RESPONSE_BYTES:
                return f"response body exceeds {MAX_RESPONSE_BYTES} bytes"
            return response_error(response.getheader("Content-Type"), body)
    except (HTTPException, OSError) as error:
        return str(error)


def probe(url: str) -> str | None:
    target_result = parse_probe_target(url)
    match target_result:
        case InvalidUrl(message=message):
            return message
        case ProbeTarget() as target:
            return probe_target(target)
    assert_never(target_result)


def wait_for_anisette(url: str) -> int:
    target_result = parse_probe_target(url)
    match target_result:
        case InvalidUrl(message=message):
            print(f"Invalid Anisette readiness URL {url}: {message}", file=sys.stderr)
            return 1
        case ProbeTarget() as target:
            last_error = "no response"
            for attempt in range(1, MAX_ATTEMPTS + 1):
                error = probe_target(target)
                if error is None:
                    return 0

                last_error = error
                if attempt < MAX_ATTEMPTS:
                    time.sleep(RETRY_DELAY_SECONDS)

            error_prefix = f"Timed out waiting for Anisette at {url}"
            print(
                f"{error_prefix} after {MAX_ATTEMPTS} attempts: {last_error}",
                file=sys.stderr,
            )
            return 1
    assert_never(target_result)


def main() -> int:
    url = os.environ.get(URL_ENVIRONMENT_VARIABLE, DEFAULT_ANISETTE_URL)
    return wait_for_anisette(url)


if __name__ == "__main__":
    raise SystemExit(main())
