"""Bigger tools: emmy, train, sql, snek, dingaling, facil, plus a few stubs."""

from __future__ import annotations

import random

from ...training.snek import Snek
from ...training.sqlrunner import DOCUMENTED, SQLDenied, format_table
from ..crab import command


# --------------------------------------------------------------------- emmy
@command("emmy", "read email (emmy, emmy read N, emmy next, emmy send ADDR)")
def emmy(game, args, out):
    st = game.state
    if not args or args[0] in ("list", "ls"):
        if not st.inbox:
            out("emmy: inbox empty. enjoy it.", "dim")
            return
        out(f"  #  {'':1} {'when':<12} {'from':<34} subject", "head")
        for i, m in enumerate(st.inbox, 1):
            flag = " " if m["read"] else "*"
            out(f"{i:>3}  {flag} d{m['day']} {m['time']:<8} {m['from'][:34]:<34} {m['subject']}",
                None if m["read"] else "mail")
        return
    sub = args[0]
    if sub == "send":
        _send(game, args[1:], out)
        return
    if sub == "next":
        idx = next((i for i, m in enumerate(st.inbox) if not m["read"]), None)
        if idx is None:
            out("emmy: no unread mail.", "dim")
            return
    elif sub == "read" and len(args) > 1 and args[1].isdigit():
        idx = int(args[1]) - 1
    elif sub.isdigit():
        idx = int(sub) - 1
    else:
        out("usage: emmy | emmy read N | emmy next | emmy send ADDR", "err")
        return
    if not 0 <= idx < len(st.inbox):
        out("emmy: no such message", "err")
        return
    m = st.inbox[idx]
    m["read"] = True
    rec = game.events.by_id.get(m["id"])
    body = rec["body"] if rec else ("[Message body unavailable. The original was not retained "
                                    "by the mail archive (retention class: none).]")
    out(f"From:    {m['from']}", "head")
    out(f"To:      pdunn@hpcg.corp")
    out(f"Date:    day {m['day']}, {m['time']}")
    out(f"Subject: {m['subject']}", "head")
    out("")
    out(body)
    if m["id"] == "e_hr_memo":
        game.state.set_flag("memo_read")


def _send(game, args, out):
    import re
    from ...game import EditRequest
    if len(args) != 1 or not re.match(r"^[\w.+-]+@[\w-]+(\.[\w-]+)+$", args[0]):
        out("usage: emmy send user@host", "err")
        return
    to = args[0].lower()

    def save(text, o):
        head, _, body = text.partition("\n")
        subject = head[len("Subject:"):].strip() if head.startswith("Subject:") else ""
        if not (subject or body.strip()):
            o("emmy: message empty; not sent.", "dim")
            return
        st = game.state
        st.sent_mail.append({"to": to, "subject": subject, "day": st.day, "time": st.clock})
        g = game.glimpses.mail_target(to)
        if game.levers.on_mail(to, o):
            pass
        elif g:
            game.glimpses.complete(g["id"])
            o(f"emmy: sent to {to}.", "ok")
        elif to.endswith("@hpcg.corp"):
            o(f"emmy: sent to {to}. (no read receipt requested. none will be sent.)", "ok")
        else:
            o(f"emmy: 550 5.1.1 <{to}>: recipient address rejected: user unknown", "err")

    game.requests.append(EditRequest(f"emmy: new message to {to} (^O write, ^X send)",
                                     "Subject: \n\n", save))


# -------------------------------------------------------------------- badge
DOORS = ["LOBBY-EAST", "3F-KITCHEN", "3F-AQUARIUM", "3F-BIGCONF", "SERVER-RM", "BIKE-STORE"]


@command("badge", "Tallyho badge console (badge log, badge door, badge revoke, badge restore)",
         requires="badging")
