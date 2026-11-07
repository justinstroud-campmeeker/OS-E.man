import time

import pytest

from os_e_man.training.snek import Snek


@pytest.mark.parametrize("src", [
    "import os",
    "from os import path",
    "x = ().__class__",
    "__import__('os')",
    "'{0.__class__}'.format(1)",
    "global x",
])
def test_rejects_escape_hatches(src):
    assert Snek().run(src).error


@pytest.mark.parametrize("src", [
    "while True: pass",
    "while True:\n    x = 1",
    "def f():\n    while 1: pass\nf()",
])
def test_stops_infinite_loops_fast(src):
    t = time.time()
    res = Snek().run(src)
    assert "budget" in res.error
    assert time.time() - t < 5


def test_no_open_or_eval():
    assert "NameError" in Snek().run("open('x')").error
    assert "NameError" in Snek().run("eval('1')").error


def test_huge_range_refused():
    assert "range" in Snek().run("sum(range(10**9))").error


def test_print_captured_and_functions_callable():
    s = Snek()
    res = s.run("def f(x):\n    return x * 2\nprint('hi', 3)")
    assert res.error is None
    assert res.output == ["hi 3"]
    assert s.call(res.env["f"], 21) == 42
