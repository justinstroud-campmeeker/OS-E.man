"""snek: a heavily stripped-down Python for the training course.

This is a game sandbox, not a security boundary. Its job is to keep player code
from touching the real machine by accident and to make sure a stray infinite loop
can't hang the UI.
"""

from __future__ import annotations

import ast
import builtins
import sys
from dataclasses import dataclass, field

FILENAME = "<snek>"
MAX_OPS = 1_000_000
MAX_RANGE = 100_000

_SAFE_NAMES = [
    "abs", "all", "any", "bool", "chr", "dict", "divmod", "enumerate", "filter",
    "float", "int", "isinstance", "len", "list", "map", "max", "min", "ord",
    "reversed", "round", "set", "sorted", "str", "sum", "tuple", "zip",
    "ValueError", "TypeError", "KeyError", "IndexError", "Exception",
    "True", "False", "None",
]
_BANNED_ATTRS = {"format", "format_map", "mro"}


class SnekError(Exception):
    """Raised for code snek refuses to run, or that exceeded its budget."""


class SnekTimeout(SnekError):
    pass


def _limited_range(*args):
    r = range(*args)
    if len(r) > MAX_RANGE:
        raise SnekError(f"range() too large for snek (max {MAX_RANGE:,} items)")
    return r


def check(tree: ast.AST) -> None:
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            raise SnekError("snek: 'import' is disabled by policy SNK-4 (no external dependencies)")
        if isinstance(node, (ast.Global, ast.Nonlocal)):
            raise SnekError("snek: global/nonlocal are not supported")
        if isinstance(node, ast.Attribute) and (node.attr.startswith("_") or node.attr in _BANNED_ATTRS):
            raise SnekError(f"snek: attribute '{node.attr}' is not available")
        if isinstance(node, ast.Name) and node.id.startswith("__"):
            raise SnekError(f"snek: name '{node.id}' is not available")


@dataclass
class SnekResult:
    env: dict = field(default_factory=dict)
    output: list[str] = field(default_factory=list)
    error: str | None = None


class Snek:
    def __init__(self, max_ops: int = MAX_OPS):
        self.max_ops = max_ops
        self._count = 0
        self.output: list[str] = []

    def _builtins(self) -> dict:
        safe = {n: getattr(builtins, n) for n in _SAFE_NAMES}
        safe["range"] = _limited_range

        def _print(*args, sep=" ", end=""):
            self.output.append(sep.join(str(a) for a in args) + end)

        safe["print"] = _print
        return safe

    def _tracer(self, frame, event, arg):
        if frame.f_code.co_filename != FILENAME:
            return None
        if event == "call":
            # Count opcodes, not lines: `while True: pass` never emits a new line event.
            frame.f_trace_opcodes = True
            frame.f_trace_lines = False
        elif event == "opcode":
            self._count += 1
            if self._count > self.max_ops:
                raise SnekTimeout("snek: execution budget exceeded (infinite loop?)")
        return self._tracer

    def _guarded(self, fn, *args):
        self._count = 0
        old = sys.gettrace()
        sys.settrace(self._tracer)
        try:
            return fn(*args)
        finally:
            sys.settrace(old)

    def run(self, source: str) -> SnekResult:
        self.output = []
        result = SnekResult(output=self.output)
        try:
            tree = ast.parse(source, FILENAME)
            check(tree)
            code = compile(tree, FILENAME, "exec")
        except SyntaxError as e:
            result.error = f"SyntaxError: {e.msg} (line {e.lineno})"
            return result
        except SnekError as e:
            result.error = str(e)
            return result
        env: dict = {"__builtins__": self._builtins(), "__name__": "snek"}
        result.env = env
        try:
            self._guarded(exec, code, env)
        except SnekError as e:
            result.error = str(e)
        except Exception as e:  # player code errors are expected
            result.error = f"{type(e).__name__}: {e}"
        return result

    def call(self, fn, *args):
        """Call a function defined by snek code, under the same budget."""
        return self._guarded(fn, *args)
