"""Content packs: the world written from outside the machine.

Breakage is dropped; drift (hallucinations) is absorbed and logged.
"""

import asyncio
import json
from pathlib import Path

import pytest

from os_e_man.game import Game
from os_e_man.protocol import hello
from os_e_man.server import WorldServer
from os_e_man.world import CONTINUITY_LOG, World, check_pack

EXAMPLE = Path(__file__).parent.parent / "examples" / "packs" / "stapler.json"


def run(game, line):
    return [t.plain for t in game.execute(line)]


def until(game, day, hhmm):
    h, m = map(int, hhmm.split(":"))
    target = (day - 1) * 1440 + h * 60 + m
    game.tick(target - game.state.t)


@pytest.fixture
def game(tmp_path):
    return Game(save_path=tmp_path / "save.json")


def pack(**sections):
    return {"id": "t", **sections}


# ----------------------------------------------------------------- clean content
def test_example_pack_applies_and_plays(game, tmp_path):
    rep = game.world.apply(EXAMPLE.read_text(encoding="utf-8"))
    assert rep.ok, rep.errors
    assert not rep.errors
    until(game, 1, "11:45")
    subjects = [m["subject"] for m in game.state.inbox]
    assert any("OS-2211" in s for s in subjects)
    chat = [e["text"] for e in game.state.ticker_log]
    assert "who is marguerite. i have worked here six years" in chat
    assert "returned." in chat
    assert "red stapler, RETURNED" in "\n".join(run(game, "cat /home/shared/lost-and-found.txt"))
    # saved, and back after a restart
    files = list((tmp_path / "world").glob("*.json"))
    assert len(files) == 1
    again = Game(save_path=tmp_path / "save.json")
    assert "ex-stapler" in again.world.packs
    assert "e_ex_stapler" in again.events.by_id


def test_pack_applied_twice_is_refused(game):
    assert game.world.apply(pack(beats=[{"id": "b", "channel": "dm", "who": "kev", "text": "hi"}])).ok
    rep = game.world.apply(pack(beats=[{"id": "b2", "channel": "dm", "who": "kev", "text": "hi"}]))
    assert not rep.ok and "already applied" in rep.errors[0]


# ----------------------------------------------------------------- drift is absorbed
def test_hallucinated_person_gets_a_stub_record(game):
    rep = game.world.apply(EXAMPLE.read_text(encoding="utf-8"))
    assert any("marguerite" in d and "no hiring record" in d for d in rep.drift)
    p = game.world.people["marguerite"]
    assert p.get("drift") and "No HR directory entry" in p["role"]
    log = "\n".join(run(game, f"cat {CONTINUITY_LOG}"))
    assert "marguerite" in log and "RRS-0001" in log


def test_mentioned_host_starts_resolving(game):
    game.world.apply(EXAMPLE.read_text(encoding="utf-8"))
    out = "\n".join(run(game, "ping print-07.hpcg.corp"))
    assert "PING print-07.hpcg.corp (10." in out
    assert "100% loss" in out
    assert "Nobody remembers provisioning it" in "\n".join(run(game, "whois print-07.hpcg.corp"))


def test_new_channel_is_just_there(game):
    rep = game.world.apply(pack(beats=[{"id": "b1", "channel": "#3rd-floor-kitchen", "who": "priya",
                                        "text": "whose soup"}]))
    assert any("#3rd-floor-kitchen" in d for d in rep.drift)
    game.tick(1)
    assert game.state.ticker_log[-1]["channel"] == "#3rd-floor-kitchen"


def test_flag_nothing_sets_happens_anyway_overnight(game):
    rep = game.world.apply(pack(emails=[{
        "id": "e1", "when": {"flag": "fire_drill_2024"}, "from": "facilities@hpcg.corp",
        "subject": "Fire drill debrief", "body": "Thank you all for evacuating so calmly."}]))
    assert "fire_drill_2024" in game.world.dangling
    assert any("no record" in d for d in rep.drift)
    until(game, 1, "16:00")
    assert not any(m["id"] == "e1" for m in game.state.inbox)
    until(game, 2, "09:05")
    assert game.state.has("fire_drill_2024")
    assert any(m["id"] == "e1" for m in game.state.inbox)


def test_flag_set_by_the_same_pack_is_not_dangling(game):
    game.world.apply(pack(beats=[
        {"id": "b1", "channel": "dm", "who": "kev", "text": "psst", "flag": "kev_psst"},
        {"id": "b2", "when": {"flag": "kev_psst"}, "channel": "dm", "who": "kev", "text": "nvm"}]))
    assert "kev_psst" not in game.world.dangling


def test_canon_flags_are_known(game):
    game.world.apply(pack(beats=[{"id": "b1", "when": {"flag": "got_facilities"},
                                  "channel": "dm", "who": "kev", "text": "hey brenda"}]))
    assert "got_facilities" not in game.world.dangling


def test_unknown_condition_and_module_are_dropped(game):
    rep = game.world.apply(pack(beats=[{"id": "b1", "when": {"moon": "full", "done": "c99"},
                                        "channel": "dm", "who": "kev", "text": "!"}]))
    assert rep.ok
    assert game.world.beats[-1]["when"] == {}
    assert sum("nobody understands" in d or "never written" in d for d in rep.drift) == 2


def test_id_collision_is_refiled_not_lost(game):
    rep = game.world.apply(pack(emails=[{"id": "e_lnd_welcome", "from": "a@hpcg.corp",
                                         "subject": "again", "body": "again"}]))
    assert rep.ok
    assert "e_lnd_welcome~t" in game.events.by_id
    assert game.events.by_id["e_lnd_welcome"]["subject"] != "again"


