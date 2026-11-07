"""The world server: owns the Game, runs the clock, and serves terminals.

Doors into the same world:
  * ssh (sshd.py) for players
  * a JSON-lines control port (protocol.py) for `status` / `stop` and tests
  * the same port with role "director", for whatever writes the world from outside
    (world.py): it reads a digest and applies content packs, and is never a player
"""

from __future__ import annotations

import asyncio
import os
import secrets
import traceback
from pathlib import Path

from rich.text import Text

from .game import Game
from .protocol import (HOST, MAX_LINE, Connection, clear_server_info, text_to_wire,
                       write_server_info)
from .session import PlayerSession, Terminal
from .shell import crab

ACTIVE_EVERY = 1       # real seconds per game minute while someone is active
IDLE_EVERY = 4         # connected, but idle / unfocused
DETACHED_EVERY = 20    # nobody connected (and the day holds at 16:59)
DEFAULT_SSH_PORT = 2222


class JsonTerminal(Terminal):
    """Terminal adapter for the JSON control/test client."""

    def __init__(self, conn: Connection):
        super().__init__()
        self.conn = conn
        self.focused = True

    def active(self) -> bool:
        return self.focused

    async def output(self, lines):
        await self.conn.send({"ev": "output", "lines": [text_to_wire(t) for t in lines]})

    async def prompt(self, label, password):
        await self.conn.send({"ev": "prompt", "label": label, "password": password})

    async def editor(self, eid, title, text):
        await self.conn.send({"ev": "editor", "id": eid, "title": title, "text": text})

    async def clear(self):
        await self.conn.send({"ev": "clear"})

    async def bye(self, reason):
        await self.conn.send({"ev": "bye", "reason": reason})

    async def ticker(self, entries):
        await self.conn.send({"ev": "ticker", "entries": entries})

    async def status(self, status):
        await self.conn.send({"ev": "status", "status": status})

    async def glimpse(self, text):
        await self.conn.send({"ev": "glimpse", "text": text})


