"""Transport-neutral player sessions.

A Terminal is whatever a player is looking at (an ssh pty, or the JSON test/control
client). PlayerSession holds the per-connection game state (pending password prompt,
open editors) and runs commands; the WorldServer broadcasts shared events to every
session's Terminal.
"""

from __future__ import annotations

import itertools
import time
import traceback
from typing import TYPE_CHECKING

from rich.text import Text

from .game import EditRequest, Out, Prompt

if TYPE_CHECKING:
    from .server import WorldServer

IDLE_AFTER = 300  # real seconds without input before a terminal counts as idle

_ids = itertools.count(1)


class Terminal:
    """Base adapter. Subclasses deliver things to an actual screen."""

    local_echo = False  # True if the screen already shows typed input (an ssh pty)

    def __init__(self):
        self.last_input = time.monotonic()

    def touch(self) -> None:
        self.last_input = time.monotonic()

    def active(self) -> bool:
        return time.monotonic() - self.last_input < IDLE_AFTER

    async def output(self, lines: list[Text]) -> None: ...
    async def notify(self, lines: list[Text]) -> None:
        """Asynchronous output (ticks): by default the same as output."""
        await self.output(lines)
    async def prompt(self, label: str, password: bool) -> None: ...
    async def editor(self, eid: int, title: str, text: str) -> None: ...
    async def clear(self) -> None: ...
    async def bye(self, reason: str) -> None: ...
    async def ticker(self, entries: list[dict]) -> None: ...
    async def status(self, status: dict) -> None: ...
    async def glimpse(self, text: str) -> None:
        """A screen flicker with text in the middle. Plain terminals get nothing."""


class PlayerSession:
    def __init__(self, server: "WorldServer", term: Terminal):
        self.server = server
        self.term = term
        self.pending: Prompt | None = None
        self.editors: dict[int, EditRequest] = {}

    @property
    def game(self):
        return self.server.game

    async def send_prompt(self) -> None:
        if self.pending:
            await self.term.prompt(self.pending.label, self.pending.password)
        else:
            await self.term.prompt(self.game.prompt_str(), False)

    async def exec(self, line: str) -> bool:
        """Run one input line. Returns False when the session should end."""
        g = self.game
        self.term.touch()
        g.pending = self.pending
        try:
            lines = g.execute(line, echo=not self.term.local_echo)
        except Exception:  # a bug in one command must not take the world down
            traceback.print_exc()
            out = Out(g)
            out("crab: Segmentation fault (core dumped). It's not you. Probably.", "err")
            lines = out.items
            g.requests = []
        self.pending, g.pending = g.pending, None
        requests, g.requests = g.requests, []
        await self.term.output(lines)
        keep = await self._handle_requests(requests)
        await self.server.flush_shared()
        if keep and not self.editors:
            await self.send_prompt()
        return keep

    async def editor_result(self, eid, text) -> bool:
        req = self.editors.pop(eid, None) if isinstance(eid, int) else None
        if req is None:
            return True
        g = self.game
        self.term.touch()
        out = Out(g)
        if text is None:
            out("(cancelled)", "dim")
        else:
            try:
                req.on_save(str(text), out)
            except Exception:
                traceback.print_exc()
                out("bledit: write failed: Input/output error", "err")
            g.events.check(out)
        requests, g.requests = g.requests, []
        await self.term.output(out.items)
        keep = await self._handle_requests(requests)
        await self.server.flush_shared()
        if keep and not self.editors:
            await self.send_prompt()
        return keep

    async def _handle_requests(self, requests: list) -> bool:
        keep = True
        for r in requests:
            if r == "clear":
                await self.term.clear()
            elif r == "quit":
                self.game.save()
                await self.term.bye("disconnected")
                keep = False
            elif r == "shutdown":
                await self.term.bye("The system is going down.")
                self.server.request_stop()
                keep = False
            elif isinstance(r, tuple) and r[0] == "glimpse":
                await self.term.glimpse(r[1])
            elif isinstance(r, EditRequest):
                eid = next(_ids)
                self.editors[eid] = r
                await self.term.editor(eid, r.title, r.text)
        return keep
