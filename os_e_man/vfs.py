"""A small in-memory filesystem built from content/fs plus files the player writes."""

from __future__ import annotations

import posixpath
from pathlib import Path

from . import content
from .state import GameState

FS_ROOT = content.ROOT / "fs"


def _load_shipped() -> dict[str, str]:
    files: dict[str, str] = {}
    for p in FS_ROOT.rglob("*"):
        if p.is_file():
            rel = "/" + p.relative_to(FS_ROOT).as_posix()
            files[rel] = p.read_text(encoding="utf-8")
    return files


_SHIPPED: dict[str, str] | None = None


def shipped() -> dict[str, str]:
    global _SHIPPED
    if _SHIPPED is None:
        _SHIPPED = _load_shipped()
    return _SHIPPED


class VFS:
    def __init__(self, state: GameState, world=None):
        self.state = state
        self.world = world
        self.perms: dict[str, str] = content.load("fs_perms.json")

    # ----- paths -----
    def home(self, user: str | None = None) -> str:
        user = user or self.state.user
        return "/srv/facilities" if user == "facilities" else f"/home/{user}"

    def resolve(self, path: str) -> str:
        if not path:
            return self.state.cwd
        if path == "~" or path.startswith("~/"):
            path = self.home() + path[1:]
        if not path.startswith("/"):
            path = posixpath.join(self.state.cwd, path)
        norm = posixpath.normpath(path)
        return "/" if norm in ("/", "//") else norm

    @property
    def files(self) -> dict[str, str]:
        merged = dict(shipped())
        if self.world is not None:
            merged.update(self.world.files)
        merged.update(self.state.user_files)
        return merged

    def is_file(self, path: str) -> bool:
        return path in self.files

    def is_dir(self, path: str) -> bool:
        if path == "/":
            return True
        prefix = path.rstrip("/") + "/"
        return any(f.startswith(prefix) for f in self.files)

    def exists(self, path: str) -> bool:
        return self.is_file(path) or self.is_dir(path)

    # ----- permissions -----
    def owner_of(self, path: str) -> str | None:
        best = None
        for prefix, owner in self.perms.items():
            if path == prefix or path.startswith(prefix.rstrip("/") + "/"):
                if best is None or len(prefix) > len(best[0]):
                    best = (prefix, owner)
        return best[1] if best else None

    def can_read(self, path: str) -> bool:
        owner = self.owner_of(path)
        return owner is None or owner == self.state.user

    def can_write(self, path: str) -> bool:
        home = self.home()
        return path.startswith(home + "/") or path.startswith("/tmp/")

    # ----- operations -----
    def listdir(self, path: str, show_hidden: bool = False) -> list[str]:
        if not self.is_dir(path):
            raise NotADirectoryError(path)
        if not self.can_read(path):
            raise PermissionError(path)
        prefix = "/" if path == "/" else path.rstrip("/") + "/"
        names: set[str] = set()
        for f in self.files:
            if f.startswith(prefix):
                rest = f[len(prefix):]
                head, sep, _ = rest.partition("/")
                names.add(head + ("/" if sep else ""))
        if not show_hidden:
            names = {n for n in names if not n.startswith(".")}
        return sorted(names, key=lambda n: (not n.endswith("/"), n.lower()))

    def read(self, path: str) -> str:
        if self.is_dir(path):
            raise IsADirectoryError(path)
        if not self.is_file(path):
            raise FileNotFoundError(path)
        if not self.can_read(path):
            raise PermissionError(path)
        return self.files[path]

    def write(self, path: str, text: str) -> None:
        if not self.can_write(path):
            raise PermissionError(path)
        if self.is_dir(path):
            raise IsADirectoryError(path)
        self.state.user_files[path] = text

    def complete(self, partial: str) -> list[str]:
        """Path completions for tab-complete."""
        d, _, stem = partial.rpartition("/")
        base = self.resolve(d + "/" if d or partial.startswith("/") else ".")
        try:
            names = self.listdir(base, show_hidden=stem.startswith("."))
        except (OSError, NotADirectoryError):
            return []
        lead = (d + "/") if (d or partial.startswith("/")) else ""
        return [lead + n for n in names if n.startswith(stem)]
