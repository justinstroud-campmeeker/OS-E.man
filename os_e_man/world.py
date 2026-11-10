"""The world outside the machine: canon content plus content packs written by the director.

Canon (os_e_man/content/) is the hand-written world. Packs are extra content in the same
schemas (people, emails, chat beats, ambient chatter, omens, files, hosts), written by
something outside wks-0417, an LLM director or a person, and applied through the
world server's control port. Applied packs live as JSON in <runtime>/world/ and are
loaded in filename order at boot, so the history they create is fixed.

check_pack() sorts problems into two kinds:

  * breakage: things that would crash the game, collide with canon, or step outside the
    simulation (real URLs, real email domains, public IPs). Those items are dropped, and
    a pack with nothing left is rejected.
  * drift: the writer imagined something the world doesn't have: a person nobody
    hired, a host that isn't on the network, a channel nobody made, a flag nothing sets.
    That's a feature. The world absorbs the hallucination (stub records, new channels,
    flags that the world sets by itself overnight) and logs it as an anomaly in
    /var/log/continuity.log.
"""

from __future__ import annotations

import copy
import hashlib
import ipaddress
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from . import content

PACK_VERSION = 1
MAX_PACK_BYTES = 256 * 1024
MAX_ITEMS = 60
LIMITS = {"body": 8000, "text": 500, "subject": 160, "file": 20000, "line": 300}
MOODS = ("normal", "uneasy", "afraid")
WHEN_INT = ("day", "curiosity", "mystique", "exposure",
            "curiosity_below", "mystique_below", "exposure_below")
MAX_THREADS = 8
MAX_FACTS = 12                      # per storyline, newest kept
WHEN_STR = ("flag", "not_flag", "done", "not_done")
HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
ID_RE = re.compile(r"^[A-Za-z0-9_.:~-]{1,64}$")
FICTIONAL_TLDS = (".corp", ".local", ".internal", ".lan", ".example")
URL_RE = re.compile(r"\b(?:https?|ftp)://|\bwww\.", re.I)
EMAIL_RE = re.compile(r"\b[\w.+-]+@([\w-]+(?:\.[\w-]+)+)\b")
IP_RE = re.compile(r"\b(\d{1,3}(?:\.\d{1,3}){3})\b")
HOST_RE = re.compile(r"\b((?:[a-z0-9-]+\.)+(?:corp|internal|local|lan))\b")
CONTINUITY_LOG = "/var/log/continuity.log"
DRIFT_ROLE = "No HR directory entry. Badge system shows regular attendance."


# ----------------------------------------------------------------- canon flags
def _code_flags() -> set[str]:
    """Flags the game's own code sets or tests, found by reading the source."""
    pat = re.compile(r"""(?:set_flag|has)\(\s*["']([\w:.-]+)["']\s*\)""")
    found: set[str] = set()
    for p in Path(__file__).parent.rglob("*.py"):
        found |= set(pat.findall(p.read_text(encoding="utf-8")))
    return found


def said(text: str) -> str:
    """A chat line, normalised for 'has anyone said this already'."""
    return re.sub(r"[\W_]+", " ", str(text).lower()).strip()


def _lines(beats, chatter) -> set[str]:
    return {said(b["text"]) for b in beats} | {said(c["text"]) for pool in chatter.values() for c in pool}


def _content_flags(emails, beats, omens) -> set[str]:
    flags: set[str] = set()
    for e in emails:
        flags |= {e["when"][k] for k in ("flag", "not_flag") if k in e.get("when", {})}
        if e.get("flag_on_deliver"):
            flags.add(e["flag_on_deliver"])
    for b in beats:
        if b.get("flag"):
            flags.add(b["flag"])
        flags |= {b["when"][k] for k in ("flag", "not_flag") if k in b.get("when", {})}
    for o in omens:
        if o.get("requires_flag"):
            flags.add(o["requires_flag"])
    return flags


# ----------------------------------------------------------------- report
@dataclass
class Report:
    pack_id: str = ""
    errors: list[str] = field(default_factory=list)   # dropped items / rejected pack
    drift: list[str] = field(default_factory=list)    # absorbed hallucinations
    pack: dict | None = None                          # normalised pack, None if rejected

    @property
    def ok(self) -> bool:
        return self.pack is not None

    def to_dict(self) -> dict:
        return {"ok": self.ok, "id": self.pack_id, "errors": self.errors, "drift": self.drift}