def badge(game, args, out):
    st, b = game.state, game.state.badge
    doors = b.setdefault("doors", {})
    revoked = b.setdefault("revoked", [])
    sub = args[0] if args else "status"
    if sub == "status":
        out("Tallyho Badging: HPCG Dunmore (tenant 0417)", "head")
        for d in DOORS:
            out(f"  {d:<12} {doors.get(d, 'normal')}")
        if revoked:
            out("  revoked: " + ", ".join(revoked))
        return
    if sub == "log":
        people = [k for k, p in game.events.people.items() if k not in ("lnd", "it") and not p.get("drift")]
        rng = random.Random(st.day)
        out(f"Badge events, day {st.day}", "head")
        for i, who in enumerate(people):
            t = 8 * 60 + 30 + rng.randint(0, 50) + i * 7
            out(f"  {t // 60:02d}:{t % 60:02d}  {game.events.name(who):<16} {rng.choice(DOORS[:4])}")
        out(f"  {9:02d}:{rng.randint(0, 9):02d}  {'pdunn':<16} LOBBY-EAST", "dim")
        game.poke("badge:log")
        return
    if sub == "door" and len(args) == 3 and args[2] in ("lock", "unlock", "normal"):
        door = next((d for d in DOORS if d.lower().startswith(args[1].lower())), None)
        if door is None:
            out("badge: no such door. Doors: " + ", ".join(DOORS), "err")
            return
        if args[2] == "normal":
            doors.pop(door, None)
        else:
            doors[door] = args[2]
        out(f"Tallyho: {door} set to {args[2]} (operator: facilities)", "ok")
        game.omens.apply("badge", f"{door} {args[2]}", out)
        return
    if sub in ("revoke", "restore") and len(args) == 2:
        who = args[1].lower()
        if who not in game.events.people:
            out(f"badge: no badge holder '{who}'", "err")
            return
        if sub == "revoke" and who not in revoked:
            revoked.append(who)
        elif sub == "restore" and who in revoked:
            revoked.remove(who)
        out(f"Tallyho: badge for {game.events.name(who)} {sub}d (operator: facilities)", "ok")
        game.omens.apply("badge", f"{sub} {who}", out)
        return
    out("usage: badge [status] | badge log | badge door DOOR lock|unlock|normal | badge revoke|restore WHO", "err")


# -------------------------------------------------------------------- train
def _progress(game) -> str:
    done = len(game.state.challenges_done)
    total = len(game.training.challenges)
    bar = "■" * done + "□" * (total - done)
    return f"EER-26 progress: {bar} {done}/{total}"


def _show(game, ch, out):
    tr = game.training
    out(f"[{tr.number(ch)}/{len(tr.challenges)}] {ch['title']}", "head")
    out(ch["prompt"])


@command("train", "Engineering Excellence Refresher (train, train next, train submit, train hint)", raw=True)
def train(game, args, out):
    from ...game import EditRequest

    tr = game.training
    st = game.state
    line = args[0] if args else ""
    sub, _, rest = line.partition(" ")
    if not tr.enrolled:
        st.set_flag("enrolled")
        out("Enrolling pdunn in EER-26 ... done. (enrollment was mandatory; you were already enrolled.)", "ok")
        sub = "next"
    if sub in ("", "status"):
        out(_progress(game))
        ch = tr.current()
        out(f"Current: {ch['title']}  (train next)" if ch else "All modules complete. Excellence achieved.")
        return
    ch = tr.current()
    if ch is None:
        out("EER-26: all modules complete. There is nothing more to learn here.", "ok")
        return
    if sub in ("next", "show"):
        _show(game, ch, out)
        return
    if sub == "hint":
        out(f"hint: {ch['hint']}", "dim")
        return
    if sub == "submit":
        if ch["kind"] == "sql":
            if rest.strip():
                _submit(game, ch, rest.strip(), out)
            else:
                game.requests.append(EditRequest(f"EER-26 {ch['id']} — SQL answer (^O write, ^X submit)",
                                                 st.drafts.get(ch["id"], "SELECT "),
                                                 lambda text, o: _submit(game, ch, text, o)))
            return
        game.requests.append(EditRequest(f"EER-26 {ch['id']} — snek (^O write, ^X submit)",
                                         st.drafts.get(ch["id"], ch["template"]),
                                         lambda text, o: _submit(game, ch, text, o)))
        return
    out("usage: train [status|next|hint|submit [ANSWER]]", "err")


