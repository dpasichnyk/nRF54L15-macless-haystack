from __future__ import annotations

import json
from http.client import HTTPException, HTTPResponse
from http.cookiejar import CookieJar
from typing import Protocol
from urllib.error import HTTPError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPCookieProcessor, Request, build_opener

from deploy.report_fetch import JSON_LOADS, MAX_RESPONSE_BYTES, JsonValue


class HttpFailure(RuntimeError):
    def __init__(self, reason: str, status: int | None = None) -> None:
        self.status: int | None = status
        super().__init__(f"{reason} (HTTP {status})" if status else reason)


class Opener(Protocol):
    def __call__(self, fullurl: Request, data: bytes | None = None,
                 timeout: float = ...) -> HTTPResponse: ...


class HttpClient:
    def __init__(self, base_url: str, timeout: float = 15) -> None:
        parts = urlsplit(base_url)
        if parts.scheme not in ("http", "https") or not parts.hostname or parts.username:
            raise ValueError("HTTP service URL must have a host and no credentials")
        _ = parts.port
        self.base_url: str = base_url.rstrip("/")
        self.timeout: float = timeout
        self._open: Opener = build_opener(HTTPCookieProcessor(CookieJar())).open

    def _send(self, request: Request) -> bytes:
        try:
            with self._open(request, timeout=self.timeout) as response:
                if not 200 <= response.status < 300:
                    raise HttpFailure("Request rejected", response.status)
                body = response.read(MAX_RESPONSE_BYTES + 1)
        except HTTPError as error:
            error.close()
            raise HttpFailure("Request rejected", error.code) from None
        except (OSError, HTTPException) as error:
            raise HttpFailure(type(error).__name__) from None
        if len(body) > MAX_RESPONSE_BYTES:
            raise HttpFailure("Response exceeds 4 MiB")
        return body

    def json(self, method: str, path: str = "", body: JsonValue = None) -> JsonValue:
        data = None if body is None else json.dumps(body, allow_nan=False).encode()
        headers = {"Accept": "application/json"}
        if data is not None:
            headers["Content-Type"] = "application/json"
        raw = self._send(Request(
            f"{self.base_url}/{path.lstrip('/')}", data=data, method=method,
            headers=headers,
        ))
        if not raw:
            return None
        try:
            return JSON_LOADS(raw)
        except (ValueError, RecursionError) as error:
            raise HttpFailure("Invalid JSON response") from error

    def form(self, path: str, fields: dict[str, str]) -> bytes:
        return self._send(Request(
            f"{self.base_url}/{path.lstrip('/')}", data=urlencode(fields).encode(),
            headers={"Content-Type": "application/x-www-form-urlencoded"}, method="POST",
        ))
