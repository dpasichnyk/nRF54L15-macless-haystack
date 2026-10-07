from __future__ import annotations

import os
import sqlite3
import tempfile
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import Final, Protocol, Self

from tracking.crypto import EncryptedReport, Position, ReportError

type SqlValue = str | bytes | int | float | None
type Row = tuple[SqlValue, ...]


class FetchOne(Protocol):
    def __call__(self, cursor: sqlite3.Cursor, /) -> Row | None: ...


class FetchAll(Protocol):
    def __call__(self, cursor: sqlite3.Cursor, /) -> list[Row]: ...


FETCH_ONE: FetchOne = sqlite3.Cursor.fetchone
FETCH_ALL: FetchAll = sqlite3.Cursor.fetchall


def _required_row(cursor: sqlite3.Cursor) -> Row:
    row = FETCH_ONE(cursor)
    if row is None:
        raise ValueError("SQLite query returned no required row")
    return row


def _present(value: SqlValue) -> str | bytes | int | float:
    if value is None:
        raise ValueError("SQLite returned an unexpected NULL")
    return value

_SCHEMA_VERSION: Final = 1
_SCHEMA: Final = """
CREATE TABLE IF NOT EXISTS reports (
    tag_id TEXT NOT NULL,
    source_id TEXT NOT NULL,
    key_id TEXT NOT NULL,
    payload BLOB NOT NULL,
    timestamp INTEGER,
    latitude REAL,
    longitude REAL,
    accuracy INTEGER,
    confidence INTEGER,
    status INTEGER,
    error TEXT,
    delivered_at INTEGER,
    UNIQUE(tag_id, source_id),
    CHECK (
        (error IS NULL AND timestamp IS NOT NULL AND latitude IS NOT NULL
            AND longitude IS NOT NULL AND accuracy IS NOT NULL
            AND confidence IS NOT NULL AND status IS NOT NULL)
        OR
        (error IS NOT NULL AND timestamp IS NULL AND latitude IS NULL
            AND longitude IS NULL AND accuracy IS NULL
            AND confidence IS NULL AND status IS NULL)
    )
);
CREATE INDEX IF NOT EXISTS reports_pending_idx
    ON reports(tag_id, timestamp)
    WHERE error IS NULL AND delivered_at IS NULL;
CREATE TABLE IF NOT EXISTS metadata (
    key TEXT PRIMARY KEY,
    value INTEGER NOT NULL
);
"""


class UnsupportedSchema(ValueError):

    def __init__(self, version: int) -> None:
        super().__init__(f"future schema version {version}")


@dataclass(frozen=True, slots=True)
class Pending:
    tag_id: str
    source_id: str
    position: Position


