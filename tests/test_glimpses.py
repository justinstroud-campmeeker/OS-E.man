"""Glimpses: a rare flicker with an address in it, which becomes a quest."""

import pytest

from os_e_man.game import Game
from os_e_man.glimpses import MUNDANE_AFTER, TODO


def run(game, line):
    return "\n".join(t.plain for t in game.execute(line))


@pytest.fixture
def game(tmp_path):
    g = Game(save_path=tmp_path / "save.json")
    g.state.t = 11 * 60          # day 1, 11:00
    g.glimpses.rng.seed(1)
    return g


def idle(game, n):
    for _ in range(n):
        game.execute("pwd")


def test_mundane_play_brings_a_glimpse(game):
    idle(game, MUNDANE_AFTER - 1)
    assert not game.state.glimpses
    idle(game, 60)
    assert game.state.glimpses == ["g_minutes"]
    assert "webble minutes.lattice-board.example" in game.state.history
    assert "- [ ] minutes.lattice-board.example" in game.state.user_files[TODO]


def test_the_request_reaches_the_terminal(game):
    game.state.mundane = 999
    game.glimpses.rng.random = lambda: 0.0
    game.execute("pwd")
    assert ("glimpse", "minutes.lattice-board.example") in game.requests


def test_progress_resets_the_count(game):
    idle(game, MUNDANE_AFTER + 3)
    game.state.glimpses.clear()
    game.state.set_flag("something_happened")
    game.state.mundane = 5
    before = game.glimpses.snapshot()
    game.state.set_flag("another")
    game.glimpses.after_command(before)
    assert game.state.mundane == 0


def test_at_most_one_a_day_and_not_too_early(game):
    game.glimpses.rng.random = lambda: 0.0
    game.state.mundane = 999
    game.execute("pwd")
    assert len(game.state.glimpses) == 1
    game.state.mundane = 999
    game.execute("pwd")
    assert len(game.state.glimpses) == 1      # same day
    g2 = Game()
    g2.state.t = 9 * 60 + 30
    g2.state.mundane = 999
    g2.glimpses.rng.random = lambda: 0.0
    g2.execute("pwd")
    assert not g2.state.glimpses              # before 10:00


def test_web_quest(game):
    game.glimpses.show(game.glimpses.by_id["g_minutes"])
    out = run(game, "webble minutes.lattice-board.example")
    assert "Session 41" in out and "[1] minutes.lattice-board.example/attendance" in out
    assert game.state.has("glimpse:g_minutes:done")
    assert "- [x] minutes.lattice-board.example" in run(game, f"cat {TODO}")
    assert "PRESENT" in run(game, "webble 1")
    assert "Unable to connect" in run(game, "webble www.nowhere.example")


def test_mail_quest_gets_a_reply(game):
    game.state.set_flag("glimpse:g_minutes:done")
    game.glimpses.show(game.glimpses.by_id["g_custodian"])
    game.execute("emmy send custodian@lattice-board.example")
    req = game.requests.pop()
    from os_e_man.game import Out
    req.on_save("Subject: hello?\n\nwho are you", Out(game))
    assert game.state.has("glimpse:g_custodian:done")
    assert game.state.sent_mail[-1]["subject"] == "hello?"
    game.tick(40)
    assert any(m["id"] == "e_g_custodian_reply" for m in game.state.inbox)


def test_other_mail(game):
    from os_e_man.game import Out
    for addr, expect in (("kmarsh@hpcg.corp", "sent to"), ("someone@elsewhere.example", "550")):
        game.execute(f"emmy send {addr}")
        out = Out(game)
        game.requests.pop().on_save("Subject: hi\n\nhi", out)
        assert expect in "\n".join(out.plain())
    assert "usage" in run(game, "emmy send not-an-address")


def test_old_saves_load(tmp_path):
    from os_e_man.state import GameState
    st = GameState.from_dict({"t": 600, "flags": ["x"]})     # a save from before glimpses
    assert st.glimpses == [] and st.mundane == 0
