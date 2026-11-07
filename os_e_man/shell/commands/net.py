"""Network commands: ping, whois, netstat, ipconfig. All very local."""

from __future__ import annotations

from ..crab import command


def _net(game):
    return game.world.net


def _lookup(game, name: str):
    hosts = _net(game)["hosts"]
    if name in hosts:
        return name, hosts[name]
    for h, info in hosts.items():
        if info["ip"] == name or h.split(".")[0] == name:
            return h, info
    return None, None


@command("ping", "send 4 polite packets to a host")
def ping(game, args, out):
    target = next((a for a in args if not a.startswith("-")), None)
    if not target:
        out("usage: ping HOST", "err")
        return
    host, info = _lookup(game, target)
    if host is None:
        out(f"ping: {target}: Name or service not known", "err")
        return
    out(f"PING {host} ({info['ip']}): 56 data bytes")
    ms = info.get("ms")
    if ms is None:
        out("Request timed out.\nRequest timed out.\nRequest timed out.\nRequest timed out.", "dim")
        out(f"--- {host}: 4 packets transmitted, 0 received, 100% loss (filtered upstream)")
        return
    ttl = info.get("ttl", 64)
    for i in range(4):
        out(f"64 bytes from {info['ip']}: icmp_seq={i} ttl={ttl} time={ms:.2f} ms")
    out(f"--- {host}: 4 packets transmitted, 4 received, 0% loss")
    if ms == 0.0 and host != "localhost":
        out("ping: note: round-trip time below measurement floor", "dim")
    game.poke(f"ping:{host}")


@command("whois", "look up who owns a host")
def whois(game, args, out):
    if not args:
        out("usage: whois HOST", "err")
        return
    host, info = _lookup(game, args[0])
    if host is None or "whois" not in info:
        out(f"whois: no record for {args[0]}", "err")
        return
    out.lines(info["whois"])
    game.poke(f"whois:{host}")


_last_links: list[str] = []


def _norm(url: str) -> str:
    url = url.strip().lower()
    for pre in ("http://", "https://"):
        if url.startswith(pre):
            url = url[len(pre):]
    return url.rstrip("/")


@command("webble", "text-mode web browser (webble URL, webble N to follow link N)")
def webble(game, args, out):
    from ... import content
    dump = "-dump" in args
    args = [a for a in args if a != "-dump"]
    if not args:
        out("usage: webble URL | webble N | webble -dump URL", "err")
        return
    target = args[0]
    if target.isdigit():
        n = int(target)
        if not 1 <= n <= len(_last_links):
            out(f"webble: no link [{n}] on the last page", "err")
            return
        target = _last_links[n - 1]
    url = _norm(target)
    page = content.load("web.json").get(url)
    if page is not None and not game.events.met(page.get("requires", {})):
        page = None
    if page is None:
        host = url.split("/")[0]
        out(f"webble: Alert!: Unable to connect to remote host {host}.", "err")
        return
    out(f"   {page['title']}", "head")
    out("")
    out(page["body"])
    for add in page.get("addenda", []):
        if game.state.has(add["flag"]):
            out("")
            out(add["text"])
    links = page.get("links", [])
    if links:
        out("")
        out("References" if dump else "Links (webble N to follow)", "dim")
        for i, link in enumerate(links, 1):
            out(f"   [{i}] {link}", "dim")
    _last_links[:] = links
    if page.get("poke"):
        game.poke(page["poke"])
    if page.get("grant"):
        game.levers.grant(page["grant"], out)
    if page.get("glimpse"):
        game.glimpses.complete(page["glimpse"])


@command("netstat", "show network connections")
def netstat(game, args, out):
    out(f"{'Proto':<6}{'Local Address':<22}{'Foreign Address':<22}{'State':<13}Program", "head")
    for proto, local, remote, st, prog in _net(game)["netstat"]:
        out(f"{proto:<6}{local:<22}{remote:<22}{st:<13}{prog}")


@command("ipconfig", "show network configuration", aliases=("ifconfig",))
def ipconfig(game, args, out):
    s = _net(game)["self"]
    out(f"Ethernet adapter (desk 17, port 3-117, cable taped down):", "head")
    out(f"   Host name . . . . . . : {s['host']}")
    out(f"   IPv4 Address. . . . . : {s['ip']}")
    out(f"   Subnet Mask . . . . . : {s['mask']}")
    out(f"   Default Gateway . . . : {s['gw']}")
    out(f"   DNS Servers . . . . . : {s['dns']}")
    out(f"   Physical Address. . . : {s['mac']}")
