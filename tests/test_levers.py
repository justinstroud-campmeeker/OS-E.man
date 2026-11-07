"""Levers: rungs, routes, ghosts, Board nudges, the exposure ladder and demotion."""

import pytest

from os_e_man.game import Game


def sh(game, line):
    return "\n".join(t.plain for t in game.execute(line))


def login(game, pw="gerald2019"):
    sh(game, "su facilities")
    return sh(game, pw)


@pytest.fixture
def game(tmp_path):
    g = Game(save_path=tmp_path / "save.json")
    g.state.t = 11 * 60
    return g


def overnight(game):
    game.state.t = (game.state.day - 1) * 1440 + 16 * 60 + 59
    game.tick(2)


def test_first_route_is_the_old_password(game):
    login(game)
    assert game.state.user == "facilities" and "facilities" in game.state.access
    assert game.state.routes_used == {"facilities": "fac_password"}


def test_badging_through_the_vendors_page(game):
    login(game)
    assert "removed in v2.3" in sh(game, "cat portal.txt")          # the ghost
    assert "linked (ADMIN-SSO" in sh(game, "facil vendors")
    assert "ADMIN-SSO session resumed" in sh(game, "facil vendors tallyho")
    assert "badging" in game.state.access
    assert "3F-KITCHEN" in sh(game, "badge")
    assert "Badge events" in sh(game, "badge log")


def test_badge_levers_move_people(game):
    login(game)
    sh(game, "facil vendors tallyho")
    m0 = game.state.mystique
    sh(game, "badge door 3f-kitchen lock")
    sh(game, "badge revoke doug")
    assert game.state.mystique > m0
    game.tick(30)
    chat = " ".join(e["text"] for e in game.state.ticker_log)
    assert "ACCESS DENIED" in chat and "I'm your manager" in chat
    assert "Addendum 41-A" in sh(game, "webble minutes.lattice-board.example")


def test_the_board_nudges_a_stuck_player(game):
    login(game)
    overnight(game)
    assert "vendors page" in game.state.user_files["/tmp/.lsb-0041"]
    overnight(game)
    assert game.state.pending_glimpse == "facil vendors"
    game.state.t += 90                                   # after 10:00
    sh(game, "pwd")
    assert game.state.history[-1] == "facil vendors"     # up-arrow offers it
    assert ("glimpse", "facil vendors") in game.requests


def test_exposure_ladder_warns_then_demotes(game):
    login(game)
    sh(game, "facil vendors tallyho")
    for x in (4, 6, 7, 8):
        game.state.exposure = x
        game.tick(5)
    assert game.state.warned == 4 and "badging" in game.state.access
    subjects = [m["subject"] for m in game.state.inbox]
    assert any("Performance Improvement Plan" in s for s in subjects)
    game.state.exposure = 9
    game.tick(5)
    st = game.state
    assert "badging" not in st.access and "facilities" in st.access   # only the top rung goes
    assert st.has("route_burned:badge_portal") and st.exposure == 2 and st.warned == 0
    assert any("reassignment" in m["subject"] for m in st.inbox)
    assert "revoked" in sh(game, "facil vendors")
    assert "SSO link revoked" in sh(game, "facil vendors tallyho")


def test_back_up_by_a_different_route(game):
    login(game)
    sh(game, "facil vendors tallyho")
    game.state.exposure = 9
    game.tick(5)
    assert "support@tallyho.example" in game.state.user_files["/home/shared/tallyho-support.txt"]
    from os_e_man.game import Out
    sh(game, "emmy send support@tallyho.example")
    game.requests.pop().on_save("Subject: console reset\n\nplease", Out(game))
    game.tick(30)
    assert any("TH-4471" in m["subject"] for m in game.state.inbox)
    assert "console reset accepted" in sh(game, "webble badge.tallyho.example/reset/th4471")
    assert "badging" in game.state.access


def test_reset_link_needs_the_mail(game):
    assert "Unable to connect" in sh(game, "webble badge.tallyho.example/reset/th4471")


def test_support_ignores_the_wrong_account(game):
    login(game)
    sh(game, "facil vendors tallyho")
    game.state.exposure = 9
    game.tick(5)
    from os_e_man.game import Out
    game.state.user = "pdunn"                           # writing from Pat's own account
    sh(game, "emmy send support@tallyho.example")
    game.requests.pop().on_save("Subject: hi\n\nreset", Out(game))
    assert not game.state.has("route_mail:badge_support")


def test_losing_facilities_opens_the_sticky_note(game):
    login(game)
    game.state.exposure = 9
    game.tick(5)
    st = game.state
    assert st.has("locked_out") and st.user == "pdunn" and "facilities" not in st.access
    assert "halcyon70" in sh(game, "cat /home/shared/scans/scan_0193.txt")
    assert "rotated" in login(game)                      # old password: burned
    login(game, "halcyon70")
    assert st.user == "facilities" and st.routes_used["facilities"] == "fac_sticky"


def test_old_lockout_saves_migrate(tmp_path):
    from os_e_man.state import GameState
    st = GameState(flags=["locked_out", "got_facilities"])
    g = Game(st, tmp_path / "save.json")
    assert st.has("route_burned:fac_password")
    assert g.levers.is_open("fac_sticky")
    g.tick(1)                                            # ghosts appear on the next check
    assert "halcyon70" in sh(g, "cat /home/shared/scans/scan_0193.txt")
