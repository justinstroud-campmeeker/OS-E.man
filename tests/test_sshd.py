"""ssh door integration tests: an in-process world server, driven over real ssh.

Most tests use asyncssh as the client (portable, fast). One test drives the system's
own OpenSSH client (Windows' built-in ssh.exe) and is skipped if there isn't one.
"""

import asyncio
import re

import asyncssh
import pytest

from os_e_man.server import WorldServer
from os_e_man.sshd import HOST_ALIAS, LOGIN, find_ssh, key_files, ssh_command

ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]|\x1b\][^\x07]*\x07|\x1b[=>]")


def plain(s: str) -> str:
    return ANSI.sub("", s)


@pytest.fixture
async def server(tmp_path):
    s = WorldServer(tmp_path / "save.json", new=True, publish=False, tick_seconds=3600, ssh_port=0)
    await s.start()
    yield s
    await s.stop()


async def _connect(server, username=LOGIN):
    kf = key_files(server.save_path)
    return await asyncio.wait_for(asyncssh.connect(
        "127.0.0.1", server.ssh_port, username=username, client_keys=[str(kf.client)],
        known_hosts=str(kf.known_hosts), host_key_alias=HOST_ALIAS), 5)


class Screen:
    """Reads a pty session and waits for things to show up in it."""

    def __init__(self, proc):
        self.proc = proc
        self.raw = ""
        self.mark = 0

    async def until(self, pattern: str, timeout: float = 3.0) -> str:
        """Wait for `pattern` (plain text) after the last mark; returns the new text."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while pattern not in plain(self.raw[self.mark:]):
            left = deadline - loop.time()
            if left <= 0:
                raise AssertionError(f"never saw {pattern!r} in:\n{plain(self.raw[self.mark:])}")
            try:
                chunk = await asyncio.wait_for(self.proc.stdout.read(65536), left)
            except asyncio.TimeoutError:
                continue
            if not chunk:
                raise AssertionError(f"session closed before {pattern!r}")
            self.raw += chunk
        new = self.raw[self.mark:]
        self.mark = len(self.raw)
        return new

    def send(self, data: str) -> None:
        self.proc.stdin.write(data)


@pytest.fixture
async def screen(server):
    conn = await _connect(server)
    proc = await conn.create_process(term_type="xterm-256color", term_size=(100, 30))
    sc = Screen(proc)
    await sc.until("pdunn@wks-0417:~$ ")
    yield sc
    conn.close()


async def test_login_banner_and_command(screen, server):
    assert "Type `emmy`" in plain(screen.raw)
    screen.send("whoami\r")
    out = plain(await screen.until("pdunn@wks-0417:~$ "))
    lines = [l for l in out.replace("\r", "").split("\n") if l]
    # the typed line is on screen once (the terminal's), not echoed again by the game
    assert sum("$ whoami" in l for l in lines) == 1
    assert "pdunn" in lines
    assert len(server.sessions) == 1


async def test_wrong_user_rejected(server):
    with pytest.raises(asyncssh.PermissionDenied):
        await _connect(server, username="root")


async def test_password_prompt_is_masked(screen, server):
    screen.send("su facilities\r")
    await screen.until("Password: ")
    screen.send("gerald2019\r")
    out = await screen.until("facilities@wks-0417:~$ ")
    assert "gerald2019" not in plain(screen.raw)
    assert "Office Services" in plain(out)
    assert server.game.state.user == "facilities"


async def test_ctrl_c_cancels_password_prompt(screen, server):
    screen.send("su facilities\r")
    await screen.until("Password: ")
    screen.send("\x03")
    await screen.until("^C")
    screen.send("whoami\r")
    out = plain(await screen.until("$ "))
    assert "pdunn" in out and server.game.state.user == "pdunn"


async def test_tab_completion_and_history(screen):
    screen.send("tra\t")
    await screen.until("train ")
    screen.send("\x15echo one\r")        # ^U clears the line
    await screen.until("one")
    screen.send("\x1b[A\r")              # up arrow recalls `echo one`
    out = plain(await screen.until("$ "))
    assert "one" in out


async def test_editor_round_trip(screen, server):
    st = server.game.state
    st.challenges_done.append("c1")
    st.set_flag("enrolled")
    screen.send("train submit\r")
    await screen.until("bledit 0.9")
    assert "\x1b[?1049h" in screen.raw   # alternate screen, like a real full-screen editor
    screen.send("" * 30)            # ^K the template away, line by line
    screen.send("SELECT store_id, SUM(amount) FROM transactions GROUP BY store_id")
    screen.send("\x0f")                  # ^O write out
    await screen.until("Wrote 1 line")
    screen.send("\x18")                  # ^X exit
    out = plain(await screen.until("grader: PASS"))
    assert "c2" in st.challenges_done
    assert "\x1b[?1049l" in screen.raw


async def test_chat_arrives_between_prompts(screen, server):
    screen.send("who")                   # half-typed when the message lands
    await screen.until("who")
    server.game.post("#dunmore-general", "kev", "is pdunn real")
    await server.advance(0)
    out = plain(await screen.until("is pdunn real"))
    assert "#dunmore-general" in out
    # the prompt and the half-typed line are redrawn under the message
    if "$ who" not in out.split("is pdunn real", 1)[1]:
        await screen.until("$ who")
    screen.send("ami\r")
    assert "pdunn" in plain(await screen.until("$ "))


async def test_dm_is_write_style(screen, server):
    server.game.post("dm", "kev", "u up")
    await server.advance(0)
    out = plain(await screen.until("EOF"))
    assert "Message from kev@" in out and "u up" in out


async def test_chat_held_while_editor_open(screen, server):
    screen.send("bledit ~/notes.txt\r")
    await screen.until("bledit 0.9")
    server.game.post("#dunmore-general", "kev", "anyone seen the stapler")
    await server.advance(0)
    await asyncio.sleep(0.1)
    screen.send("\x18")                  # exit unmodified
    out = plain(await screen.until("anyone seen the stapler"))
    assert out


async def test_mesg_n_silences_chat(screen, server):
    screen.send("mesg n\r")
    await screen.until("$ ")
    server.game.post("#dunmore-general", "kev", "quiet one")
    await server.advance(0)
    screen.send("mesg\r")
    out = plain(await screen.until("is n"))
    assert "quiet one" not in plain(screen.raw)
    screen.send("mesg y\r")
    await screen.until("$ ")
    assert not server.game.state.has("mesg_n")
    assert out


async def test_quit_closes_connection(screen, server):
    screen.send("quit\r")
    await screen.until("Connection to wks-0417 closed")
    await asyncio.wait_for(screen.proc.wait_closed(), 3)
    for _ in range(20):
        if not server.sessions:
            break
        await asyncio.sleep(0.05)
    assert not server.sessions


async def test_shutdown_reaches_ssh_sessions(server):
    conn = await _connect(server)
    proc = await conn.create_process(term_type="xterm", term_size=(80, 24))
    sc = Screen(proc)
    await sc.until("$ ")
    await server.stop()
    await sc.until("The system is going down.")
    await asyncio.wait_for(proc.wait_closed(), 3)


@pytest.mark.skipif(find_ssh() is None, reason="no OpenSSH client on this machine")
async def test_system_ssh_client(server):
    """The real thing: the OS's ssh binary, with the exact command `python -m os_e_man` runs."""
    cmd = ssh_command(server.save_path, server.ssh_port, find_ssh(), tty="-tt")
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE)
    for _ in range(100):
        if server.sessions or proc.returncode is not None:
            break
        await asyncio.sleep(0.05)
    assert server.sessions, (await proc.stderr.read()).decode(errors="replace")
    proc.stdin.write(b"whoami\rquit\r")
    out, err = await asyncio.wait_for(proc.communicate(), 10)
    text = plain(out.decode("utf-8", errors="replace"))
    assert proc.returncode == 0, err.decode(errors="replace")
    assert "\npdunn\r" in text.replace("\r\n", "\r\n\n") or "pdunn\r\n" in text
    assert "Connection to wks-0417 closed" in text
