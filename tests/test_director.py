"""The director loop: digest -> plan -> writers -> pack -> check -> apply."""

import asyncio
import json

import pytest

from os_e_man.director import (FakeModel, LocalLink, ServerLink, extract_json, pack_id_for,
                               plan_prompt, run_once, target_day, writer_prompt)
from os_e_man.game import Game
from os_e_man.protocol import hello
from os_e_man.server import WorldServer


def until(game, day, hhmm):
    # tick a minute at a time: 17:00 jumps the clock to tomorrow 09:00
    h, m = map(int, hhmm.split(":"))
    while (game.state.day, game.state.minute_of_day) < (day, h * 60 + m):
        game.tick(1)


@pytest.fixture
def game(tmp_path):
    return Game(save_path=tmp_path / "save.json")


class Scripted:
    """A model that says whatever the test tells it to, per task."""

    name = "scripted"

    def __init__(self, **replies):
        self.replies = replies
        self.fake = FakeModel()

    def complete(self, task, prompt):
        r = self.replies.get(task)
        if isinstance(r, Exception):
            raise r
        return r if r is not None else self.fake.complete(task, prompt)


def go(link, model, **kw):
    return asyncio.run(run_once(link, model, **kw))


# ----------------------------------------------------------------- the happy path
def test_fake_director_writes_a_day_that_plays(game, tmp_path):
    res = go(LocalLink(game), FakeModel(), transcript_dir=tmp_path / "director")
    assert res.status == "applied", res
    assert res.day == 1 and res.pack_id == "dir-d001"
    assert not res.report["errors"] and not res.log
    assert "dir-d001" in game.world.packs
    until(game, 1, "16:30")
    chat = [e["text"] for e in game.state.ticker_log]
    assert any("Hold" in t for t in chat)          # day 1 -> theme 1
    assert any(m["id"] == "e_dir1" for m in game.state.inbox)
    t = json.loads((tmp_path / "director" / "dir-d001.json").read_text(encoding="utf-8"))
    assert [x["task"] for x in t["transcript"]] == ["plan", "chatter", "beats", "emails"]


def test_a_written_day_is_not_written_twice(game):
    assert go(LocalLink(game), FakeModel()).status == "applied"
    again = go(LocalLink(game), FakeModel())
    assert again.status == "skipped" and "already written" in again.log[0]
    assert game.world.packs.count("dir-d001") == 1


def test_late_in_the_day_it_writes_tomorrow(game):
    until(game, 1, "16:30")
    res = go(LocalLink(game), FakeModel())
    assert res.status == "applied" and res.day == 2
    until(game, 2, "16:30")
    assert any(m["id"] == "e_dir2" for m in game.state.inbox)


def test_several_days_of_fake_content_apply_cleanly(game):
    for day in (1, 2, 3, 4):
        until(game, day, "16:10")
        res = go(LocalLink(game), FakeModel())
        assert res.status == "applied" and not res.report["errors"], res
        assert "!" not in json.dumps(res.report)
    assert game.world.packs == ["dir-d002", "dir-d003", "dir-d004", "dir-d005"]


def test_dry_run_changes_nothing(game, tmp_path):
    res = go(LocalLink(game), FakeModel(), dry_run=True)
    assert res.status == "checked" and res.report["ok"]
    assert not game.world.packs and not (tmp_path / "world").exists()


def test_scheduling():
    assert target_day({"day": 3, "clock": "09:00"}) == 3
    assert target_day({"day": 3, "clock": "16:59"}) == 4
    assert pack_id_for(12) == "dir-d012"


# ----------------------------------------------------------------- a bad model costs slots, not the world
def test_garbage_from_one_slot_drops_only_that_slot(game):
    res = go(LocalLink(game), Scripted(beats="I'm sorry, I can't help with that."))
    assert res.status == "applied"
    assert any("beats: nothing usable" in line for line in res.log)
    assert not any(b["id"].startswith("b_dir") for b in game.world.beats)
    assert any(e["id"] == "e_dir1" for e in game.world.emails)


