# OS-E.man writing guide

## Voice
- Everything is written as a real document by someone who doesn't know they're in a game: emails, logs, man pages, asset records, chat.
- Flat and bureaucratic. The joke is how accurate it is, not how loud. No winking, no "hacker movie" lingo, no exclamation marks except from L&D.
- Corporate filler should be believable: tracking IDs, ticket numbers (ITSD-, HPCG-LND-), "per my last email", mandatory-acknowledgement footers.
- The anomalous parts read like containment records: `Item #`, `Access Class`, `Handling`, `Description`, `Addendum`. Calm wording for things that are not fine.
- Power starts at office scale: pods, water, rooms, the thermostat. Escalate one rung per milestone (badging, then building management, then the client's PoS network, then...).
- The player is Pat Dunn (pdunn), referred to as they/them. Nobody notices Pat. That's the alibi.

## Redaction markup
`[[R3:text]]` renders as `████` until the player's curiosity is 3 or more, then shows the text in amber.
Use it in emails, files, whois records and database rows. Lower numbers mean easier to reveal.
Redact the line that makes the record frightening, not the boring part.

## Content files
| File | What |
|---|---|
| `emails.json` | Mail. `when` supports `day`/`at`, `curiosity`, `mystique`, `exposure` (and `*_below` for "less than"), `flag`, `not_flag`, `done`, `not_done`; `delay` in game minutes. |
| `npcs.json` | People, scheduled chat `beats` (can set flags), ambient `chatter` pools by mood (normal / uneasy / afraid). |
| `omens.json` | Facilities actions that unsettle people. `kind` + `match` keywords, `requires_flag`, `mystique`, `exposure`, delayed `reactions`. |
| `challenges.json` | EER-26 modules and grader anomalies (`min_curiosity`). |
| `curiosity.json` | Things worth poking, and how much curiosity each is worth (once). |
| `pos_db.sql` | The training replica, including tables that shouldn't be there. |
| `net.json` | Hosts for ping/whois/netstat. |
| `fs/` | The filesystem, as real files. |
| `man/` | Man pages. Jokes go in BUGS and NOTES. |