# ----------------------------------------------------------------- world
class World:
    """Merged canon + packs. The game reads its content from here; lists and dicts are
    shared with Events/Omens/VFS, so applying a pack takes effect immediately."""

    def __init__(self, folder: Path | None = None):
        self.folder = folder
        npcs = content.load("npcs.json")
        self.people: dict = copy.deepcopy(npcs["people"])
        self.beats: list = copy.deepcopy(npcs["beats"])
        self.chatter: dict = copy.deepcopy(npcs["chatter"])
        self.emails: list = copy.deepcopy(content.load("emails.json"))
        self.email_by_id: dict = {e["id"]: e for e in self.emails}
        self.omens: list = copy.deepcopy(content.load("omens.json"))
        self.net: dict = copy.deepcopy(content.load("net.json"))
        self.files: dict[str, str] = {}
        self.packs: list[str] = []
        self.dangling: set[str] = set()     # flags only a hallucination ever asked for
        self.anomalies: list[str] = []
        self.threads: dict[str, dict] = {}  # the director's storylines, latest state each
        self.written: dict[int, str] = {}   # day -> id of the pack written for that day
        self.notes: dict[str, str] = {}     # pack id -> its note
        self.canon_files = set()            # filled lazily (vfs import cycle)
        self.canon_ids = ({e["id"] for e in self.emails} | {b["id"] for b in self.beats}
                          | {o["id"] for o in self.omens})
        self.canon_people = set(self.people)
        self.known_flags = _code_flags() | _content_flags(self.emails, self.beats, self.omens)
        self.lines = _lines(self.beats, self.chatter)   # everything anyone has been written saying
        if folder and folder.is_dir():
            for p in sorted(folder.glob("*.json")):
                try:
                    self._add(json.loads(p.read_text(encoding="utf-8")))
                except (OSError, ValueError, KeyError, TypeError) as e:
                    self.anomalies.append(f"pack file {p.name} unreadable ({e.__class__.__name__}); skipped")

    # ----- lookups -----
    @property
    def channels(self) -> set[str]:
        ch = {b["channel"] for b in self.beats} | {"dm"}
        ch |= {c["channel"] for pool in self.chatter.values() for c in pool}
        ch |= {r["channel"] for o in self.omens for r in o.get("reactions", [])}
        return ch

    @property
    def ids(self) -> set[str]:
        return set(self.email_by_id) | {b["id"] for b in self.beats} | {o["id"] for o in self.omens}

    def _canon_paths(self) -> set[str]:
        if not self.canon_files:
            from .vfs import shipped
            self.canon_files = set(shipped())
        return self.canon_files

    # ----- applying -----
    def _add(self, pack: dict) -> None:
        """Merge an already-checked pack."""
        self.people.update(pack.get("people", {}))
        for e in pack.get("emails", []):
            self.emails.append(e)
            self.email_by_id[e["id"]] = e
        self.beats.extend(pack.get("beats", []))
        self.lines |= _lines(pack.get("beats", []), pack.get("chatter", {}))
        for mood, pool in pack.get("chatter", {}).items():
            self.chatter.setdefault(mood, []).extend(pool)
        self.omens.extend(pack.get("omens", []))
        self.net["hosts"].update(pack.get("hosts", {}))
        self.files.update(pack.get("files", {}))
        self.known_flags |= _content_flags(pack.get("emails", []), pack.get("beats", []),
                                           pack.get("omens", []))
        self.dangling |= set(pack.get("dangling", []))
        self.dangling -= {b["flag"] for b in pack.get("beats", []) if b.get("flag")}
        self.anomalies.extend(pack.get("drift", []))
        for t in pack.get("threads", []):
            old = self.threads.get(t["id"], {}).get("facts", [])
            facts = old + [f for f in t.get("facts", []) if f not in old]
            self.threads[t["id"]] = {**t, "facts": facts[-MAX_FACTS:],
                                     "day": pack.get("for_day", pack.get("applied_day", 0))}
        if isinstance(pack.get("for_day"), int):
            self.written[pack["for_day"]] = pack["id"]
        self.notes[pack["id"]] = pack.get("note", "")
        self.packs.append(pack["id"])
        if self.anomalies:
            self.files[CONTINUITY_LOG] = _continuity_log(self.anomalies)

    def apply(self, raw, day: int = 0) -> Report:
        """Check a pack, and if anything survives, save it and merge it in."""
        rep = check_pack(raw, self)
        if not rep.ok:
            return rep
        rep.pack["applied_day"] = day
        if self.folder:
            self.folder.mkdir(parents=True, exist_ok=True)
            n = len(list(self.folder.glob("*.json"))) + 1
            safe = re.sub(r"[^A-Za-z0-9_.-]", "_", rep.pack_id)[:48]
            (self.folder / f"{n:04d}-{safe}.json").write_text(
                json.dumps(rep.pack, indent=1, ensure_ascii=False), encoding="utf-8")
        self._add(rep.pack)
        return rep

    # ----- what the director sees -----
    def voices(self, per: int = 3) -> dict[str, list[str]]:
        """A few canon lines per person, so a writer can hear how they talk."""
        out: dict[str, list[str]] = {}
        lines = [(b["who"], b["text"]) for b in self.beats if b.get("id") in self.canon_ids]
        npcs = content.load("npcs.json")["chatter"]
        lines += [(c["who"], c["text"]) for pool in npcs.values() for c in pool]
        for who, text in lines:
            if who in self.canon_people and len(out.setdefault(who, [])) < per:
                out[who].append(text)
        return out

    def digest(self, game) -> dict:
        st = game.state
        return {
            "day": st.day, "clock": st.clock, "user": st.user, "access": list(st.access),
            "meters": {"curiosity": st.curiosity, "mystique": st.mystique, "exposure": st.exposure},
            "flags": sorted(f for f in st.flags if not f.startswith("poke:")),
            "poked": sorted(f[5:] for f in st.flags if f.startswith("poke:")),
            "challenges_done": list(st.challenges_done),
            "omens_fired": list(st.omens_fired),
            "inbox": [{"from": m["from"], "subject": m["subject"], "day": m["day"],
                       "read": m["read"]} for m in st.inbox[-10:]],
            "recent_chat": [{"channel": e["channel"], "who": e["who"], "text": e["text"]}
                            for e in st.ticker_log[-15:]],
            "recent_commands": st.history[-20:],
            "people": {k: {"handle": v["handle"], "role": v.get("role", "")}
                       for k, v in self.people.items()},
            "voices": self.voices(),
            "channels": sorted(self.channels),
            "hosts": sorted(self.net["hosts"]),
            "omen_kinds": sorted({o["kind"] for o in self.omens}),
            "known_flags": sorted(self.known_flags | self.dangling),
            "packs": list(self.packs),
            "anomalies": self.anomalies[-10:],
            "pokeable": sorted(k for k in game.curiosity_triggers if not st.has(f"poke:{k}")),
            "threads": [t for t in self.threads.values() if t.get("state") != "closed"][-MAX_THREADS:],
            "written_days": {str(d): self.notes.get(pid, "") for d, pid in sorted(self.written.items())},
        }


