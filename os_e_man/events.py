"""Emails, scheduled chat beats, ambient chatter and the slow drip of consequences."""

from __future__ import annotations

import random



def _hm(s: str) -> int:
    h, m = s.split(":")
    return int(h) * 60 + int(m)


class Events:
    def __init__(self, game):
        self.game = game
        w = game.world  # canon + content packs; shared, so new packs show up live
        self.emails: list[dict] = w.emails
        self.by_id: dict = w.email_by_id
        self.people: dict = w.people
        self.beats: list[dict] = w.beats
        self.chatter: dict = w.chatter

    @property
    def state(self):
        return self.game.state

    def name(self, who: str) -> str:
        p = self.people.get(who)
        return p["handle"] if p else who

    # ----- conditions -----
    def met(self, when: dict) -> bool:
        st = self.state
        if "day" in when:
            if st.day < when["day"]:
                return False
            if st.day == when["day"] and "at" in when and st.minute_of_day < _hm(when["at"]):
                return False
        elif "at" in when and st.minute_of_day < _hm(when["at"]):
            return False
        for key in ("curiosity", "mystique", "exposure"):
            if key in when and getattr(st, key) < when[key]:
                return False
            if f"{key}_below" in when and getattr(st, key) >= when[f"{key}_below"]:
                return False
        if "flag" in when and not st.has(when["flag"]):
            return False
        if "not_flag" in when and st.has(when["not_flag"]):
            return False
        if "done" in when and when["done"] not in st.challenges_done:
            return False
        if "not_done" in when and when["not_done"] in st.challenges_done:
            return False
        return True

    # ----- main loop -----
    def check(self, out) -> None:
        st = self.state
        # emails
        for e in self.emails:
            eid = e["id"]
            if eid in st.delivered:
                continue
            if eid not in st.queued and self.met(e.get("when", {})):
                st.queued[eid] = st.t + e.get("delay", 0)
            if eid in st.queued and st.t >= st.queued[eid]:
                del st.queued[eid]
                self.deliver(e, out)
        # chat beats
        for b in self.beats:
            if b["id"] in st.beats_fired:
                continue
            if self.met(b.get("when", {})):
                st.beats_fired.append(b["id"])
                if b.get("flag"):
                    st.set_flag(b["flag"])
                self.game.post(b["channel"], b["who"], b["text"])
        # scheduled reactions
        due = [s for s in st.scheduled_lines if s["at"] <= st.t]
        if due:
            st.scheduled_lines = [s for s in st.scheduled_lines if s["at"] > st.t]
            for s in due:
                self.game.post(s["channel"], s["who"], s["text"])
        # ambient chatter
        if st.t >= st.next_chatter:
            st.next_chatter = st.t + random.randint(18, 45)
            self.ambient()
        # consequences
        self.game.omens.check_lockout(out)

    def deliver(self, e: dict, out) -> None:
        st = self.state
        st.delivered.append(e["id"])
        st.inbox.append({
            "id": e["id"], "from": e["from"], "subject": e["subject"],
            "day": st.day, "time": st.clock, "read": False,
        })
        if e.get("flag_on_deliver"):
            st.set_flag(e["flag_on_deliver"])
        out(f"emmy: new mail from {e['from']} — \"{e['subject']}\" (emmy read {len(st.inbox)})", "mail")

    def ambient(self) -> None:
        st = self.state
        mood = "normal"
        if st.mystique >= 6:
            mood = "afraid"
        elif st.mystique >= 3:
            mood = "uneasy"
        pool = self.chatter.get(mood, []) + (self.chatter["normal"] if mood != "normal" else [])
        recent = {e["text"] for e in st.ticker_log[-12:]}
        pool = [c for c in pool if c["text"] not in recent] or pool
        if pool:
            c = random.choice(pool)
            self.game.post(c["channel"], c["who"], c["text"])
