"""Read-only SQLite replica of the client's PoS reporting database."""

from __future__ import annotations

import random
import sqlite3
from dataclasses import dataclass, field

from .. import content

# Tables listed in the course material. Everything else is "not supposed to be there".
DOCUMENTED = {"stores", "products", "transactions", "employees"}

_ALLOWED = {
    sqlite3.SQLITE_SELECT,
    sqlite3.SQLITE_READ,
    sqlite3.SQLITE_FUNCTION,
    getattr(sqlite3, "SQLITE_RECURSIVE", 33),
}


class SQLDenied(Exception):
    pass


@dataclass
class QueryResult:
    columns: list[str] = field(default_factory=list)
    rows: list[tuple] = field(default_factory=list)
    tables: set[str] = field(default_factory=set)


def _seed_transactions(conn: sqlite3.Connection) -> None:
    rng = random.Random(5512)
    stores = [r[0] for r in conn.execute("SELECT store_id FROM stores")]
    products = [(s, p) for s, p in conn.execute("SELECT sku, price FROM products WHERE price > 0")]
    rows = []
    for i in range(1, 161):
        store = rng.choice(stores)
        sku, price = rng.choice(products)
        qty = rng.randint(1, 4)
        day = rng.randint(1, 5)
        hh, mm = rng.randint(7, 21), rng.randint(0, 59)
        rows.append((i, store, f"{rng.randint(1, 6):02d}", sku, qty,
                     round(price * qty, 2), f"2026-11-0{day}T{hh:02d}:{mm:02d}:00"))
    # Lane 4 at store 42. It isn't plugged in.
    rows.append((161, 42, "04", "IR-0091", 1, 0.00, "2026-11-03T03:33:00"))
    conn.executemany("INSERT INTO transactions VALUES (?,?,?,?,?,?,?)", rows)


class SQLRunner:
    def __init__(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.executescript(content.text("pos_db.sql"))
        _seed_transactions(self.conn)
        self.conn.commit()
        self._tables: set[str] = set()
        self._denied: str | None = None
        self.conn.set_authorizer(self._authorize)

    def _authorize(self, action, arg1, arg2, dbname, source):
        if action not in _ALLOWED:
            self._denied = "only SELECT is permitted on the training replica"
            return sqlite3.SQLITE_DENY
        if action == sqlite3.SQLITE_READ and arg1 and not arg1.startswith("sqlite_"):
            self._tables.add(arg1)
        return sqlite3.SQLITE_OK

    def table_names(self) -> list[str]:
        return [r[0] for r in self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]

    def schema(self, table: str) -> list[tuple[str, str]]:
        if table not in self.table_names():
            raise SQLDenied(f"no such table: {table}")
        cur = self.conn.execute(f"SELECT * FROM \"{table}\" LIMIT 0")
        return [(d[0], "") for d in cur.description]

    def query(self, sql: str) -> QueryResult:
        self._tables = set()
        self._denied = None
        try:
            cur = self.conn.execute(sql)
            rows = cur.fetchmany(500)
        except sqlite3.DatabaseError as e:
            raise SQLDenied(self._denied or str(e)) from None
        except sqlite3.Warning as e:  # e.g. multiple statements
            raise SQLDenied(str(e)) from None
        cols = [d[0] for d in (cur.description or [])]
        return QueryResult(columns=cols, rows=rows, tables=set(self._tables))


def normalize(rows: list[tuple], ordered: bool) -> list[tuple]:
    def norm(v):
        return round(v, 2) if isinstance(v, float) else v
    out = [tuple(norm(v) for v in r) for r in rows]
    return out if ordered else sorted(out, key=repr)


def _cell(v) -> str:
    return "NULL" if v is None else (f"{v:.2f}" if isinstance(v, float) else str(v))


def format_vertical(res: QueryResult, max_rows: int = 25) -> list[str]:
    """MySQL \\G-style output for rows too wide for a short terminal strip."""
    label_w = max(len(c) for c in res.columns)
    out = []
    for n, r in enumerate(res.rows[:max_rows], 1):
        out.append(f"*************************** {n}. row ***************************")
        for c, v in zip(res.columns, r):
            out.append(f"{c.rjust(label_w)}: {_cell(v)}")
    extra = len(res.rows) - min(len(res.rows), max_rows)
    out.append(f"({len(res.rows)} row{'s' if len(res.rows) != 1 else ''}"
               + (f", {extra} not shown" if extra > 0 else "") + ")")
    return out


def format_table(res: QueryResult, max_rows: int = 25, max_width: int = 100) -> list[str]:
    if not res.columns:
        return ["(no columns)"]
    shown = [[_cell(v) for v in r] for r in res.rows[:max_rows]]
    widths = [len(c) for c in res.columns]
    for r in shown:
        for i, c in enumerate(r):
            widths[i] = max(widths[i], _visible_len(c))
    if sum(widths) + 3 * len(widths) + 1 > max_width:
        return format_vertical(res, max_rows)
    line = "+" + "+".join("-" * (w + 2) for w in widths) + "+"
    out = [line, "| " + " | ".join(c.ljust(w) for c, w in zip(res.columns, widths)) + " |", line]
    for r in shown:
        out.append("| " + " | ".join(_ljust(c, w) for c, w in zip(r, widths)) + " |")
    out.append(line)
    extra = len(res.rows) - len(shown)
    out.append(f"({len(res.rows)} row{'s' if len(res.rows) != 1 else ''}"
               + (f", {extra} not shown" if extra > 0 else "") + ")")
    return out


# Redaction markup ([[R3:text]]) collapses to the inner text length when rendered,
# so table widths are measured on the visible text.
import re as _re
_RED = _re.compile(r"\[\[R\d+:(.*?)\]\]", _re.S)


def _visible_len(s: str) -> int:
    return len(_RED.sub(lambda m: m.group(1), s))


def _ljust(s: str, w: int) -> str:
    return s + " " * max(0, w - _visible_len(s))
