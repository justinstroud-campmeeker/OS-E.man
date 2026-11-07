"""bledit: a small pico/nano-style full-screen editor drawn with ANSI escapes.

Pure logic plus a render() that returns a full-frame ANSI string, so it can be
driven over any byte stream (an ssh channel) and tested without a terminal.

Semantics follow nano: ^O writes out (and you stay in the editor), ^X exits,
asking to save if the buffer was modified since the last write. The editor's
result is the last text written out, or None if nothing was ever written.
"""

from __future__ import annotations

ENTER_ALT = "\x1b[?1049h\x1b[H\x1b[2J"
LEAVE_ALT = "\x1b[?1049l"
GUTTER = 5  # "123 " plus a space


class Editor:
    def __init__(self, title: str, text: str, width: int = 80, height: int = 24):
        self.title = title
        self.lines = text.split("\n") if text else [""]
        self.row = self.col = 0
        self.top = self.left = 0
        self.width, self.height = width, height
        self.modified = False
        self.written: str | None = None
        self.confirming = False
        self.message = ""
        self.cutbuf: list[str] = []
        self.done = False

    # ----- geometry -----
    @property
    def body_rows(self) -> int:
        return max(1, self.height - 3)  # title, status, help

    @property
    def text_cols(self) -> int:
        return max(10, self.width - GUTTER)

    def resize(self, width: int, height: int) -> None:
        self.width, self.height = width, height
        self._scroll()

    @property
    def text(self) -> str:
        return "\n".join(self.lines)

    @property
    def result(self) -> str | None:
        return self.written

    # ----- input -----
    def handle(self, key: str) -> None:
        self.message = "" if not self.confirming else self.message
        if self.confirming:
            self._confirm(key)
            return
        handler = {
            "up": lambda: self._move(-1, 0), "down": lambda: self._move(1, 0),
            "left": self._left, "right": self._right,
            "home": self._home, "end": self._end, "ctrl-a": self._home, "ctrl-e": self._end,
            "pgup": lambda: self._move(-self.body_rows, 0), "pgdn": lambda: self._move(self.body_rows, 0),
            "enter": self._enter, "backspace": self._backspace, "delete": self._delete,
            "ctrl-d": self._delete, "tab": lambda: self._insert("    "),
            "ctrl-o": self._write, "ctrl-s": self._write, "ctrl-x": self._exit,
            "ctrl-k": self._cut, "ctrl-u": self._paste, "ctrl-c": self._cursor_pos,
        }.get(key)
        if handler:
            handler()
        elif len(key) == 1 and key.isprintable():
            self._insert(key)
        self._scroll()

    def _confirm(self, key: str) -> None:
        k = key.lower()
        if k == "y":
            self._write()
            self.done = True
        elif k == "n":
            self.done = True
        elif key in ("ctrl-c", "esc"):
            self.confirming = False
            self.message = "[ Cancelled ]"

    def _write(self) -> None:
        self.written = self.text
        self.modified = False
        n = len(self.lines)
        self.message = f"[ Wrote {n} line{'s' if n != 1 else ''} ]"

    def _exit(self) -> None:
        if self.modified:
            self.confirming = True
            self.message = "Save modified buffer?  Y Yes   N No   ^C Cancel"
        else:
            self.done = True

    def _cursor_pos(self) -> None:
        self.message = f"[ line {self.row + 1}/{len(self.lines)}, col {self.col + 1} ]"

    # ----- editing -----
    def _changed(self) -> None:
        self.modified = True

    def _insert(self, s: str) -> None:
        line = self.lines[self.row]
        self.lines[self.row] = line[:self.col] + s + line[self.col:]
        self.col += len(s)
        self._changed()

    def _enter(self) -> None:
        line = self.lines[self.row]
        indent = line[: len(line) - len(line.lstrip(" "))]
        indent = indent[: self.col]
        self.lines[self.row] = line[:self.col]
        self.lines.insert(self.row + 1, indent + line[self.col:])
        self.row += 1
        self.col = len(indent)
        self._changed()

    def _backspace(self) -> None:
        if self.col > 0:
            line = self.lines[self.row]
            self.lines[self.row] = line[:self.col - 1] + line[self.col:]
            self.col -= 1
            self._changed()
        elif self.row > 0:
            prev = self.lines[self.row - 1]
            self.lines[self.row - 1] = prev + self.lines.pop(self.row)
            self.row -= 1
            self.col = len(prev)
            self._changed()

    def _delete(self) -> None:
        line = self.lines[self.row]
        if self.col < len(line):
            self.lines[self.row] = line[:self.col] + line[self.col + 1:]
            self._changed()
        elif self.row + 1 < len(self.lines):
            self.lines[self.row] = line + self.lines.pop(self.row + 1)
            self._changed()

    def _cut(self) -> None:
        self.cutbuf = [self.lines[self.row]]
        if len(self.lines) > 1:
            self.lines.pop(self.row)
            self.row = min(self.row, len(self.lines) - 1)
        else:
            self.lines = [""]
        self.col = min(self.col, len(self.lines[self.row]))
        self._changed()

    def _paste(self) -> None:
        if not self.cutbuf:
            return
        for i, l in enumerate(self.cutbuf):
            self.lines.insert(self.row + i, l)
        self.row += len(self.cutbuf)
        self.col = 0
        self._changed()

    # ----- movement -----
    def _move(self, drow: int, dcol: int) -> None:
        self.row = max(0, min(len(self.lines) - 1, self.row + drow))
        self.col = min(self.col, len(self.lines[self.row]))

    def _left(self) -> None:
        if self.col > 0:
            self.col -= 1
        elif self.row > 0:
            self.row -= 1
            self.col = len(self.lines[self.row])

    def _right(self) -> None:
        if self.col < len(self.lines[self.row]):
            self.col += 1
        elif self.row + 1 < len(self.lines):
            self.row += 1
            self.col = 0

    def _home(self) -> None:
        self.col = 0

    def _end(self) -> None:
        self.col = len(self.lines[self.row])

    def _scroll(self) -> None:
        if self.row < self.top:
            self.top = self.row
        elif self.row >= self.top + self.body_rows:
            self.top = self.row - self.body_rows + 1
        if self.col < self.left:
            self.left = self.col
        elif self.col >= self.left + self.text_cols:
            self.left = self.col - self.text_cols + 1

    # ----- drawing -----
    def render(self) -> str:
        w = self.width
        out = ["\x1b[?25l"]
        head = f"  bledit 0.9   {self.title}"
        flag = "Modified  " if self.modified else ""
        head = head[: max(0, w - len(flag))].ljust(w - len(flag)) + flag
        out.append(f"\x1b[1;1H\x1b[7m{head[:w]}\x1b[0m")
        for i in range(self.body_rows):
            n = self.top + i
            out.append(f"\x1b[{i + 2};1H")
            if n < len(self.lines):
                seg = self.lines[n][self.left:self.left + self.text_cols]
                out.append(f"\x1b[2m{n + 1:>4} \x1b[0m{seg}")
            out.append("\x1b[K")
        status_row = self.body_rows + 2
        msg = self.message
        if msg:
            out.append(f"\x1b[{status_row};1H\x1b[K\x1b[7m{msg[:w]}\x1b[0m")
        else:
            out.append(f"\x1b[{status_row};1H\x1b[K")
        helpline = ("^O WriteOut   ^X Exit   ^K Cut Line   ^U Paste   ^C Cur Pos"
                    if not self.confirming else " Y Yes   N No   ^C Cancel")
        out.append(f"\x1b[{status_row + 1};1H\x1b[K\x1b[2m{helpline[:w]}\x1b[0m")
        if self.confirming:
            crow, ccol = status_row, min(w, len(msg) + 1)
        else:
            crow = self.row - self.top + 2
            ccol = GUTTER + (self.col - self.left) + 1
        out.append(f"\x1b[{crow};{ccol}H\x1b[?25h")
        return "".join(out)
