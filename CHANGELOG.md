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

### Fixed
- Director with LM Studio: no more 400s; JSON mode is dropped when a server doesn't support it.
- `--model local` sends a JSON schema per task (structured output), so models that can't
  write JSON on their own still produce valid packs. Local timeout raised to 300s.

### Changed
- Storylines keep a ledger of established facts (names, numbers, times, IDs). The director
  is shown them every day and told never to contradict them, so plots stay consistent.
- The director's voice allows a little SCP-style weirdness (it said "not horror" before).
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
