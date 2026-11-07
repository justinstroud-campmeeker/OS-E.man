import pytest

from os_e_man.training.sqlrunner import SQLDenied, SQLRunner

REFERENCE = {
    "c1": "SELECT COUNT(*) AS n FROM stores",
    "c2": "SELECT store_id, ROUND(SUM(amount), 2) FROM transactions GROUP BY store_id ORDER BY 2 DESC",
    "c3": ("def parse_line(line):\n"
           "    out = {}\n"
           "    for part in line.split()[1:]:\n"
           "        k, v = part.split('=')\n"
           "        out[k.lower()] = float(v) if k == 'AMT' else v\n"
           "    return out\n"),
    "c4": "SELECT name FROM employees WHERE hired >= '2020-01-01' AND store_id = 42",
    "c5": ("def mask(value):\n"
           "    if len(value) < 5:\n"
           "        return value\n"
           "    return '*' * (len(value) - 4) + value[-4:]\n"),
    "c6": "SELECT sku, on_hand FROM products WHERE on_hand < 0",
}


@pytest.mark.parametrize("sql", [
    "DELETE FROM stores",
    "UPDATE stores SET name = 'x'",
    "DROP TABLE stores",
    "INSERT INTO stores VALUES (1,'a','b','c','d')",
    "CREATE TABLE x (a)",
    "ATTACH DATABASE 'x.db' AS x",
])
def test_replica_is_read_only(sql):
    with pytest.raises(SQLDenied):
        SQLRunner().query(sql)


def test_tracks_tables_read():
    res = SQLRunner().query("SELECT s.name FROM stores s JOIN employees e ON e.store_id = s.store_id")
    assert res.tables == {"stores", "employees"}


def test_every_reference_solution_passes(game):
    tr = game.training
    for ch in tr.challenges:
        g = tr.grade(ch, REFERENCE[ch["id"]])
        assert g.passed, (ch["id"], g.lines)


def test_wrong_answers_fail(game):
    tr = game.training
    assert not tr.grade(tr.by_id["c1"], "SELECT 7").passed
    assert not tr.grade(tr.by_id["c3"], "def parse_line(line):\n    return {}").passed
    assert not tr.grade(tr.by_id["c5"], "def mask(v):\n    while True: pass").passed


def test_course_flow_through_shell(game, sh):
    sh("train")
    assert game.training.enrolled
    out = sh("train submit SELECT COUNT(*) FROM stores")
    assert "grader: PASS" in out
    assert game.state.challenges_done == ["c1"]
    sh("train submit")  # c2 is SQL with no inline answer: opens the editor
    req = game.requests.pop()
    from os_e_man.game import Out
    o = Out(game)
    req.on_save(REFERENCE["c2"], o)
    assert "c2" in game.state.challenges_done


def test_redaction_thins_with_curiosity(game):
    line = "notes: [[R2:the lobby plant]]"
    assert "lobby" not in game.fmt(line).plain
    game.state.curiosity = 2
    assert "lobby" in game.fmt(line).plain


def test_poking_raises_curiosity_once(game, sh):
    sh("sql .tables")
    sh("sql .tables")
    assert game.state.curiosity == 1
    sh("sql SELECT * FROM svc_accounts")
    assert game.state.curiosity == 2
