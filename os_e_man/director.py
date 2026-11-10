"""The director: writes tomorrow's world from outside the machine.

One pass (`run_once`) is: digest -> plan -> one writer prompt per slot -> pack -> check -> apply.
The model sits behind one small interface (`Model.complete(task, prompt) -> str`). It only
ever returns text. The director parses that text as JSON, and the world's own checker
decides what survives (see docs/director.md). The director never emits code, and it can only
reach the world through its door: a `Link` with digest/check/apply.

Authority, for now: texture only (chatter, chat beats, mail). No omens, no rung changes.

`FakeModel` returns canned JSON so the loop can be tested without a model. A real local model
(OpenAI-compatible, 127.0.0.1) plugs in behind the same interface later.
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

SLOTS = ("chatter", "beats", "emails")
WRITE_AHEAD_AT = "16:00"   # from this time on, the director writes tomorrow, not today


# ----------------------------------------------------------------- the model
class Model(Protocol):
    name: str

    def complete(self, task: str, prompt: str) -> str:
        """task is "plan" or a slot name. Returns text, which should contain JSON."""
        ...


# ----------------------------------------------------------------- links (the door)
class Link(Protocol):
    async def digest(self) -> dict: ...
    async def check(self, pack: dict) -> dict: ...
    async def apply(self, pack: dict) -> dict: ...


class LocalLink:
    """In-process link to a Game (tests, and a world that isn't running)."""

    def __init__(self, game, persist: bool = True):
        self.game = game
        self.persist = persist   # False: write the pack file only, leave the save alone

    async def digest(self) -> dict:
        return self.game.world.digest(self.game)

    async def check(self, pack: dict) -> dict:
        from .world import check_pack
        return check_pack(pack, self.game.world).to_dict()

    async def apply(self, pack: dict) -> dict:
        rep = self.game.world.apply(pack, day=self.game.state.day)
        if rep.ok and self.persist:
            self.game.save()
        return rep.to_dict()


class ServerLink:
    """The director door on the world server's control port (an authenticated Connection)."""

    def __init__(self, conn):
        self.conn = conn

    async def _ask(self, msg: dict) -> dict:
        await self.conn.send(msg)
        reply = await self.conn.recv()
        if reply is None:
            raise ConnectionError("the world closed the director door")
        reply.pop("ev", None)
        return reply

    async def digest(self) -> dict:
        return (await self._ask({"op": "digest"})).get("digest") or {}

    async def check(self, pack: dict) -> dict:
        return await self._ask({"op": "check", "pack": pack})

    async def apply(self, pack: dict) -> dict:
        return await self._ask({"op": "apply", "pack": pack})


# ----------------------------------------------------------------- scheduling
def target_day(digest: dict) -> int:
    """Late in the day (or held at 16:59 with nobody in), write tomorrow; otherwise today."""
    day = int(digest.get("day", 1))
    return day + 1 if str(digest.get("clock", "09:00")) >= WRITE_AHEAD_AT else day


def pack_id_for(day: int) -> str:
    return f"dir-d{day:03d}"


# ----------------------------------------------------------------- prompts
VOICE = """\
You write content for a fictional office in a satirical game. Everything you write is a real
document by someone who doesn't know they're in a story: chat, mail, notices.
- Flat, bureaucratic, believable. The joke is how accurate it is. No winking, no hacker lingo,
  no exclamation marks.
- Ticket numbers and tracking IDs are welcome (ITSD-, HPCG-, FAC-).
- Each day has one small thing that is slightly wrong (a label, a booking, a record, a
  number) and nobody can explain. Mundane, specific, never resolved. A little SCP-style
  weirdness is welcome, logged as if it were routine paperwork. Not sci-fi.
- Chat is chat: short, mostly lowercase, typed by tired people. Match each person's voice,
  but never reuse their sample lines or anything in recent chat: anything already said is
  thrown away.
- Anything strange is described calmly, as if it were routine.
- The player is Pat Dunn (pdunn, they/them). Nobody notices Pat: nobody mentions, sees or
  addresses Pat or pdunn. Never address the player.
- Everything is fictional and internal: only *.hpcg.corp hosts and @hpcg.corp addresses,
  10.x.x.x IPs, no URLs, no real companies or people.
Reply with JSON only."""

SCHEMAS = {
    "plan": '{"notes": {"chatter": "one line", "beats": "one line", "emails": "one line"},'
            ' "threads": [{"id": "short-kebab-id", "title": "what it is", "state": "open|closed",'
            ' "next": "where it goes next", "facts": ["a concrete detail established today"]}]}',
    "chatter": '{"normal": [{"channel": "#dunmore-general", "who": "<person key>", "text": "..."}],'
               ' "uneasy": [...], "afraid": [...]}',
    "beats": '{"beats": [{"id": "d<D>_<short>", "when": {"day": D, "at": "HH:MM", ...branch keys},'
             ' "channel": "#...", "who": "<person key>", "text": "..."}]}',
    "emails": '{"emails": [{"id": "d<D>_<short>", "when": {"day": D, "at": "HH:MM", ...branch keys},'
              ' "delay": 0, "from": "<handle>@hpcg.corp", "subject": "...", "body": "..."}]}',
}


# The same shapes as JSON Schema, for servers that constrain output to a schema (LM Studio's
# structured output). The grammar forces valid JSON even from models that can't write it.
_S, _I = {"type": "string"}, {"type": "integer"}
_WHEN = {"type": "object", "properties": {"day": _I, "at": _S}, "required": ["day", "at"]}
_LINE = {"type": "object", "properties": {"channel": _S, "who": _S, "text": _S},
         "required": ["channel", "who", "text"]}


def _arr(item, lo=1):
    return {"type": "array", "items": item, "minItems": lo}


def _obj(props, req=None):
    return {"type": "object", "properties": props, "required": req or list(props)}


JSON_SCHEMAS = {
    "plan": _obj({"notes": _obj({"chatter": _S, "beats": _S, "emails": _S}),
                  "threads": _arr(_obj({"id": _S, "title": _S, "state": {"enum": ["open", "closed"]},
                                        "next": _S, "facts": _arr(_S)}))}),
    "chatter": _obj({"normal": _arr(_LINE), "uneasy": _arr(_LINE), "afraid": _arr(_LINE)}),
    "beats": _obj({"beats": _arr(_obj({"id": _S, "when": _WHEN, "channel": _S, "who": _S, "text": _S}), 2)}),
    "emails": _obj({"emails": _arr(_obj({"id": _S, "when": _WHEN, "delay": _I, "from": _S,
                                         "subject": _S, "body": _S}))}),
}

def _mood(m: dict) -> str:
    return "afraid" if m.get("mystique", 0) >= 6 else "uneasy" if m.get("mystique", 0) >= 3 else "normal"


def _situation(digest: dict, day: int) -> str:
    m = digest.get("meters", {})
    people = ", ".join(f"{k} ({v.get('role', '')}; mail {v.get('handle', k)}@hpcg.corp)"
                       for k, v in digest.get("people", {}).items())
    voices = "\n".join(f"  {k}: " + " / ".join(f'"{t}"' for t in lines)
                       for k, lines in digest.get("voices", {}).items())
    chat = "\n".join(f"  {c['channel']} <{c['who']}> {c['text']}" for c in digest.get("recent_chat", [])[-8:])
    mail = "\n".join(f"  {e['from']}: {e['subject']}" for e in digest.get("inbox", [])[-5:])
    threads = "\n".join(f"  - {t['id']}: {t.get('title', '')} (last seen day {t.get('day', '?')}; "
                        f"next: {t.get('next', '?')})"
                        + "".join(f"\n      fact: {f}" for f in t.get("facts", []))
                        for t in digest.get("threads", []))
    written = "\n".join(f"  day {d}: {note or '(no note)'}"
                        for d, note in list(digest.get("written_days", {}).items())[-5:])
    return (f"You are writing day {day}. In the office it is now day {digest.get('day')}, "
            f"{digest.get('clock')}.\n"
            f"Office mood now: {_mood(m)}.\n"
            f"People (use these keys as \"who\"): {people}\n"
            f"How they talk:\n{voices or '  (no samples)'}\n"
            f"Channels: {', '.join(digest.get('channels', []))}\n"
            f"Things the player has poked at: {', '.join(digest.get('poked', [])) or 'nothing yet'}\n"
            f"Recent chat:\n{chat or '  (quiet)'}\n"
            f"Recent mail:\n{mail or '  (none)'}\n"
            f"Recent records anomalies: {'; '.join(digest.get('anomalies', [])[-3:]) or 'none'}\n"
            f"Your storylines so far:\n{threads or '  (none yet)'}\n"
            f"Days you have already written:\n{written or '  (none yet)'}")


def _branching(digest: dict) -> str:
    """What the writer may condition on. The game picks the branch at play time."""
    m = digest.get("meters", {})
    pokeable = ", ".join(digest.get("pokeable", [])[:12]) or "(nothing left)"
    return (
        "The player will play this day later, and what they do before then changes it. Make some\n"
        "lines depend on the player's state with extra keys in \"when\" (the game checks them live):\n"
        f"  \"mystique\": N / \"mystique_below\": N   how unsettled the office is (now {m.get('mystique', 0)}; 3+ is uneasy)\n"
        f"  \"curiosity\": N / \"curiosity_below\": N how much the player has dug (now {m.get('curiosity', 0)})\n"
        "  \"flag\": \"poke:<thing>\" / \"not_flag\": \"poke:<thing>\"   only if / unless the player has looked at <thing>\n"
        f"  things they could still look at: {pokeable}\n"
        "Write branches in pairs: two versions of the same moment (same time, different ids), one\n"
        "for each side of one condition, e.g. {\"mystique\": 3} and {\"mystique_below\": 3}.\n"
        "The two versions must differ in what happens, not just in wording: one side is mundane,\n"
        "the other is the same moment gone slightly further wrong.")


def plan_prompt(digest: dict, day: int) -> str:
    return (f"{VOICE}\n\n{_situation(digest, day)}\n\n"
            f"Plan day {day} in a few words per slot. Continue one or two of your storylines "
            f"(start one if you have fewer than two). A storyline runs for several days before it "
            f"closes, and nothing is ever explained. Every day a storyline you continue gets one "
            f"new, concrete development (a second instance, a new number, a reply that makes it "
            f"worse); it never just waits for tomorrow. Return every storyline you touched in "
            f"\"threads\", with its new state and where it goes next.\n"
            f"The facts under a storyline are canon: never contradict them, and reuse the same "
            f"names, numbers, times and IDs. Put each new concrete detail you introduce today in "
            f"that storyline's \"facts\" (short, one detail each).\n"
            f"Reply as: {SCHEMAS['plan']}")


def writer_prompt(slot: str, digest: dict, day: int, note: str) -> str:
    asks = {
        "chatter": "Write 1-2 ambient chat lines for each mood: normal, uneasy, afraid. Each mood is "
                   "more tense than the last, and all of them stay deadpan.",
        "beats": f"Write 3-5 scheduled chat lines for day {day}, between 09:00 and 16:30. "
                 f"Include one branching pair.",
        "emails": f"Write 1-2 emails delivered on day {day}, between 09:00 and 16:30. "
                  f"If there are two, make them a branching pair.",
    }
    branch = f"\n{_branching(digest)}\n" if slot in ("beats", "emails") else "\n"
    return (f"{VOICE}\n\n{_situation(digest, day)}\n\nThe plan for this slot: {note}\n{branch}"
            f"{asks[slot]} Start every id with \"d{day}_\".\nReply as: {SCHEMAS[slot]}")


# ----------------------------------------------------------------- parsing model output
def extract_json(text: str):
    """The first JSON object or array in the text (models like to add prose and fences)."""
    if not isinstance(text, str):
        return None
    dec = json.JSONDecoder()
    for m in re.finditer(r"[\[{]", text):
        try:
            return dec.raw_decode(text, m.start())[0]
        except ValueError:
            continue
    return None


def _section(slot: str, data):
    """Coerce a writer's reply into the pack section shape, or None."""
    if isinstance(data, dict) and slot in data:
        data = data[slot]
    if slot == "chatter":
        if isinstance(data, list):
            data = {"normal": data}
        return data if isinstance(data, dict) and data else None
    if isinstance(data, dict):
        data = [data]
    return data if isinstance(data, list) and data else None


# ----------------------------------------------------------------- one pass
CALLS_PER_DAY = 1 + len(SLOTS)


@dataclass
class Result:
    day: int
    pack_id: str
    status: str                         # applied / checked / skipped / rejected / empty
    report: dict = field(default_factory=dict)
    log: list[str] = field(default_factory=list)
    calls: int = 0


def is_written(digest: dict, day: int) -> bool:
    return pack_id_for(day) in digest.get("packs", []) or str(day) in digest.get("written_days", {})


def _threads(plan) -> list[dict]:
    if not isinstance(plan, dict) or not isinstance(plan.get("threads"), list):
        return []
    return [t for t in plan["threads"] if isinstance(t, dict)][:8]


async def run_once(link: Link, model: Model, *, day: int | None = None, dry_run: bool = False,
                   transcript_dir: Path | None = None, digest: dict | None = None) -> Result:
    """Write one day (default: today, or tomorrow late in the day)."""
    digest = digest if digest is not None else await link.digest()
    day = day if day is not None else target_day(digest)
    pid = pack_id_for(day)
    res = Result(day, pid, "skipped")
    if is_written(digest, day):
        res.log.append(f"day {day} is already written ({pid})")
        return res

    transcript: list[dict] = []

    async def ask(task: str, prompt: str):
        res.calls += 1
        try:
            text = await asyncio.to_thread(model.complete, task, prompt)
        except Exception as e:  # a model failure costs a slot, never the world
            text = ""
            res.log.append(f"{task}: model failed ({e.__class__.__name__}: {e})")
        transcript.append({"task": task, "prompt": prompt, "response": text})
        return extract_json(text)

    plan = await ask("plan", plan_prompt(digest, day))
    notes = plan.get("notes", plan) if isinstance(plan, dict) else {}
    if not isinstance(notes, dict):
        notes = {}

    pack: dict = {"id": pid, "source": f"director:{model.name}", "for_day": day,
                  "note": "; ".join(f"{k}: {v}" for k, v in notes.items() if isinstance(v, str))[:500]}
    if _threads(plan):
        pack["threads"] = _threads(plan)
    for slot in SLOTS:
        note = notes.get(slot) if isinstance(notes.get(slot), str) else "keep the office going"
        sec = _section(slot, await ask(slot, writer_prompt(slot, digest, day, note)))
        if sec is None:
            res.log.append(f"{slot}: nothing usable came back")
            continue
        pack[slot] = sec

    if transcript_dir:
        transcript_dir.mkdir(parents=True, exist_ok=True)
        (transcript_dir / f"{pid}.json").write_text(
            json.dumps({"pack": pack, "transcript": transcript}, indent=1, ensure_ascii=False),
            encoding="utf-8")

    if not any(s in pack for s in SLOTS):
        res.status = "empty"
        return res
    res.report = await (link.check(pack) if dry_run else link.apply(pack))
    res.status = ("checked" if dry_run else "applied") if res.report.get("ok") else "rejected"
    return res


async def run_ahead(link: Link, model: Model, *, days: int = 3, budget: int = 40,
                    dry_run: bool = False, transcript_dir: Path | None = None) -> list[Result]:
    """While the player is away: write the next `days` unwritten days, in order, each one
    planned with the digest after the one before it (so storylines carry over), and stop
    before going over `budget` model calls. With dry_run, nothing is applied, so later days
    can't see earlier ones."""
    results: list[Result] = []
    digest = await link.digest()
    day, spent, written = target_day(digest), 0, 0
    while written < days:
        if is_written(digest, day):
            day += 1
            continue
        if spent + CALLS_PER_DAY > budget:
            results.append(Result(day, pack_id_for(day), "skipped",
                                  log=[f"budget: {spent}/{budget} model calls used; stopping"]))
            break
        r = await run_once(link, model, day=day, dry_run=dry_run, transcript_dir=transcript_dir,
                           digest=digest)
        spent += r.calls
        results.append(r)
        if r.status == "empty" and any("model failed" in x for x in r.log):
            break                      # the model is down; don't burn the budget
        written += 1
        day += 1
        digest = await link.digest()
    return results


# ----------------------------------------------------------------- the fake model
_THEMES = [
    {
        "notes": {"chatter": "the fridge, and whose name is on things",
                  "beats": "Friday fridge purge; a label nobody recognises",
                  "emails": "Facilities announces the clear-out"},
        "thread": {
            "id": "fridge-labels",
            "title": "labels in the kitchen fridge with names nobody can place",
            "state": "open",
            "next": "Facilities retains a labelled item"},
        "fork": {
            "at": "15:10",
            "who": "brenda",
            "calm": "fridge cleared. the PD oat milk was retained per guidance.",
            "tense": "fridge cleared. the PD oat milk was retained. so was a second one. it was not there this morning."},
        "uneasy": "labels keep turning up in handwriting nobody recognises",
        "chatter": {"normal": [
            {"channel": "#dunmore-general", "who": "brenda", "text": "the fridge is not a filing system"},
            {"channel": "#dunmore-general", "who": "doug", "text": "if your lunch is a deliverable, label it"}]},
        "beats": [
            {"at": "10:40", "channel": "#dunmore-general", "who": "kev",
             "text": "fridge purge friday. my yoghurt has a name on it. not my name. but a name."},
            {"at": "11:15", "channel": "#dunmore-general", "who": "priya",
             "text": "the oat milk is labelled 'PD'. it has been labelled 'PD' since march."}],
        "email": {"at": "09:30", "from": "facilities@hpcg.corp",
                  "subject": "Kitchen Fridge Clear-Out, Friday 16:00 (FAC-{n})",
                  "body": "Hi all,\n\nThe 3rd floor kitchen fridge will be cleared on Friday at 16:00.\n"
                          "Anything unlabelled will be disposed of.\n\nItems labelled with a name that "
                          "does not appear in the staff\ndirectory will be retained, as per previous "
                          "guidance (FAC-0388).\n\nThanks,\nFacilities, HPCG Dunmore"},
    },
    {
        "notes": {"chatter": "rooms that say they're in use",
                  "beats": "the Aquarium is booked all day under 'Hold'",
                  "emails": "IT acknowledges bookings with no organiser"},
        "thread": {
            "id": "hold-booking",
            "title": "a room booking called Hold that will not stay deleted",
            "state": "open",
            "next": "the Hold booking spreads to a second room"},
        "fork": {
            "at": "15:40",
            "who": "doug",
            "calm": "client call moved to the Fishbowl. fine. it is fine.",
            "tense": "client call moved to the Fishbowl. the Fishbowl is now also booked under Hold. organiser blank."},
        "uneasy": "nobody has deleted the Hold booking today. nobody wants to be the one",
        "chatter": {"normal": [
            {"channel": "#dunmore-general", "who": "priya",
             "text": "the panel outside the Aquarium says IN USE. the room is empty. it says it in a very confident font"},
            {"channel": "#dunmore-general", "who": "kev", "text": "badge reader on 3 is doing the double beep again"}]},
        "beats": [
            {"at": "09:40", "channel": "#dunmore-general", "who": "doug",
             "text": "who booked the Aquarium all day under 'Hold'. I have a client call at 2."},
            {"at": "14:05", "channel": "#dunmore-general", "who": "kev",
             "text": "deleted the Hold booking. it's back. it has a longer description now"}],
        "email": {"at": "11:00", "from": "it-servicedesk@hpcg.corp",
                  "subject": "Known Issue: Meeting Room Bookings With No Organiser (ITSD-{n})",
                  "body": "Hello,\n\nWe are aware that some meeting rooms are showing bookings titled\n"
                          "'Hold' with a blank organiser field.\n\nPlease do not delete these bookings. "
                          "Deleting them has not worked.\n\nThis ticket will be updated when there is "
                          "more to say.\n\nIT Service Desk"},
    },
    {
        "notes": {"chatter": "timesheets, as always",
                  "beats": "hours logged and approved by nobody in particular",
                  "emails": "the timesheet system thanks an unassigned resource"},
        "thread": {
            "id": "rtl-0042-hours",
            "title": "41.5 hours a week logged to RTL-0042 by a resource with no role",
            "state": "open",
            "next": "the hours are invoiced to the client"},
        "fork": {
            "at": "16:05",
            "who": "priya",
            "calm": "the 03:12 approvals stopped. good.",
            "tense": "another approval at 03:12. same 41.5 hours. same me."},
        "uneasy": "utilisation for RTL-0042 is 104%. nobody on the floor is on RTL-0042",
        "chatter": {"normal": [
            {"channel": "#dunmore-general", "who": "doug", "text": "timesheets. I know. I know. but timesheets."},
            {"channel": "#dunmore-general", "who": "it", "text": "ITSD-reminder: please reboot before raising a ticket about rebooting"}]},
        "beats": [
            {"at": "09:20", "channel": "#dunmore-general", "who": "doug",
             "text": "whoever logged 41.5 hours to RTL-0042 last week: thank you. please tell me who you are."},
            {"at": "12:30", "channel": "#dunmore-general", "who": "priya",
             "text": "the timesheet system says those hours were approved by me. I didn't. it says I did it at 03:12."}],
        "email": {"at": "15:00", "from": "timesheets@hpcg.corp",
                  "subject": "Timesheet Confirmation, Engagement RTL-0042 (HPCG-TS-{n})",
                  "body": "Thank you for submitting your timesheet.\n\nOur records show 41.5 hours logged "
                          "against engagement RTL-0042 by a\nresource with no assigned role. These hours "
                          "have been approved.\n\nIf this is you, no action is required.\n\n"
                          "This is an automated message. Replies are not monitored."},
    },
]


class FakeModel:
    """Canned replies, chosen by the day in the prompt. Good JSON, good voice, no model."""

    name = "fake"

    def complete(self, task: str, prompt: str) -> str:
        m = re.search(r"(?:writing|Tomorrow is) day (\d+)", prompt)
        day = int(m.group(1)) if m else 1
        th = _THEMES[day % len(_THEMES)]
        if task == "plan":
            return json.dumps({"notes": th["notes"], "threads": [th["thread"]]})
        if task == "chatter":
            return json.dumps({**th["chatter"], "uneasy": [
                {"channel": "#dunmore-general", "who": "kev", "text": th["uneasy"]}]})
        if task == "beats":
            f = th["fork"]
            beats = [{"id": f"b_dir{day}_{i}", "when": {"day": day, "at": b["at"]},
                      "channel": b["channel"], "who": b["who"], "text": b["text"]}
                     for i, b in enumerate(th["beats"], 1)]
            for side, cond in (("calm", {"mystique_below": 3}), ("tense", {"mystique": 3})):
                beats.append({"id": f"b_dir{day}_{side}", "when": {"day": day, "at": f["at"], **cond},
                              "channel": "#dunmore-general", "who": f["who"], "text": f[side]})
            return json.dumps(beats)
        if task == "emails":
            e = th["email"]
            return "Here is the email:\n```json\n" + json.dumps([{
                "id": f"e_dir{day}", "when": {"day": day, "at": e["at"]}, "delay": 0,
                "from": e["from"], "subject": e["subject"].format(n=4100 + day * 7),
                "body": e["body"]}]) + "\n```"
        return "{}"


# ----------------------------------------------------------------- real models
class ChatModel:
    """Any OpenAI-compatible chat endpoint: Groq (remote), or LM Studio / Ollama on 127.0.0.1.
    Text in, text out; JSON mode on. Note: a remote endpoint receives the prompt, which
    includes the digest (fictional world state and the player's recent in-game commands)."""

    def __init__(self, name: str, base_url: str, model: str, api_key: str | None = None,
                 temperature: float = 0.9, timeout: float = 90.0, client=None, attempts: int = 6,
                 structured: bool = False):
        import httpx
        self.attempts = attempts
        self.name = f"{name}:{model}"
        self.url = base_url.rstrip("/") + "/chat/completions"
        self.model = model
        self.temperature = temperature
        self.headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self.client = client or httpx.Client(timeout=timeout)
        self.json_mode = True
        self.structured = structured     # send a JSON schema per task (LM Studio)

    def complete(self, task: str, prompt: str) -> str:
        import time
        body = {"model": self.model, "temperature": self.temperature,
                "messages": [{"role": "user", "content": prompt}]}
        if self.structured and task in JSON_SCHEMAS:
            body["response_format"] = {"type": "json_schema", "json_schema": {
                "name": task, "strict": True, "schema": JSON_SCHEMAS[task]}}
        elif self.json_mode:
            body["response_format"] = {"type": "json_object"}
        for attempt in range(self.attempts):
            r = self.client.post(self.url, json=body, headers=self.headers)
            if r.status_code == 429 or r.status_code >= 500:     # rate limit / hiccup: wait, retry
                try:
                    wait = float(r.headers.get("retry-after", 5 * (attempt + 1)))
                except ValueError:
                    wait = 5 * (attempt + 1)
                time.sleep(min(wait, 90))                         # free tiers count tokens per minute
                continue
            if r.status_code == 400 and "response_format" in body:
                # Groq: the reply wasn't valid JSON. LM Studio and others: json_object isn't
                # supported at all, so stop asking. Either way, let it talk; extract_json copes.
                body.pop("response_format")
                if "json_validate_failed" not in r.text:
                    self.json_mode = self.structured = False
                continue
            r.raise_for_status()
            return r.json()["choices"][0]["message"].get("content") or ""
        r.raise_for_status()
        return ""


GROQ_URL = "https://api.groq.com/openai/v1"
GROQ_DEFAULT = "openai/gpt-oss-120b"
LOCAL_URL = "http://127.0.0.1:1234/v1"      # LM Studio's default; Ollama is :11434/v1


def make_model(name: str, model_name: str | None = None, base_url: str | None = None) -> Model:
    import os
    if name == "fake":
        return FakeModel()
    if name == "groq":
        key = os.environ.get("GROQ_API_KEY")
        if not key:
            raise SystemExit("os_e_man: set GROQ_API_KEY to use the groq director.")
        return ChatModel("groq", base_url or GROQ_URL, model_name or GROQ_DEFAULT, key)
    if name == "local":
        if not model_name:
            raise SystemExit("os_e_man: --model local needs --model-name (whatever the server has loaded).")
        return ChatModel("local", base_url or LOCAL_URL, model_name, timeout=300, structured=True)
    raise SystemExit(f"os_e_man: unknown director model {name!r} (have: fake, groq, local)")
