from __future__ import annotations

from typing import Any
from xml.etree import ElementTree as ET

from .models import VodItem
from .utils import normalize_title


def _text(el: ET.Element | None) -> str | None:
    if el is None:
        return None
    if el.text is None:
        return None
    t = el.text.strip()
    return t if t != "" else None


def parse_list(text: str, *, source_id: int) -> tuple[dict[str, Any], list[VodItem]]:
    root = ET.fromstring(text.lstrip("\ufeff"))
    list_el = root.find("list")
    meta: dict[str, Any] = {}
    if list_el is not None:
        meta = {
            "page": list_el.attrib.get("page"),
            "pagecount": list_el.attrib.get("pagecount"),
            "limit": list_el.attrib.get("pagesize"),
            "total": list_el.attrib.get("recordcount"),
        }
    items: list[VodItem] = []
    if list_el is None:
        return meta, items
    for v in list_el.findall("video"):
        vod_id = _text(v.find("id"))
        title = _text(v.find("name")) or ""
        title = title.strip()
        if not title:
            continue
        type_id = _text(v.find("tid"))
        type_name = _text(v.find("type"))
        vod_time = _text(v.find("last"))
        play_from = _text(v.find("dt"))
        remarks = _text(v.find("note"))

        title_norm = normalize_title(title)
        unique_key = vod_id or title_norm + "|" + (vod_time or "") + "|" + (play_from or "")

        raw_piece = ET.tostring(v, encoding="unicode")
        items.append(
            VodItem(
                source_id=source_id,
                vod_id=vod_id,
                title=title,
                title_norm=title_norm,
                type_id=type_id,
                type_name=type_name,
                vod_time=vod_time,
                thumb_url=None,
                play_url=None,
                play_from=play_from,
                remarks=remarks,
                unique_key=unique_key,
                raw_text=raw_piece,
            )
        )
    return meta, items


def _extract_first_play_url(dd_text: str | None) -> str | None:
    if not dd_text:
        return None
    s = str(dd_text)
    if s.strip() == "":
        return None
    first = s.split("#", 1)[0]
    if "$" in first:
        return first.split("$", 1)[1].strip() or None
    return first.strip() or None


def parse_detail(text: str) -> dict[str, dict[str, str | None]]:
    root = ET.fromstring(text.lstrip("\ufeff"))
    out: dict[str, dict[str, str | None]] = {}
    list_el = root.find("list")
    if list_el is None:
        return out
    for v in list_el.findall("video"):
        vod_id = _text(v.find("id"))
        if not vod_id:
            continue
        thumb_url = _text(v.find("pic"))
        play_url: str | None = None
        dl = v.find("dl")
        if dl is not None:
            dd = dl.find("dd")
            play_url = _extract_first_play_url(_text(dd) if dd is not None else None)
        out[vod_id] = {"thumb_url": thumb_url, "play_url": play_url}
    return out
