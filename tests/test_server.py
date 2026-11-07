"""World server tests: an in-process server driven by a raw JSON client."""

import asyncio

import pytest
from rich.text import Text

from os_e_man.protocol import hello, open_connection, text_from_wire, text_to_wire
from os_e_man.server import WorldServer
from os_e_man.state import GameState


def test_text_round_trip(game):
    t = game.fmt("notes: [[R2:the lobby plant]] end", "warn")
    back = text_from_wire(text_to_wire(t))
    assert back.plain == t.plain
    assert [(s.start, s.end, str(s.style)) for s in back.spans] == \
           [(s.start, s.end, str(s.style)) for s in t.spans]
    assert str(back.style) == str(t.style)


@pytest.fixture
async def server(tmp_path):
    s = WorldServer(tmp_path / "save.json", new=True, publish=False, tick_seconds=3600)
    await s.start()
    yield s
    await s.stop()


async def _until(conn, ev, limit=20):
    for _ in range(limit):
        msg = await asyncio.wait_for(conn.recv(), 3)
        if msg is None:
            return None
        if msg.get("ev") == ev:
            return msg
    raise AssertionError(f"no {ev}")


def _plain(msg):
    return [text_from_wire(d).plain for d in msg["lines"]]


async def test_bad_token_rejected(server):
    conn = await open_connection(server.port)
    await conn.send({"op": "hello", "token": "nope"})
    msg = await conn.recv()
    assert msg["ev"] == "bye"
    with pytest.raises(ConnectionRefusedError):
        await hello(server.port, "nope")


async def test_exec_and_output(server):
    conn, welcome = await hello(server.port, server.token)
    assert welcome["prompt"].startswith("pdunn@wks-0417")
    await conn.send({"op": "exec", "line": "whoami"})
    out = await _until(conn, "output")
    assert _plain(out)[-1] == "pdunn"
    await conn.close()


async def test_password_prompt_is_per_connection(server):
    a, _ = await hello(server.port, server.token)
    b, _ = await hello(server.port, server.token)
    await a.send({"op": "exec", "line": "su facilities"})
    p = await _until(a, "prompt")
    assert p["password"] and p["label"] == "Password: "
    # b's next line is a normal command, not a's password
    await b.send({"op": "exec", "line": "whoami"})
    assert _plain(await _until(b, "output"))[-1] == "pdunn"
    await a.send({"op": "exec", "line": "gerald2019"})
    out = await _until(a, "output")
    assert not any("gerald2019" in line for line in _plain(out))
    assert server.game.state.user == "facilities"
    await a.close()
    await b.close()


async def test_editor_round_trip(server):
    conn, _ = await hello(server.port, server.token)
    server.game.state.challenges_done.append("c1")
    server.game.state.set_flag("enrolled")
    await conn.send({"op": "exec", "line": "train submit"})
    ed = await _until(conn, "editor")
    await conn.send({"op": "editor_result", "id": ed["id"],
                     "text": "SELECT store_id, SUM(amount) FROM transactions GROUP BY store_id"})
    out = await _until(conn, "output")
    assert "grader: PASS" in _plain(out)
    assert "c2" in server.game.state.challenges_done
    await conn.close()


async def test_ticker_broadcast_to_all(server):
    a, _ = await hello(server.port, server.token)
    b, _ = await hello(server.port, server.token)
    server.game.post("#dunmore-general", "kev", "hello everyone")
    await server.advance(0)
    for c in (a, b):
        msg = await _until(c, "ticker")
        assert msg["entries"][0]["text"] == "hello everyone"
    await a.close()
    await b.close()


async def test_detached_clock_holds_before_five(server):
    st = server.game.state
    st.t = 16 * 60 + 50
    await server.advance(30)  # nobody connected
    assert st.day == 1 and st.clock == "16:59"
    conn, _ = await hello(server.port, server.token)
    await server.advance(2)
    assert st.day == 2
    await conn.close()


async def test_quit_detaches_and_saves(server, tmp_path):
    conn, _ = await hello(server.port, server.token)
    await conn.send({"op": "exec", "line": "echo hi"})
    await _until(conn, "output")
    await conn.send({"op": "exec", "line": "quit"})
    bye = await _until(conn, "bye")
    assert bye["reason"] == "disconnected"
    await asyncio.sleep(0.1)
    assert not server.sessions
    saved = GameState.load(tmp_path / "save.json")
    assert "echo hi" in saved.history


async def test_crashing_command_does_not_kill_server(server, monkeypatch):
    from os_e_man.shell import crab
    crab._load_commands()
    def boom(game, args, out):
        raise RuntimeError("kaboom")
    monkeypatch.setattr(crab.REGISTRY["echo"], "fn", boom)
    conn, _ = await hello(server.port, server.token)
    await conn.send({"op": "exec", "line": "echo x"})
    out = await _until(conn, "output")
    assert "Segmentation fault" in _plain(out)[-1]
    await conn.send({"op": "exec", "line": "whoami"})
    assert _plain(await _until(conn, "output"))[-1] == "pdunn"
    await conn.close()
