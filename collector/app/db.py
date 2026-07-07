from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable

from .paths import data_dir, db_path, exports_dir


def _utc_now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat(timespec="seconds")


def ensure_dirs() -> None:
    data_dir().mkdir(parents=True, exist_ok=True)
    exports_dir().mkdir(parents=True, exist_ok=True)


def connect() -> sqlite3.Connection:
    ensure_dirs()
    conn = sqlite3.connect(str(db_path()), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS sources (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          name TEXT NOT NULL,
          base_url TEXT NOT NULL,
          format TEXT NOT NULL DEFAULT 'auto',
          enabled INTEGER NOT NULL DEFAULT 1,
          proxy TEXT,
          headers_json TEXT,
          last_ok_format TEXT,
          last_cursor_time TEXT,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS items (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          source_id INTEGER NOT NULL,
          vod_id TEXT,
          title TEXT NOT NULL,
          title_norm TEXT NOT NULL,
          type_id TEXT,
          type_name TEXT,
          vod_time TEXT,
          thumb_url TEXT,
          play_url TEXT,
          play_from TEXT,
          remarks TEXT,
          unique_key TEXT NOT NULL,
          raw_text TEXT,
          created_at TEXT NOT NULL,
          FOREIGN KEY(source_id) REFERENCES sources(id) ON DELETE CASCADE
        );

        CREATE UNIQUE INDEX IF NOT EXISTS idx_items_source_vod_id
          ON items(source_id, vod_id)
          WHERE vod_id IS NOT NULL;

        CREATE UNIQUE INDEX IF NOT EXISTS idx_items_source_unique_key
          ON items(source_id, unique_key);

        CREATE INDEX IF NOT EXISTS idx_items_title_norm ON items(title_norm);
        CREATE INDEX IF NOT EXISTS idx_items_vod_time ON items(vod_time);

        CREATE TABLE IF NOT EXISTS jobs (
          id TEXT PRIMARY KEY,
          status TEXT NOT NULL,
          mode TEXT NOT NULL,
          start_time TEXT,
          end_time TEXT,
          source_ids_json TEXT NOT NULL,
          concurrency INTEGER NOT NULL,
          created_at TEXT NOT NULL,
          started_at TEXT,
          finished_at TEXT,
          error TEXT
        );

        CREATE TABLE IF NOT EXISTS job_sources (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          job_id TEXT NOT NULL,
          source_id INTEGER NOT NULL,
          status TEXT NOT NULL,
          started_at TEXT,
          finished_at TEXT,
          fetched INTEGER NOT NULL DEFAULT 0,
          inserted INTEGER NOT NULL DEFAULT 0,
          skipped INTEGER NOT NULL DEFAULT 0,
          error TEXT,
          FOREIGN KEY(job_id) REFERENCES jobs(id) ON DELETE CASCADE,
          FOREIGN KEY(source_id) REFERENCES sources(id) ON DELETE CASCADE
        );
        """
    )
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(items);").fetchall()}
    if "thumb_url" not in cols:
        conn.execute("ALTER TABLE items ADD COLUMN thumb_url TEXT;")
    if "play_url" not in cols:
        conn.execute("ALTER TABLE items ADD COLUMN play_url TEXT;")
    conn.commit()


def json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def json_loads(value: str | None) -> Any:
    if not value:
        return None
    return json.loads(value)


@dataclass(frozen=True)
class SourceRow:
    id: int
    name: str
    base_url: str
    format: str
    enabled: int
    proxy: str | None
    headers: dict[str, str] | None
    last_ok_format: str | None
    last_cursor_time: str | None
    created_at: str
    updated_at: str


def row_to_source(row: sqlite3.Row) -> SourceRow:
    return SourceRow(
        id=int(row["id"]),
        name=str(row["name"]),
        base_url=str(row["base_url"]),
        format=str(row["format"]),
        enabled=int(row["enabled"]),
        proxy=row["proxy"],
        headers=json_loads(row["headers_json"]),
        last_ok_format=row["last_ok_format"],
        last_cursor_time=row["last_cursor_time"],
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )


def list_sources(conn: sqlite3.Connection) -> list[SourceRow]:
    cur = conn.execute("SELECT * FROM sources ORDER BY id DESC;")
    return [row_to_source(r) for r in cur.fetchall()]


def get_source(conn: sqlite3.Connection, source_id: int) -> SourceRow | None:
    cur = conn.execute("SELECT * FROM sources WHERE id = ?;", (source_id,))
    row = cur.fetchone()
    return row_to_source(row) if row else None


def create_source(
    conn: sqlite3.Connection,
    *,
    name: str,
    base_url: str,
    format: str,
    enabled: int,
    proxy: str | None,
    headers: dict[str, str] | None,
) -> int:
    now = _utc_now_iso()
    cur = conn.execute(
        """
        INSERT INTO sources(name, base_url, format, enabled, proxy, headers_json, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?);
        """,
        (name, base_url, format, enabled, proxy, json_dumps(headers) if headers else None, now, now),
    )
    conn.commit()
    return int(cur.lastrowid)


def update_source(
    conn: sqlite3.Connection,
    source_id: int,
    *,
    name: str,
    base_url: str,
    format: str,
    enabled: int,
    proxy: str | None,
    headers: dict[str, str] | None,
) -> None:
    now = _utc_now_iso()
    conn.execute(
        """
        UPDATE sources
        SET name = ?, base_url = ?, format = ?, enabled = ?, proxy = ?, headers_json = ?, updated_at = ?
        WHERE id = ?;
        """,
        (name, base_url, format, enabled, proxy, json_dumps(headers) if headers else None, now, source_id),
    )
    conn.commit()


def delete_source(conn: sqlite3.Connection, source_id: int) -> None:
    conn.execute("DELETE FROM sources WHERE id = ?;", (source_id,))
    conn.commit()


def set_source_last_ok_format(conn: sqlite3.Connection, source_id: int, fmt: str) -> None:
    now = _utc_now_iso()
    conn.execute(
        "UPDATE sources SET last_ok_format = ?, updated_at = ? WHERE id = ?;",
        (fmt, now, source_id),
    )
    conn.commit()


def set_source_cursor_time(conn: sqlite3.Connection, source_id: int, cursor_time: str | None) -> None:
    now = _utc_now_iso()
    conn.execute(
        "UPDATE sources SET last_cursor_time = ?, updated_at = ? WHERE id = ?;",
        (cursor_time, now, source_id),
    )
    conn.commit()


def create_job(
    conn: sqlite3.Connection,
    *,
    job_id: str,
    mode: str,
    start_time: str | None,
    end_time: str | None,
    source_ids: list[int],
    concurrency: int,
) -> None:
    now = _utc_now_iso()
    conn.execute(
        """
        INSERT INTO jobs(id, status, mode, start_time, end_time, source_ids_json, concurrency, created_at)
        VALUES (?, 'queued', ?, ?, ?, ?, ?, ?);
        """,
        (job_id, mode, start_time, end_time, json_dumps(source_ids), concurrency, now),
    )
    for sid in source_ids:
        conn.execute(
            "INSERT INTO job_sources(job_id, source_id, status) VALUES (?, ?, 'queued');",
            (job_id, sid),
        )
    conn.commit()


def job_set_status(conn: sqlite3.Connection, job_id: str, status: str, *, error: str | None = None) -> None:
    now = _utc_now_iso()
    if status == "running":
        conn.execute(
            "UPDATE jobs SET status = ?, started_at = ? WHERE id = ?;",
            (status, now, job_id),
        )
    elif status in ("success", "failed", "stopped"):
        conn.execute(
            "UPDATE jobs SET status = ?, finished_at = ?, error = ? WHERE id = ?;",
            (status, now, error, job_id),
        )
    else:
        conn.execute("UPDATE jobs SET status = ? WHERE id = ?;", (status, job_id))
    conn.commit()


def job_source_set_status(
    conn: sqlite3.Connection,
    job_id: str,
    source_id: int,
    status: str,
    *,
    fetched: int | None = None,
    inserted: int | None = None,
    skipped: int | None = None,
    error: str | None = None,
) -> None:
    now = _utc_now_iso()
    row = conn.execute(
        "SELECT started_at FROM job_sources WHERE job_id = ? AND source_id = ?;",
        (job_id, source_id),
    ).fetchone()
    started_at = row["started_at"] if row else None
    if status == "running" and not started_at:
        conn.execute(
            "UPDATE job_sources SET status = ?, started_at = ? WHERE job_id = ? AND source_id = ?;",
            (status, now, job_id, source_id),
        )
    elif status in ("success", "failed", "stopped"):
        conn.execute(
            """
            UPDATE job_sources
            SET status = ?, finished_at = ?, fetched = COALESCE(?, fetched),
                inserted = COALESCE(?, inserted), skipped = COALESCE(?, skipped), error = ?
            WHERE job_id = ? AND source_id = ?;
            """,
            (status, now, fetched, inserted, skipped, error, job_id, source_id),
        )
    else:
        conn.execute(
            """
            UPDATE job_sources
            SET status = ?, fetched = COALESCE(?, fetched),
                inserted = COALESCE(?, inserted), skipped = COALESCE(?, skipped), error = COALESCE(?, error)
            WHERE job_id = ? AND source_id = ?;
            """,
            (status, fetched, inserted, skipped, error, job_id, source_id),
        )
    conn.commit()


def list_jobs(conn: sqlite3.Connection, limit: int = 30) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?;", (limit,)).fetchall()
    return [dict(r) for r in rows]


def get_job(conn: sqlite3.Connection, job_id: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM jobs WHERE id = ?;", (job_id,)).fetchone()
    if not row:
        return None
    job = dict(row)
    sources = conn.execute(
        "SELECT * FROM job_sources WHERE job_id = ? ORDER BY id ASC;",
        (job_id,),
    ).fetchall()
    job["sources"] = [dict(r) for r in sources]
    return job


def insert_items(conn: sqlite3.Connection, rows: Iterable[dict[str, Any]]) -> tuple[int, int]:
    inserted = 0
    skipped = 0
    now = _utc_now_iso()
    for r in rows:
        try:
            conn.execute(
                """
                INSERT INTO items(
                  source_id, vod_id, title, title_norm, type_id, type_name, vod_time,
                  thumb_url, play_url, play_from, remarks, unique_key, raw_text, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    r.get("source_id"),
                    r.get("vod_id"),
                    r.get("title"),
                    r.get("title_norm"),
                    r.get("type_id"),
                    r.get("type_name"),
                    r.get("vod_time"),
                    r.get("thumb_url"),
                    r.get("play_url"),
                    r.get("play_from"),
                    r.get("remarks"),
                    r.get("unique_key"),
                    r.get("raw_text"),
                    now,
                ),
            )
            inserted += 1
        except sqlite3.IntegrityError:
            source_id = r.get("source_id")
            unique_key = r.get("unique_key")
            if source_id is None or unique_key is None:
                skipped += 1
                continue
            cur = conn.execute(
                """
                UPDATE items
                SET
                  thumb_url = CASE
                    WHEN (thumb_url IS NULL OR thumb_url = '') AND (? IS NOT NULL AND ? != '') THEN ?
                    ELSE thumb_url
                  END,
                  play_url = CASE
                    WHEN (play_url IS NULL OR play_url = '') AND (? IS NOT NULL AND ? != '') THEN ?
                    ELSE play_url
                  END
                WHERE source_id = ? AND unique_key = ?
                  AND (
                    ((thumb_url IS NULL OR thumb_url = '') AND (? IS NOT NULL AND ? != ''))
                    OR ((play_url IS NULL OR play_url = '') AND (? IS NOT NULL AND ? != ''))
                  );
                """,
                (
                    r.get("thumb_url"),
                    r.get("thumb_url"),
                    r.get("thumb_url"),
                    r.get("play_url"),
                    r.get("play_url"),
                    r.get("play_url"),
                    source_id,
                    unique_key,
                    r.get("thumb_url"),
                    r.get("thumb_url"),
                    r.get("play_url"),
                    r.get("play_url"),
                ),
            )
            if cur.rowcount == 0:
                skipped += 1
    conn.commit()
    return inserted, skipped


def clear_items(conn: sqlite3.Connection) -> None:
    conn.execute("DELETE FROM items;")
    conn.execute("DELETE FROM job_sources;")
    conn.execute("DELETE FROM jobs;")
    conn.execute("UPDATE sources SET last_cursor_time = NULL, last_ok_format = NULL;")
    conn.commit()


def dedup_by_title(conn: sqlite3.Connection) -> int:
    rows = conn.execute(
        """
        WITH ranked AS (
          SELECT
            id,
            ROW_NUMBER() OVER (
              PARTITION BY title_norm
              ORDER BY COALESCE(vod_time, '') DESC, id DESC
            ) AS rn
          FROM items
        )
        SELECT id FROM ranked WHERE rn > 1;
        """
    ).fetchall()
    ids = [int(r["id"]) for r in rows]
    if not ids:
        return 0
    conn.executemany("DELETE FROM items WHERE id = ?;", [(i,) for i in ids])
    conn.commit()
    return len(ids)
