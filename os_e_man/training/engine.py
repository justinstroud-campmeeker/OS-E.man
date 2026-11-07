"""The 'Engineering Excellence Refresher' course: challenges, grading, anomalies."""

from __future__ import annotations

import random
from dataclasses import dataclass

from .. import content
from .snek import Snek, SnekError
from .sqlrunner import SQLDenied, SQLRunner, normalize


@dataclass
class Grade:
    passed: bool
    lines: list[str]


class Training:
    def __init__(self, game):
        self.game = game
        data = content.load("challenges.json")
        self.challenges: list[dict] = data["challenges"]
        self.anomalies: list[dict] = data["anomalies"]
        self.by_id = {c["id"]: c for c in self.challenges}

    @property
    def state(self):
        return self.game.state

    @property
    def enrolled(self) -> bool:
        return self.state.has("enrolled")

    def current(self) -> dict | None:
        for c in self.challenges:
            if c["id"] not in self.state.challenges_done:
                return c
        return None

    def number(self, ch: dict) -> int:
        return self.challenges.index(ch) + 1

    # ----- grading -----
    def grade(self, ch: dict, answer: str) -> Grade:
        if ch["kind"] == "sql":
            return self._grade_sql(ch, answer)
        return self._grade_snek(ch, answer)

    def _grade_sql(self, ch: dict, answer: str) -> Grade:
        db: SQLRunner = self.game.db
        try:
            got = db.query(answer)
        except SQLDenied as e:
            return Grade(False, [f"grader: query failed: {e}"])
        self.game.note_tables(got.tables)
        want = db.query(ch["expected_sql"])
        ordered = ch.get("ordered", False)
        if len(got.columns) != len(want.columns):
            return Grade(False, [f"grader: expected {len(want.columns)} column(s), got {len(got.columns)}"])
        if normalize(got.rows, ordered) != normalize(want.rows, ordered):
            return Grade(False, [f"grader: result mismatch ({len(got.rows)} rows returned, "
                                 f"{len(want.rows)} expected)"])
        return Grade(True, ["grader: PASS"])

    def _grade_snek(self, ch: dict, answer: str) -> Grade:
        snek = Snek()
        res = snek.run(answer)
        lines = [f"  {o}" for o in res.output[:10]]
        if res.error:
            return Grade(False, lines + [f"grader: {res.error}"])
        fn = res.env.get(ch["func"])
        if not callable(fn):
            return Grade(False, lines + [f"grader: no function named '{ch['func']}' found"])
        for args, expected in ch["tests"]:
            try:
                out = snek.call(fn, *args)
            except SnekError as e:
                return Grade(False, lines + [f"grader: {e}"])
            except Exception as e:
                return Grade(False, lines + [f"grader: {ch['func']}{tuple(args)!r} raised {type(e).__name__}: {e}"])
            if out != expected:
                return Grade(False, lines + [f"grader: {ch['func']}({', '.join(map(repr, args))})",
                                             f"        expected {expected!r}", f"        got      {out!r}"])
        return Grade(True, lines + [f"grader: PASS ({len(ch['tests'])}/{len(ch['tests'])} cases)"])

    # ----- anomalies -----
    def maybe_anomaly(self) -> str | None:
        """Occasionally, the grader says something it shouldn't. More often the more you look."""
        cur = self.state.curiosity
        pool = [a for a in self.anomalies
                if a["id"] not in self.state.seen_anomalies and a.get("min_curiosity", 0) <= cur]
        if not pool:
            return None
        chance = min(0.9, 0.3 + 0.15 * cur)
        if random.random() > chance:
            return None
        a = pool[0]
        self.state.seen_anomalies.append(a["id"])
        return a["text"]
