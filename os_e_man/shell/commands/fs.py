"""Filesystem commands: ls, cd, pwd, cat, bledit."""

from __future__ import annotations

from ..crab import command


def _err(out, cmd, path, e):
    msg = {
        FileNotFoundError: "No such file or directory",
        PermissionError: "Permission denied",
        IsADirectoryError: "Is a directory",
        NotADirectoryError: "Not a directory",
    }.get(type(e), str(e))
    out(f"{cmd}: {path}: {msg}", "err")


@command("ls", "list directory contents")
def ls(game, args, out):
    show_all = any(a in ("-a", "-la", "-al") for a in args)
    paths = [a for a in args if not a.startswith("-")] or ["."]
    for p in paths:
        path = game.vfs.resolve(p)
        if game.vfs.is_file(path):
            out(p)
            continue
        try:
            names = game.vfs.listdir(path, show_hidden=show_all)
        except (OSError, NotADirectoryError) as e:
            _err(out, "ls", p, e)
            continue
        if show_all:
            game.poke(f"ls:{path}")
            names = ["./", "../"] + names
        if len(paths) > 1:
            out(f"{p}:", "head")
        out("  ".join(names) if names else "")


@command("cd", "change directory")
def cd(game, args, out):
    target = game.vfs.resolve(args[0] if args else "~")
    if not game.vfs.is_dir(target):
        out(f"cd: {args[0] if args else '~'}: No such file or directory", "err")
    elif not game.vfs.can_read(target):
        out(f"cd: {args[0]}: Permission denied", "err")
    else:
        game.state.cwd = target


@command("pwd", "print working directory")
def pwd(game, args, out):
    out(game.state.cwd)


@command("cat", "print files")
def cat(game, args, out):
    if not args:
        out("usage: cat FILE...", "err")
        return
    for p in args:
        path = game.vfs.resolve(p)
        try:
            out(game.vfs.read(path).rstrip("\n"))
        except OSError as e:
            _err(out, "cat", p, e)
            continue
        game.poke(f"cat:{path}")


@command("bledit", "edit a text file (a bit like pico, but less)")
def bledit(game, args, out):
    from ...game import EditRequest

    if not args:
        out("usage: bledit FILE", "err")
        return
    path = game.vfs.resolve(args[0])
    if not game.vfs.can_write(path):
        out(f"bledit: {args[0]}: read-only (you can write under ~ and /tmp)", "err")
        return
    try:
        text = game.vfs.read(path) if game.vfs.is_file(path) else ""
    except OSError as e:
        _err(out, "bledit", args[0], e)
        return

    def save(new_text, o):
        game.vfs.write(path, new_text)
        o(f"bledit: wrote {len(new_text.splitlines())} lines to {path}", "ok")

    game.requests.append(EditRequest(f"bledit — {path}", text, save))