def test_a_model_that_falls_over_writes_nothing(game):
    boom = RuntimeError("connection refused")
    res = go(LocalLink(game), Scripted(plan=boom, chatter=boom, beats=boom, emails=boom))
    assert res.status == "empty" and not game.world.packs
    assert any("model failed" in line for line in res.log)


def test_unparsable_plan_falls_back_to_defaults(game):
    res = go(LocalLink(game), Scripted(plan="sure! here's a plan: be spooky"))
    assert res.status == "applied"


def test_hallucinations_are_absorbed(game):
    beats = json.dumps([{"id": "b_h1", "when": {"day": 1, "at": "10:00"}, "channel": "#4th-floor",
                         "who": "marguerite", "text": "the stapler is back where it belongs"}])
    res = go(LocalLink(game), Scripted(beats=beats))
    assert res.status == "applied"
    assert "marguerite" in game.world.people and "#4th-floor" in game.world.channels
    assert res.report["drift"]


def test_boundary_violations_are_dropped(game):
    beats = json.dumps([
        {"id": "b_x1", "channel": "dm", "who": "kev", "text": "check https://example.com"},
        {"id": "b_x2", "channel": "dm", "who": "kev", "text": "never mind"}])
    res = go(LocalLink(game), Scripted(beats=beats))
    assert res.status == "applied"
    ids = {b["id"] for b in game.world.beats}
    assert "b_x2" in ids and "b_x1" not in ids
    assert any("URL" in e for e in res.report["errors"])


def test_extract_json():
    assert extract_json('Sure.\n```json\n{"a": [1, 2]}\n```') == {"a": [1, 2]}
    assert extract_json("no json [here at all") is None
    assert extract_json('[{"x": 1}] trailing') == [{"x": 1}]
    assert extract_json(None) is None


def test_prompts_carry_the_situation(game):
    d = game.world.digest(game)
    p = plan_prompt(d, 2)
    assert "You are writing day 2" in p and "kev" in p and "#dunmore-general" in p
    assert "Reply with JSON only" in writer_prompt("emails", d, 2, "a note")
    assert "a note" in writer_prompt("beats", d, 2, "a note")


def test_prompts_carry_voices_and_id_prefix(game):
    d = game.world.digest(game)
    assert d["voices"]["kev"] and all(len(v) <= 3 for v in d["voices"].values())
    p = writer_prompt("beats", d, 4, "n")
    assert 'Start every id with "d4_"' in p and d["voices"]["kev"][0] in p
    assert "kmarsh@hpcg.corp" in p


# ----------------------------------------------------------------- an OpenAI-compatible endpoint
def _chat_model(handler):
    import httpx
    from os_e_man.director import ChatModel
    return ChatModel("groq", "https://api.groq.test/openai/v1", "m1", api_key="k",
                     client=httpx.Client(transport=httpx.MockTransport(handler)))


def _reply(content):
    import httpx
    return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})


def test_chat_model_speaks_openai(game):
    seen = []

    def handler(req):
        seen.append(req)
        return _reply(FakeModel().complete("beats", "Tomorrow is day 1."))

    m = _chat_model(handler)
    assert m.name == "groq:m1"
    out = m.complete("beats", "write JSON")
    assert extract_json(out)[0]["id"] == "b_dir1_1"
    body = json.loads(seen[0].content)
    assert seen[0].url.path == "/openai/v1/chat/completions"
    assert seen[0].headers["authorization"] == "Bearer k"
    assert body["model"] == "m1" and body["response_format"] == {"type": "json_object"}


def test_chat_model_retries_rate_limits_and_json_failures():
    import httpx
    calls = []

    def handler(req):
        calls.append(json.loads(req.content))
        if len(calls) == 1:
            return httpx.Response(429, headers={"retry-after": "0"})
        if len(calls) == 2:
            return httpx.Response(400, text='{"error": {"code": "json_validate_failed"}}')
        return _reply('{"ok": 1}')

    assert _chat_model(handler).complete("plan", "p") == '{"ok": 1}'
    assert "response_format" in calls[1] and "response_format" not in calls[2]