def _continuity_log(entries: list[str]) -> str:
    head = ("# Records Reconciliation Service: continuity exceptions\n"
            "# Generated nightly. Items below reference records with no source document.\n"
            "# Do not correct by hand. Corrections are also reconciled.\n\n")
    return head + "\n".join(f"RRS-{i:04d}  {e}" for i, e in enumerate(entries, 1)) + "\n"


# ----------------------------------------------------------------- checking
def _strings(obj):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield str(k)
            yield from _strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _strings(v)


def boundary_problem(obj) -> str | None:
    """Anything that points outside the simulation. These are never absorbed."""
    for s in _strings(obj):
        if URL_RE.search(s):
            return "contains a URL"
        for dom in EMAIL_RE.findall(s):
            if not dom.lower().endswith(FICTIONAL_TLDS):
                return f"email address at a real-world domain ({dom})"
        for ip in IP_RE.findall(s):
            try:
                addr = ipaddress.ip_address(ip)
            except ValueError:
                continue
            if not (addr.is_private or addr.is_loopback):
                return f"public IP address ({ip})"
    return None


def _fake_ip(name: str) -> str:
    h = hashlib.sha256(name.encode()).digest()
    return f"10.{60 + h[0] % 60}.{h[1]}.{1 + h[2] % 253}"


