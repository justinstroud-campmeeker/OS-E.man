"""Unlocks: a new command or flag installs itself every game day."""

import pytest

from os_e_man.game import Game


def sh(game, line):
    return "\n".join(t.plain for t in game.execute(line))


@pytest.fixture
def game(tmp_path):
    g = Game(save_path=tmp_path / "save.json")
    g.state.t = 10 * 60
    return g


def give(game, uid):
    game.state.access.append(f"u:{uid}")


def test_first_unlock_arrives_soon_then_one_a_day(game):
    assert game.state.next_unlock_t
    out = game.tick(130)
    assert "u:finger" in game.state.access
    assert any("finger" in t.plain and "installed" in t.plain for t in out)
    nxt = game.state.next_unlock_t
    assert (nxt // 1440 + 1) == game.state.day + 1 and 600 <= nxt % 1440 <= 960


def test_unlocks_wait_for_their_requirements(game):
    for uid in ("finger", "at", "dingaling-post"):
        give(game, uid)
    assert game.unlocks.next_one() is None          # quiet needs facilities first
    game.state.set_flag("got_facilities")
    assert game.unlocks.next_one()["id"] == "quiet"


def test_locked_commands_are_hidden(game):
    assert "command not found" in sh(game, "finger kev") or "not found" in sh(game, "finger kev")
    assert "disabled" in sh(game, "dingaling post #dunmore-general hi")


def test_finger(game):
    give(game, "finger")
    game.post("#dunmore-general", "kev", "is it friday")
    out = sh(game, "finger kmarsh")
    assert "Login: kmarsh" in out and "is it friday" in out
    assert "no such user" in sh(game, "finger nobody")


def test_at_runs_jobs_while_you_wait(game):
    give(game, "at")
    assert "job 1 at day 1 10:30" in sh(game, "at 10:30 echo hello from the past")
    assert "echo hello" in sh(game, "at -l")
    out = "\n".join(t.plain for t in game.tick(31))
    assert "hello from the past" in out and not game.state.at_jobs
    assert "job 1 at day 2 09:15" in sh(game, "at 09:15 pwd")       # passed: tomorrow
    assert "removed" in sh(game, "at -r 1") and not game.state.at_jobs
    assert "usage" in sh(game, "at 25:00 pwd") and "usage" in sh(game, "at 10:00 at 11:00 pwd")


def test_anonymous_post_makes_people_react(game):
    give(game, "dingaling-post")
    m0 = game.state.mystique
    sh(game, "dingaling post #dunmore-general the thermostat is listening")
    assert any(e["who"] == "(unattributed)" for e in game.state.ticker_log[-3:])
    assert game.state.mystique == m0 + 1
    game.tick(13)
    assert any(e["text"].startswith(("who posted", "the message", "whoever posted", "it wasn't me"))
               for e in game.state.ticker_log)


def test_quiet_halves_exposure(game):
    game.state.user = "facilities"
    game.state.access.append("facilities")
    assert "unrecognized option" in sh(game, "facil --quiet pods matcha")
    give(game, "quiet")
    game.omens.omens.append({"id": "o_t", "kind": "pods", "match": ["zzz"], "mystique": 0,
                             "exposure": 3, "reactions": []})
    e0 = game.state.exposure
    sh(game, "facil --quiet pods zzz")
    assert game.state.exposure == e0 + 1 and not game.quiet          # 3 halved
