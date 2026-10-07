import base64
import sqlite3
from pathlib import Path

import pytest

from tracking.crypto import EncryptedReport, Position, ReportError
from tracking.store import Store


def report(tag_id: str, marker: bytes) -> EncryptedReport:
    key_id = base64.b64encode(tag_id.encode().ljust(32, b"_")).decode()
    return EncryptedReport(tag_id=tag_id, key_id=key_id, payload=b"\x00\x00\x00\x01" + marker)


def position(timestamp: int) -> Position:
    return Position(
        timestamp=timestamp,
        latitude=51.5,
        longitude=-0.12,
        accuracy=4,
        confidence=80,
        status=1,
    )


def test_add_persists_a_pending_position_across_reopen(tmp_path: Path) -> None:
    path = tmp_path / "private" / "history.db"
    item = report("alpha", b"one")

    with Store(path) as store:
        assert not store.contains(item)
        assert store.add(item, position(100))
        assert store.contains(item)
        store.progress(300)

    with Store(path) as store:
        pending = store.pending(("alpha",))
        assert [(entry.tag_id, entry.source_id, entry.position.timestamp) for entry in pending] == [
            ("alpha", item.source_id, 100),
        ]
        assert store.status() == {
            "reports": 1,
            "pending": 1,
            "rejected": 0,
            "delivered": 0,
            "latest_report": 100,
            "last_progress": 300,
        }


def test_duplicate_source_does_not_overwrite_delivered_report(tmp_path: Path) -> None:
    item = report("alpha", b"same")
    path = tmp_path / "history.db"

    with Store(path) as store:
        assert store.add(item, position(100))
        store.mark_delivered(store.pending(("alpha",))[0], 500)
        assert not store.add(item, position(999))
        assert store.pending(("alpha",)) == []
        assert store.status()["delivered"] == 1
        assert store.status()["latest_report"] == 100


def test_distinct_same_second_reports_remain_pending_in_insert_order(tmp_path: Path) -> None:
    first = report("alpha", b"first")
    second = report("alpha", b"second")

    with Store(tmp_path / "history.db") as store:
        assert store.add(first, position(100))
        assert store.add(second, position(100))
        pending = store.pending(("alpha",))

    assert [entry.source_id for entry in pending] == [first.source_id, second.source_id]


def test_rejected_report_is_stored_but_excluded_from_pending(tmp_path: Path) -> None:
    with Store(tmp_path / "history.db") as store:
        assert store.add(report("alpha", b"bad"), ReportError("cannot decrypt"))

        assert store.pending(("alpha",)) == []
        assert store.status()["rejected"] == 1


def test_pending_filters_active_tags_and_returns_oldest_first(tmp_path: Path) -> None:
    with Store(tmp_path / "history.db") as store:
        assert store.add(report("alpha", b"late"), position(200))
        assert store.add(report("bravo", b"early"), position(50))
        assert store.add(report("alpha", b"early"), position(100))

        assert [entry.position.timestamp for entry in store.pending(("alpha",), limit=1)] == [100]
        assert [entry.position.timestamp for entry in store.pending(("alpha", "bravo"))] == [50, 100, 200]


def test_backup_is_a_consistent_snapshot(tmp_path: Path) -> None:
    path = tmp_path / "history.db"
    backup = tmp_path / "backup.db"

    with Store(path) as store:
        assert store.add(report("alpha", b"before"), position(100))
        store.backup(backup)
        assert store.add(report("alpha", b"after"), position(200))

    with Store(backup) as snapshot:
        assert snapshot.status()["reports"] == 1
        assert [entry.position.timestamp for entry in snapshot.pending(("alpha",))] == [100]


def test_requeue_reopens_only_valid_reports_for_active_tags(tmp_path: Path) -> None:
    valid = report("alpha", b"valid")
    rejected = report("alpha", b"rejected")
    other = report("bravo", b"other")

    with Store(tmp_path / "history.db") as store:
        assert store.add(valid, position(100))
        assert store.add(rejected, ReportError("bad"))
        assert store.add(other, position(200))
        store.mark_delivered(store.pending(("alpha",))[0], 500)
        store.mark_delivered(store.pending(("bravo",))[0], 500)

        assert store.requeue(("alpha",)) == 1
        assert [entry.source_id for entry in store.pending(("alpha", "bravo"))] == [valid.source_id]


def test_open_rejects_unknown_future_schema_version(tmp_path: Path) -> None:
    path = tmp_path / "future.db"
    with sqlite3.connect(path) as connection:
        _ = connection.execute("PRAGMA user_version = 2")

    with pytest.raises(ValueError, match="future schema"):
        _ = Store(path)
