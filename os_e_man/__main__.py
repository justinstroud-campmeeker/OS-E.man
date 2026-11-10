"""OS-E.man command line.

    python -m os_e_man              connect over ssh (boots the world first if it isn't running)
    python -m os_e_man boot         start the world in the background
    python -m os_e_man stop         save and shut the world down
    python -m os_e_man status       is it running? what time is it in there?
    python -m os_e_man world digest         what the world looks like from outside (JSON)
    python -m os_e_man world check PACK     dry-run a content pack: what breaks, what drifts
    python -m os_e_man world apply PACK     write a content pack into the world
    python -m os_e_man director [once|ahead|watch] [--model fake|groq|local] [--days N]
                                            the director writes the world: one day (once),
                                            the next N days (ahead), or ahead while you're away
"""

from __future__ import annotations

import argparse
import asyncio
import os
import subprocess
import sys
import time
from pathlib import Path

from .protocol import clear_server_info, hello, read_server_info, runtime_dir
from .state import default_save_path

PKG_PARENT = Path(__file__).resolve().parent.parent


def probe(save: Path) -> tuple[dict, dict] | None:
    """(server info, welcome) if a live, authenticated server answers; else None."""
    info = read_server_info(save)
    if not info:
        return None

    async def _try():
        conn, welcome = await hello(info["port"], info["token"], timeout=2.0)
        await conn.send({"op": "detach"})
        await conn.close()
        return welcome

    try:
        return info, asyncio.run(_try())
    except (OSError, asyncio.TimeoutError, KeyError):
        clear_server_info(save)  # stale
        return None


def boot_background(save: Path, new: bool) -> dict:
    log = runtime_dir(save) / "server.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, "-m", "os_e_man", "--save", str(save), "boot", "--foreground"]
    if new:
        cmd.append("--new")
    kw: dict = {}
    if os.name == "nt":
        kw["creationflags"] = (subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
                               | subprocess.CREATE_NO_WINDOW)
    else:
        kw["start_new_session"] = True
    with open(log, "ab") as fh:
        subprocess.Popen(cmd, cwd=PKG_PARENT, stdin=subprocess.DEVNULL, stdout=fh,
                         stderr=subprocess.STDOUT, **kw)
    deadline = time.time() + 10
    while time.time() < deadline:
        time.sleep(0.25)
        found = probe(save)
        if found:
            return found[0]
    raise SystemExit(f"os_e_man: the world didn't come up. See {log}")


def cmd_boot(args, save: Path) -> None:
    if probe(save):
        print("wks-0417 is already up.")
        if args.new:
            print("Refusing --new while it's running. Run `python -m os_e_man stop` first.")
        return
    if args.foreground:
        from .server import run_server
        print(f"[os_e_man] world server starting (save: {save})", flush=True)
        run_server(save, new=args.new)
        return
    info = boot_background(save, args.new)
    print(f"wks-0417 is up (pid {info['pid']}). Connect with: python -m os_e_man")


def cmd_connect(args, save: Path) -> None:
    found = probe(save)
    info = found[0] if found else boot_background(save, new=False)
    if not info.get("ssh_port"):
        raise SystemExit("os_e_man: the running world has no ssh door (it was booted by an older "
                         "version). Run `python -m os_e_man stop`, then connect again.")
    from .sshd import find_ssh, ssh_command
    ssh = find_ssh()
    if not ssh:
        raise SystemExit("os_e_man: no ssh client found. On Windows: Settings > System > Optional "
                         "features > OpenSSH Client.")
    raise SystemExit(subprocess.call(ssh_command(save, info["ssh_port"], ssh)))


def cmd_stop(args, save: Path) -> None:
    found = probe(save)
    if not found:
        print("wks-0417 is not running.")
        return
    info = found[0]

    async def _stop():
        conn, _ = await hello(info["port"], info["token"])
        await conn.send({"op": "shutdown", "token": info["token"]})
        await conn.close()

    asyncio.run(_stop())
    for _ in range(40):
        if not read_server_info(save):
            break
        time.sleep(0.25)
    print("wks-0417 is down. The office is dark. Gerald waits.")


def cmd_status(args, save: Path) -> None:
    found = probe(save)
    if not found:
        print("wks-0417 is not running.")
        return
    info, w = found
    print(f"wks-0417 is up: pid {info['pid']}, port {info['port']}. "
          f"In there it is day {w['day']}, {w['clock']}.")
    if info.get("ssh_port"):
        from .sshd import key_files
        print(f"ssh: ssh -p {info['ssh_port']} -i \"{key_files(save).client}\" pdunn@127.0.0.1")


