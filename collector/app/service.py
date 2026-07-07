from __future__ import annotations

import asyncio
from dataclasses import asdict
from datetime import datetime
from typing import Any, Literal
from uuid import uuid4

from . import macms_json, macms_xml
from .db import (
    SourceRow,
    connect,
    create_job,
    get_source,
    insert_items,
    job_set_status,
    job_source_set_status,
    json_loads,
    list_sources,
    set_source_cursor_time,
    set_source_last_ok_format,
)
from .fetcher import fetch_text, make_client
from .utils import join_url


CollectMode = Literal["daily", "range", "full"]

_JOB_TASKS: dict[str, asyncio.Task[None]] = {}


def new_job_id() -> str:
    return uuid4().hex


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace(" ", "T"))
    except ValueError:
        return None


def _should_stop(mode: CollectMode, *, item_time: str | None, daily_cursor: str | None, start: str | None) -> bool:
    t = _parse_time(item_time)
    if not t:
        return False
    if mode == "daily" and daily_cursor:
        cursor_t = _parse_time(daily_cursor)
        if cursor_t and t <= cursor_t:
            return True
    if mode == "range" and start:
        start_t = _parse_time(start)
        if start_t and t < start_t:
            return True
    return False


def _in_range(mode: CollectMode, *, item_time: str | None, start: str | None, end: str | None) -> bool:
    if mode != "range":
        return True
    t = _parse_time(item_time)
    if not t:
        return False
    start_t = _parse_time(start) if start else None
    end_t = _parse_time(end) if end else None
    if start_t and t < start_t:
        return False
    if end_t and t > end_t:
        return False
    return True


def _urls_for_source(source: SourceRow, fmt: str, page: int) -> str:
    base = source.base_url
    if fmt == "json":
        url = base
        if "?" in url:
            if not url.endswith("&") and not url.endswith("?"):
                url += "&"
        else:
            if not url.endswith("?"):
                url += "?"
        url += f"ac=list&pg={page}"
        return url

    url = join_url(base, "at/xml/")
    if "?" in url:
        if not url.endswith("&") and not url.endswith("?"):
            url += "&"
    else:
        if not url.endswith("?"):
            url += "?"
    url += f"pg={page}"
    return url


def _url_for_detail(source: SourceRow, fmt: str, ids: list[str]) -> str:
    base = source.base_url
    ids_param = ",".join(ids)
    if fmt == "json":
        url = base
        if "?" in url:
            if not url.endswith("&") and not url.endswith("?"):
                url += "&"
        else:
            if not url.endswith("?"):
                url += "?"
        url += f"ac=detail&ids={ids_param}"
        return url

    url = join_url(base, "at/xml/")
    if "?" in url:
        if not url.endswith("&") and not url.endswith("?"):
            url += "&"
    else:
        if not url.endswith("?"):
            url += "?"
    url += f"ac=detail&ids={ids_param}"
    return url


def _detect_format(text: str) -> str:
    s = text.lstrip().lstrip("\ufeff").lstrip()
    if s.startswith("{"):
        return "json"
    if s.startswith("<"):
        head = s[:200].lower()
        if head.startswith("<?xml") or "<rss" in head:
            return "xml"
        return "unknown"
    return "unknown"


async def _fetch_detail_map(
    *,
    source: SourceRow,
    fmt: str,
    ids: list[str],
    client,
) -> dict[str, dict[str, str | None]]:
    url = _url_for_detail(source, fmt, ids)
    text = await fetch_text(url, proxy=source.proxy, headers=source.headers, client=client)
    real_fmt = _detect_format(text)
    if real_fmt == "json":
        return macms_json.parse_detail(text)
    if real_fmt == "xml":
        return macms_xml.parse_detail(text)
    raise ValueError("unknown detail format")


