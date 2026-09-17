from __future__ import annotations

from collections import deque
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from typing import override

import pytest

from scripts import wait_for_anisette as waiter


@dataclass(frozen=True, slots=True)
class ResponseSpec:
    status: int
    content_type: str | None
    body: bytes


READY_RESPONSE = ResponseSpec(
    status=200,
    content_type="application/json; charset=utf-8",
    body=(
        b'{"X-Apple-I-MD":"ready",'
        b'"X-Apple-I-MD-M":"ready"}'
    ),
)


@contextmanager
def serve_responses(response_specs: tuple[ResponseSpec, ...]) -> Generator[str]:
    responses = deque(response_specs)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            response = responses.popleft()
            self.send_response(response.status)
            if response.content_type is not None:
                self.send_header("Content-Type", response.content_type)
            self.send_header("Content-Length", str(len(response.body)))
            self.end_headers()
            _ = self.wfile.write(response.body)

        @override
        def log_message(self, format: str, *args: object) -> None:
            return

    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        thread = Thread(target=server.serve_forever)
        thread.start()
        try:
            yield f"http://127.0.0.1:{server.server_address[1]}/ready"
        finally:
            server.shutdown()
            thread.join()


@pytest.mark.parametrize(
    ("url", "expected_error"),
    [
        ("http://anisette:not-a-port", "URL has an invalid port"),
        ("http://[::1", "URL is malformed"),
        ("ftp://anisette:6969", "URL must use HTTP or HTTPS"),
    ],
)
def test_rejects_invalid_url_without_retry(
    url: str,
    expected_error: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Given
    sleep_delays: list[float] = []
    monkeypatch.setattr("scripts.wait_for_anisette.time.sleep", sleep_delays.append)

    # When
    status = waiter.wait_for_anisette(url)

    # Then
    captured = capsys.readouterr()
    assert status == 1
    assert expected_error in captured.err
    assert "Timed out" not in captured.err
    assert sleep_delays == []


@pytest.mark.parametrize(
    ("response", "expected_error"),
    [
        (
            ResponseSpec(
                status=200,
                content_type="application/jsonp",
                body=READY_RESPONSE.body,
            ),
            "response is not JSON",
        ),
        (
            ResponseSpec(
                status=200,
                content_type="application/json",
                body=b'{"X-Apple-I-MD":"ready"',
            ),
            "invalid JSON response:",
        ),
    ],
)
def test_rejects_invalid_json_response_at_http_boundary(
    response: ResponseSpec, expected_error: str
) -> None:
    # Given
    with serve_responses((response,)) as url:
        # When
        error = waiter.probe(url)

    # Then
    assert error is not None
    assert error.startswith(expected_error)


def test_rejects_oversized_json_response_at_http_boundary() -> None:
    # Given
    response = ResponseSpec(
        status=200,
        content_type="application/json",
        body=b"x" * (waiter.MAX_RESPONSE_BYTES + 1),
    )

    with serve_responses((response,)) as url:
        # When
        error = waiter.probe(url)

    # Then
    assert error == f"response body exceeds {waiter.MAX_RESPONSE_BYTES} bytes"


def test_retries_transient_http_failure_without_wall_clock_sleep(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    sleep_delays: list[float] = []
    monkeypatch.setattr("scripts.wait_for_anisette.time.sleep", sleep_delays.append)
    unavailable = ResponseSpec(status=503, content_type=None, body=b"")

    with serve_responses((unavailable, READY_RESPONSE)) as url:
        # When
        status = waiter.wait_for_anisette(url)

    # Then
    assert status == 0
    assert sleep_delays == [waiter.RETRY_DELAY_SECONDS]
