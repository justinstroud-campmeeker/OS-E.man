"""floorplan: an ASCII plan drawn from badge doors, bookings and mystique."""

from os_e_man.game import Game
from os_e_man.shell.commands.floor import render


def sh(game, line):
    return "\n".join(t.plain for t in game.execute(line))


def widths(lines):
    return {len(line) for line in lines[:-1]}           # the last line is the LOBBY-EAST label


def test_plan_is_rectangular_and_live(tmp_path):
    g = Game(save_path=tmp_path / "save.json")
    lines = render(g)
    assert widths(lines) == {66}
    assert "3.14" not in "\n".join(lines)
    g.state.badge.setdefault("doors", {})["3F-KITCHEN"] = "locked"
    g.state.facil["rooms"]["Aquarium"] = "QBR prep"
    g.state.mystique = 3
    lines = render(g)
    assert widths(lines) == {66}
    text = "\n".join(lines)
    assert "##" in text and "QBR prep" in text and "3.14" in text


def test_command_and_alias(tmp_path):
    g = Game(save_path=tmp_path / "save.json")
    assert "LEVEL 3" in sh(g, "floorplan") and "BOILER RM" in sh(g, "fp")
    g.state.mystique = 6
    assert "no record of it" in sh(g, "floorplan")
