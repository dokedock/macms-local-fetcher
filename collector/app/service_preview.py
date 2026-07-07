from __future__ import annotations

from datetime import datetime
from typing import Any

from . import macms_json, macms_xml
from .db import get_source, connect
from .fetcher import fetch_text, make_client
from .service import _detect_format, _urls_for_source, _url_for_detail


def _today_str() -> str:
    return datetime.now().astimezone().date().isoformat()


async def preview_source_today(*, source_id: int, limit: int = 200) -> dict[str, Any]:
    conn = connect()
    source = get_source(conn, source_id)
    if not source:
        return {"source_id": source_id, "count": 0, "items": [], "error": "source not found"}

    today = _today_str()

    fmt_pref = source.format
    if fmt_pref == "json":
        trial_order = ["json"]
    elif fmt_pref == "xml":
        trial_order = ["xml"]
    else:
        if source.last_ok_format in ("json", "xml"):
            trial_order = [source.last_ok_format, "xml" if source.last_ok_format == "json" else "json"]
        else:
            trial_order = ["json", "xml"]

    for fmt in trial_order:
        pages_scanned = 0
        items_out: list[dict[str, Any]] = []
        client = make_client(proxy=source.proxy, headers=source.headers)
        try:
            page = 1
            while True:
                url = _urls_for_source(source, fmt, page)
                text = await fetch_text(url, proxy=source.proxy, headers=source.headers, client=client)
                real_fmt = _detect_format(text)
                if fmt_pref in ("json", "xml") and real_fmt != fmt:
                    raise ValueError("format mismatch")
                if real_fmt == "json":
                    _, items = macms_json.parse_list(text, source_id=source.id)
                elif real_fmt == "xml":
                    _, items = macms_xml.parse_list(text, source_id=source.id)
                else:
                    raise ValueError("unknown format")

                pages_scanned += 1

                stop = False
                for it in items:
                    if it.vod_time and it.vod_time[:10] != today:
                        stop = True
                        continue
                    if it.vod_time and it.vod_time[:10] == today:
                        items_out.append(
                            {
                                "source_id": it.source_id,
                                "vod_id": it.vod_id,
                                "title": it.title,
                                "type_id": it.type_id,
                                "type_name": it.type_name,
                                "vod_time": it.vod_time,
                                "play_from": it.play_from,
                                "remarks": it.remarks,
                            }
                        )
                        if len(items_out) >= limit:
                            stop = True
                            break

                if stop:
                    break
                if not items:
                    break
                page += 1

            ids = [x.get("vod_id") for x in items_out if x.get("vod_id")]
            ids = [str(x) for x in ids if x]
            if ids:
                for i in range(0, len(ids), 20):
                    chunk = ids[i : i + 20]
                    detail_url = _url_for_detail(source, fmt, chunk)
                    detail_text = await fetch_text(detail_url, proxy=source.proxy, headers=source.headers, client=client)
                    real_detail_fmt = _detect_format(detail_text)
                    if real_detail_fmt == "json":
                        detail_map = macms_json.parse_detail(detail_text)
                    elif real_detail_fmt == "xml":
                        detail_map = macms_xml.parse_detail(detail_text)
                    else:
                        detail_map = {}
                    for it in items_out:
                        vid = it.get("vod_id")
                        if not vid:
                            continue
                        d = detail_map.get(str(vid))
                        if not d:
                            continue
                        it["thumb_url"] = d.get("thumb_url")
                        it["play_url"] = d.get("play_url")

            return {
                "source_id": source_id,
                "date": today,
                "format": fmt,
                "pages_scanned": pages_scanned,
                "count": len(items_out),
                "items": items_out,
            }
        except Exception as e:
            if fmt_pref in ("json", "xml"):
                return {"source_id": source_id, "count": 0, "items": [], "error": str(e)}
            continue
        finally:
            await client.aclose()

    return {"source_id": source_id, "count": 0, "items": [], "error": "no usable format"}
