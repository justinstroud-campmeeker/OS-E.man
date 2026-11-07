"""Levers: the hidden ladder of influence.

Each rung (facilities -> badging -> ...) is an access the player can hold. Each rung has
several routes in. A route opens when its `requires` is met; its ghost (a file that shouldn't
be there) appears then. The Lattice Stewardship Board nudges a stuck player toward an open
route, one hint per game day stuck.

Exposure climbs a warning ladder (a DM, an IT review, People Relations, a PIP). At the top
the player is reassigned: they lose their highest rung, and the route they used for it is
burned. Getting it back means a different route, never the same tasks again.

Content: content/levers.json. Commands call grant()/secret_route()/on_mail().
"""

from __future__ import annotations

from . import content


class Levers:
    def __init__(self, game):
        self.game = game
        data = content.load("levers.json")
        self.rungs: list[dict] = data["rungs"]
        self.rank = {r["access"]: r["rank"] for r in self.rungs}
        self.routes: list[dict] = data["routes"]
        self.by_id = {r["id"]: r for r in self.routes}
        self.ladder: list[dict] = data["ladder"]
        self._migrate()
        self._register_mail()

    @property
    def st(self):
        return self.game.state

    # ----- saves from before levers -----
    def _migrate(self) -> None:
        st = self.st
        if st.has("locked_out"):
            st.set_flag("route_burned:fac_password")
        if "facilities" in st.access and "facilities" not in st.routes_used:
            st.routes_used["facilities"] = "fac_password"

    def _register_mail(self) -> None:
        """Ladder and route replies are ordinary emails, waiting on flags."""
        w = self.game.world
        recs = []
        for n in range(self.st.demotions + 2):
            for i, step in enumerate(self.ladder):
                if "email" in step:
                    eid = f"e_ladder_{i}_{n}"
                    recs.append({"id": eid, "when": {"flag": f"ladder:{eid}"}, "delay": 3, **step["email"]})
        for r in self.routes:
            if r.get("mail"):
                recs.append({"id": f"e_route_{r['id']}", "when": {"flag": f"route_mail:{r['id']}"},
                             **r["mail"]["reply"]})
        for e in recs:
            if e["id"] not in w.email_by_id:
                w.emails.append(e)
                w.email_by_id[e["id"]] = e

    # ----- routes -----
    def is_open(self, rid: str) -> bool:
        r = self.by_id[rid]
        return (not self.st.has(f"route_burned:{rid}") and r["rung"] not in self.st.access
                and self.game.events.met(r.get("requires", {})))

    def grant(self, rid: str, out) -> bool:
        if not self.is_open(rid):
            return False
        r, st = self.by_id[rid], self.st
        st.access.append(r["rung"])
        st.routes_used[r["rung"]] = rid
        st.set_flag(f"route:{rid}")
        if r.get("granted"):
            out(r["granted"], "ok")
        return True

    def secret_route(self, rung: str, secret: str) -> dict | None:
        """A route whose secret matches. Burned or not: callers decide what a burned one means."""
        s = secret.strip().lower()
        return next((r for r in self.routes if r["rung"] == rung and r.get("secret") == s), None)

    def on_mail(self, to: str, out) -> bool:
        """emmy send hook. True if this mail was a route step."""
        for r in self.routes:
            m = r.get("mail")
            if m and m["to"] == to and self.is_open(r["id"]):
                if m.get("as") and self.st.user != m["as"]:
                    out(f"emmy: sent to {to}.", "ok")        # from the wrong account: ignored
                    return True
                self.st.set_flag(f"route_mail:{r['id']}")
                out(f"emmy: sent to {to} (from {self.st.user}@hpcg.corp).", "ok")
                return True
        return False

    # ----- every check: ghosts appear, the ladder climbs -----
    def check(self, out) -> None:
        st = self.st
        for r in self.routes:
            g = r.get("ghost")
            if g and g["path"] not in st.user_files and self.is_open(r["id"]):
                st.user_files[g["path"]] = g["text"]
        for i, step in enumerate(self.ladder):
            if st.warned > i or st.exposure < step["at"]:
                continue
            st.warned = i + 1
            if "dm" in step:
                self.game.post("dm", step["dm"]["who"], step["dm"]["text"])
            if "email" in step:
                st.set_flag(f"ladder:e_ladder_{i}_{st.demotions}")
            if step.get("demote"):
                self.demote(out)
                break

    def demote(self, out) -> None:
        st = self.st
        held = [a for a in st.access if a in self.rank]
        st.set_flag("demoted")
        st.demotions += 1
        st.warned = 0
        st.exposure = 2
        self._register_mail()
        if not held:
            return
        top = max(held, key=self.rank.get)
        st.access.remove(top)
        rid = st.routes_used.pop(top, None) or next(
            (r["id"] for r in self.routes if r["rung"] == top), None)
        if rid:
            st.set_flag(f"route_burned:{rid}")
            burn = self.by_id[rid].get("burn")
            if burn:
                out(burn, "err")
        if top == "facilities":
            st.set_flag("locked_out")
            if st.user == "facilities":
                st.user = "pdunn"
                st.cwd = self.game.vfs.home()
                out("Connection to facilities portal closed by remote host.", "err")

    # ----- overnight: the Board nudges whoever is stuck -----
    def nudge(self) -> None:
        st = self.st
        for r in self.routes:
            if not r.get("hints") or not self.is_open(r["id"]):
                continue
            days = st.stuck.get(r["id"], 0) + 1
            st.stuck[r["id"]] = days
            hint = r["hints"][min(days, len(r["hints"])) - 1]
            key = f"hint:{r['id']}:{min(days, len(r['hints']))}"
            if not st.set_flag(key):
                continue
            if hint["kind"] == "file":
                st.user_files[hint["path"]] = hint["text"]
            elif hint["kind"] == "glimpse":
                st.pending_glimpse = hint["text"]
            return  # one nudge a night
