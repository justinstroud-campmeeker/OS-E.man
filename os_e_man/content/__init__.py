"""Loads the JSON/text content shipped with the game."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).parent


@lru_cache(maxsize=None)
def load(name: str):
    return json.loads((ROOT / name).read_text(encoding="utf-8"))


def text(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def man_page(topic: str) -> str | None:
    p = ROOT / "man" / f"{topic}.txt"
    return p.read_text(encoding="utf-8") if p.is_file() else None


def man_topics() -> list[str]:
    return sorted(p.stem for p in (ROOT / "man").glob("*.txt"))