class Store:

    def __init__(self, path: Path) -> None:
        if not path.parent.exists():
            path.parent.mkdir(parents=True, mode=0o700)
        self._connection: sqlite3.Connection = sqlite3.connect(path)
        path.chmod(0o600)
        _ = self._connection.execute("PRAGMA busy_timeout = 5000")
        version = int(_present(_required_row(self._connection.execute("PRAGMA user_version"))[0]))
        if version > _SCHEMA_VERSION:
            self._connection.close()
            raise UnsupportedSchema(version)
        _ = self._connection.execute("PRAGMA journal_mode = WAL")
        _ = self._connection.execute("PRAGMA synchronous = FULL")
        _ = self._connection.executescript(_SCHEMA)
        if version == 0:
            _ = self._connection.execute(f"PRAGMA user_version = {_SCHEMA_VERSION}")

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self._connection.close()

    def contains(self, report: EncryptedReport) -> bool:
        row = FETCH_ONE(self._connection.execute(
            "SELECT 1 FROM reports WHERE tag_id = ? AND source_id = ?",
            (report.tag_id, report.source_id),
        ))
        return row is not None

    def add(self, report: EncryptedReport, result: Position | ReportError) -> bool:
        match result:
            case Position(timestamp, latitude, longitude, accuracy, confidence, status):
                values = (timestamp, latitude, longitude, accuracy, confidence, status, None)
            case ReportError() as error:
                values = (None, None, None, None, None, None, str(error))
        with self._connection:
            cursor = self._connection.execute(
                """
                INSERT INTO reports (
                    tag_id, source_id, key_id, payload, timestamp, latitude, longitude,
                    accuracy, confidence, status, error
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(tag_id, source_id) DO NOTHING
                """,
                (report.tag_id, report.source_id, report.key_id, report.payload, *values),
            )
        return cursor.rowcount == 1

    def pending(self, active_tags: tuple[str, ...], limit: int = 250) -> list[Pending]:
        if not active_tags:
            return []
        placeholders = ", ".join("?" for _ in active_tags)
        rows = FETCH_ALL(self._connection.execute(
            f"""
            SELECT tag_id, source_id, timestamp, latitude, longitude, accuracy, confidence, status
            FROM reports
            WHERE error IS NULL AND delivered_at IS NULL AND tag_id IN ({placeholders})
            ORDER BY timestamp ASC, rowid ASC
            LIMIT ?
            """,
            (*active_tags, limit),
        ))
        return [
            Pending(
                tag_id=str(_present(row[0])),
                source_id=str(_present(row[1])),
                position=Position(
                    timestamp=int(_present(row[2])),
                    latitude=float(_present(row[3])),
                    longitude=float(_present(row[4])),
                    accuracy=int(_present(row[5])),
                    confidence=int(_present(row[6])),
                    status=int(_present(row[7])),
                ),
            )
            for row in rows
        ]

    def mark_delivered(self, item: Pending, now: int) -> None:
        with self._connection:
            _ = self._connection.execute(
                """
                UPDATE reports SET delivered_at = ?
                WHERE tag_id = ? AND source_id = ?
                    AND error IS NULL AND delivered_at IS NULL
                """,
                (now, item.tag_id, item.source_id),
            )

    def progress(self, now: int) -> None:
        with self._connection:
            _ = self._connection.execute(
                """
                INSERT INTO metadata(key, value) VALUES ('last_progress', ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (now,),
            )

    def status(self) -> dict[str, int | None]:
        reports, pending, rejected, delivered, latest = _required_row(self._connection.execute(
            """
            SELECT
                COUNT(*),
                SUM(error IS NULL AND delivered_at IS NULL),
                SUM(error IS NOT NULL),
                SUM(error IS NULL AND delivered_at IS NOT NULL),
                MAX(timestamp)
            FROM reports
            """,
        ))
        progress = FETCH_ONE(self._connection.execute(
            "SELECT value FROM metadata WHERE key = 'last_progress'",
        ))
        return {
            "reports": int(_present(reports)),
            "pending": int(pending or 0),
            "rejected": int(rejected or 0),
            "delivered": int(delivered or 0),
            "latest_report": int(latest) if latest is not None else None,
            "last_progress": int(_present(progress[0])) if progress is not None else None,
        }

    def backup(self, path: Path) -> None:
        if path.exists():
            raise FileExistsError("Backup destination already exists")
        if not path.parent.exists():
            path.parent.mkdir(parents=True, mode=0o700)
        descriptor, name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
        os.close(descriptor)
        temporary = Path(name)
        try:
            with closing(sqlite3.connect(temporary)) as destination:
                self._connection.backup(destination)
            os.link(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    def requeue(self, active_tags: tuple[str, ...]) -> int:
        if not active_tags:
            return 0
        placeholders = ", ".join("?" for _ in active_tags)
        with self._connection:
            cursor = self._connection.execute(
                f"""
                UPDATE reports SET delivered_at = NULL
                WHERE error IS NULL AND delivered_at IS NOT NULL AND tag_id IN ({placeholders})
                """,
                active_tags,
            )
        return cursor.rowcount
