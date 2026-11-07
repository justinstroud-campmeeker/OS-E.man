"""Decode raw terminal input (VT/xterm escape sequences) into key names."""

from __future__ import annotations

CSI_FINAL = {"A": "up", "B": "down", "C": "right", "D": "left", "H": "home", "F": "end"}
CSI_TILDE = {"1": "home", "2": "insert", "3": "delete", "4": "end", "5": "pgup", "6": "pgdn",
             "7": "home", "8": "end"}
CONTROL = {"\r": "enter", "\n": "enter", "\t": "tab", "\x7f": "backspace", "\x08": "backspace"}


class KeyParser:
    """Feed raw chunks in, get key names out. Holds incomplete escape sequences
    between chunks. Printable characters come back as themselves; control keys as
    'ctrl-x' style names."""

    def __init__(self):
        self._buf = ""

    def feed(self, data: str) -> list[str]:
        self._buf += data
        keys: list[str] = []
        i, buf = 0, self._buf
        while i < len(buf):
            ch = buf[i]
            if ch == "\x1b":
                if i + 1 >= len(buf):
                    break  # wait for more (or flush() if it was a lone Esc)
                nxt = buf[i + 1]
                if nxt in "[O":
                    j = i + 2
                    while j < len(buf) and not (buf[j].isalpha() or buf[j] == "~"):
                        j += 1
                    if j >= len(buf):
                        break  # incomplete sequence
                    body, final = buf[i + 2:j], buf[j]
                    if final == "~":
                        keys.append(CSI_TILDE.get(body.split(";")[0], "unknown"))
                    else:
                        keys.append(CSI_FINAL.get(final, "unknown"))
                    i = j + 1
                    continue
                keys.append("esc")
                i += 1
                continue
            if ch == "\r" and i + 1 < len(buf) and buf[i + 1] == "\n":
                keys.append("enter")
                i += 2
                continue
            if ch in CONTROL:
                keys.append(CONTROL[ch])
            elif ord(ch) < 32:
                keys.append("ctrl-" + chr(ord(ch) + 96))
            else:
                keys.append(ch)
            i += 1
        self._buf = buf[i:]
        return keys

    @property
    def pending(self) -> bool:
        """A lone Esc is waiting: call flush() if nothing follows soon."""
        return self._buf == ""

    def flush(self) -> list[str]:
        """Resolve a pending lone Esc."""
        if self._buf == "\x1b":
            self._buf = ""
            return ["esc"]
        return []
