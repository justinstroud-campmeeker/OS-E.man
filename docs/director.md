# The director: writing the world from outside the machine

wks-0417 is the machine. The world it sits in (the office, the people, the network, tomorrow's
mail) can be written by something outside it: a local LLM "director", or a person with a text
editor. Both do it the same way: they read a **digest** of the world and send back a **content
pack** in the game's existing schemas. The game code stays the only thing that decides what
happens. The director only adds material for it to work with.

Code: `os_e_man/world.py` (overlay, checker, digest), the director door in `server.py`,
`python -m os_e_man world ...` in `__main__.py`, tests in `tests/test_world.py`.

## The door

The JSON control port (127.0.0.1, token from `server.json`). Say hello with
`{"op": "hello", "token": T, "role": "director"}`. A director connection never becomes a player
session, so it doesn't keep the clock running. Ops:

| op | reply | |
|---|---|---|
| `digest` | `{"ev": "digest", "digest": {...}}` | day, clock, access, hidden meters, flags, what the player poked, recent chat/mail/commands, people, channels, hosts, omen kinds, known flags, applied packs, recent anomalies |
| `check` + `pack` | `{"ev": "report", "ok", "id", "errors", "drift"}` | dry run |
| `apply` + `pack` | same | saves to `<runtime>/world/NNNN-<id>.json`, merges live |

`pack` may be a JSON object or a JSON string. From a shell: `python -m os_e_man world
digest | check PACK | apply PACK`. With the world down, `check`/`apply` work on the world folder
directly.

## Pack format

```json
{
  "id": "day-003-a",              // unique; re-applying the same id is refused
  "source": "director",           // optional, free text
  "note": "why this pack exists", // optional
  "people":  {"key": {"handle": "...", "name": "...", "role": "..."}},
  "emails":  [{"id", "when", "delay", "from", "subject", "body", "flag_on_deliver"}],
  "beats":   [{"id", "when", "channel", "who", "text", "flag"}],
  "chatter": {"normal|uneasy|afraid": [{"channel", "who", "text"}]},
  "omens":   [{"id", "kind", "match": [..], "mystique", "exposure", "requires_flag", "note",
               "reactions": [{"delay", "channel", "who", "text"}]}],
  "files":   {"/abs/path": "text"},
  "hosts":   {"name.hpcg.corp": {"ip": "10.x.x.x", "ms": 2.1, "whois": ["..."]}}
}
```

`when` is the same as canon: `day`, `at` ("HH:MM"), `curiosity`, `mystique`, `exposure`
(at least N), `curiosity_below`, `mystique_below`, `exposure_below` (less than N),
`flag`, `not_flag`, `done`, `not_done`. See `examples/packs/stapler.json`, and
`os_e_man/content/STYLE.md` for the voice.

## Breakage vs drift

Hallucinations are a feature. The checker only refuses what would break the game or leave
the simulation. Everything else the writer imagined becomes true, and a note goes in the
in-world `/var/log/continuity.log` ("Records Reconciliation Service").

**Dropped (breakage):** malformed items (missing fields, wrong types, bad `at`, bad paths);
anything touching canon (existing files, people, hosts; canon always wins); anything outside
the simulation (URLs, email addresses at real-world domains, public IPs, non-internal host
names); oversize packs (256 KB). Bad items are dropped one at a time. A pack is only rejected
when nothing usable survives.

**Absorbed (drift):**

| the writer... | the world... |
|---|---|
| has someone nobody hired talk | adds a stub person: "No HR directory entry. Badge system shows regular attendance." |
| posts in a channel that doesn't exist | now has that channel |
| mentions `something.hpcg.corp` | DNS resolves it; ping is filtered; whois owner is redacted |
| waits on a flag nothing sets | at the next 17:00 rollover, records it as having happened |
| waits on a training module that doesn't exist | drops that condition |
| uses a condition nobody understands | drops that condition |
| reuses an id | files the copy as `id~packid` |
| sets omen mystique/exposure outside 0–3 | clamps to 0–3 |
| reports an unknown office mood | files it under `uneasy` |
| runs long | cuts it off mid-thought |
| invents a new omen `kind` | keeps it; it waits for an action facilities can't take |