def test_a_chat_model_through_the_whole_loop(game):
    fake = FakeModel()

    def handler(req):
        prompt = json.loads(req.content)["messages"][0]["content"]
        tail = prompt.rsplit("Reply as: ", 1)[1]
        task = ("plan" if tail.startswith('{"notes"') else "chatter" if tail.startswith('{"normal"')
                else "beats" if tail.startswith('{"beats"') else "emails")
        return _reply(fake.complete(task, prompt))

    res = go(LocalLink(game), _chat_model(handler))
    assert res.status == "applied" and not res.report["errors"], res


def test_make_model_needs_a_key(monkeypatch):
    from os_e_man.director import make_model
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    with pytest.raises(SystemExit, match="GROQ_API_KEY"):
        make_model("groq")
    monkeypatch.setenv("GROQ_API_KEY", "k")
    assert make_model("groq").name == "groq:openai/gpt-oss-120b"
    assert make_model("groq", "qwen/qwen3.8-27b").name == "groq:qwen/qwen3.8-27b"


# ----------------------------------------------------------------- through the director door
async def test_director_through_the_door(tmp_path):
    server = WorldServer(tmp_path / "save.json", new=True, publish=False, tick_seconds=3600)
    await server.start()
    try:
        conn, _ = await hello(server.port, server.token, role="director")
        res = await run_once(ServerLink(conn), FakeModel())
        assert res.status == "applied" and res.report["ok"]
        assert not server.sessions
        assert "dir-d001" in server.game.world.packs
        assert len(list((tmp_path / "world").glob("*.json"))) == 1
        again = await run_once(ServerLink(conn), FakeModel())
        assert again.status == "skipped"
        await conn.close()
    finally:
        await server.stop()


# ----------------------------------------------------------------- branches: decided at write time, picked at play time
def test_below_conditions(game):
    from os_e_man.world import check_pack
    rep = game.world.apply({"id": "t", "beats": [
        {"id": "calm", "when": {"at": "09:30", "mystique_below": 3}, "channel": "dm", "who": "kev", "text": "calm"},
        {"id": "tense", "when": {"at": "09:30", "mystique": 3}, "channel": "dm", "who": "kev", "text": "tense"}]})
    assert rep.ok and not rep.drift
    until(game, 1, "09:31")
    fired = [e["text"] for e in game.state.ticker_log]
    assert "calm" in fired and "tense" not in fired
    assert check_pack({"id": "u", "beats": [{"id": "x", "when": {"curiosity_below": "lots"},
                                             "channel": "dm", "who": "kev", "text": "x"}]},
                      game.world).errors


@pytest.mark.parametrize("mystique,expect,other", [(0, "calm", "tense"), (4, "tense", "calm")])
def test_the_branch_follows_the_player(game, mystique, expect, other):
    go(LocalLink(game), FakeModel())          # day 1 -> the Hold booking, fork at 15:40
    game.state.mystique = mystique
    until(game, 1, "15:41")
    fired = set(game.state.beats_fired)
    assert f"b_dir1_{expect}" in fired and f"b_dir1_{other}" not in fired


# ----------------------------------------------------------------- storylines
def test_threads_are_kept_and_shown(game, tmp_path):
    res = go(LocalLink(game), FakeModel())
    assert res.status == "applied"
    d = game.world.digest(game)
    assert [t["id"] for t in d["threads"]] == ["hold-booking"]
    assert d["threads"][0]["day"] == 1 and d["written_days"]["1"].startswith("chatter:")
    again = Game(save_path=tmp_path / "save.json")            # replays from the world folder
    assert "hold-booking" in again.world.threads and 1 in again.world.written


