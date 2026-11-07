"""Meta commands: help, man, clear, history, echo, whoami, date, mesg, su, exit, quit."""

from __future__ import annotations

from ... import content
from ..crab import available, command

FACILITIES_PASSWORD = "gerald2019"


@command("help", "list commands")
def help_(game, args, out):
    out("crab — available commands (man <command> for details):", "head")
    for c in available(game):
        out(f"  {c.name:<11}{c.summary}")


@command("man", "read the manual")
def man(game, args, out):
    if not args:
        out("What manual page do you want? Try: man crab, man intro", "err")
        out("Pages: " + ", ".join(content.man_topics()), "dim")
        return
    page = content.man_page(args[0])
    if page is None:
        out(f"No manual entry for {args[0]}", "err")
        return
    out(page.rstrip("\n"))


@command("clear", "clear the screen")
def clear(game, args, out):
    game.requests.append("clear")


@command("history", "show command history")
def history(game, args, out):
    for i, h in enumerate(game.state.history[-25:], 1):
        out(f"{i:>4}  {h}", "dim")


@command("echo", "print text")
def echo(game, args, out):
    out(" ".join(args))


@command("whoami", "print the current user")
def whoami(game, args, out):
    out(game.state.user)


@command("date", "print the date and time")
def date(game, args, out):
    st = game.state
    days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    out(f"{days[(st.day - 1) % 7]} Nov {1 + st.day:02d} {st.clock} EST 2026")


@command("mesg", "let chat interrupt your terminal, or not (mesg y|n)")
def mesg(game, args, out):
    st = game.state
    if not args:
        out("is " + ("n" if st.has("mesg_n") else "y"))
        return
    a = args[0].lower()
    if a in ("y", "yes"):
        if st.has("mesg_n"):
            st.flags.remove("mesg_n")
    elif a in ("n", "no"):
        st.set_flag("mesg_n")
    else:
        out("usage: mesg [y|n]", "err")


@command("su", "switch user")
def su(game, args, out):
    from ...game import Prompt

    user = args[0] if args else "root"
    if user == "root":
        out("su: Authentication failure (this incident will not be reported, nobody reads them)", "err")
        return
    if user == "pdunn":
        _logout(game, out)
        return
    if user != "facilities":
        out(f"su: user {user} does not exist", "err")
        return
    def check(pw, o):
        lv = game.levers
        route = lv.secret_route("facilities", pw)
        st = game.state
        if route is None:
            o("su: Authentication failure", "err")
            return
        if "facilities" not in st.access:
            if not lv.is_open(route["id"]):
                o(route.get("burn", "su: Authentication failure") + " Lie low.", "err")
                return
            lv.grant(route["id"], o)
        elif st.routes_used.get("facilities") != route["id"]:
            o("su: Authentication failure", "err")
            return
        st.user = "facilities"
        st.cwd = game.vfs.home()
        first = st.set_flag("got_facilities")
        game.poke("su:facilities")
        o("Last login: Mon Mar 11 08:58 2019 from wks-0102 (2,431 days ago)", "dim")
        o("Office Services — facilities portal. Type `facil` or `cat portal.txt`.", "ok")
        if first:
            o("(You are logged in as the office manager's portal account. "
              "Whatever happens next happens under her name.)", "sys")

    game.pending = Prompt("Password: ", check, password=True)


def _logout(game, out):
    st = game.state
    if st.user == "pdunn":
        out("crab: you are already pdunn. you are always pdunn.", "dim")
        return
    st.user = "pdunn"
    st.cwd = game.vfs.home()
    out("logout", "dim")


@command("exit", "leave the current su session (or the game)", aliases=("logout",))
def exit_(game, args, out):
    if game.state.user != "pdunn":
        _logout(game, out)
    else:
        quit_(game, args, out)


@command("quit", "disconnect (the world keeps running)", aliases=("disconnect",))
def quit_(game, args, out):
    out("Connection to wks-0417 closed. The office carries on without you.", "sys")
    game.requests.append("quit")


@command("shutdown", "save the world and stop the server")
def shutdown(game, args, out):
    out("Broadcast message from root@wks-0417: The system is going down for maintenance NOW.", "sys")
    game.requests.append("shutdown")