class WorldServer:
    def __init__(self, save_path: Path, new: bool = False, port: int = 0,
                 publish: bool = True, tick_seconds: float = 1.0,
                 ssh_port: int | None = None):
        self.save_path = save_path
        self.game = Game.load_or_new(save_path, new=new)
        self.port = port
        self.ssh_port = ssh_port          # None disables the ssh door
        self.publish = publish            # write server.json (off in tests)
        self.tick_seconds = tick_seconds
        self.token = secrets.token_hex(16)
        self.sessions: list[PlayerSession] = []
        self._server: asyncio.base_events.Server | None = None
        self._sshd = None
        self._ticker_task: asyncio.Task | None = None
        self._stopped = asyncio.Event()
        self._seconds = 0

    # ----- lifecycle -----
    async def start(self) -> None:
        self._server = await asyncio.start_server(self._handle_json, HOST, self.port, limit=MAX_LINE)
        self.port = self._server.sockets[0].getsockname()[1]
        if self.ssh_port is not None:
            from .sshd import start_sshd
            self._sshd = await start_sshd(self, self.ssh_port)
            self.ssh_port = self._sshd.get_port()
        if self.publish:
            write_server_info({"port": self.port, "ssh_port": self.ssh_port,
                               "token": self.token, "pid": os.getpid()}, self.save_path)
        self._ticker_task = asyncio.create_task(self._tick_loop())

    async def serve_forever(self) -> None:
        await self.start()
        await self._stopped.wait()
        await self.stop()

    async def stop(self) -> None:
        self.game.save()
        for s in list(self.sessions):
            await s.term.bye("The system is going down.")
        if self._ticker_task:
            self._ticker_task.cancel()
        if self._server:
            self._server.close()
        if self._sshd:
            self._sshd.close()
            await self._sshd.wait_closed()
        if self.publish:
            clear_server_info(self.save_path, os.getpid())
        self._stopped.set()

    def request_stop(self) -> None:
        self._stopped.set()

    # ----- sessions -----
    def attach(self, term: Terminal) -> PlayerSession:
        s = PlayerSession(self, term)
        self.sessions.append(s)
        return s

    def detach(self, s: PlayerSession) -> None:
        if s in self.sessions:
            self.sessions.remove(s)
        self.game.save()

    # ----- clock -----
    def _every(self) -> int:
        if not self.sessions:
            return DETACHED_EVERY
        return ACTIVE_EVERY if any(s.term.active() for s in self.sessions) else IDLE_EVERY

    async def _tick_loop(self) -> None:
        while True:
            await asyncio.sleep(self.tick_seconds)
            self._seconds += 1
            if self._seconds % self._every():
                continue
            try:
                await self.advance(1)
            except Exception:
                traceback.print_exc()

    async def advance(self, minutes: int) -> None:
        lines = self.game.tick(minutes, rollover=bool(self.sessions))
        if lines:
            await self.notify_all(lines)
        await self.flush_shared()

    # ----- broadcasting -----
    async def notify_all(self, lines: list[Text]) -> None:
        for s in list(self.sessions):
            await s.term.notify(lines)

    async def flush_shared(self) -> None:
        if self.game.ticker_new:
            entries, self.game.ticker_new = self.game.ticker_new, []
            for s in list(self.sessions):
                await s.term.ticker(entries)
        status = self.game.status()
        for s in list(self.sessions):
            await s.term.status(status)

    def welcome(self) -> dict:
        g = self.game
        st = g.state
        return {
            "ev": "welcome",
            "motd": g.vfs.files.get("/etc/motd", "").rstrip().split("\n"),
            "fresh": not st.history,
            "day": st.day, "clock": st.clock,
            "ticker": st.ticker_log[-15:],
            "history": st.history[-100:],
            "status": g.status(),
            "prompt": g.prompt_str(),
            "names": {k: v["handle"] for k, v in g.events.people.items()},
            "ssh_port": self.ssh_port,
        }

    # ----- JSON door -----
    async def _handle_json(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        conn = Connection(reader, writer)
        first = await conn.recv()
        if not first or first.get("op") != "hello" or first.get("token") != self.token:
            await conn.send({"ev": "bye", "reason": "authentication failure"})
            await conn.close()
            return
        if first.get("role") == "director":
            await self._director(conn)
            return
        term = JsonTerminal(conn)
        session = self.attach(term)
        await conn.send(self.welcome())
        try:
            while not conn.closed:
                msg = await conn.recv()
                if msg is None or not await self._dispatch(session, term, msg):
                    break
        finally:
            self.detach(session)
            await conn.close()

    async def _director(self, conn: Connection) -> None:
        """Outside the machine. Reads the world, writes the world; never sits at a terminal."""
        g = self.game
        await conn.send({"ev": "welcome", "role": "director", "day": g.state.day,
                         "clock": g.state.clock})
        try:
            while not conn.closed:
                msg = await conn.recv()
                if msg is None:
                    break
                op = msg.get("op")
                if op == "digest":
                    await conn.send({"ev": "digest", "digest": {**g.world.digest(g),
                                                                "players": len(self.sessions)}})
                elif op == "check":
                    from .world import check_pack
                    await conn.send({"ev": "report", **check_pack(msg.get("pack"), g.world).to_dict()})
                elif op == "apply":
                    rep = g.world.apply(msg.get("pack"), day=g.state.day)
                    if rep.ok:
                        g.save()
                    await conn.send({"ev": "report", **rep.to_dict()})
                elif op == "detach":
                    break
                else:
                    await conn.send({"ev": "error", "reason": f"unknown op {op!r}"})
        finally:
            await conn.close()

    async def _dispatch(self, s: PlayerSession, term: JsonTerminal, msg: dict) -> bool:
        op = msg.get("op")
        if op == "exec":
            return await s.exec(str(msg.get("line", "")))
        if op == "complete":
            text = str(msg.get("text", ""))
            await term.conn.send({"ev": "completions", "text": text,
                                  "options": crab.complete(self.game, text)})
        elif op == "editor_result":
            return await s.editor_result(msg.get("id"), msg.get("text"))
        elif op == "focus":
            term.focused = bool(msg.get("focused", True))
        elif op == "detach":
            await term.bye("detached")
            return False
        elif op == "shutdown":
            if msg.get("token") == self.token:
                self.request_stop()
                return False
        return True


def run_server(save_path: Path, new: bool = False, ssh_port: int | None = DEFAULT_SSH_PORT) -> None:
    server = WorldServer(save_path, new=new, ssh_port=ssh_port)
    try:
        asyncio.run(server.serve_forever())
    except KeyboardInterrupt:
        server.game.save()
        clear_server_info(save_path, os.getpid())
