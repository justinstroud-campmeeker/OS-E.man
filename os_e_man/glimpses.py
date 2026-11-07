"""Glimpses: rarely, when the player has been doing nothing that matters for a while, the
screen flickers and an address shows for a moment. It goes into their shell history and
~/todo.txt, and becomes a quest (visit it in webble, or email it with emmy send).

Content: content/glimpses.json (what shows, when) and content/web.json (webble pages).
"""

from __future__ import annotations

import random

from . import content

MUNDANE_AFTER = 15     # commands without progress before a glimpse can happen
EARLIEST = 10 * 60     # not before 10:00
TODO = "/home/pdunn/todo.txt"


class Glimpses:
    def __init__(self, game):
        self.game = game
        self.all: list[dict] = content.load("glimpses.json")
        self.by_id = {g["id"]: g for g in self.all}
        self.rng = random.Random()
        # replies to quest mail are ordinary emails, waiting on the quest flag
        for g in self.all:
            if g.get("reply"):
                e = {"id": f"e_{g['id']}_reply", "when": {"flag": f"glimpse:{g['id']}:done"},
                     **g["reply"]}
                if e["id"] not in game.world.email_by_id:
                    game.world.emails.append(e)
                    game.world.email_by_id[e["id"]] = e

    # ----- progress tracking -----
    def snapshot(self) -> tuple:
        st = self.game.state
        return (len(st.flags), st.curiosity, st.mystique, len(st.access), len(st.challenges_done))

    def after_command(self, before: tuple) -> dict | None:
        """Call after each command. Returns a glimpse to show, or None."""
        st = self.game.state
        if st.pending_glimpse and st.minute_of_day >= EARLIEST:
            text, st.pending_glimpse = st.pending_glimpse, ""
            g = {"id": f"hint:{text}", "kind": "cmd", "text": text, "todo": f"{text}  (it was on the screen)"}
            self.show(g)
            return g
        if self.snapshot() != before:
            st.mundane = 0
            return None
        st.mundane += 1
        if st.mundane < MUNDANE_AFTER or st.last_glimpse_day >= st.day or st.minute_of_day < EARLIEST:
            return None
        if self.rng.random() >= min(0.25, 0.03 * (st.mundane - MUNDANE_AFTER + 1)):
            return None
        g = next((g for g in self.all if g["id"] not in st.glimpses
                  and self.game.events.met(g.get("when", {}))), None)
        if g:
            self.show(g)
        return g

    def show(self, g: dict) -> None:
        st = self.game.state
        st.glimpses.append(g["id"])
        if g["kind"] != "cmd":
            st.last_glimpse_day = st.day
        st.mundane = 0
        t = g["text"]
        if g["kind"] == "cmd":
            cmd = f"emmy send {t}" if "@" in t else t if " " in t else f"webble {t}"
        else:
            cmd = ("webble " if g["kind"] == "web" else "emmy send ") + t
        st.history.append(cmd)
        todo = st.user_files.get(TODO, "TODO\n")
        st.user_files[TODO] = todo + f"- [ ] {g['todo']}\n"
        self.game.requests.append(("glimpse", g["text"]))

    # ----- completion -----
    def complete(self, gid: str) -> bool:
        st = self.game.state
        g = self.by_id.get(gid)
        if not g or not st.set_flag(f"glimpse:{gid}:done"):
            return False
        if TODO in st.user_files:
            st.user_files[TODO] = st.user_files[TODO].replace(f"- [ ] {g['todo']}", f"- [x] {g['todo']}")
        return True

    def mail_target(self, addr: str) -> dict | None:
        return next((g for g in self.all if g["kind"] == "mail" and g["text"] == addr.lower()), None)
