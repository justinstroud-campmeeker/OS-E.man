"""Persistent game state. Everything that must survive a quit lives here."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

DAY_START = 9 * 60   # 09:00
DAY_END = 17 * 60    # 17:00
SAVE_VERSION = 1


def default_save_path() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home() / ".config")
    return Path(base) / "OS-E.man" / "save.json"


@dataclass
class GameState:
    # Absolute game time in minutes since day 1, 00:00.
    t: int = DAY_START - 1
    user: str = "pdunn"
    cwd: str = "/home/pdunn"

    curiosity: int = 0
    mystique: int = 0
    exposure: int = 0

    flags: list[str] = field(default_factory=list)
    access: list[str] = field(default_factory=list)

    inbox: list[dict] = field(default_factory=list)
    delivered: list[str] = field(default_factory=list)       # email ids delivered
    queued: dict[str, int] = field(default_factory=dict)     # email id -> deliver at t

    challenges_done: list[str] = field(default_factory=list)
    drafts: dict[str, str] = field(default_factory=dict)
    seen_anomalies: list[str] = field(default_factory=list)

    beats_fired: list[str] = field(default_factory=list)
    omens_fired: list[str] = field(default_factory=list)
    scheduled_lines: list[dict] = field(default_factory=list)  # {at, channel, who, text}
    ticker_log: list[dict] = field(default_factory=list)       # {t, channel, who, text}
    next_chatter: int = DAY_START + 25

    facil: dict = field(default_factory=lambda: {
        "pods": "Assorted (Medium Roast)",
        "cooler": "Tue/Fri delivery, 5 gal x 4",
        "thermostat": 70,
        "rooms": {"Aquarium": "", "Boiler Room": "", "Big Conf": "", "Phone Booth 2": ""},
        "orders": [],
    })

    user_files: dict[str, str] = field(default_factory=dict)
    glimpses: list[str] = field(default_factory=list)          # glimpse ids shown
    last_glimpse_day: int = 0
    mundane: int = 0                                           # commands since progress
    sent_mail: list[dict] = field(default_factory=list)        # {to, subject, day, time}
    routes_used: dict[str, str] = field(default_factory=dict)  # rung access -> route id
    warned: int = 0                                            # exposure ladder steps taken
    demotions: int = 0
    stuck: dict[str, int] = field(default_factory=dict)        # route id -> nights open
    pending_glimpse: str = ""                                  # a Board hint, shown next command
    badge: dict = field(default_factory=dict)                  # door -> locked/unlocked, revokes
    history: list[str] = field(default_factory=list)
    version: int = SAVE_VERSION

    # ----- derived -----
    @property
    def day(self) -> int:
        return self.t // 1440 + 1

    @property
    def minute_of_day(self) -> int:
        return self.t % 1440

    @property
    def clock(self) -> str:
        m = self.minute_of_day
        return f"{m // 60:02d}:{m % 60:02d}"

    def has(self, flag: str) -> bool:
        return flag in self.flags

    def set_flag(self, flag: str) -> bool:
        """Set a flag. Returns True if it was newly set."""
        if flag in self.flags:
            return False
        self.flags.append(flag)
        return True

    @property
    def unread(self) -> int:
        return sum(1 for m in self.inbox if not m.get("read"))

    # ----- persistence -----
    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "GameState":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.to_dict(), indent=1), encoding="utf-8")
        tmp.replace(path)

    @classmethod
    def load(cls, path: Path) -> "GameState | None":
        try:
            return cls.from_dict(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError, TypeError):
            return None