def cmd_world(args, save: Path) -> None:
    import json

    from .world import World, check_pack

    pack = None
    if args.action in ("check", "apply"):
        if not args.pack:
            raise SystemExit(f"usage: python -m os_e_man world {args.action} PACK.json")
        pack = Path(args.pack).read_text(encoding="utf-8")
    found = probe(save)
    if found:
        info = found[0]

        async def _go():
            conn, _ = await hello(info["port"], info["token"], role="director")
            await conn.send({"op": args.action, **({"pack": pack} if pack is not None else {})})
            msg = await conn.recv()
            await conn.close()
            return msg

        msg = asyncio.run(_go()) or {}
        if args.action == "digest":
            print(json.dumps(msg.get("digest"), indent=1, ensure_ascii=False))
            return
    else:
        # the world is down: work on its folder directly (no digest without a running world)
        if args.action == "digest":
            raise SystemExit("wks-0417 is not running; the digest needs a live world.")
        world = World(save.parent / "world")
        rep = check_pack(pack, world) if args.action == "check" else world.apply(pack)
        msg = rep.to_dict()
    verb = {"check": "would apply", "apply": "applied"}[args.action]
    print(f"pack {msg.get('id')}: " + (verb if msg.get("ok") else "REJECTED"))
    for e in msg.get("errors", []):
        print(f"  dropped  {e}")
    for d in msg.get("drift", []):
        print(f"  drift    {d}")
    if not msg.get("ok"):
        raise SystemExit(1)


def cmd_director(args, save: Path) -> None:
    from .director import LocalLink, ServerLink, SplitModel, make_model, run_ahead, run_once

    model = make_model(args.model, args.model_name, args.base_url)
    if args.plan_model:
        model = SplitModel(make_model(args.plan_model, args.plan_model_name), model)
    transcripts = runtime_dir(save) / "director"

    def show(res) -> None:
        print(f"director ({model.name}): day {res.day}, pack {res.pack_id}: {res.status}")
        for line in res.log:
            print(f"  note     {line}")
        for e in res.report.get("errors", []):
            print(f"  dropped  {e}")
        for d in res.report.get("drift", []):
            print(f"  drift    {d}")

    async def with_link(fn):
        found = probe(save)
        if found:
            conn, _ = await hello(found[0]["port"], found[0]["token"], role="director")
            try:
                return await fn(ServerLink(conn))
            finally:
                await conn.close()
        from .game import Game
        if not save.exists():
            raise SystemExit("os_e_man: no save yet. Connect once first.")
        return await fn(LocalLink(Game.load_or_new(save), persist=False))

    async def one(link):
        return [await run_once(link, model, dry_run=args.dry_run, transcript_dir=transcripts)]

    async def ahead(link):
        return await run_ahead(link, model, days=args.days, budget=args.budget,
                               dry_run=args.dry_run, transcript_dir=transcripts)

    async def watch_pass(link):
        # nobody at the keyboard: build out the days ahead. Someone playing: just keep today written.
        away = not (await link.digest()).get("players")
        return await (ahead(link) if away else one(link))

    if args.action in ("once", "ahead"):
        for res in asyncio.run(with_link(one if args.action == "once" else ahead)):
            show(res)
        return
    print(f"director ({model.name}) watching wks-0417 every {args.every}s; writes up to "
          f"{args.days} days ahead while nobody is connected. Ctrl-C to stop.")
    try:
        while True:
            for res in asyncio.run(with_link(watch_pass)):
                if res.status != "skipped" or any(x.startswith("budget") for x in res.log):
                    show(res)
            time.sleep(args.every)
    except KeyboardInterrupt:
        print("director: stopped.")


def main() -> None:
    ap = argparse.ArgumentParser(prog="os_e_man", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    from . import __version__
    ap.add_argument("--version", action="version", version=f"os_e_man {__version__}")
    ap.add_argument("--save", type=Path, default=None, help="save file path")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("connect", help="connect to the world (default)")
    b = sub.add_parser("boot", help="start the world")
    b.add_argument("--foreground", action="store_true", help="run in this console")
    b.add_argument("--new", action="store_true", help="start a new game")
    sub.add_parser("stop", help="save and stop the world")
    sub.add_parser("status", help="show whether the world is running")
    w = sub.add_parser("world", help="read or write the world from outside")
    w.add_argument("action", choices=["digest", "check", "apply"])
    w.add_argument("pack", nargs="?", help="content pack JSON file (check/apply)")
    d = sub.add_parser("director", help="write the world from outside (digest, plan, pack)")
    d.add_argument("action", nargs="?", default="once", choices=["once", "ahead", "watch"])
    d.add_argument("--days", type=int, default=3, help="ahead/watch: days to write ahead")
    d.add_argument("--budget", type=int, default=40, help="ahead/watch: max model calls per pass")
    d.add_argument("--model", default="fake", choices=["fake", "groq", "local"],
                   help="director model (default: fake)")
    d.add_argument("--model-name", default=None,
                   help="model id at the endpoint (groq default: openai/gpt-oss-120b)")
    d.add_argument("--base-url", default=None, help="override the OpenAI-compatible endpoint")
    d.add_argument("--plan-model", default=None, choices=["fake", "groq", "local"],
                   help="a separate model for planning the day (plot, storylines, facts)")
    d.add_argument("--plan-model-name", default=None, help="model id for --plan-model")
    d.add_argument("--dry-run", action="store_true", help="check the pack, don't apply it")
    d.add_argument("--every", type=int, default=30, help="watch: seconds between looks")
    args = ap.parse_args()
    save = args.save or default_save_path()
    {"boot": cmd_boot, "stop": cmd_stop, "status": cmd_status, "world": cmd_world,
     "director": cmd_director}.get(args.cmd, cmd_connect)(args, save)


if __name__ == "__main__":
    main()