Applied packs are stored normalised (stubs and all), so a world replays the same way every
boot. If a pack file goes missing, mail it delivered still opens ("not retained by the mail
archive").

## The director command

Code: `os_e_man/director.py`, tests in `tests/test_director.py`.

    python -m os_e_man director              one pass now (alias: director once)
    python -m os_e_man director watch        a pass every --every seconds (default 30)
    python -m os_e_man director --dry-run    check the pack, don't apply it
    python -m os_e_man director --model fake (canned, default)
    python -m os_e_man director --model groq [--model-name openai/gpt-oss-120b]
    python -m os_e_man director --model local --model-name <id> [--base-url http://127.0.0.1:1234/v1]

`groq` and `local` use the same `ChatModel`: any OpenAI-compatible `/chat/completions`, with
JSON mode (on Groq, a `json_validate_failed` falls back to free text, and 429/5xx are
retried). `groq` reads `GROQ_API_KEY`. It is remote, so the prompt, which includes the digest
(fictional world state and the player's recent in-game commands), leaves the machine. The world
server itself still only listens on 127.0.0.1. The digest carries `voices`: a few canon lines
per person, so the writer hears how each character talks.

One pass: digest → plan (short notes per slot) → one writer prompt per slot (`chatter`,
`beats`, `emails`) → assemble pack `dir-dNNN` → check/apply through the door. Before 16:00
it writes today; from 16:00 on (including the 16:59 hold with nobody connected) it
writes tomorrow. A day that already has its `dir-dNNN` pack is skipped, so `watch` is idempotent.
With the world down it works on the save directly and only writes the pack file.

- **Model interface:** `complete(task, prompt) -> str`, where task is `plan` or a slot name.
  Only text goes in and out. `extract_json` takes the first JSON value from the reply
  (fences and prose are fine). A slot whose reply is unusable, or whose model call fails,
  is just left out; the checker handles everything else.
- **Authority:** texture only (chatter, beats, mail). No omens, files, hosts or rung changes yet.
- **Transcripts:** every prompt and reply goes to `<runtime>/director/dir-dNNN.json`.
- `FakeModel` rotates three canned office threads by day (fridge labels, phantom room
  bookings, timesheets nobody filed).

### Writing ahead while the player is away

    python -m os_e_man director ahead --model groq --days 3 [--budget 40]
    python -m os_e_man director watch --model groq      # ahead while nobody is connected,
                                                        # just today while someone plays

`run_ahead` writes the next N unwritten days in order. After each day it re-reads the digest,
so day N+1's planner sees day N. It stops before spending more than `--budget` model
calls (4 per day), and stops early if the model is down. The digest's `players` count (from
the server) tells `watch` whether anyone is at the keyboard.

What makes pre-written days feel live:

- **Branches.** The writer conditions lines on the player's state, and the game picks the
  branch at play time. On top of the canon `when` keys there are `mystique_below`,
  `curiosity_below` and `exposure_below`, so a pair like `{"mystique": 3}` / `{"mystique_below": 3}`
  is exclusive. `flag: "poke:<thing>"` / `not_flag` branches on what the player has looked
  at (the digest lists `pokeable`). Chatter is written for all three moods.
- **Storylines.** The planner returns `threads` (`id`, `title`, `state` open/closed, `next`),
  which are stored in the pack. The digest shows the open ones (`threads`, with the day last
  seen) and a note per day already written (`written_days`), so storylines continue across
  days and across runs.
- **No repeats.** A chat line (beat or chatter) that matches something already in the world,
  ignoring case and punctuation, is absorbed as drift and not filed. Models like to copy the
  voice samples.

Pack fields added for this: `for_day` (int) and `threads` (list). Old packs without them still
load.

## Next steps

1. Done: director command with a fake model (above), Groq, write-ahead, branches, storylines.
2. **Local model:** an OpenAI-compatible endpoint on 127.0.0.1 (LM Studio or Ollama), using
   structured output (a JSON schema per section). Planner writes short notes; writers fill one
   slot each. Start with chatter, then emails/beats, then omens.
3. Open decisions: how much authority (texture only vs. rung changes), auto-apply vs. a
   `world/pending/` review step, and whether the director ever shows up in the fiction.