def _submit(game, ch, answer, out):
    st = game.state
    st.drafts[ch["id"]] = answer
    out(f"Submitting {ch['id']} to lnd-grader ...", "dim")
    g = game.training.grade(ch, answer)
    for line in g.lines:
        out(line, "ok" if g.passed and line.startswith("grader: PASS") else None)
    anomaly = game.training.maybe_anomaly()
    if anomaly:
        out(anomaly, "dim")
    if g.passed:
        st.challenges_done.append(ch["id"])
        out(_progress(game), "ok")
        nxt = game.training.current()
        if nxt:
            out("Next: `train next`", "dim")


# ---------------------------------------------------------------------- sql
@command("sql", "query the EER-26 training replica (read-only)", raw=True)
def sql(game, args, out):
    q = args[0] if args else ""
    if not q:
        out("usage: sql SELECT ... | sql .tables | sql .schema TABLE", "err")
        return
    if q.startswith(".tables"):
        names = game.db.table_names()
        out("  ".join(names))
        game.poke("sql:.tables")
        return
    if q.startswith(".schema"):
        parts = q.split()
        if len(parts) < 2:
            out("usage: sql .schema TABLE", "err")
            return
        try:
            cols = game.db.schema(parts[1])
        except SQLDenied as e:
            out(f"sql: {e}", "err")
            return
        out(f"{parts[1]}: " + ", ".join(c for c, _ in cols))
        if parts[1] not in DOCUMENTED:
            game.poke(f"sql:{parts[1]}")
        return
    try:
        res = game.db.query(q)
    except SQLDenied as e:
        out(f"sql: error: {e}", "err")
        return
    out.lines(format_table(res))
    game.note_tables(res.tables)


# --------------------------------------------------------------------- snek
@command("snek", "run snek (sandboxed Python): snek FILE | snek -c CODE")
def snek(game, args, out):
    if not args:
        out("usage: snek FILE | snek -c CODE", "err")
        return
    if args[0] == "-c":
        src = " ".join(args[1:])
    else:
        path = game.vfs.resolve(args[0])
        try:
            src = game.vfs.read(path)
        except OSError:
            out(f"snek: can't open file '{args[0]}'", "err")
            return
    res = Snek().run(src)
    out.lines(res.output[:200])
    if res.error:
        out(res.error, "err")


# ---------------------------------------------------------------- dingaling
@command("dingaling", "company chat (read-only, pending onboarding since 2021)")
def dingaling(game, args, out):
    if args and args[0] in ("send", "post", "say", "msg"):
        out("dingaling: sending is disabled for your account (status: read-only, pending onboarding, since 2021)", "err")
        return
    log = game.state.ticker_log[-20:]
    if not log:
        out("dingaling: nothing yet. it's early.", "dim")
        return
    for e in log:
        t = e["t"] % 1440
        out(f"[{t // 60:02d}:{t % 60:02d}] {e['channel']:<17} <{game.events.name(e['who'])}> {e['text']}")


# --------------------------------------------------------------------- stubs
_GROG = [
    "grog: Great question! The answer is SELECT * FROM answers. I am 97% confident.",
    "grog: As a large language model, I have deleted your timesheets to help you focus.",
    "grog: Based on my training data, Brenda is a type of ficus.",
    "grog: I cannot help with that. I can, however, help with that.",
    "grog: The capital of SQL is JOIN.",
]


@command("grog", "the company LLM (beta) (forever)")
def grog(game, args, out):
    if not args:
        out("usage: grog QUESTION", "err")
        return
    out(random.choice(_GROG))


@command("boardz", "abusenet reader")
def boardz(game, args, out):
    out("boardz: connection to abusenet refused by proxy (category: Leisure). "
        "Submit an exception request via ITSD.", "err")


# -------------------------------------------------------------------- facil
def _need_facilities(game, out) -> bool:
    if game.state.user != "facilities":
        out("facil: permission denied (this tool is for Office Services. su facilities)", "err")
        return False
    return True


_BW_ORDER = 48213


