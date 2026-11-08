"""Unlocks: every game day, at a random time, a new command or flag installs itself
(maintainer: none). Each one gives the player a little more power to make things happen.

Content: content/unlocks.json, in order; an unlock waits until its `requires` is met.
Unlock `x` grants access `u:x`; commands are registered with `requires="u:x"`, flags check
`game.unlocks.has("x")`. Also runs `at` jobs.
"""

from __future__ import annotations

import random

from . import content

FIRST_WAIT = (20, 120)   # game minutes until the first unlock in a save that has none yet
WINDOW = (10 * 60, 16 * 60)


class Unlocks:
    def __init__(self, game):
        self.game = game
        self.all: list[dict] = content.load("unlocks.json")
        self.rng = random.Random()
        st = game.state
        if not st.next_unlock_t and self.next_one():
            st.next_unlock_t = st.t + self.rng.randint(*FIRST_WAIT)

    def has(self, uid: str) -> bool:
        return f"u:{uid}" in self.game.state.access

    def next_one(self) -> dict | None:
        return next((u for u in self.all if not self.has(u["id"])
                     and self.game.events.met(u.get("requires", {}))), None)

    def check(self, out) -> None:
        st = self.game.state
        self._run_jobs(out)
        if not st.next_unlock_t or st.t < st.next_unlock_t:
            return
        u = self.next_one()
        if u is None:
            st.next_unlock_t = st.t + 60          # look again in an hour (requirements may change)
            return
        st.access.append(f"u:{u['id']}")
        out(u["notice"], "sys")
        tomorrow = st.day * 1440                    # next game day, somewhere in working hours
        st.next_unlock_t = tomorrow + self.rng.randint(*WINDOW)

    # ----- at(1) -----
    def _run_jobs(self, out) -> None:
        from .shell import crab
        st = self.game.state
        due = [j for j in st.at_jobs if j["t"] <= st.t]
        if not due:
            return
        st.at_jobs = [j for j in st.at_jobs if j["t"] > st.t]
        for j in due:
            out(f"at: job {j['n']} ({j['line']}):", "dim")
            crab.run(self.game, j["line"], out)
            self.game.requests = [r for r in self.game.requests if r in ("clear",)]  # no editors from cron
