from __future__ import annotations

import asyncio
import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .db import (
    ensure_dirs,
    clear_items,
    connect,
    create_source,
    dedup_by_title,
    get_job,
    get_source,
    init_db,
    list_jobs,
    list_sources,
    update_source,
    delete_source,
    json_loads,
)
from .paths import exports_dir, web_dir
from .service import create_collect_job, start_job_task, stop_job


app = FastAPI()
ensure_dirs()


def _utc_now_str() -> str:
    return datetime.now(tz=timezone.utc).isoformat(timespec="seconds")


@app.on_event("startup")
def _startup() -> None:
    conn = connect()
    init_db(conn)


web_path = web_dir()
app.mount("/static", StaticFiles(directory=str(web_path)), name="static")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(str(web_path / "index.html"))

@app.get("/source")
def source_page() -> FileResponse:
    return FileResponse(str(web_path / "source.html"))

@app.get("/job")
def job_page() -> FileResponse:
    return FileResponse(str(web_path / "job.html"))


@app.get("/api/sources")
def api_list_sources() -> list[dict[str, Any]]:
    conn = connect()
    return [
        {
            "id": s.id,
            "name": s.name,
            "base_url": s.base_url,
            "format": s.format,
            "enabled": bool(s.enabled),
            "proxy": s.proxy,
            "headers": s.headers or {},
            "last_ok_format": s.last_ok_format,
            "last_cursor_time": s.last_cursor_time,
            "created_at": s.created_at,
            "updated_at": s.updated_at,
        }
        for s in list_sources(conn)
    ]

@app.get("/api/sources/{source_id}/today")
async def api_source_today(source_id: int) -> dict[str, Any]:
    conn = connect()
    src = get_source(conn, source_id)
    if not src:
        raise HTTPException(status_code=404, detail="source not found")
    from .service_preview import preview_source_today

    return await preview_source_today(source_id=source_id)