def _order_no(game) -> str:
    return f"BW-{_BW_ORDER + len(game.state.facil['orders'])}"


@command("facil", "Office Services facilities portal", requires="facilities")
def facil(game, args, out):
    if not _need_facilities(game, out):
        return
    f = game.state.facil
    sub = args[0] if args else "status"
    rest = args[1:]
    if sub == "status":
        out("Office Services — HPCG Dunmore", "head")
        out(f"  Kitchen pods:   {f['pods']}")
        out(f"  Water cooler:   {f['cooler']}")
        out(f"  3rd floor:      {f['thermostat']}°F")
        for room, title in f["rooms"].items():
            out(f"  {room:<14}  {title or '(free)'}")
        if f["orders"]:
            out(f"  Recent orders:  " + "; ".join(f["orders"][-3:]))
        return
    if sub == "pods":
        if not rest:
            out("usage: facil pods <variety>   e.g. facil pods hazelnut", "err")
            return
        variety = " ".join(rest)
        f["pods"] = variety.title() + " (all boxes)"
        out(f"Brightwater order {_order_no(game)} confirmed: kitchen pods -> {variety}. "
            "Delivery today, 13:00-15:00. Existing stock will be swapped.", "ok")
        f["orders"].append(f"pods: {variety}")
        game.omens.apply("pods", variety, out)
        return
    if sub == "cooler":
        if not rest:
            out("usage: facil cooler <schedule>   e.g. facil cooler pause", "err")
            return
        sched = " ".join(rest)
        f["cooler"] = sched
        out(f"Brightwater water schedule updated: {sched}.", "ok")
        game.omens.apply("cooler", sched, out)
        return
    if sub == "order":
        if not rest:
            out('usage: facil order "<item>"', "err")
            return
        item = " ".join(rest)
        out(f"Order {_order_no(game)} placed: {item}. Approved automatically (approver: facilities).", "ok")
        f["orders"].append(item)
        game.omens.apply("order", item, out)
        return
    if sub == "book":
        if len(rest) < 2:
            out('usage: facil book <room> "<title>"   rooms: ' + ", ".join(f["rooms"]), "err")
            return
        room = next((r for r in f["rooms"] if r.lower().startswith(rest[0].lower())), None)
        if room is None:
            out(f"facil: no room matching '{rest[0]}'. Rooms: " + ", ".join(f["rooms"]), "err")
            return
        title = " ".join(rest[1:])
        f["rooms"][room] = title
        out(f"{room} booked all day: \"{title}\" (organizer: Office Services)", "ok")
        game.omens.apply("book", title, out)
        return
    if sub == "vendors":
        if rest and rest[0].lower().startswith("tallyho"):
            if "badging" in game.state.access:
                out("Tallyho Badging: session already open. Use `badge`.", "dim")
            elif not game.levers.grant("badge_portal", out):
                out("Tallyho Badging: SSO link revoked (ITSD-118451).", "err")
            return
        out("Vendors (this page was removed in v2.3)", "head")
        out("  brightwater   Brightwater Coffee Services   orders: linked")
        out("  halcyon       Halcyon HVAC                  setpoint: linked")
        tally = "revoked" if game.state.has("route_burned:badge_portal") else "linked (ADMIN-SSO, last used 2019)"
        out(f"  tallyho       Tallyho Badging               console: {tally}")
        out("  facil vendors <name> to open", "dim")
        return
    if sub == "thermostat":
        if not rest or not rest[0].lstrip("-").isdigit():
            out("usage: facil thermostat <degF>", "err")
            return
        deg = int(rest[0])
        if not 60 <= deg <= 80:
            out("Halcyon HVAC: setpoint out of range (60-80). Nice try.", "err")
            return
        f["thermostat"] = deg
        out(f"Halcyon HVAC: 3rd floor setpoint {deg}°F. Change takes effect in ~20 minutes.", "ok")
        game.omens.apply("thermostat", str(deg), out)
        return
    out("usage: facil [status|pods|cooler|order|book|thermostat] ...  (cat ~/portal.txt)", "err")