class _Checker:
    def __init__(self, world: World, pack_id: str):
        self.w = world
        self.pid = pack_id
        self.rep = Report(pack_id=pack_id)
        self.out: dict = {"id": pack_id, "version": PACK_VERSION}
        self.people: dict = {}
        self.hosts: dict = {}
        self.ids: set[str] = set()
        self.new_channels: set[str] = set()
        self.flags_set: set[str] = set()
        self.flags_wanted: set[str] = set()
        self.said: set[str] = set()

    def fresh(self, text, where: str) -> bool:
        """Chat that repeats a line already in the world is filed once: the copy is dropped."""
        k = said(text)
        if k in self.w.lines or k in self.said:
            self.drift(f"{where} repeated something already said; the duplicate was not filed")
            return False
        self.said.add(k)
        return True

    def err(self, msg: str) -> None:
        self.rep.errors.append(msg)

    def drift(self, msg: str) -> None:
        self.rep.drift.append(msg)

    # ----- shared field checks -----
    def text(self, item: dict, key: str, limit: str, where: str, required: bool = True) -> bool:
        v = item.get(key)
        if v is None and not required:
            return True
        if not isinstance(v, str) or not v.strip():
            self.err(f"{where}: '{key}' must be non-empty text")
            return False
        if len(v) > LIMITS[limit]:
            item[key] = v[:LIMITS[limit]]
            self.drift(f"{where}: {key} ran long and was cut off mid-thought")
        return True

    def new_id(self, item: dict, where: str) -> bool:
        i = item.get("id")
        if not isinstance(i, str) or not ID_RE.match(i):
            self.err(f"{where}: missing or malformed id")
            return False
        if i in self.w.ids or i in self.ids:
            new = f"{i}~{self.pid}"
            n = 2
            while new in self.w.ids or new in self.ids:
                new, n = f"{i}~{self.pid}{n}", n + 1
            item["id"] = new
            self.drift(f"record {i} was issued twice; the second copy is filed as {new}")
        self.ids.add(item["id"])
        return True

    def who(self, who, where: str) -> bool:
        if not isinstance(who, str) or not ID_RE.match(who):
            self.err(f"{where}: 'who' must be a short handle")
            return False
        if who not in self.w.people and who not in self.people:
            self.people[who] = {"handle": who, "name": "(no directory entry)", "role": DRIFT_ROLE,
                                "drift": True}
            self.drift(f"personnel record '{who}' referenced in {where}; no hiring record exists")
        return True

    def channel(self, ch, where: str) -> bool:
        if not isinstance(ch, str) or not re.match(r"^(#[a-z0-9_-]{1,40}|dm)$", ch):
            self.err(f"{where}: bad channel {ch!r}")
            return False
        if ch not in self.w.channels and ch not in self.new_channels:
            self.new_channels.add(ch)
            self.drift(f"channel {ch} has messages but no creation record")
        return True

    def when(self, item: dict, where: str) -> bool:
        w = item.get("when", {})
        if not isinstance(w, dict):
            self.err(f"{where}: 'when' must be an object")
            return False
        for k in list(w):
            v = w[k]
            if k in WHEN_INT:
                if not isinstance(v, int) or isinstance(v, bool) or v < 0:
                    self.err(f"{where}: when.{k} must be a whole number")
                    return False
            elif k == "at":
                if not isinstance(v, str) or not HHMM.match(v):
                    self.err(f"{where}: when.at must be HH:MM")
                    return False
            elif k in WHEN_STR:
                if not isinstance(v, str) or not v:
                    self.err(f"{where}: when.{k} must be text")
                    return False
                if k in ("done", "not_done") and v not in self.w_challenges():
                    del w[k]
                    self.drift(f"{where} waited on training module '{v}', which was never written")
                elif k == "flag":
                    self.flags_wanted.add(v)
            else:
                del w[k]
                self.drift(f"{where} had a condition nobody understands ('{k}'); it was ignored")
        item["when"] = w
        return True

    def w_challenges(self) -> set[str]:
        return {c["id"] for c in content.load("challenges.json")["challenges"]}

    def delay(self, item: dict, key: str, where: str, cap: int = 3 * 1440) -> bool:
        v = item.get(key, 0)
        if not isinstance(v, int) or isinstance(v, bool):
            self.err(f"{where}: {key} must be whole minutes")
            return False
        item[key] = max(0, min(cap, v))
        return True

    def section(self, raw: dict, key: str, kind):
        v = raw.get(key)
        if v is None:
            return kind()
        if not isinstance(v, kind):
            self.err(f"'{key}' must be a {'list' if kind is list else 'object'}; section dropped")
            return kind()
        if len(v) > MAX_ITEMS:
            self.drift(f"'{key}' had {len(v)} entries; only the first {MAX_ITEMS} were filed")
            v = v[:MAX_ITEMS] if kind is list else dict(list(v.items())[:MAX_ITEMS])
        return v

    def keep(self, item, where: str) -> bool:
        problem = boundary_problem(item)
        if problem:
            self.err(f"{where}: {problem} (outside the simulation)")
            return False
        return True

    # ----- sections -----
    def run(self, raw: dict) -> Report:
        known = {"id", "version", "source", "note", "people", "emails", "beats", "chatter",
                 "omens", "files", "hosts", "threads", "for_day"}
        for k in raw:
            if k not in known:
                self.drift(f"pack carried an unfiled attachment '{k}'; it was not opened")
        if isinstance(raw.get("source"), str):
            self.out["source"] = raw["source"][:60]
        if isinstance(raw.get("note"), str):
            self.out["note"] = raw["note"][:LIMITS["text"]]
        fd = raw.get("for_day")
        if isinstance(fd, int) and not isinstance(fd, bool) and fd > 0:
            self.out["for_day"] = fd
        threads = []
        for i, t in enumerate(self.section(raw, "threads", list)[:MAX_THREADS]):
            where = f"thread #{i + 1}"
            if not isinstance(t, dict) or not self.keep(t, where):
                continue
            t = {k: t[k] for k in ("id", "title", "state", "next", "facts") if k in t}
            facts = t.pop("facts", [])
            if isinstance(facts, list):
                facts = [f.strip()[:LIMITS["line"]] for f in facts[:5] if isinstance(f, str) and f.strip()]
                if facts:
                    t["facts"] = facts
            if not isinstance(t.get("id"), str) or not ID_RE.match(t["id"]):
                self.err(f"{where}: missing or malformed id")
                continue
            if self.text(t, "title", "line", where) and self.text(t, "next", "line", where, required=False):
                if t.get("state") not in ("open", "closed"):
                    t["state"] = "open"
                threads.append(t)
        if threads:
            self.out["threads"] = threads

        for key, p in self.section(raw, "people", dict).items():
            where = f"person {key}"
            if not isinstance(p, dict) or not ID_RE.match(str(key)):
                self.err(f"{where}: malformed")
                continue
            if not self.keep(p, where):
                continue
            if key in self.w.canon_people:
                self.err(f"{where}: already exists in canon; canon wins")
                continue
            if not (self.text(p, "handle", "line", where) and self.text(p, "name", "line", where)
                    and self.text(p, "role", "text", where, required=False)):
                continue
            self.people[key] = {"handle": p["handle"], "name": p["name"], "role": p.get("role", "")}

        emails = []
        for i, e in enumerate(self.section(raw, "emails", list)):
            where = f"email #{i + 1}"
            if not isinstance(e, dict) or not self.keep(e, where):
                continue
            e = {k: e[k] for k in ("id", "when", "delay", "from", "subject", "body", "flag_on_deliver") if k in e}
            if (self.new_id(e, where) and self.text(e, "from", "line", where)
                    and self.text(e, "subject", "subject", where) and self.text(e, "body", "body", where)
                    and self.when(e, where) and self.delay(e, "delay", where)):
                if e.get("flag_on_deliver") is not None:
                    if not isinstance(e["flag_on_deliver"], str):
                        del e["flag_on_deliver"]
                    else:
                        self.flags_set.add(e["flag_on_deliver"])
                emails.append(e)

        beats = []
        for i, b in enumerate(self.section(raw, "beats", list)):
            where = f"beat #{i + 1}"
            if not isinstance(b, dict) or not self.keep(b, where):
                continue
            b = {k: b[k] for k in ("id", "when", "channel", "who", "text", "flag") if k in b}
            if (self.new_id(b, where) and self.channel(b.get("channel"), where)
                    and self.who(b.get("who"), where) and self.text(b, "text", "text", where)
                    and self.when(b, where) and self.fresh(b["text"], where)):
                if isinstance(b.get("flag"), str):
                    self.flags_set.add(b["flag"])
                else:
                    b.pop("flag", None)
                beats.append(b)

        chatter: dict[str, list] = {}
        for mood, pool in self.section(raw, "chatter", dict).items():
            if not isinstance(pool, list):
                self.err(f"chatter.{mood}: must be a list")
                continue
            target = mood
            if mood not in MOODS:
                target = "uneasy"
                self.drift(f"office mood '{mood}' was reported; filed under 'uneasy'")
            for i, c in enumerate(pool[:MAX_ITEMS]):
                where = f"chatter.{mood} #{i + 1}"
                if not isinstance(c, dict) or not self.keep(c, where):
                    continue
                c = {k: c[k] for k in ("channel", "who", "text") if k in c}
                if (self.channel(c.get("channel"), where) and self.who(c.get("who"), where)
                        and self.text(c, "text", "text", where) and self.fresh(c["text"], where)):
                    chatter.setdefault(target, []).append(c)

        omens = []
        kinds = {o["kind"] for o in self.w.omens}
        for i, o in enumerate(self.section(raw, "omens", list)):
            where = f"omen #{i + 1}"
            if not isinstance(o, dict) or not self.keep(o, where):
                continue
            o = {k: o[k] for k in ("id", "kind", "match", "mystique", "exposure", "note",
                                   "reactions", "requires_flag") if k in o}
            if not self.new_id(o, where):
                continue
            if not isinstance(o.get("kind"), str):
                self.err(f"{where}: needs a kind")
                continue
            if o["kind"] not in kinds:
                self.drift(f"{where} watches for a '{o['kind']}' action that facilities can't take; it waits anyway")
            m = o.get("match")
            if not isinstance(m, list) or not m or not all(isinstance(x, str) and x.strip() for x in m):
                self.err(f"{where}: match must be a list of keywords")
                continue
            o["match"] = [x.lower()[:40] for x in m[:10]]
            for k in ("mystique", "exposure"):
                v = o.get(k, 0)
                if not isinstance(v, int) or isinstance(v, bool):
                    v = 0
                if v > 3 or v < 0:
                    self.drift(f"{where} wanted {k} {v}; the world only allows 0-3 at a time")
                o[k] = max(0, min(3, v))
            reactions = []
            for j, r in enumerate(o.get("reactions", []) if isinstance(o.get("reactions"), list) else []):
                rw = f"{where} reaction {j + 1}"
                if not isinstance(r, dict):
                    continue
                r = {k: r[k] for k in ("delay", "channel", "who", "text") if k in r}
                if (self.delay(r, "delay", rw, cap=1440) and self.channel(r.get("channel"), rw)
                        and self.who(r.get("who"), rw) and self.text(r, "text", "text", rw)):
                    reactions.append(r)
            o["reactions"] = reactions
            if isinstance(o.get("requires_flag"), str):
                self.flags_wanted.add(o["requires_flag"])
            else:
                o.pop("requires_flag", None)
            if not isinstance(o.get("note"), str):
                o.pop("note", None)
            omens.append(o)

        files = {}
        canon_paths = self.w._canon_paths()
        for path, text in self.section(raw, "files", dict).items():
            where = f"file {path}"
            if not isinstance(text, str) or not isinstance(path, str) or not self.keep(text, where):
                continue
            if not path.startswith("/") or ".." in path.split("/") or path.endswith("/") \
                    or not re.match(r"^[\w./ -]{2,160}$", path):
                self.err(f"{where}: not a usable path")
                continue
            if path in canon_paths or path == CONTINUITY_LOG:
                self.err(f"{where}: canon file; canon wins")
                continue
            if len(text) > LIMITS["file"]:
                text = text[:LIMITS["file"]]
                self.drift(f"{where} was truncated in transit")
            files[path] = text

        for name, h in self.section(raw, "hosts", dict).items():
            where = f"host {name}"
            if not isinstance(h, dict) or not isinstance(name, str) or not self.keep(h, where):
                continue
            if not name.lower().endswith(FICTIONAL_TLDS) or not re.match(r"^[a-z0-9.-]{3,80}$", name):
                self.err(f"{where}: only internal (.corp/.internal/.local) hosts exist here")
                continue
            if name in self.w.net["hosts"]:
                self.err(f"{where}: already on the network; canon wins")
                continue
            ip = h.get("ip")
            try:
                ok = ipaddress.ip_address(ip).is_private
            except (ValueError, TypeError):
                ok = False
            if not ok:
                ip = _fake_ip(name)
                self.drift(f"{where} had no believable address; DHCP gave it {ip}")
            ms = h.get("ms")
            ms = float(ms) if isinstance(ms, (int, float)) and not isinstance(ms, bool) and 0 <= ms < 5000 else None
            whois = [str(x)[:LIMITS["line"]] for x in h.get("whois", []) if isinstance(x, str)][:20] \
                if isinstance(h.get("whois"), list) else []
            self.hosts[name] = {"ip": ip, "ms": ms, **({"whois": whois} if whois else {})}

        # ----- absorb hosts that are mentioned but don't exist -----
        mentioned: set[str] = set()
        for s in _strings([emails, beats, chatter, omens, files]):
            mentioned |= set(HOST_RE.findall(s.lower()))
        for name in sorted(mentioned):
            if name in self.w.net["hosts"] or name in self.hosts:
                continue
            if any(name.endswith("." + h) or h.endswith("." + name) for h in self.w.net["hosts"]):
                continue  # a domain or a short form of a known host
            self.hosts[name] = {"ip": _fake_ip(name), "ms": None,
                                "whois": [f"Host: {name}", "Owner: [[R4:(field blank)]]",
                                          "Notes: answers DNS. Nobody remembers provisioning it."]}
            self.drift(f"host {name} was mentioned in correspondence; DNS now resolves it")

        # ----- flags nothing will ever set: the world sets them itself, overnight -----
        dangling = sorted(f for f in self.flags_wanted
                          if f not in self.w.known_flags and f not in self.w.dangling
                          and f not in self.flags_set and not f.startswith("poke:"))
        for f in dangling:
            self.drift(f"condition '{f}' refers to an event with no record; it will be recorded as having happened")

        for key, val in (("people", self.people), ("emails", emails), ("beats", beats),
                         ("chatter", chatter), ("omens", omens), ("files", files),
                         ("hosts", self.hosts)):
            if val:
                self.out[key] = val
        if dangling:
            self.out["dangling"] = dangling
        self.out["drift"] = [f"[{self.pid}] {d}" for d in self.rep.drift]
        if not any(k in self.out for k in ("people", "emails", "beats", "chatter", "omens",
                                           "files", "hosts")):
            self.err("nothing usable survived; pack rejected")
            return self.rep
        self.rep.pack = self.out
        return self.rep


def check_pack(raw, world: World) -> Report:
    if isinstance(raw, (str, bytes)):
        if len(raw) > MAX_PACK_BYTES:
            return Report(errors=[f"pack is over {MAX_PACK_BYTES // 1024} KB"])
        try:
            raw = json.loads(raw)
        except ValueError as e:
            return Report(errors=[f"not JSON: {e}"])
    if not isinstance(raw, dict):
        return Report(errors=["a pack must be a JSON object"])
    if len(json.dumps(raw, ensure_ascii=False)) > MAX_PACK_BYTES:
        return Report(errors=[f"pack is over {MAX_PACK_BYTES // 1024} KB"])
    pid = raw.get("id")
    if not isinstance(pid, str) or not ID_RE.match(pid):
        pid = f"pack-{len(world.packs) + 1:04d}"
    if pid in world.packs:
        return Report(pack_id=pid, errors=[f"pack {pid} was already applied"])
    return _Checker(world, pid).run(copy.deepcopy(raw))
