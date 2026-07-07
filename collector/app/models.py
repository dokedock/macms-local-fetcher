from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class VodItem:
    source_id: int
    vod_id: str | None
    title: str
    title_norm: str
    type_id: str | None
    type_name: str | None
    vod_time: str | None
    thumb_url: str | None
    play_url: str | None
    play_from: str | None
    remarks: str | None
    unique_key: str
    raw_text: str | None
