# OS-E.man

An idle-style, satirical terminal game. The player is Pat Dunn (pdunn, they/them), a DevOps
consultant at a faceless consultancy (HPCG). It starts as a mandatory SQL/Python training course
and slowly becomes a story about quiet, anonymous influence over a fictional office, and later a
fictional world. The tone is realistic corporate satire written like SCP-style records.
`game-spec.md` is the original design spec.

## The simulation boundary (design rules)
The game is fiction, and it runs entirely inside its own simulated operating system.
- Everything that resembles hacking or social engineering exists only inside the simulation:
  accounts, passwords, hosts, files, tools and "leaked" data. None of it works outside the game,
  and in-game commands are not real tools. They may look a little like real ones in sequence,
  but the methods don't carry over to real systems at all.
- NPCs, companies and organisations are fictional. Interacting with them has no effect outside
  the game.
- Never implement real techniques against real systems: no real exploits, credential attacks
  or malware behaviour. No network scanning or access beyond the game's own fake hosts. No
  touching the player's real filesystem beyond the game's save/runtime folder.
- The world server listens only on 127.0.0.1 and only serves the game.
- Game mechanics are abstracted: a "password" is a story clue that unlocks a fictional
  account, and the player's power is told through in-world documents and NPC reactions.

## Architecture
- `os_e_man/game.py`: the game core, with no UI. It takes `execute(line)` and `tick()` and
  returns rich `Text` lines. It sets `requests` (editor/clear/quit/shutdown) and `pending`
  (password prompts).
- `os_e_man/server.py`: `WorldServer` owns the Game and the clock, and keeps running in the
  background. It also runs a JSON-lines control port (`protocol.py`) used by the CLI and tests.
- `os_e_man/session.py`: the transport-neutral `Terminal` / `PlayerSession` layer. Every
  front end plugs in through `WorldServer.attach()`. `Terminal.local_echo` tells the game
  not to echo typed lines back.
- `os_e_man/sshd.py`: the player front end, an asyncssh door on 127.0.0.1:2222 (falls back
  to a free port). Key-only auth as `pdunn`, with keys generated in the runtime folder
  (client key ACL'd owner-only so Windows OpenSSH accepts it). `SshTerminal` does raw-mode
  line editing (history, tab completion, masked passwords), runs bledit on the alternate
  screen, and prints chat between prompts (redrawing the half-typed line; held while
  bledit is open). `python -m os_e_man` just runs the system `ssh` with `ssh_command()`.
- `os_e_man/term/`: terminal building blocks used by sshd. `editor.py` is a pico-style
  full-screen editor, `keys.py` parses key sequences, `ansi.py` renders `Text` to ANSI.
- `os_e_man/shell/`: the `crab` shell. `crab.py` handles parsing, the registry, pipes into grep
  and completion. `commands/*.py` holds the commands.
- `os_e_man/vfs.py`: the fake filesystem (shipped files in `content/fs/` plus player files).
- `os_e_man/training/`: the EER-26 course. `snek.py` is the sandboxed Python subset,
  `sqlrunner.py` is the read-only in-memory SQLite replica, `engine.py` handles grading.
- `os_e_man/world.py`: the world outside the machine. `World` merges canon content with
  content packs from `<runtime>/world/*.json` (Events/Omens/VFS/net read from it, live).
  `check_pack()` drops breakage and absorbs drift; see `docs/director.md`. Directors connect
  to the control port with `role: "director"` (digest/check/apply, never a player session).
- `os_e_man/director.py`: the director loop (`run_once`: digest → plan → slot writers → pack),
  a `Model` interface (`complete(task, prompt) -> str`), `FakeModel`, and Local/Server links.
- `os_e_man/glimpses.py`: after a run of commands with no progress, rarely (once a day at
  most) the screen flickers and an address shows (`content/glimpses.json`). It's put into shell
  history and `~/todo.txt` and becomes a quest: `webble` it (`content/web.json`, `.example`
  domains only) or `emmy send` it (replies are emails gated on `glimpse:<id>:done`).
- `os_e_man/levers.py` + `content/levers.json`: the ladder of influence. Rungs (facilities,
  badging, ...) each have several routes; a route opens on `requires`, drops its ghost file,
  and the Lattice Board nudges a stuck player one hint per night (file or command glimpse).
  Exposure climbs a warning ladder; at the top the player is demoted: they lose the top rung
  and its route is burned (`route_burned:<id>`), so getting back takes a different route.
- `os_e_man/events.py`, `omens.py`: emails, chat beats, ambient chatter, and omens
  (office-logistics actions that raise mystique/exposure).
- `os_e_man/content/`: all story content as data (JSON, SQL, text files, man pages). Read
  `content/STYLE.md` before writing content.

## Design decisions so far
- The world runs as its own background server. When nobody is connected the clock slows down
  and the day holds at 16:59, so the next day waits for the player.
- **Front end:** a plain, Unix-familiar terminal: real `ssh` from the player's own terminal
  (Textual was removed). Chat arrives between prompts, Unix-style (`write(1)`-style DMs,
  one-line channel notices, `mesg y/n`, stored as the `mesg_n` flag). Login banner with
  "You have new mail.", a full-screen pico-style editor, status in the terminal title.
- Meters (curiosity, mystique, exposure) stay hidden: they're felt through redactions thinning
  out and NPC behaviour, never shown as numbers.
- The power curve starts at office scale (coffee pods, rooms, thermostat) and goes up one rung
  per milestone.
- The LLM director lives outside the VM and must be local and free (LM Studio/Ollama on
  127.0.0.1), producing content packs in the existing schemas, with hand-written content as
  the fallback. It never emits code.
- **Hallucinations are a feature.** When a writer invents people, hosts, channels or events,
  the world absorbs them (stub records, `/var/log/continuity.log`) instead of rejecting them.
  Only breakage and anything outside the simulation boundary is dropped.

## Status / next up
1. Done: the ssh front end (`sshd.py`, tests in `tests/test_sshd.py`, including one that
   drives the real system `ssh.exe`).
2. The director (`docs/director.md`): the overlay, checker, director door, `world` CLI and the
   `director` command (`director.py`, texture slots only) are done, with `--model fake|groq|local`
   (`ChatModel` = any OpenAI-compatible endpoint; Groq is the user's chosen first real model,
   free tier, `GROQ_API_KEY`). `director ahead`/`watch` write several days ahead while the
   player is away: branches on player state (`*_below` conditions, `poke:` flags), storylines
   (`threads`) carried between days, duplicate chat lines dropped. Next: a pending/review step,
   then omens/files authority.
3. Later "VM" steps: machines with their own disk images, users and permissions; programs on
   the PATH and a snek system API; cron, daemons and logs; networking between machines.

## Working here
- Windows. Use `python` (3.11) and always `python -m pip`, because bare `pip` points at a
  different Python.
- Run: `python -m os_e_man` (connects, auto-boots the world). `python -m os_e_man status|stop`.
- Test: `python -m pytest`. Keep the suite green, and add tests with each change.
- Version: semver, single source `os_e_man/__init__.py` (`pyproject.toml` reads it). Bump it
  and add a `CHANGELOG.md` entry with each release: patch for fixes and content, minor for
  new systems.
- Runtime files: `%APPDATA%\OS-E.man\` (save.json, server.json, server.log). The user has a
  real save in progress, so don't break save compatibility; migrate instead. Backup:
  `save.v1-backup.json`.
