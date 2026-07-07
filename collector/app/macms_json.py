from __future__ import annotations

import json
from typing import Any

from .models import VodItem
from .utils import normalize_title


def parse_list(text: str, *, source_id: int) -> tuple[dict[str, Any], list[VodItem]]:
    obj = json.loads(text.lstrip("\ufeff"))
    meta = {
        "page": obj.get("page"),
        "pagecount": obj.get("pagecount"),
        "limit": obj.get("limit"),
        "total": obj.get("total"),
    }
    items: list[VodItem] = []
    for it in obj.get("list") or []:
        title = str(it.get("vod_name") or "").strip()
        if not title:
            continue
        vod_id = it.get("vod_id")
        vod_id_str = str(vod_id) if vod_id is not None and str(vod_id) != "" else None
        type_id = it.get("type_id")
        type_id_str = str(type_id) if type_id is not None and str(type_id) != "" else None
        vod_time = it.get("vod_time")
        vod_time_str = str(vod_time) if vod_time is not None and str(vod_time) != "" else None
        play_from = it.get("vod_play_from")
        play_from_str = str(play_from) if play_from is not None and str(play_from) != "" else None
        remarks = it.get("vod_remarks")
        remarks_str = str(remarks) if remarks is not None and str(remarks) != "" else None

        title_norm = normalize_title(title)
        unique_key = vod_id_str or title_norm + "|" + (vod_time_str or "") + "|" + (play_from_str or "")

        items.append(
            VodItem(
                source_id=source_id,
                vod_id=vod_id_str,
                title=title,
                title_norm=title_norm,
                type_id=type_id_str,
                type_name=str(it.get("type_name") or "") or None,
                vod_time=vod_time_str,
                thumb_url=None,
                play_url=None,
                play_from=play_from_str,
                remarks=remarks_str,
                unique_key=unique_key,
                raw_text=json.dumps(it, ensure_ascii=False, separators=(",", ":")),
            )
        )
    return meta, items


def _extract_first_play_url(vod_play_url: str | None) -> str | None:
    if not vod_play_url:
        return None
    s = str(vod_play_url)
    if s.strip() == "":
        return None
    first = s.split("#", 1)[0]
    if "$" in first:
        return first.split("$", 1)[1].strip() or None
    return first.strip() or None


def parse_detail(text: str) -> dict[str, dict[str, str | None]]:
    obj = json.loads(text.lstrip("\ufeff"))
    out: dict[str, dict[str, str | None]] = {}
    for it in obj.get("list") or []:
        vod_id = it.get("vod_id")
        vod_id_str = str(vod_id) if vod_id is not None and str(vod_id) != "" else None
        if not vod_id_str:
            continue
        thumb_url = it.get("vod_pic")
        thumb_url_str = str(thumb_url) if thumb_url is not None and str(thumb_url) != "" else None
        play_url_str = _extract_first_play_url(it.get("vod_play_url"))
        out[vod_id_str] = {"thumb_url": thumb_url_str, "play_url": play_url_str}
    return out
