"""The ssh door: players log in to wks-0417 with a stock ssh client.

    ssh -p 2222 pdunn@127.0.0.1      (what `python -m os_e_man` runs for you)

Only listens on 127.0.0.1 and only serves the game. Auth is key-only, with keys
generated in the game's runtime folder (never ~/.ssh): a host key for the server,
a client key for the player, and a known_hosts line under the alias `wks-0417`.

Each connection is an SshTerminal: a session Terminal (session.py) that does its
own raw-mode line editing, opens bledit (term/editor.py) on the alternate screen,
and prints chat between prompts, Unix-style, redrawing whatever you were typing.
"""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import subprocess
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import asyncssh
from rich.text import Text

from .protocol import HOST, runtime_dir
from .session import PlayerSession, Terminal
from .shell import crab
from .term.ansi import to_ansi
from .term.editor import ENTER_ALT, LEAVE_ALT, Editor
from .term.keys import KeyParser

if TYPE_CHECKING:
    from .server import WorldServer

LOGIN = "pdunn"
HOST_ALIAS = "wks-0417"
ESC_TIMEOUT = 0.05          # seconds to wait before a lone Esc counts as Esc
PROMPT_RE = re.compile(r"^(\S+@\S+?):(.*)\$ $")


# ----------------------------------------------------------------- keys
@dataclass
class KeyFiles:
    host: Path          # server host key (private)
    client: Path        # player's private key
    known_hosts: Path   # "wks-0417 ssh-ed25519 ..." for the player's ssh client


def key_files(save_path: Path) -> KeyFiles:
    d = runtime_dir(save_path)
    return KeyFiles(d / "ssh_host_ed25519_key", d / "id_ed25519", d / "known_hosts")


def _load_or_make(path: Path) -> asyncssh.SSHKey:
    if path.exists():
        return asyncssh.read_private_key(str(path))
    key = asyncssh.generate_private_key("ssh-ed25519", comment=f"{LOGIN}@{HOST_ALIAS}")
    path.parent.mkdir(parents=True, exist_ok=True)
    key.write_private_key(str(path))
    key.write_public_key(str(path) + ".pub")
    return key


