"""Omens: small, specific office-logistics changes that make people nervous.

Each omen in content/omens.json matches a facilities action (kind + keywords).
Firing one raises mystique (people think the office manager Knows Things) and
exposure (people start to wonder who else could have known). Reactions arrive
later in chat. Rumors stick to the office manager, which is the point.
"""

from __future__ import annotations

LOCKOUT_AT = 9


class Omens:
    def __init__(self, game):
        self.game = game
        self.omens: list[dict] = game.world.omens

    @property
    def state(self):
        return self.game.state

    def match(self, kind: str, arg: str) -> dict | None:
        a = arg.lower()
        for o in self.omens:
            if o["id"] in self.state.omens_fired or o["kind"] != kind:
                continue
            if o.get("requires_flag") and not self.state.has(o["requires_flag"]):
                continue  # nobody has said the thing yet, so nobody will connect it
            if any(k in a for k in o["match"]):
                return o
        return None

    def apply(self, kind: str, arg: str, out) -> None:
        o = self.match(kind, arg)
        if o is None:
            # Ordinary logistics. Nobody notices; occasionally someone does, mildly.
            return
        st = self.state
        st.omens_fired.append(o["id"])
        exposure = o.get("exposure", 0)
        self.game.bump(mystique=o.get("mystique", 0), exposure=exposure)
        for r in o.get("reactions", []):
            self.game.schedule(r["delay"], r["channel"], r["who"], r["text"])
        if exposure >= 3:
            out("facil: (you have a feeling only a few people knew about that.)", "warn")

    def check_lockout(self, out) -> None:
        """The exposure ladder and its demotion live in levers.py now."""
        self.game.levers.check(out)
