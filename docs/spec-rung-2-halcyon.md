# Tech Spec: Rung 2: Halcyon Building Management

## 1. Overview & Business Goal
* **Feature Slug:** `rung-2-halcyon-bms`
* **Target Git Branch:** `feat/rung-2-halcyon-bms`
* **Objective:** Add the third rung of the influence ladder, so the player's reach grows from
  doors (badging) to the whole building (lights, lifts, temperature zones). Like rungs 0 and 1,
  it has two routes in, so a demotion from this rung is recovered through a different task
  rather than a repeat.

Background: read `os_e_man/levers.py` (framework), `os_e_man/content/levers.json` (rungs 0–1
as the pattern), `os_e_man/content/STYLE.md` (voice) and the "simulation boundary" section of
`CLAUDE.md`. Every mechanic is fiction inside the game. No real building-management
protocols, no real techniques.

## 2. Scope & File Boundaries
* **Files to Create:**
  * `os_e_man/content/man/bms.txt` (man page, same format as `man/badge.txt`)
  * `tests/test_rung2.py`
* **Files to Modify:**
  * `os_e_man/content/levers.json`: add rung `{"rank": 2, "access": "bms", ...}` and routes
    `bms_tech_badge`, `bms_tenant_portal` (section 5). Do not edit existing routes.
  * `os_e_man/content/omens.json`: append 3 omens of `kind: "bms"`. Append only.
  * `os_e_man/content/web.json`: add page `status.halcyon-hvac.example/tenant` and two
    addenda on `minutes.lattice-board.example`. Do not change existing page bodies.
  * `os_e_man/shell/commands/tools.py`: add the `bms` command; add a `badge assign`
    subcommand inside function `badge` only.
  * `os_e_man/state.py`: add exactly one field, `bms: dict = field(default_factory=dict)`.
  * `CLAUDE.md`, `docs/director.md`: one line each noting rung 2 exists.
