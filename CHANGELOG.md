# Changelog

All notable changes to OS-E.man. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

The version lives in one place: `os_e_man/__init__.py` (`__version__`); `pyproject.toml`
reads it. While the version is `0.x`, anything may change between minor versions. Saves
are still kept compatible (migrated, never broken), as a project rule.

How to bump: while in early alpha, every release is a patch (`0.0.x`), new systems included.
The first minor (`0.1.0`) comes at a steady state: the player can fully control their
coworkers' working lives. After that: patch for fixes and content, minor for new systems or
commands, major (`1.0.0`) when the game is considered released.

## [Unreleased]

### Added
- `floorplan` (`fp`): an ASCII plan of level 3, drawn live from badge door modes and room
  bookings. Once the office is uneasy, it shows room 3.14, which has no door.
- `director --plan-model groq|local [--plan-model-name ID]`: one model plans the day and keeps
  the plot; the main `--model` writes the chat, beats and emails.

### Fixed
- Director chat was being dropped: the schema example said `"who": "<person key>"` and
  models copied the brackets. The example is fixed, and near-miss speakers (`<kev>`, `Kev`,
  `Kev Marsh`) and senders (`<doug>@hpcg.corp`) are now absorbed instead of dropped.
- Storylines can't close before their third day; an early close is kept open.
- Local models couldn't write branches: the structured-output schema only allowed `day` and
  `at` in `when`. It now allows the branch keys (`mystique`, `curiosity`, `flag`, ...).
- A model stuck in a loop can't flood the inbox: duplicate emails in a pack are dropped, and
  a day holds at most 4. Lines that start with the speaker's own name ("kevin: ...") are
  trimmed, using the people directory.
- Director with LM Studio: no more 400s; JSON mode is dropped when a server doesn't support it.
- `--model local` sends a JSON schema per task (structured output), so models that can't
  write JSON on their own still produce valid packs. Local timeout raised to 300s.

### Changed
- Director writers are shown a few tone examples each call (`content/director_examples.json`,
  a different sample each day); verbatim copies are dropped. The planner must hand each
  slot an exact, specific strange detail instead of a one-line summary.
- Chat that repeats something already said (canon, earlier days, the tone examples, or the
  same day) is sent back to the writer to be rewritten, up to twice, instead of only being
  dropped. Near copies count too: a line that reuses half its meaningful words from an
  earlier line (branch pairs on the same day may resemble each other).
- Director ids that leak into chat ("d49_01 the printer...") are trimmed.
- Branch pairs: the prompt now says which side gets the stranger version (the stirred-up
  side), and beats are spread across speakers (nobody says more than two).
- The director sends its standing rules (the voice) as a system message, and the day's
  situation as the user message. gpt-oss models also get `Reasoning: medium` for planning
  and `low` for writing.
- Storylines keep a ledger of established facts (names, numbers, times, IDs). The director
  is shown them every day and told never to contradict them, so plots stay consistent.
- Storylines have arcs: 3 to 6 days with a turn in the middle, closing unexplained. Each
  day's development must differ in kind from the last (no counting up), and closed
  storylines are remembered so they aren't repeated.
- The director's voice goes further: outlandish, creepypasta told through paperwork (found
  notes, unofficial rules, things nobody explains). Still no gore, still not sci-fi.
- The Board now nudges players stuck on the facilities password toward the newsletters.

## [0.0.2] - 2026-11-08

### Added
- Unlocks: once a game day a new tool installs itself (`finger`, `at`, `dingaling post`,
  `--quiet` for `facil`/`badge`). Content in `content/unlocks.json`.

## [0.0.1] - 2026-11-07
First versioned alpha.

### Added
- The world server, crab shell, EER-26 training course, facilities foothold and omens.
- The ssh front end (`python -m os_e_man`).
- Content packs and the director: `world digest|check|apply`, and `director once|ahead|watch`
  with fake, Groq and local models; write-ahead with branches and storylines.
- Glimpses: rare flickers that become quests; `webble` browser; `emmy send`.
- The lever ladder: rungs 0 (facilities) and 1 (badging) with two routes each, Lattice Board
  nudges, and the exposure ladder ending in demotion with burned routes.
- `python -m os_e_man --version`.