async def _enrich_items_with_detail(
    *,
    source: SourceRow,
    fmt: str,
    items: list[dict[str, Any]],
    client,
) -> None:
    ids = [str(it["vod_id"]) for it in items if it.get("vod_id")]
    if not ids:
        return
    for i in range(0, len(ids), 20):
        chunk = ids[i : i + 20]
        detail = await _fetch_detail_map(source=source, fmt=fmt, ids=chunk, client=client)
        for it in items:
            vid = it.get("vod_id")
            if not vid:
                continue
            d = detail.get(str(vid))
            if not d:
                continue
            if d.get("thumb_url"):
                it["thumb_url"] = d.get("thumb_url")
            if d.get("play_url"):
                it["play_url"] = d.get("play_url")


async def collect_one_source(
    *,
    job_id: str,
    source_id: int,
    mode: CollectMode,
    start_time: str | None,
    end_time: str | None,
) -> dict[str, Any]:
    conn = connect()
    source = get_source(conn, source_id)
    if not source or not source.enabled:
        job_source_set_status(conn, job_id, source_id, "failed", error="source not found or disabled")
        return {"source_id": source_id, "status": "failed"}

    job_source_set_status(conn, job_id, source_id, "running")

    fmt_pref = source.format
    trial_order: list[str]
    if fmt_pref == "json":
        trial_order = ["json"]
    elif fmt_pref == "xml":
        trial_order = ["xml"]
    else:
        if source.last_ok_format in ("json", "xml"):
            trial_order = [source.last_ok_format, "xml" if source.last_ok_format == "json" else "json"]
        else:
            trial_order = ["json", "xml"]

    fetched = 0
    inserted_total = 0
    skipped_total = 0
    newest_time: str | None = None
    last_error: str | None = None

    daily_cursor = source.last_cursor_time if mode == "daily" else None

    client = make_client(proxy=source.proxy, headers=source.headers)
    try:
        for fmt in trial_order:
            try:
                page = 1
                while True:
                    url = _urls_for_source(source, fmt, page)
                    text = await fetch_text(url, proxy=source.proxy, headers=source.headers, client=client)
                    real_fmt = _detect_format(text)
                    if fmt_pref in ("json", "xml"):
                        if real_fmt != fmt:
                            raise ValueError("format mismatch")
                    if real_fmt == "json":
                        meta, items = macms_json.parse_list(text, source_id=source.id)
                    elif real_fmt == "xml":
                        meta, items = macms_xml.parse_list(text, source_id=source.id)
                    else:
                        raise ValueError("unknown format")

                    fetched += len(items)

                    rows: list[dict[str, Any]] = []
                    stop = False
                    for it in items:
                        if it.vod_time and (newest_time is None or it.vod_time > newest_time):
                            newest_time = it.vod_time

                        if _should_stop(mode, item_time=it.vod_time, daily_cursor=daily_cursor, start=start_time):
                            stop = True
                            continue
                        if not _in_range(mode, item_time=it.vod_time, start=start_time, end=end_time):
                            continue
                        rows.append(asdict(it))

                    await _enrich_items_with_detail(source=source, fmt=fmt, items=rows, client=client)

                    ins, sk = insert_items(conn, rows)
                    inserted_total += ins
                    skipped_total += sk
                    job_source_set_status(
                        conn,
                        job_id,
                        source_id,
                        "running",
                        fetched=fetched,
                        inserted=inserted_total,
                        skipped=skipped_total,
                    )

                    pagecount = meta.get("pagecount")
                    try:
                        pagecount_int = int(pagecount) if pagecount is not None else None
                    except (TypeError, ValueError):
                        pagecount_int = None

                    if stop:
                        break
                    if pagecount_int and page >= pagecount_int:
                        break
                    if not items:
                        break
                    page += 1

                set_source_last_ok_format(conn, source.id, fmt)
                break
            except asyncio.CancelledError:
                job_source_set_status(
                    conn,
                    job_id,
                    source_id,
                    "stopped",
                    fetched=fetched,
                    inserted=inserted_total,
                    skipped=skipped_total,
                    error="stopped",
                )
                raise
            except Exception as e:
                if fmt_pref in ("json", "xml"):
                    job_source_set_status(conn, job_id, source_id, "failed", error=str(e))
                    raise
                last_error = str(e)
                job_source_set_status(conn, job_id, source_id, "running", error=last_error)
                continue
        else:
            err = "no usable format"
            if last_error:
                err = f"{err}: {last_error}"
            job_source_set_status(conn, job_id, source_id, "failed", error=err)
            return {"source_id": source_id, "status": "failed"}
    finally:
        await client.aclose()

    if mode in ("daily", "full") and newest_time:
        set_source_cursor_time(conn, source.id, newest_time)

    job_source_set_status(
        conn,
        job_id,
        source_id,
        "success",
        fetched=fetched,
        inserted=inserted_total,
        skipped=skipped_total,
    )
    return {
        "source_id": source_id,
        "status": "success",
        "fetched": fetched,
        "inserted": inserted_total,
        "skipped": skipped_total,
        "newest_time": newest_time,
    }