def _owner_only(path: Path) -> None:
    """ssh refuses private keys other users can read. On Windows a new file inherits its
    folder's ACL, so strip inheritance and grant only the current user."""
    if os.name != "nt":
        os.chmod(path, 0o600)
        return
    user = os.environ.get("USERNAME")
    if not user:
        return
    if os.environ.get("USERDOMAIN"):
        user = f"{os.environ['USERDOMAIN']}\\{user}"
    subprocess.run(["icacls", str(path), "/inheritance:r", "/grant:r", f"{user}:F"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)


def ensure_keys(save_path: Path) -> tuple[asyncssh.SSHKey, asyncssh.SSHKey]:
    """(host key, client key), generating them on first boot."""
    kf = key_files(save_path)
    host, client = _load_or_make(kf.host), _load_or_make(kf.client)
    _owner_only(kf.client)
    pub = host.export_public_key().decode().split()
    kf.known_hosts.write_text(f"{HOST_ALIAS} {pub[0]} {pub[1]}\n", encoding="utf-8")
    return host, client


def find_ssh() -> str | None:
    if os.name == "nt":
        builtin = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "OpenSSH" / "ssh.exe"
        if builtin.exists():
            return str(builtin)
    return shutil.which("ssh")


def ssh_command(save_path: Path, port: int, ssh: str = "ssh", tty: str = "-t") -> list[str]:
    kf = key_files(save_path)
    return [ssh, tty, "-p", str(port), "-i", str(kf.client),
            "-o", "IdentitiesOnly=yes",
            "-o", f'UserKnownHostsFile="{kf.known_hosts.as_posix()}"',
            "-o", f"HostKeyAlias={HOST_ALIAS}",
            "-o", "StrictHostKeyChecking=yes",
            "-o", "LogLevel=ERROR",
            f"{LOGIN}@{HOST}"]


# ----------------------------------------------------------------- server
class _SSHServer(asyncssh.SSHServer):
    def __init__(self, world: "WorldServer", authorized):
        self.world = world
        self.authorized = authorized
        self.conn: asyncssh.SSHServerConnection | None = None

    def connection_made(self, conn):
        self.conn = conn

    def begin_auth(self, username):
        # Only pdunn has an account here. Anyone else gets no keys and no way in.
        if username == LOGIN and self.conn is not None:
            self.conn.set_authorized_keys(self.authorized)
        return True

    def session_requested(self):
        return SshTerminal(self.world)


async def start_sshd(world: "WorldServer", port: int):
    host_key, client_key = ensure_keys(world.save_path)
    authorized = asyncssh.import_authorized_keys(client_key.export_public_key().decode())
    kw = dict(server_factory=lambda: _SSHServer(world, authorized), server_host_keys=[host_key],
              server_version="OpenSSH_6.6.1p1_HPCG-hardened", keepalive_interval=30,
              login_timeout=30, line_editor=False)
    try:
        return await asyncssh.listen(HOST, port, **kw)
    except OSError:
        if not port:
            raise
        return await asyncssh.listen(HOST, 0, **kw)  # 2222 taken: any free port will do


# ----------------------------------------------------------------- terminal
class SshTerminal(Terminal, asyncssh.SSHServerSession):
    local_echo = True  # the line is already on screen; the game needn't echo it

    def __init__(self, world: "WorldServer"):
        Terminal.__init__(self)
        self.world = world
        self.chan = None
        self.session: PlayerSession | None = None
        self.width, self.height = 80, 24
        self.parser = KeyParser()
        self.inbox: asyncio.Queue[str | None] = asyncio.Queue()
        self.closed = False
        # line editor
        self.label, self.password = "$ ", False
        self.buf, self.pos = "", 0
        self.at_prompt = False
        self._row = 0                 # rows from prompt start to cursor at last draw
        self._hist: int | None = None
        # full-screen editor
        self.bledit: Editor | None = None
        self.bledit_id: int | None = None
        self.queued_editors: list[tuple[int, str, str]] = []
        self.held: list[Text] = []    # async lines that arrive while bledit is open
        self._title = ""
        self._stash = ""

    # ----- asyncssh session callbacks -----
    def connection_made(self, chan):
        self.chan = chan

    def pty_requested(self, term_type, term_size, term_modes):
        self._resize(term_size[0], term_size[1])
        return True

    def shell_requested(self):
        return True

    def exec_requested(self, command):
        return False  # interactive logins only

    def subsystem_requested(self, subsystem):
        return False

    def session_started(self):
        asyncio.ensure_future(self._run())

    def data_received(self, data, datatype):
        self.inbox.put_nowait(data)

    def eof_received(self):
        self.inbox.put_nowait(None)
        return False

    def terminal_size_changed(self, width, height, pixwidth, pixheight):
        self._resize(width, height)
        if self.bledit:
            self.bledit.resize(self.width, self.height)
            self._write(self.bledit.render())

    def connection_lost(self, exc):
        self.closed = True
        self.inbox.put_nowait(None)

    def _resize(self, w: int, h: int) -> None:
        self.width, self.height = max(20, w or 80), max(8, h or 24)

    # ----- main loop -----
    async def _run(self) -> None:
        self.session = self.world.attach(self)
        try:
            await self._banner()
            await self.session.send_prompt()
            while not self.closed:
                try:
                    timeout = ESC_TIMEOUT if self.parser.pending else None
                    data = await asyncio.wait_for(self.inbox.get(), timeout)
                except asyncio.TimeoutError:
                    keys = self.parser.flush()
                else:
                    if data is None:
                        break
                    keys = self.parser.feed(data)
                for k in keys:
                    if self.closed:
                        break
                    self.touch()
                    if not await self._key(k):
                        self.closed = True
        except Exception:
            traceback.print_exc()
        finally:
            self.world.detach(self.session)
            self._close()

    async def _banner(self) -> None:
        g = self.world.game
        st = g.state
        motd = g.vfs.files.get("/etc/motd", "").rstrip().split("\n")
        lines = [g.fmt(line, "dim") for line in motd if motd != [""]]
        if not st.history:
            lines.append(g.fmt("Type `emmy` to read your mail, `help` for commands, "
                               "`man intro` if lost.", "sys"))
        else:
            lines.append(g.fmt(f"Last login: day {st.day}, {st.clock} from 127.0.0.1", "dim"))
        if st.unread:
            lines.append(g.fmt("You have new mail.", "mail"))
        await self.output(lines)

    def _close(self) -> None:
        self.closed = True
        if self.chan is not None:
            try:
                if self.bledit:
                    self._write(LEAVE_ALT)
                self.chan.exit(0)
            except Exception:
                pass

    # ----- writing -----
    def _write(self, s: str) -> None:
        if self.chan is not None and not self.closed:
            try:
                self.chan.write(s)
            except Exception:
                self.closed = True

    def _lines(self, lines: list[Text]) -> str:
        return to_ansi(lines, self.width).replace("\n", "\r\n") if lines else ""

    # ----- Terminal interface -----
    async def output(self, lines):
        self._write(self._lines(lines))

    async def notify(self, lines):
        self._async_lines(list(lines))

    async def ticker(self, entries):
        g = self.world.game
        if g.state.has("mesg_n"):
            return  # mesg n: it's all still in `dingaling`
        lines: list[Text] = []
        for e in entries:
            lines += chat_lines(g, e)
        self._async_lines(lines)

    async def status(self, status):
        title = (f"{status.get('user')}@{HOST_ALIAS} \u2014 day {status.get('day')} "
                 f"{status.get('clock')}" + (f" \u2014 \u2709 {status['unread']}" if status.get("unread") else ""))
        if title != self._title:
            self._title = title
            self._write(f"\x1b]0;{title}\x07")

    async def glimpse(self, text):
        """Flicker, show the text centred for a moment, then put the screen back."""
        if self.bledit:
            return
        row, col = self.height // 2, max(1, (self.width - len(text)) // 2 + 1)
        self._write("\x1b[?1049h\x1b[?25l\x1b[?5h")
        await asyncio.sleep(0.08)
        self._write(f"\x1b[?5l\x1b[H\x1b[2J\x1b[{row};{col}H\x1b[1m{text}\x1b[0m")
        await asyncio.sleep(1.4)
        self._write("\x1b[?5h")
        await asyncio.sleep(0.05)
        self._write("\x1b[?5l\x1b[?1049l\x1b[?25h")

    async def prompt(self, label, password):
        self.label, self.password = label, password
        self.buf, self.pos, self._hist = "", 0, None
        self.at_prompt = True
        self._row = 0
        self._redraw(fresh=True)

    async def editor(self, eid, title, text):
        if self.bledit:
            self.queued_editors.append((eid, title, text))
            return
        self.at_prompt = False
        self.bledit_id = eid
        self.bledit = Editor(title, text, self.width, self.height)
        self._write(ENTER_ALT + self.bledit.render())

    async def clear(self):
        self._write("\x1b[H\x1b[2J")

    async def bye(self, reason):
        if self.bledit:
            self._write(LEAVE_ALT)
            self.bledit = None
        if reason != "disconnected":
            self._write(("\r\n" if self.at_prompt else "") + self._lines([Text(reason, style="italic #7f8f7a")]))
        self.at_prompt = False
        self._close()

    # ----- async output between prompts -----
    def _async_lines(self, lines: list[Text]) -> None:
        if not lines:
            return
        if self.bledit:
            self.held += lines
            return
        if self.at_prompt:
            self._erase()
            self._write(self._lines(lines))
            self._row = 0
            self._redraw(fresh=True)
        else:
            self._write(self._lines(lines))

    # ----- line editor -----
    def _prompt_ansi(self) -> str:
        m = PROMPT_RE.match(self.label)
        if not m:
            return self.label
        return f"\x1b[1;32m{m.group(1)}\x1b[0m:\x1b[1;34m{m.group(2)}\x1b[0m$ "

    def _erase(self) -> None:
        """Move to where the prompt starts and clear from there down."""
        self._write((f"\x1b[{self._row}A" if self._row else "") + "\r\x1b[J")

    def _redraw(self, fresh: bool = False) -> None:
        if not fresh:
            self._erase()
        shown = "" if self.password else self.buf
        cursor = 0 if self.password else self.pos
        w = self.width
        plen = len(self.label)
        total, target = plen + len(shown), plen + cursor
        s = self._prompt_ansi() + shown
        if total and total % w == 0:
            s += "\r\n"  # step past the terminal's pending wrap so the cursor maths holds
        end_row = total // w
        t_row, t_col = divmod(target, w)
        if end_row > t_row:
            s += f"\x1b[{end_row - t_row}A"
        s += "\r" + (f"\x1b[{t_col}C" if t_col else "")
        self._row = t_row
        self._write(s)

    def _set(self, buf: str, pos: int | None = None) -> None:
        self.buf = buf
        self.pos = len(buf) if pos is None else max(0, min(len(buf), pos))
        self._redraw()

    async def _key(self, k: str) -> bool:
        if self.bledit:
            return await self._editor_key(k)
        if not self.at_prompt:
            return True
        b, p = self.buf, self.pos
        if k == "enter":
            return await self._submit()
        if len(k) == 1 and k.isprintable():
            self._set(b[:p] + k + b[p:], p + 1)
        elif k == "backspace" and p:
            self._set(b[:p - 1] + b[p:], p - 1)
        elif k in ("delete",) and p < len(b):
            self._set(b[:p] + b[p + 1:], p)
        elif k == "ctrl-d":
            if b:
                if p < len(b):
                    self._set(b[:p] + b[p + 1:], p)
            elif not self.password:
                self._write("\r\n")
                self.at_prompt = False
                return await self.session.exec("exit")
        elif k == "left":
            self._set(b, p - 1)
        elif k == "right":
            self._set(b, p + 1)
        elif k in ("home", "ctrl-a"):
            self._set(b, 0)
        elif k in ("end", "ctrl-e"):
            self._set(b, len(b))
        elif k == "ctrl-u":
            self._set(b[p:], 0)
        elif k == "ctrl-k":
            self._set(b[:p], p)
        elif k == "ctrl-w":
            left = b[:p].rstrip()
            cut = left.rfind(" ") + 1
            self._set(b[:cut] + b[p:], cut)
        elif k in ("up", "down", "ctrl-p", "ctrl-n"):
            self._history(-1 if k in ("up", "ctrl-p") else 1)
        elif k == "tab":
            self._complete()
        elif k == "ctrl-c":
            self._write(("" if self.password else "") + "^C\r\n")
            self.at_prompt = False
            self.session.pending = None
            await self.session.send_prompt()
        elif k == "ctrl-l":
            self._write("\x1b[H\x1b[2J")
            self._row = 0
            self._redraw(fresh=True)
        return True

    async def _submit(self) -> bool:
        line = self.buf
        self.pos = len(line)
        self._redraw()
        self._write("\r\n")
        self.at_prompt = False
        return await self.session.exec(line)

    def _history(self, step: int) -> None:
        if self.password:
            return
        hist = self.world.game.state.history
        if not hist:
            return
        if self._hist is None:
            self._stash = self.buf
            pos = len(hist)
        else:
            pos = self._hist
        pos = max(0, min(len(hist), pos + step))
        self._hist = pos
        self._set(hist[pos] if pos < len(hist) else self._stash)

    def _complete(self) -> None:
        if self.password:
            return
        head, tail = self.buf[:self.pos], self.buf[self.pos:]
        options = crab.complete(self.world.game, head)
        if not options:
            self._write("\a")
        elif len(options) == 1:
            self._set(options[0] + tail, len(options[0]))
        else:
            prefix = os.path.commonprefix(options)
            if len(prefix) > len(head):
                self._set(prefix + tail, len(prefix))
            else:
                words = "  ".join(o.rsplit(" ", 1)[-1] or o for o in options)
                self.pos = len(self.buf)
                self._redraw()
                self._write("\r\n" + words + "\r\n")
                self._row = 0
                self.pos = len(head)
                self._redraw(fresh=True)

    # ----- full-screen editor -----
    async def _editor_key(self, k: str) -> bool:
        ed = self.bledit
        ed.handle(k)
        if not ed.done:
            self._write(ed.render())
            return True
        self._write(LEAVE_ALT)
        eid, self.bledit, self.bledit_id = self.bledit_id, None, None
        held, self.held = self.held, []
        if held:
            self._write(self._lines(held))
        keep = await self.session.editor_result(eid, ed.result)
        if keep and self.queued_editors:
            await self.editor(*self.queued_editors.pop(0))
        return keep


def chat_lines(game, e: dict) -> list[Text]:
    """A chat entry, the way a Unix box would show it between prompts."""
    t = e["t"] % 1440
    hhmm = f"{t // 60:02d}:{t % 60:02d}"
    name = game.events.name(e["who"])
    if e["channel"] == "dm":
        # write(1)-style
        head = Text("\a")
        head.append(f"Message from {e['who']}@dingaling on pts/{sum(map(ord, e['who'])) % 9 + 1} at {hhmm} ...",
                    style="bold #d8a657")
        return [head, Text(e["text"], style="#b8c4a8"), Text("EOF", style="#5f6f5a")]
    line = Text()
    line.append(f"[{hhmm}] ", style="#5f6f5a")
    line.append(f"{e['channel']} ", style="#7c8f9a")
    line.append(f"<{name}> ", style="bold #9fbf8f")
    line.append(e["text"], style="#b8c4a8")
    return [line]
