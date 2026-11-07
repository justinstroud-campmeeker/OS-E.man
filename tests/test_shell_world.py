from os_e_man.state import GameState


def test_fs_navigation(game, sh):
    assert sh("pwd")[-1] == "/home/pdunn"
    sh("cd /srv/training")
    assert game.state.cwd == "/srv/training"
    assert ".staging/" not in sh("ls")[-1]
    assert ".staging/" in sh("ls -a")[-1]
    sh("cd ..")
    assert game.state.cwd == "/srv"
    assert "Permission denied" in sh("cat /srv/facilities/portal.txt")[-1]
    assert "No such file" in sh("cat nope.txt")[-1]


def test_pipe_to_grep(sh):
    out = sh("cat /var/log/pos-sync.log | grep -i RELAY")
    assert len(out) == 2 and "svc-relay" in out[1]


def test_unknown_command_and_hidden_facil(sh):
    assert "command not found" in sh("rm -rf /")[-1]
    assert "command not found" in sh("facil status")[-1]


def test_su_facilities_and_omen(game, sh):
    sh("su facilities")
    assert game.pending and game.pending.password
    out = sh("wrong")
    assert "Authentication failure" in out[-1]
    sh("su facilities")
    sh("gerald2019")
    assert game.state.user == "facilities"
    assert "facilities" in game.state.access

    # Omen doesn't land until Kev has actually complained.
    sh("facil pods hazelnut")
    assert game.state.mystique == 0
    game.state.set_flag("heard_hazelnut")
    sh("facil pods hazelnut")
    assert game.state.mystique == 2 and game.state.exposure == 0
    assert any(s["who"] == "kev" for s in game.state.scheduled_lines)

    # Something only you heard: exposure.
    game.state.set_flag("heard_status")
    out = sh('facil book aquarium "Re: status reports"')
    assert game.state.exposure == 4
    assert any("only a few people" in line for line in out)


def test_reactions_post_to_chat_over_time(game, sh):
    game.state.access.append("facilities")
    game.state.user = "facilities"
    game.state.set_flag("heard_clive")
    sh('facil order "stapler, engraved CLIVE"')
    game.tick(120)
    texts = [e["text"] for e in game.state.ticker_log]
    assert any("CLIVE" in t for t in texts)


def test_exposure_lockout(game, sh):
    game.state.access.append("facilities")
    game.state.user = "facilities"
    game.state.exposure = 9
    game.tick(1)
    assert game.state.has("locked_out")
    assert game.state.user == "pdunn"
    sh("su facilities")
    assert "rotated" in sh("gerald2019")[-1]     # the old password is burned


def test_memo_arrives_with_mystique(game):
    game.state.set_flag("got_facilities")
    game.state.mystique = 6
    game.tick(30)
    assert "e_hr_memo" in game.state.delivered


def test_day_rollover(game):
    game.state.t = 16 * 60 + 59
    game.tick(2)
    assert game.state.day == 2 and game.state.clock == "09:01"


def test_save_round_trip(game, sh, tmp_path):
    game.tick(10)
    sh("train")
    game.state.user_files["/home/pdunn/x.txt"] = "hi"
    game.save()
    loaded = GameState.load(tmp_path / "save.json")
    assert loaded == game.state


def test_emails_arrive_and_read(game, sh):
    game.tick(5)
    assert game.state.unread >= 1
    out = sh("emmy read 1")
    assert any("EER-26" in line for line in out)
    assert game.state.inbox[0]["read"]


def test_tab_completion(game):
    from os_e_man.shell import crab
    assert "train " in crab.complete(game, "tra")
    assert "facil " not in crab.complete(game, "fa")
    assert "cat notes.txt" in crab.complete(game, "cat no")
    assert "man snek" in crab.complete(game, "man sn")