@app.post("/api/sources")
def api_create_source(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    name = str(payload.get("name") or "").strip()
    base_url = str(payload.get("base_url") or "").strip()
    fmt = str(payload.get("format") or "auto").strip()
    enabled = 1 if bool(payload.get("enabled", True)) else 0
    proxy = str(payload.get("proxy") or "").strip() or None
    headers = payload.get("headers") or {}
    if not isinstance(headers, dict):
        raise HTTPException(status_code=400, detail="headers must be object")

    if name == "" or base_url == "":
        raise HTTPException(status_code=400, detail="name/base_url required")
    if fmt not in ("auto", "json", "xml"):
        raise HTTPException(status_code=400, detail="format invalid")

    conn = connect()
    source_id = create_source(
        conn,
        name=name,
        base_url=base_url,
        format=fmt,
        enabled=enabled,
        proxy=proxy,
        headers={str(k): str(v) for k, v in headers.items()} if headers else None,
    )
    return {"id": source_id}


@app.put("/api/sources/{source_id}")
def api_update_source(source_id: int, payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    conn = connect()
    src = get_source(conn, source_id)
    if not src:
        raise HTTPException(status_code=404, detail="source not found")

    name = str(payload.get("name") or "").strip()
    base_url = str(payload.get("base_url") or "").strip()
    fmt = str(payload.get("format") or "auto").strip()
    enabled = 1 if bool(payload.get("enabled", True)) else 0
    proxy = str(payload.get("proxy") or "").strip() or None
    headers = payload.get("headers") or {}
    if not isinstance(headers, dict):
        raise HTTPException(status_code=400, detail="headers must be object")

    if name == "" or base_url == "":
        raise HTTPException(status_code=400, detail="name/base_url required")
    if fmt not in ("auto", "json", "xml"):
        raise HTTPException(status_code=400, detail="format invalid")

    update_source(
        conn,
        source_id,
        name=name,
        base_url=base_url,
        format=fmt,
        enabled=enabled,
        proxy=proxy,
        headers={str(k): str(v) for k, v in headers.items()} if headers else None,
    )
    return {"ok": True}


@app.delete("/api/sources/{source_id}")
def api_delete_source(source_id: int) -> dict[str, Any]:
    conn = connect()
    delete_source(conn, source_id)
    return {"ok": True}


@app.post("/api/collect")
async def api_collect(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    mode = str(payload.get("mode") or "daily").strip()
    if mode not in ("daily", "range", "full"):
        raise HTTPException(status_code=400, detail="mode invalid")

    start_time = str(payload.get("start_time") or "").strip() or None
    end_time = str(payload.get("end_time") or "").strip() or None
    concurrency = int(payload.get("concurrency") or 5)
    src_ids = payload.get("source_ids")
    if src_ids is not None:
        if not isinstance(src_ids, list):
            raise HTTPException(status_code=400, detail="source_ids must be array")
        source_ids = [int(x) for x in src_ids]
    else:
        source_ids = None

    job_id, source_ids_final = create_collect_job(
        mode=mode,
        start_time=start_time,
        end_time=end_time,
        source_ids=source_ids,
        concurrency=concurrency,
    )
    start_job_task(
        loop=asyncio.get_running_loop(),
        job_id=job_id,
        source_ids=source_ids_final,
        mode=mode,
        start_time=start_time,
        end_time=end_time,
        concurrency=concurrency,
    )
    return {"job_id": job_id}


@app.get("/api/jobs")
def api_jobs() -> list[dict[str, Any]]:
    conn = connect()
    return list_jobs(conn, limit=30)


@app.get("/api/jobs/{job_id}")
def api_job(job_id: str) -> dict[str, Any]:
    conn = connect()
    job = get_job(conn, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    job["source_ids"] = json_loads(job.get("source_ids_json")) or []
    return job

@app.delete("/api/jobs/{job_id}")
def api_delete_job(job_id: str) -> dict[str, Any]:
    conn = connect()
    job = get_job(conn, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    if job.get("status") in ("queued", "running"):
        raise HTTPException(status_code=400, detail="job is running, stop first")
    conn.execute("DELETE FROM jobs WHERE id = ?;", (job_id,))
    conn.commit()
    return {"ok": True}

@app.post("/api/jobs/{job_id}/stop")
def api_stop_job(job_id: str) -> dict[str, Any]:
    conn = connect()
    job = get_job(conn, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    stopped = stop_job(job_id)
    if stopped:
        return {"stopped": True}

    if job.get("status") in ("queued", "running"):
        conn.execute(
            """
            UPDATE job_sources
            SET status = 'stopped', finished_at = COALESCE(finished_at, ?), error = COALESCE(error, 'stopped')
            WHERE job_id = ? AND status IN ('queued', 'running');
            """,
            (_utc_now_str(), job_id),
        )
        conn.execute(
            "UPDATE jobs SET status = 'stopped', finished_at = COALESCE(finished_at, ?), error = COALESCE(error, 'stopped') WHERE id = ?;",
            (_utc_now_str(), job_id),
        )
        conn.commit()
        return {"stopped": True}

    return {"stopped": False}


@app.post("/api/dedup")
def api_dedup(payload: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    mode = str(payload.get("mode") or "title").strip()
    if mode != "title":
        raise HTTPException(status_code=400, detail="only title dedup supported")
    conn = connect()
    deleted = dedup_by_title(conn)
    return {"deleted": deleted}


@app.post("/api/clear")
def api_clear() -> dict[str, Any]:
    conn = connect()
    clear_items(conn)
    return {"ok": True}


@app.post("/api/export")
def api_export(payload: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    conn = connect()

    keyword = str(payload.get("keyword") or "").strip()
    source_id = payload.get("source_id")
    start_time = str(payload.get("start_time") or "").strip()
    end_time = str(payload.get("end_time") or "").strip()

    where = []
    params: list[Any] = []
    if keyword:
        where.append("title LIKE ?")
        params.append(f"%{keyword}%")
    if source_id is not None and str(source_id) != "":
        where.append("source_id = ?")
        params.append(int(source_id))
    if start_time:
        where.append("vod_time >= ?")
        params.append(start_time)
    if end_time:
        where.append("vod_time <= ?")
        params.append(end_time)

    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    rows = conn.execute(
        f"""
        SELECT
          s.name AS source,
          i.vod_id AS vod_id,
          i.title AS title,
          i.type_name AS type_name,
          i.vod_time AS vod_time,
          i.thumb_url AS thumb_url,
          i.play_url AS play_url,
          i.play_from AS play_from,
          i.remarks AS remarks
        FROM items i
        JOIN sources s ON s.id = i.source_id
        {where_sql}
        ORDER BY COALESCE(i.vod_time, '') DESC, i.id DESC;
        """,
        params,
    ).fetchall()

    ts = _utc_now_str().replace(":", "").replace("-", "")
    name = f"export_{ts}.csv"
    out_path = exports_dir() / name
    with out_path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["source", "vod_id", "title", "type_name", "vod_time", "thumb_url", "play_url", "play_from", "remarks"])
        for r in rows:
            w.writerow(
                [
                    r["source"],
                    r["vod_id"],
                    r["title"],
                    r["type_name"],
                    r["vod_time"],
                    r["thumb_url"],
                    r["play_url"],
                    r["play_from"],
                    r["remarks"],
                ]
            )

    return {"file": f"/exports/{name}", "count": len(rows)}


app.mount("/exports", StaticFiles(directory=str(exports_dir())), name="exports")
