import base64
import json

import pytest

from deploy.report_fetch import (
    APPLE_EPOCH,
    MAX_REQUEST_BYTES,
    MAX_RESPONSE_BYTES,
    InvalidRequest,
    InvalidResponse,
    ReportCache,
    ReportQuery,
    filter_response,
    parse_query,
    search_body,
)

KEYS = tuple(base64.b64encode(i.to_bytes(32, "big")).decode() for i in range(51))
NOW = APPLE_EPOCH + 1_000_000


def test_each_rotating_key_has_its_own_search() -> None:
    query = parse_query(json.dumps({"ids": list(KEYS[:50]) + [KEYS[0]]}).encode())
    assert len(query.ids) == 50
    assert query.days == 7
    assert search_body(query) == {
        "search": [{"startDate": 1, "ids": [key]} for key in sorted(KEYS[:50])]
    }


@pytest.mark.parametrize("body", [
    b"", b"[]", b"{", b'{"ids": "wrong"}', b'{"ids": []}',
    b'{"ids": [null]}', b'{"ids": ["invalid"]}',
    json.dumps({"ids": list(KEYS)}).encode(),
    b" " * (MAX_REQUEST_BYTES + 1),
])
def test_invalid_queries_are_rejected(body: bytes) -> None:
    with pytest.raises(InvalidRequest):
        _ = parse_query(body)


@pytest.mark.parametrize("days", [True, 0, -1, 32, 1.5, "7", None])
def test_invalid_report_windows_are_rejected(days: bool | float | str | None) -> None:
    with pytest.raises(InvalidRequest):
        _ = parse_query(json.dumps({"ids": [KEYS[0]], "days": days}).encode())


def report(key: str, timestamp: int, marker: bytes = b"a") -> dict[str, str]:
    payload = (timestamp - APPLE_EPOCH).to_bytes(4, "big") + marker
    return {"id": key, "payload": base64.b64encode(payload).decode()}


def test_merge_keeps_distinct_same_second_reports_and_sorts_newest_first() -> None:
    older = report(KEYS[0], NOW - 10)
    first = report(KEYS[0], NOW)
    second = report(KEYS[1], NOW)
    other_finder = report(KEYS[0], NOW, b"b")
    expired = report(KEYS[0], NOW - 86400)
    raw = json.dumps({
        "statusCode": "200", "results": [older, first, expired, second, first, other_finder],
    }).encode()
    result = filter_response(raw, ReportQuery(KEYS[:2], 1), NOW)
    assert result["results"] == [first, second, other_finder, older]


@pytest.mark.parametrize("body", [
    b"", b"{", b"[]", b'{"statusCode":401,"results":[]}',
    b'{"statusCode":200,"results":[],"value":NaN}',
    b'{"statusCode":200,"results":null}', b'{"statusCode":200,"results":[null]}',
    json.dumps({"statusCode": 200, "results": [report(KEYS[1], NOW)]}).encode(),
    json.dumps({"statusCode": 200, "results": [{"id": KEYS[0], "payload": "bad"}]}).encode(),
    json.dumps({"statusCode": 200, "results": [{"id": KEYS[0], "payload": "YQ=="}]}).encode(),
    b"x" * (MAX_RESPONSE_BYTES + 1),
])
def test_invalid_upstream_data_is_not_returned_as_success(body: bytes) -> None:
    with pytest.raises(InvalidResponse):
        _ = filter_response(body, ReportQuery(KEYS[:1], 7), NOW)


def test_valid_empty_response_is_success() -> None:
    assert filter_response(
        b'{"statusCode":200,"results":[]}', ReportQuery(KEYS[:1], 7), NOW,
    )["results"] == []


def test_cache_reuses_raw_reports_but_applies_each_requested_window() -> None:
    cache = ReportCache()
    week = ReportQuery(KEYS[:1], 7)
    day = ReportQuery(KEYS[:1], 1)
    raw = json.dumps({"statusCode": 200, "results": [report(KEYS[0], NOW - 172800)]}).encode()
    cache.put(week, raw, 10)
    assert cache.get(day, 39) == raw
    assert filter_response(raw, day, NOW)["results"] == []
    assert filter_response(raw, week, NOW)["results"] != []
    assert cache.get(day, 40) is None


def test_cache_does_not_share_data_between_key_sets_and_evicts_oldest() -> None:
    cache = ReportCache()
    for index in range(5):
        cache.put(ReportQuery((KEYS[index],), 7), str(index).encode(), 0)
    assert cache.get(ReportQuery(KEYS[:1], 7), 1) is None
    assert cache.get(ReportQuery((KEYS[4],), 1), 1) == b"4"
    assert cache.get(ReportQuery(KEYS[:2], 7), 1) is None