def test_threads_are_checked(game):
    from os_e_man.world import check_pack
    rep = check_pack({"id": "t", "for_day": 3, "threads": [
        {"id": "ok-one", "title": "fine", "state": "weird"},
        {"id": "bad id!", "title": "x"},
        {"id": "url", "title": "see https://example.com"}],
        "beats": [{"id": "b", "channel": "dm", "who": "kev", "text": "."}]}, game.world)
    assert rep.ok and rep.pack["for_day"] == 3
    assert rep.pack["threads"] == [{"id": "ok-one", "title": "fine", "state": "open"}]
    assert not check_pack({"id": "t2", "threads": [{"id": "a", "title": "b"}]}, game.world).ok


# ----------------------------------------------------------------- writing ahead while the player is away
class Recording(FakeModel):
    def __init__(self):
        self.prompts = []

    def complete(self, task, prompt):
        self.prompts.append((task, prompt))
        return super().complete(task, prompt)


def test_ahead_writes_several_days_that_remember_each_other(game):
    from os_e_man.director import run_ahead
    until(game, 1, "16:30")                    # player has gone home: start with tomorrow
    m = Recording()
    rs = asyncio.run(run_ahead(LocalLink(game), m, days=3))
    assert [(r.day, r.status) for r in rs] == [(2, "applied"), (3, "applied"), (4, "applied")]
    assert game.world.packs == ["dir-d002", "dir-d003", "dir-d004"]
    plans = [p for t, p in m.prompts if t == "plan"]
    assert "(none yet)" in plans[0].split("Your storylines so far:")[1].split("\n")[1]
    assert "rtl-0042-hours" in plans[1] and "day 2:" in plans[1]      # day 3 sees day 2
    assert "fridge-labels" in plans[2] and "rtl-0042-hours" in plans[2] and "day 3:" in plans[2]


def test_ahead_skips_written_days_and_respects_the_budget(game):
    from os_e_man.director import CALLS_PER_DAY, run_ahead
    go(LocalLink(game), FakeModel())           # day 1 already written
    rs = asyncio.run(run_ahead(LocalLink(game), FakeModel(), days=5, budget=2 * CALLS_PER_DAY + 1))
    assert [r.day for r in rs if r.status == "applied"] == [2, 3]
    assert rs[-1].status == "skipped" and "budget" in rs[-1].log[0]


def test_ahead_stops_when_the_model_is_down(game):
    from os_e_man.director import run_ahead
    boom = OSError("no route")
    rs = asyncio.run(run_ahead(LocalLink(game), Scripted(plan=boom, chatter=boom, beats=boom,
                                                         emails=boom), days=5))
    assert len(rs) == 1 and rs[0].status == "empty" and not game.world.packs


async def test_digest_says_whether_anyone_is_playing(tmp_path):
    server = WorldServer(tmp_path / "save.json", new=True, publish=False, tick_seconds=3600)
    await server.start()
    try:
        d_conn, _ = await hello(server.port, server.token, role="director")
        link = ServerLink(d_conn)
        assert (await link.digest())["players"] == 0
        p_conn, _ = await hello(server.port, server.token)
        assert (await link.digest())["players"] == 1
        await p_conn.close()
        await d_conn.close()
    finally:
        await server.stop()


def test_lines_already_said_are_filed_once(game):
    canon = game.world.digest(game)["voices"]["kev"][0]
    rep = game.world.apply({"id": "t", "chatter": {"normal": [
        {"channel": "#dunmore-general", "who": "kev", "text": canon.upper() + "!!"},
        {"channel": "#dunmore-general", "who": "kev", "text": "a new thing"},
        {"channel": "#dunmore-general", "who": "kev", "text": "A new thing."}]}})
    assert [c["text"] for c in rep.pack["chatter"]["normal"]] == ["a new thing"]
    assert sum("already said" in d for d in rep.drift) == 2
    rep = game.world.apply({"id": "t2", "beats": [{"id": "b", "channel": "dm", "who": "kev",
                                                    "text": "a new thing"}]})
    assert not rep.ok                                   # nothing left that hasn't been said
