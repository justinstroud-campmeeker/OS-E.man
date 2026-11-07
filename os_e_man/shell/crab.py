"""crab: the stripped-down shell. Parsing, command registry, dispatch."""

from __future__ import annotations

import shlex
from dataclasses import dataclass
from typing import Callable

REGISTRY: dict[str, "Command"] = {}


@dataclass
class Command:
    name: str
    fn: Callable
    summary: str
    raw: bool = False         # pass the rest of the line unparsed (sql, train submit)
    hidden: bool = False      # not listed in `help` until available
    requires: str | None = None  # access needed, e.g. "facilities"


def command(name: str, summary: str, raw: bool = False, hidden: bool = False,
            requires: str | None = None, aliases: tuple[str, ...] = ()):
    def deco(fn):
        cmd = Command(name, fn, summary, raw, hidden, requires)
        REGISTRY[name] = cmd
        for a in aliases:
            REGISTRY[a] = Command(a, fn, summary, raw, True, requires)
        return fn
    return deco


def _load_commands() -> None:
    from .commands import fs, meta, net, tools  # noqa: F401  (registers commands)


def available(game) -> list[Command]:
    _load_commands()
    out = []
    for c in REGISTRY.values():
        if c.hidden:
            continue
        if c.requires and c.requires not in game.state.access:
            continue
        out.append(c)
    return sorted(out, key=lambda c: c.name)


def split_pipe(line: str) -> tuple[str, str | None]:
    if "|" in line:
        left, _, right = line.rpartition("|")
        right = right.strip()
        if right.startswith("grep ") and not left.endswith("|"):
            return left.strip(), right
    return line, None


def run(game, line: str, out) -> None:
    _load_commands()
    line, pipe = split_pipe(line)
    name, _, rest = line.partition(" ")
    cmd = REGISTRY.get(name)
    if cmd is None or (cmd.requires and cmd.requires not in game.state.access):
        out(f"crab: {name}: command not found", "err")
        return
    if cmd.raw:
        args = [rest.strip()] if rest.strip() else []
    else:
        try:
            args = shlex.split(rest)
        except ValueError as e:
            out(f"crab: parse error: {e}", "err")
            return
    if pipe is None:
        cmd.fn(game, args, out)
        return
    # `cmd | grep [-i] pattern`
    from ..game import Out
    buf = Out(game)
    cmd.fn(game, args, buf)
    try:
        gargs = shlex.split(pipe)[1:]
    except ValueError:
        gargs = []
    insensitive = "-i" in gargs
    pats = [a for a in gargs if a != "-i"]
    if not pats:
        out("usage: ... | grep [-i] PATTERN", "err")
        return
    pat = pats[0].lower() if insensitive else pats[0]
    for item in buf.items:
        text = item.plain.lower() if insensitive else item.plain
        if pat in text:
            out.items.append(item)


def complete(game, text: str) -> list[str]:
    """Return candidate completions for the current input line."""
    _load_commands()
    if " " not in text:
        return [c.name + " " for c in available(game) if c.name.startswith(text)]
    head, _, last = text.rpartition(" ")
    name = head.split(" ")[0]
    if name == "man":
        from .. import content
        return [f"{head} {t}" for t in content.man_topics() if t.startswith(last)]
    return [f"{head} {p}" for p in game.vfs.complete(last)]
