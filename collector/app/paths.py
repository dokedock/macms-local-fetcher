from __future__ import annotations

from pathlib import Path


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def data_dir() -> Path:
    return project_root() / "data"


def exports_dir() -> Path:
    return data_dir() / "exports"


def db_path() -> Path:
    return data_dir() / "app.db"


def web_dir() -> Path:
    return project_root() / "web"