def test_omen_effects_are_clamped(game):
    rep = game.world.apply(pack(omens=[{"id": "o1", "kind": "pods", "match": ["matcha"],
                                        "mystique": 50, "exposure": -4}]))
    o = game.world.omens[-1]
    assert (o["mystique"], o["exposure"]) == (3, 0)
    assert any("0-3" in d for d in rep.drift)


def test_unknown_mood_and_section(game):
    rep = game.world.apply({"id": "t", "vibes": 11, "chatter": {"ecstatic": [
        {"channel": "#dunmore-general", "who": "doug", "text": "great quarter everyone"}]}})
    assert rep.ok
    assert game.world.chatter["uneasy"][-1]["text"] == "great quarter everyone"
    assert any("vibes" in d for d in rep.drift) and any("ecstatic" in d for d in rep.drift)


# ----------------------------------------------------------------- breakage is dropped
@pytest.mark.parametrize("text,why", [
    ("see https://example.com/thing", "URL"),
    ("mail me at pat@gmail.com", "real-world domain"),
    ("it phones home to 8.8.8.8", "public IP"),
])
def test_boundary_items_are_dropped(game, text, why):
    rep = check_pack(pack(beats=[
        {"id": "tb1", "channel": "dm", "who": "kev", "text": text},
        {"id": "tb2", "channel": "dm", "who": "kev", "text": "fine"}]), game.world)
    assert rep.ok
    assert [b["id"] for b in rep.pack["beats"]] == ["tb2"]
    assert any(why in e for e in rep.errors)


def test_internal_addresses_are_fine(game):
    rep = check_pack(pack(beats=[{"id": "b1", "channel": "dm", "who": "kev",
                                  "text": "brenda@hpcg.corp says 10.17.0.10 is down"}]), game.world)
    assert not rep.errors


def test_canon_wins(game):
    rep = check_pack(pack(files={"/etc/motd": "pwned"},
                          people={"kev": {"handle": "kev2", "name": "Not Kev"}},
                          hosts={"mail.hpcg.corp": {"ip": "10.0.0.1"}},
                          beats=[{"id": "b1", "channel": "dm", "who": "kev", "text": "ok"}]),
                     game.world)
    assert rep.ok
    assert "files" not in rep.pack and "people" not in rep.pack and "hosts" not in rep.pack
    assert sum("canon wins" in e for e in rep.errors) == 3


def test_external_hosts_are_refused(game):
    rep = check_pack(pack(hosts={"evil.com": {"ip": "10.1.1.1"}}), game.world)
    assert not rep.ok
    assert any("only internal" in e for e in rep.errors)


@pytest.mark.parametrize("raw", ["{not json", "[]", json.dumps({"id": "x"}),
                                 json.dumps({"id": "x", "beats": [{"text": "no id"}]})])
def test_useless_packs_are_rejected(game, raw):
    rep = check_pack(raw, game.world)
    assert not rep.ok and rep.errors


def test_bad_paths_are_refused(game):
    rep = check_pack(pack(files={"../../etc/x": "a", "relative.txt": "b", "/tmp/ok.txt": "c"}),
                     game.world)
    assert list(rep.pack["files"]) == ["/tmp/ok.txt"]


def test_missing_pack_leaves_old_mail_readable(game, tmp_path):
    game.world.apply(pack(emails=[{"id": "e1", "from": "a@hpcg.corp", "subject": "s",
                                   "body": "the body"}]))
    game.tick(1)
    game.save()
    for f in (tmp_path / "world").glob("*.json"):
        f.unlink()
    again = Game.load_or_new(tmp_path / "save.json")
    n = next(i for i, m in enumerate(again.state.inbox, 1) if m["id"] == "e1")
    assert "not retained" in "\n".join(run(again, f"emmy read {n}"))


def test_corrupt_pack_file_is_skipped(tmp_path):
    (tmp_path / "world").mkdir()
    (tmp_path / "world" / "0001-x.json").write_text("{nope", encoding="utf-8")
    w = World(tmp_path / "world")
    assert w.packs == [] and "unreadable" in w.anomalies[0]


# ----------------------------------------------------------------- the director door
async def test_director_door(tmp_path):
    server = WorldServer(tmp_path / "save.json", new=True, publish=False, tick_seconds=3600)
    await server.start()
    try:
        conn, welcome = await hello(server.port, server.token, role="director")
        assert welcome["role"] == "director"
        assert not server.sessions  # outside the machine: not a player
        await conn.send({"op": "digest"})
        d = (await asyncio.wait_for(conn.recv(), 3))["digest"]
        assert d["day"] == 1 and "kev" in d["people"] and "#dunmore-general" in d["channels"]
        assert "meters" in d and "known_flags" in d

        p = EXAMPLE.read_text(encoding="utf-8")
        await conn.send({"op": "check", "pack": p})
        r = await asyncio.wait_for(conn.recv(), 3)
        assert r["ok"] and not (tmp_path / "world").exists()  # dry run

        await conn.send({"op": "apply", "pack": p})
        r = await asyncio.wait_for(conn.recv(), 3)
        assert r["ok"] and r["drift"]
        assert "marguerite" in server.game.world.people
        assert len(list((tmp_path / "world").glob("*.json"))) == 1

        await conn.send({"op": "exec", "line": "shutdown"})  # player ops don't work here
        r = await asyncio.wait_for(conn.recv(), 3)
        assert r["ev"] == "error"
        await conn.close()
    finally:
        await server.stop()


async def test_director_needs_the_token(tmp_path):
    server = WorldServer(tmp_path / "save.json", new=True, publish=False, tick_seconds=3600)
    await server.start()
    try:
        with pytest.raises(ConnectionRefusedError):
            await hello(server.port, "wrong", role="director")
    finally:
        await server.stop()
