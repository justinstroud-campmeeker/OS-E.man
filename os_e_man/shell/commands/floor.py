"""floorplan: the Office Services floor plan for level 3, drawn live from the office's state
(badge door modes, room bookings). Past a certain point it shows a room that isn't there."""

from __future__ import annotations

from ..crab import command

PLAN = """\
+--------------+------------+-----------+------------+-----------+
|              |            |           |            |           |
|   BIG CONF   |  AQUARIUM  |  PHONE 2  |  KITCHEN   | SERVER RM |
|{bc:^14}|{aq:^12}|{pb:^11}|            |           |
+-----{dB}-------+-----{dA}-----+----==-----+-----{dK}-----+----{dS}-----+
|                                                   +------------+
|   [ ][ ][ ][ ]   [ ][ ][ ][ ]   [ ][ ][ ][ ]      |  BOILER RM |
|   [ ][ ][ ][ ]   [ ][ ][P][ ]   [ ][ ][ ][ ]      |{bo:^12}|
|   [ ][ ][ ][ ]   [ ][ ][k][ ]   [ ][ ][ ][ ]      +-----==-----+
{x1}
{x2}
{x3}
|   [ ][ ][ ][ ]   [ ][ ][ ][ ]                       LIFTS  [=] |
+------------------------------------------------{dL}--------------+
                                                 LOBBY-EAST"""

ROOM = ("|                                 +--------+                     |",
        "|   [ ][ ][ ][ ]   [ ][ ][ ][ ]   |  3.14  |                     |",
        "|                                 +--------+                     |")
NO_ROOM = ("|                                                                |",
           "|   [ ][ ][ ][ ]   [ ][ ][ ][ ]                                  |",
           "|                                                                |")
DOOR = {"locked": "##", "unlocked": "//"}


def render(game) -> list[str]:
    st = game.state
    doors = st.badge.get("doors", {})
    rooms = st.facil.get("rooms", {})

    def d(name):
        return DOOR.get(doors.get(name, ""), "==")

    def booked(room, width):
        title = rooms.get(room, "")
        return title[:width - 2] if title else ""

    x = ROOM if st.mystique >= 3 else NO_ROOM
    return PLAN.format(
        bc=booked("Big Conf", 14), aq=booked("Aquarium", 12), pb=booked("Phone Booth 2", 11),
        bo=booked("Boiler Room", 12),
        dB=d("3F-BIGCONF"), dA=d("3F-AQUARIUM"), dK=d("3F-KITCHEN"), dS=d("SERVER-RM"),
        dL=d("LOBBY-EAST"), x1=x[0], x2=x[1], x3=x[2]).splitlines()


@command("floorplan", "Office Services floor plan, level 3", aliases=("fp",))
def floorplan(game, args, out):
    out("HPCG DUNMORE, LEVEL 3   floor plan rev. 2019-03 (Office Services)", "head")
    for line in render(game):
        out(line)
    out("[P] you  [k] kev  == door  ## locked  // held open   BIKE-STORE: ground floor", "dim")
    game.poke("floorplan")
    if game.state.mystique >= 3:
        game.poke("floorplan:3.14")
    if game.state.mystique >= 6:
        out("Room 3.14 has no door. Office Services has no record of it. Please do not book it.", "dim")