* **Files NOT to Touch (Forbidden):**
  * `os_e_man/levers.py` (the framework must already support this; if it doesn't, stop and
    report what's missing rather than changing it)
  * `os_e_man/world.py`, `os_e_man/director.py` (pack checker and director)
  * `os_e_man/sshd.py`, `os_e_man/session.py`, `os_e_man/server.py` (transport)
  * `os_e_man/content/pos_db.sql`, `os_e_man/content/fs/**` (canon files)
  * The player's runtime folder `%APPDATA%\OS-E.man\` (never write to the real save)

## 3. Functional Requirements (Pass/Fail Criteria)
* With `"badging"` in `state.access`, `badge log` **must** include a line for badge holder
  `halcyon-tech` (shown as `Halcyon Tech`) entering `SERVER-RM` at `07:10`. This is the ghost for
  route `bms_tech_badge`.
* `badge assign halcyon-tech` **must** call `game.levers.grant("bms_tech_badge", out)`. On
  success `"bms"` is in `state.access`, `state.routes_used["bms"] == "bms_tech_badge"`, and the
  output contains the route's `granted` text.
* `webble status.halcyon-hvac.example/tenant` **must** grant route `bms_tenant_portal` only
  when that route is open (`route_burned:bms_tech_badge` set, `"facilities"` in access) and
  `state.user == "facilities"`. Otherwise it prints `Tenant portal: sign-in required
  (Office Services account).` and grants nothing.
* The `bms` command **must** be registered with `requires="bms"` so it's hidden from `help`
  until granted, and support exactly:
  * `bms` / `bms status`: floors 2–4 with lights state, zone setpoint (°F), and lifts A/B.
  * `bms lights FLOOR on|off|dim` (FLOOR is 2, 3 or 4)
  * `bms zone FLOOR DEGF` (60–80 inclusive)
  * `bms lift A|B hold|release`
  Each successful change **must** persist in `state.bms` and call
  `game.omens.apply("bms", "<sub> <args joined by space>", out)`.
* The 3 new omens **must** match `"lights 3 off"`, `"lift a hold"` and `"zone 4 60"`, each with
  2 chat reactions in canon voice. Their `exposure` values must sum to at least 6, so heavy
  rung-2 use reaches the warning ladder.
* Demotion while holding `bms` **must** remove only `"bms"` (badging and facilities stay) and
  burn the route used. `levers.py` already does this; test it.
* Each route **must** have 2 hints (`file` first, then `glimpse`), delivered by the existing
  nightly `Levers.nudge()`.
* The Board minutes **must** show addendum `41-D` after `route:bms_tech_badge` and `41-E` after
  `route:bms_tenant_portal`.

## 4. Edge Cases & Failure States
* **Empty State:** `state.bms` empty (fresh grant or old save): `bms status` shows defaults:
  lights `on`, zones `70`, lifts `in service`. Saves without the `bms` field **must** load
  (`GameState.from_dict` defaults it).
* **Permission/Auth Error:** no `bms` access: `bms` is "command not found" (existing crab
  behaviour for `requires`). `badge assign` with route burned or `bms` already held:
  `Tallyho: role assignment rejected (HAL-SEC-12).`, with no grant.
* **Invalid input:** floor not in 2–4, setpoint outside 60–80, unknown lift, or bad verb: one
  `usage: ...` or range error line in style `err`, no state change, no omen.
* **Both routes burned:** `bms` can't be regained in this version. Expected, and must not
  crash. Note it in the PR as follow-up (route 3).
* **Wrong account:** the tenant portal visited as `pdunn` gets the sign-in-required line and
  does not set any flag.

## 5. Data Model & API Contract (If Applicable)
* **levers.json additions:**
  ```json
  {"rank": 2, "access": "bms", "name": "the Halcyon building console"}
  ```
  ```json
  {"id": "bms_tech_badge", "rung": "bms", "requires": {"flag": "route:badge_portal"},
   "hints": [{"kind": "file", "path": "/tmp/.lsb-0043", "text": "..."},
             {"kind": "glimpse", "text": "badge assign halcyon-tech"}],
   "granted": "Halcyon BMS: technician role attached to your badge. Console: `bms`.",
   "burn": "Tallyho: role assignments frozen for this tenant (HAL-SEC-12)."}
  ```
  ```json
  {"id": "bms_tenant_portal", "rung": "bms",
   "requires": {"flag": "route_burned:bms_tech_badge"},
   "hints": [{"kind": "file", "path": "/tmp/.lsb-0044", "text": "..."},
             {"kind": "glimpse", "text": "status.halcyon-hvac.example/tenant"}],
   "granted": "Halcyon tenant portal: Office Services signed in. Console: `bms`.",
   "burn": "Halcyon: tenant portal access suspended pending review (HAL-77120-R)."}
  ```
  Note: `bms_tech_badge` requires `route:badge_portal` *or* `route:badge_support`. The `when`
  format has no OR, so use `{"flag": "got_badging"}` and set that flag in both badge routes'
  grant path (in `tools.py` / webble `grant` handling: on any successful badging grant,
  `state.set_flag("got_badging")`).
* **state.bms shape:**
  ```json
  {"lights": {"2": "on", "3": "off", "4": "dim"}, "zones": {"2": 70, "3": 70, "4": 64},
   "lifts": {"A": "in service", "B": "held"}}
  ```

## 6. Verification & Test Plan
* **Commands to Run:**
  * Unit tests: `python -m pytest tests/test_rung2.py -q`
  * Full suite (must stay green): `python -m pytest -q`
  * No linter is configured; at minimum `python -m compileall -q os_e_man` must succeed.
* **Tests `tests/test_rung2.py` must cover:** ghost in `badge log`; grant via `badge assign`;
  each `bms` subcommand changes state and fires its omen; invalid input changes nothing;
  demotion from `bms` keeps lower rungs and opens `bms_tenant_portal`; tenant portal refuses
  `pdunn` and grants as `facilities`; nightly hints arrive in order; addenda 41-D/41-E appear;
  a save dict without `bms` loads.
* **Expected Evidence Required in Final Output:**
  * The pytest summary line for both commands (e.g. `N passed`) and the new test count.
  * A manual run on a scratch save (`python -m os_e_man --save <scratch>\save.json`, never the
    real one): gain badging, `badge log`, `badge assign halcyon-tech`, `bms lights 3 off`,
    then tick to see the chat reactions. Paste the transcript.
