from __future__ import annotations

import re


_space_re = re.compile(r"\s+")


def normalize_title(title: str) -> str:
    t = title.strip().lower()
    t = _space_re.sub(" ", t)
    return t


def join_url(base: str, path: str) -> str:
    if not base:
        return path
    if base.endswith("/") and path.startswith("/"):
        return base + path[1:]
    if not base.endswith("/") and not path.startswith("/"):
        return base + "/" + path
    return base + path

