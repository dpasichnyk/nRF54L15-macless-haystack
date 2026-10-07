from typing import override

from deploy.report_fetch import JsonValue
from tracking.crypto import Position
from tracking.http import HttpClient
from tracking.store import Pending
from tracking.traccar import Credentials, Traccar


class StoredReportClient(HttpClient):
    def __init__(self) -> None:
        super().__init__("http://example.invalid")

    @override
    def form(self, path: str, fields: dict[str, str]) -> bytes:
        assert path == "api/session"
        return b"{}"

    @override
    def json(self, method: str, path: str = "", body: JsonValue = None) -> JsonValue:
        if path == "api/devices":
            return [{"id": 1, "uniqueId": "opaque", "attributes": {"findmytagid": "tag"}}]
        assert path.startswith("api/positions?")
        return [{"attributes": {"findmyreportid": "legacy-id"}}]


def test_existing_stored_report_is_not_resubmitted() -> None:
    pending = Pending("tag", "legacy-id", Position(1789840000, 1, 2, 3, 4, 5))
    client = StoredReportClient()
    sink = Traccar(client, client, Credentials("fixture", "fixture"))
    assert sink.deliver(pending)
