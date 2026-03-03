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

CREATE TABLE IF NOT EXISTS signals (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_id        TEXT NOT NULL REFERENCES scans(id) ON DELETE CASCADE,
    freq_mhz       REAL NOT NULL,
    power_db       REAL NOT NULL,
    prominence_db  REAL NOT NULL,
    bandwidth_khz  REAL NOT NULL,
    signal_type    TEXT,
    confidence     REAL,
    band           TEXT,
    duty_cycle     REAL,
    transient      INTEGER DEFAULT 0,
    created_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_signals_scan_id ON signals(scan_id);
CREATE INDEX IF NOT EXISTS idx_signals_freq ON signals(freq_mhz);

CREATE TABLE IF NOT EXISTS recordings (
    id             TEXT PRIMARY KEY,
    mode           TEXT NOT NULL,
    filename       TEXT NOT NULL,
    freq_mhz       REAL NOT NULL,
    bandwidth_khz  REAL,
    sample_rate    REAL NOT NULL,
    gain           REAL NOT NULL,
    start_mhz      REAL NOT NULL,
    stop_mhz       REAL NOT NULL,
    num_samples    INTEGER NOT NULL,
    file_size      INTEGER NOT NULL,
    created_at     TEXT NOT NULL,
    stopped_at     TEXT NOT NULL,
    duration_s     REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_recordings_created_at ON recordings(created_at);
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
    _migrate(_conn)
    _conn.commit()
    logger.info("Database ready: %s", path)


def _migrate(conn: sqlite3.Connection) -> None:
    cols = {r[1] for r in conn.execute("PRAGMA table_info(signals)").fetchall()}
    if "transient" not in cols:
        conn.execute("ALTER TABLE signals ADD COLUMN transient INTEGER DEFAULT 0")
        logger.info("Migration: added 'transient' column to signals")


def _compress(data: dict) -> bytes:
    return zlib.compress(json.dumps(data, separators=(",", ":")).encode(), level=6)


def _decompress(blob: bytes) -> dict:
    return json.loads(zlib.decompress(blob))


def save_scan(job) -> None:
    if not _conn:
        return
    p = job.params
    peaks = p.get("peaks", [])

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
        for pk in peaks:
            _conn.execute(
                """INSERT INTO signals
                   (scan_id, freq_mhz, power_db, prominence_db,
                    bandwidth_khz, signal_type, confidence, band, duty_cycle,
                    transient, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (job.id, pk["freq_mhz"], pk["power_db"],
                 pk["prominence_db"], pk["bandwidth_khz"],
                 pk.get("signal_type"), pk.get("confidence"),
                 pk.get("band"), pk.get("duty_cycle"),
                 int(pk.get("transient", False)),
                 job.created_at.isoformat()),
            )
        _conn.commit()
    logger.info("Saved scan %s (%d peaks)", job.id[:8], len(peaks))


def list_scans(limit: int = 50, offset: int = 0) -> dict:
    if not _conn:
        return {"scans": [], "total": 0}
    total = _conn.execute("SELECT COUNT(*) FROM scans").fetchone()[0]
    rows = _conn.execute(
        """SELECT s.id, s.start_mhz, s.stop_mhz, s.duration, s.gain,
                  s.created_at, s.duration_s,
                  (SELECT COUNT(*) FROM signals WHERE scan_id = s.id) AS num_peaks
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

    signals = _conn.execute(
        "SELECT * FROM signals WHERE scan_id = ? ORDER BY prominence_db DESC",
        (scan_id,),
    ).fetchall()
    peaks = []
    for s in signals:
        d = dict(s)
        d.pop("id", None)
        d.pop("scan_id", None)
        d["transient"] = bool(d.get("transient", 0))
        peaks.append(d)

    return {
        "id": row["id"],
        "type": "scan",
        "status": "complete",
        "params": {
            "start_mhz": row["start_mhz"],
            "stop_mhz": row["stop_mhz"],
            "duration": row["duration"],
            "gain": row["gain"],
            "peaks": peaks,
            **({"spectrum_data": spectrum} if spectrum else {}),
            **({"waterfall_data": waterfall} if waterfall else {}),
        },
        "error": None,
        "created_at": row["created_at"],
        "duration_s": row["duration_s"],
    }


# ── Recordings ────────────────────────────────────────

RECORDINGS_DIR = DB_DIR / "recordings"


def save_recording(meta: dict) -> None:
    if not _conn:
        return
    with _lock:
        _conn.execute(
            """INSERT INTO recordings
               (id, mode, filename, freq_mhz, bandwidth_khz, sample_rate,
                gain, start_mhz, stop_mhz, num_samples, file_size,
                created_at, stopped_at, duration_s)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (meta["id"], meta["mode"], meta["filename"], meta["freq_mhz"],
             meta.get("bandwidth_khz"), meta["sample_rate"], meta["gain"],
             meta["start_mhz"], meta["stop_mhz"], meta["num_samples"],
             meta["file_size"], meta["created_at"], meta["stopped_at"],
             meta["duration_s"]),
        )
        _conn.commit()
    logger.info("Saved recording %s (%s, %.1f MHz, %.1fs)",
                meta["id"][:8], meta["mode"], meta["freq_mhz"], meta["duration_s"])


def list_recordings(limit: int = 50, offset: int = 0) -> dict:
    if not _conn:
        return {"recordings": [], "total": 0}
    total = _conn.execute("SELECT COUNT(*) FROM recordings").fetchone()[0]
    rows = _conn.execute(
        """SELECT id, mode, filename, freq_mhz, bandwidth_khz, sample_rate,
                  gain, start_mhz, stop_mhz, num_samples, file_size,
                  created_at, stopped_at, duration_s
           FROM recordings ORDER BY created_at DESC LIMIT ? OFFSET ?""",
        (limit, offset),
    ).fetchall()
    return {"recordings": [dict(r) for r in rows], "total": total}


def delete_recording(rec_id: str) -> bool:
    if not _conn:
        return False
    row = _conn.execute("SELECT filename FROM recordings WHERE id = ?", (rec_id,)).fetchone()
    if not row:
        return False
    filepath = RECORDINGS_DIR / row["filename"]
    with _lock:
        _conn.execute("DELETE FROM recordings WHERE id = ?", (rec_id,))
        _conn.commit()
    if filepath.exists():
        filepath.unlink()
    logger.info("Deleted recording %s", rec_id[:8])
    return True
