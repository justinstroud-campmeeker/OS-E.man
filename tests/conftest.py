import random

import pytest

from os_e_man.game import Game


@pytest.fixture
def game(tmp_path):
    random.seed(0)
    return Game(save_path=tmp_path / "save.json")


def run(game, line):
    return [t.plain for t in game.execute(line)]


@pytest.fixture
def sh(game):
    return lambda line: run(game, line)
