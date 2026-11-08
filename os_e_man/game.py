"""The game core. No UI here: the world server's sessions (and the tests) drive this."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from rich.text import Text

from . import content
from .events import Events
from .glimpses import Glimpses
from .levers import Levers
from .unlocks import Unlocks
from .omens import Omens
from .state import DAY_END, DAY_START, GameState
from .training.engine import Training
from .training.sqlrunner import SQLRunner
from .vfs import VFS
from .world import World

REDACT = re.compile(r"\[\[R(\d+):(.*?)\]\]", re.S)
AUTOSAVE_EVERY = 60  # game minutes

STYLES = {
    "echo": "bold #9fbf8f",
    "dim": "#5f6f5a",
    "err": "#d08770",
    "ok": "#a3be8c",
    "mail": "#ebcb8b",
    "head": "bold #c8d3b8",
    "warn": "#d8a657",
    "sys": "italic #7f8f7a",
}


@dataclass
class EditRequest:
    title: str
    text: str
    on_save: Callable[[str, "Out"], None]


@dataclass
class Prompt:
    label: str
    callback: Callable[[str, "Out"], None]
    password: bool = False


class Out:
    """Collects output lines for one command (or one tick)."""

    def __init__(self, game: "Game"):
        self.game = game
        self.items: list[Text] = []

    def __call__(self, text: str = "", style: str | None = None) -> None:
        for line in str(text).split("\n"):
            self.items.append(self.game.fmt(line, style))

    def lines(self, lines, style: str | None = None) -> None:
        for line in lines:
            self(line, style)

    def plain(self) -> list[str]:
        return [t.plain for t in self.items]


class Game:
    def __init__(self, state: GameState | None = None, save_path: Path | None = None):
        self.state = state or GameState()
        self.save_path = save_path
        # content packs from outside the machine live next to the save
        self.world = World(save_path.parent / "world" if save_path else None)
        self.vfs = VFS(self.state, self.world)
        self.db = SQLRunner()
        self.training = Training(self)
        self.events = Events(self)
        self.omens = Omens(self)
        self.glimpses = Glimpses(self)
        self.levers = Levers(self)
        self.unlocks = Unlocks(self)
        self.quiet = False                # --quiet: halves exposure from omens
        self.curiosity_triggers: dict[str, int] = content.load("curiosity.json")
        self.ticker_new: list[dict] = []
        self.requests: list = []          # EditRequest | "clear" | "quit"
        self.pending: Prompt | None = None
        self._last_save_t = self.state.t

    # ----- persistence -----
    @classmethod
    def load_or_new(cls, path: Path, new: bool = False) -> "Game":
        state = None if new else GameState.load(path)
        return cls(state, path)

    def save(self) -> None:
        if self.save_path:
            self.state.save(self.save_path)
            self._last_save_t = self.state.t

    # ----- text -----
    def fmt(self, line: str, style: str | None = None) -> Text:
        """Render a line, applying redactions based on current curiosity."""
        base = STYLES.get(style, style) if style else None
        out = Text(style=base or "")
        pos = 0
        for m in REDACT.finditer(line):
            out.append(line[pos:m.start()])
            level, inner = int(m.group(1)), m.group(2)
            if self.state.curiosity >= level:
                out.append(inner, style="#d8a657")
            else:
                out.append("█" * len(inner), style="#3a4236")
            pos = m.end()
        out.append(line[pos:])
        return out

    def status(self) -> dict:
        st = self.state
        return {
            "day": st.day, "clock": st.clock, "user": st.user, "unread": st.unread,
            "curiosity": st.curiosity, "mystique": st.mystique, "exposure": st.exposure,
            "meters": "facilities" in st.access or st.has("locked_out"),
        }

    def prompt_str(self) -> str:
        cwd = self.state.cwd
        home = self.vfs.home()
        if cwd == home or cwd.startswith(home + "/"):
            cwd = "~" + cwd[len(home):]
        return f"{self.state.user}@wks-0417:{cwd}$ "

    # ----- progression hooks -----
    def poke(self, key: str) -> None:
        """The player looked at something they maybe shouldn't have."""
        amount = self.curiosity_triggers.get(key)
        if amount is None:
            return
        if self.state.set_flag(f"poke:{key}"):
            self.state.curiosity += amount

    def note_tables(self, tables) -> None:
        for t in tables:
            self.poke(f"sql:{t}")

    def bump(self, mystique: int = 0, exposure: int = 0) -> None:
        self.state.mystique = max(0, self.state.mystique + mystique)
        self.state.exposure = max(0, self.state.exposure + exposure)

    def post(self, channel: str, who: str, text: str) -> None:
        entry = {"t": self.state.t, "channel": channel, "who": who, "text": text}
        self.state.ticker_log.append(entry)
        del self.state.ticker_log[:-200]
        self.ticker_new.append(entry)

    def schedule(self, delay: int, channel: str, who: str, text: str) -> None:
        self.state.scheduled_lines.append(
            {"at": self.state.t + delay, "channel": channel, "who": who, "text": text})

    # ----- input -----
    def execute(self, line: str, echo: bool = True) -> list[Text]:
        """Run one input line. echo=False for terminals that already show what was typed."""
        from .shell import crab

        out = Out(self)
        if self.pending:
            p, self.pending = self.pending, None
            if echo:
                out(p.label + ("" if p.password else line), "echo")
            p.callback(line, out)
        else:
            line = line.strip()
            if not line:
                return []
            self.state.history.append(line)
            del self.state.history[:-300]
            if echo:
                out(self.prompt_str() + line, "echo")
            before = self.glimpses.snapshot()
            crab.run(self, line, out)
            self.glimpses.after_command(before)
        self.events.check(out)
        return out.items

    # ----- time -----
    def tick(self, minutes: int = 1, rollover: bool = True) -> list[Text]:
        """Advance the clock. With rollover=False (nobody connected) the day holds at 17:00:
        tomorrow only starts once someone comes back."""
        out = Out(self)
        for _ in range(minutes):
            if not rollover and self.state.minute_of_day >= DAY_END - 1:
                break
            self.state.t += 1
            if self.state.minute_of_day >= DAY_END:
                self._end_of_day(out)
            self.events.check(out)
            self.unlocks.check(out)
        if self.state.t - self._last_save_t >= AUTOSAVE_EVERY:
            self.save()
        return out.items

    def _end_of_day(self, out: Out) -> None:
        st = self.state
        out("")
        out(f"17:00. Day {st.day} ends. You go home. You eat something over the sink. "
            "You come back.", "sys")
        st.t = st.day * 1440 + DAY_START
        st.exposure = max(0, st.exposure - 2)  # people forget, a little
        self.levers.nudge()
        for f in sorted(self.world.dangling):  # things that, it turns out, happened
            st.set_flag(f)
        out(f"Day {st.day}, {st.clock}.", "sys")
        out("")
