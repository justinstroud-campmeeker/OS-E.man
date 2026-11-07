"""Wire protocol between the world server and its clients.

JSON lines over a localhost TCP socket. Each message is one JSON object with an
"op" (client -> server) or "ev" (server -> client) key. Rich Text is sent as
plain text plus style spans so styling and redaction blocks survive the trip.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

from rich.text import Span, Text

from .state import default_save_path

HOST = "127.0.0.1"
MAX_LINE = 4 * 1024 * 1024


def runtime_dir(save_path: Path | None = None) -> Path:
    return (save_path or default_save_path()).parent


def server_file(save_path: Path | None = None) -> Path:
    return runtime_dir(save_path) / "server.json"


def read_server_info(save_path: Path | None = None) -> dict | None:
    try:
        return json.loads(server_file(save_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def write_server_info(info: dict, save_path: Path | None = None) -> None:
    p = server_file(save_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(info), encoding="utf-8")
    try:
        os.chmod(p, 0o600)
    except OSError:
        pass


def clear_server_info(save_path: Path | None = None, pid: int | None = None) -> None:
    info = read_server_info(save_path)
    if info and (pid is None or info.get("pid") == pid):
        try:
            server_file(save_path).unlink()
        except OSError:
            pass


# ----- rich Text <-> JSON -----
def text_to_wire(t: Text) -> dict:
    return {
        "t": t.plain,
        "s": str(t.style) if t.style else "",
        "sp": [[s.start, s.end, str(s.style)] for s in t.spans],
    }


def text_from_wire(d: dict) -> Text:
    return Text(d["t"], style=d.get("s") or "",
                spans=[Span(a, b, s) for a, b, s in d.get("sp", [])])


# ----- framing -----
class Connection:
    """One JSON-lines stream. Transport-agnostic enough for an ssh front end later."""

    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        self.reader = reader
        self.writer = writer
        self.closed = False

    async def send(self, msg: dict) -> None:
        if self.closed:
            return
        try:
            self.writer.write((json.dumps(msg, ensure_ascii=False) + "\n").encode("utf-8"))
            await self.writer.drain()
        except (ConnectionError, RuntimeError):
            self.closed = True

    async def recv(self) -> dict | None:
        try:
            line = await self.reader.readline()
        except (ConnectionError, ValueError, asyncio.LimitOverrunError):
            line = b""
        if not line:
            self.closed = True
            return None
        try:
            msg = json.loads(line.decode("utf-8"))
        except ValueError:
            return {}
        return msg if isinstance(msg, dict) else {}

    async def close(self) -> None:
        self.closed = True
        try:
            self.writer.close()
            await self.writer.wait_closed()
        except (ConnectionError, RuntimeError, OSError):
            pass


async def open_connection(port: int) -> Connection:
    reader, writer = await asyncio.open_connection(HOST, port, limit=MAX_LINE)
    return Connection(reader, writer)


async def hello(port: int, token: str, timeout: float = 3.0,
                role: str | None = None) -> tuple[Connection, dict]:
    """Connect and authenticate. Returns (connection, welcome message). Raises on failure.
    role="director" connects from outside the world: no player session, no clock effect."""
    conn = await asyncio.wait_for(open_connection(port), timeout)
    await conn.send({"op": "hello", "token": token, **({"role": role} if role else {})})
    msg = await asyncio.wait_for(conn.recv(), timeout)
    if not msg or msg.get("ev") != "welcome":
        await conn.close()
        raise ConnectionRefusedError((msg or {}).get("reason", "no welcome from server"))
    return conn, msg