async def run_job(
    *,
    job_id: str,
    source_ids: list[int],
    mode: CollectMode,
    start_time: str | None,
    end_time: str | None,
    concurrency: int,
) -> None:
    conn = connect()
    job_set_status(conn, job_id, "running")

    sem = asyncio.Semaphore(max(1, concurrency))

    async def _run_one(sid: int) -> dict[str, Any]:
        async with sem:
            return await collect_one_source(
                job_id=job_id,
                source_id=sid,
                mode=mode,
                start_time=start_time,
                end_time=end_time,
            )

    try:
        await asyncio.gather(*[_run_one(sid) for sid in source_ids])
        failed_count = conn.execute(
            "SELECT COUNT(1) AS c FROM job_sources WHERE job_id = ? AND status = 'failed';",
            (job_id,),
        ).fetchone()["c"]
        stopped_count = conn.execute(
            "SELECT COUNT(1) AS c FROM job_sources WHERE job_id = ? AND status = 'stopped';",
            (job_id,),
        ).fetchone()["c"]
        if int(stopped_count) > 0:
            job_set_status(conn, job_id, "stopped", error="stopped")
        elif int(failed_count) > 0:
            job_set_status(conn, job_id, "failed", error="some sources failed")
        else:
            job_set_status(conn, job_id, "success")
    except asyncio.CancelledError:
        conn.execute(
            """
            UPDATE job_sources
            SET status = 'stopped', finished_at = COALESCE(finished_at, ?), error = COALESCE(error, 'stopped')
            WHERE job_id = ? AND status IN ('queued', 'running');
            """,
            (datetime.now().isoformat(timespec="seconds"), job_id),
        )
        conn.commit()
        job_set_status(conn, job_id, "stopped", error="stopped")
        raise
    except Exception as e:
        job_set_status(conn, job_id, "failed", error=str(e))
    finally:
        _JOB_TASKS.pop(job_id, None)


def create_collect_job(
    *,
    mode: CollectMode,
    start_time: str | None,
    end_time: str | None,
    source_ids: list[int] | None,
    concurrency: int,
) -> tuple[str, list[int]]:
    conn = connect()
    all_sources = list_sources(conn)
    if source_ids is None:
        source_ids = [s.id for s in all_sources if s.enabled]
    job_id = new_job_id()
    create_job(
        conn,
        job_id=job_id,
        mode=mode,
        start_time=start_time,
        end_time=end_time,
        source_ids=source_ids,
        concurrency=concurrency,
    )
    return job_id, source_ids


def start_job_task(
    *,
    loop: asyncio.AbstractEventLoop,
    job_id: str,
    source_ids: list[int],
    mode: CollectMode,
    start_time: str | None,
    end_time: str | None,
    concurrency: int,
) -> None:
    task = loop.create_task(
        run_job(
            job_id=job_id,
            source_ids=source_ids,
            mode=mode,
            start_time=start_time,
            end_time=end_time,
            concurrency=concurrency,
        )
    )
    _JOB_TASKS[job_id] = task


def stop_job(job_id: str) -> bool:
    task = _JOB_TASKS.get(job_id)
    if not task or task.done():
        return False
    task.cancel()
    return True
