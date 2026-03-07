"""SQLite persistence for scan history."""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import zlib
from pathlib import Path

logger = logging.getLogger("rfsentinel.db")

_conn: sqlite3.Connection | None = None
_lock = threading.Lock()

DB_DIR = Path(__file__).resolve().parent.parent.parent / "data"
DB_PATH = DB_DIR / "rfsentinel.db"

_SCHEMA = """\
CREATE TABLE IF NOT EXISTS scans (
    id            TEXT PRIMARY KEY,
    start_mhz     REAL NOT NULL,
    stop_mhz      REAL NOT NULL,
    duration       REAL NOT NULL,
    gain           REAL NOT NULL,
    created_at     TEXT NOT NULL,
    duration_s     REAL,
    spectrum_data  BLOB,
    waterfall_data BLOB
);
CREATE INDEX IF NOT EXISTS idx_scans_created_at ON scans(created_at);
"""


def init(db_path: Path | None = None) -> None:
    global _conn
    path = db_path or DB_PATH
    os.makedirs(path.parent, exist_ok=True)
    _conn = sqlite3.connect(str(path), check_same_thread=False)
    _conn.row_factory = sqlite3.Row
    _conn.execute("PRAGMA journal_mode=WAL")
    _conn.execute("PRAGMA foreign_keys=ON")
    _conn.executescript(_SCHEMA)
    _conn.commit()
    logger.info("Database ready: %s", path)


def _compress(data: dict) -> bytes:
    return zlib.compress(json.dumps(data, separators=(",", ":")).encode(), level=6)


def _decompress(blob: bytes) -> dict:
    return json.loads(zlib.decompress(blob))


def save_scan(job) -> None:
    if not _conn:
        return
    p = job.params

    spectrum_blob = _compress(p["spectrum_data"]) if "spectrum_data" in p else None
    waterfall_blob = _compress(p["waterfall_data"]) if "waterfall_data" in p else None

    with _lock:
        _conn.execute(
            """INSERT OR REPLACE INTO scans
               (id, start_mhz, stop_mhz, duration, gain,
                created_at, duration_s,
                spectrum_data, waterfall_data)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (job.id, p["start_mhz"], p["stop_mhz"],
             p["duration"], p["gain"],
             job.created_at.isoformat(), job.duration_s,
             spectrum_blob, waterfall_blob),
        )
        _conn.commit()
    logger.info("Saved scan %s", job.id[:8])


def list_scans(limit: int = 50, offset: int = 0) -> dict:
    if not _conn:
        return {"scans": [], "total": 0}
    total = _conn.execute("SELECT COUNT(*) FROM scans").fetchone()[0]
    rows = _conn.execute(
        """SELECT s.id, s.start_mhz, s.stop_mhz, s.duration, s.gain,
                  s.created_at, s.duration_s
           FROM scans s ORDER BY s.created_at DESC LIMIT ? OFFSET ?""",
        (limit, offset),
    ).fetchall()
    return {"scans": [dict(r) for r in rows], "total": total}


def delete_scan(scan_id: str) -> bool:
    if not _conn:
        return False
    with _lock:
        cur = _conn.execute("DELETE FROM scans WHERE id = ?", (scan_id,))
        _conn.commit()
    deleted = cur.rowcount > 0
    if deleted:
        logger.info("Deleted scan %s", scan_id[:8])
    return deleted


def get_scan(scan_id: str) -> dict | None:
    if not _conn:
        return None
    row = _conn.execute("SELECT * FROM scans WHERE id = ?", (scan_id,)).fetchone()
    if not row:
        return None
    row = dict(row)

    spectrum = _decompress(row.pop("spectrum_data")) if row.get("spectrum_data") else None
    waterfall = _decompress(row.pop("waterfall_data")) if row.get("waterfall_data") else None

    return {
        "id": row["id"],
        "type": "scan",
        "status": "complete",
        "params": {
            "start_mhz": row["start_mhz"],
            "stop_mhz": row["stop_mhz"],
            "duration": row["duration"],
            "gain": row["gain"],
            **({"spectrum_data": spectrum} if spectrum else {}),
            **({"waterfall_data": waterfall} if waterfall else {}),
        },
        "error": None,
        "created_at": row["created_at"],
        "duration_s": row["duration_s"],
    }

