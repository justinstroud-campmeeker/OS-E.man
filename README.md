# OS-E.man

An idle-style terminal game. You are Pat Dunn, a DevOps consultant at a faceless
consultancy, doing a mandatory SQL/Python refresher on "sanitized" client data.
It is not sanitized.

The world runs as its own little machine (`wks-0417`) in the background. You
log in to it over ssh from your own terminal; when you disconnect, the office keeps going.

## Install

You need:
- **Python 3.11+**. Check with `python --version`.
- **An ssh client.** Windows 10/11 has OpenSSH built in. If `ssh -V` fails, add "OpenSSH
  Client" under Settings > System > Optional features. macOS and Linux already have one.

From the project folder:

```powershell
python -m pip install .                # the game (asyncssh, rich)
python -m pip install ".[director]"    # optional: the LLM director (Groq or a local model)
```

Always use `python -m pip`, because on some machines bare `pip` installs into a different
Python. To play without installing, run `python -m pip install asyncssh rich` and launch from
the project folder.

The first launch creates `%APPDATA%\OS-E.man\` (on macOS/Linux, `~/.config/OS-E.man/`) with
your save and the game's own ssh keys. Nothing else on your machine is touched.

## Run

```powershell
python -m os_e_man                     # log in over ssh (boots the world if it isn't running)
```

| Command | What it does |
|---|---|
| `python -m os_e_man` | Log in (runs your system `ssh`). Boots the world first if needed |
| `python -m os_e_man status` | Is it up? What day/time is it in there? Prints the raw `ssh` command too |
| `python -m os_e_man stop` | Save and shut the world down |
| `python -m os_e_man boot --new` | Start over (stop the world first) |
| `python -m os_e_man boot --foreground` | Run the server in this console, for debugging |

In game: `quit` (or Ctrl+D at an empty prompt) disconnects and leaves the world running;
`shutdown` stops it. Coworker chat appears between prompts; `mesg n` silences it.

`python -m os_e_man` uses Windows' built-in OpenSSH client (`ssh.exe`; if it's missing,
add "OpenSSH Client" under Settings > System > Optional features). Any ssh client works:
log in as `pdunn` on 127.0.0.1, port 2222, with the key `%APPDATA%\OS-E.man\id_ed25519`.

Time runs at one game minute per second while you're active, slower after five minutes
without input, and one minute per 20 seconds while nobody is connected. While
you're away the day holds just before 17:00, so the next day waits for you.

Files live in `%APPDATA%\OS-E.man\`: `save.json`, `server.json` (ports + session token while
running), `server.log`, and the game's own ssh keys (`ssh_host_ed25519_key`, `id_ed25519`,
`known_hosts`). Your `~/.ssh` is never touched. The server only listens on 127.0.0.1.

## Play
Start with `emmy`, then `train`. `help` and `man intro` for everything else.

## Writing the world from outside

Content packs add people, mail, chat, omens, files and hosts without touching the code:
`python -m os_e_man world check PACK.json`, then `world apply PACK.json`. See
`docs/director.md` and `examples/packs/`.

The director writes packs for you with an LLM (install the `director` extra first):

```powershell
python -m os_e_man director --model fake                 # canned content, no model needed
$env:GROQ_API_KEY = "..."                                # free key from console.groq.com
python -m os_e_man director ahead --model groq --days 3  # write the next 3 days
python -m os_e_man director watch --model groq           # keep writing while you're away
python -m os_e_man director --model local --model-name <id>   # LM Studio on 127.0.0.1:1234
```

With Groq, the prompts (the fictional world state and your recent in-game commands) are
sent to Groq's servers. A local model keeps everything on your machine. Add `--dry-run` to
check a pack without applying it.

## Develop

```powershell
python -m pip install -e .[dev]
python -m pytest
```

Layout: `game.py` is the game core (no UI), `server.py` owns the world and the clock,
`sshd.py` is the ssh front end, `protocol.py` is the JSON-lines control port (status/stop/tests).
Writing content? Read `os_e_man/content/STYLE.md` first.
