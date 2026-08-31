# AGENTS.md — project rules for coding agents

This is a **vinyl cutter web UI**: a zero-dependency Python 3 (stdlib only) server that serves a single-page web UI for uploading HPGL files and printing them raw to a cutter.

## Changelog — required, do not skip

- **Before** making any change, read `dev/changelog.md` — it is the authoritative record of what exists, what was decided, and why.
- **After** making any meaningful change (code, config, docs, behavior), **append** a new entry to the bottom of the "Completed work" section of `dev/changelog.md`, using its documented format (date + title, then Goal/why, Changes, Decisions, Verification).
- Append only — never rewrite or reorder existing entries.
- If work is left half-done or new ideas appear, record them in the "Open work / ideas" section.
- If you could not run verification, say so explicitly in the entry ("Verification: not run — why").

## Non-negotiables

- **No third-party dependencies.** `server.py` is stdlib-only on purpose so deployment is "copy two files". Do not add pip/Node/frontend build tooling unless the user explicitly asks.
- **Printing must stay `cat <file> > <printer device>`** (currently `sh -c 'cat ... > ...'` in `server.py`, device defaulting to `/dev/usb/lp1`, configurable via `--printer-dev` / `PRINTER_DEV`). Do not replace it with a different printing mechanism without the user asking — that path is proven on the user's real cutter.
- **Print jobs stay serialized** (single worker thread + queue) — LP devices cannot take concurrent writes.
- **No authentication exists** by design (trusted-LAN tool). File names are sanitized and confined to the upload dir; keep it that way.
- Don't treat `uploads/` contents as code — it's user data (gitignored). Never delete user uploads "for cleanup".

## Layout

- `server.py` — the whole backend (HTTP, multipart parsing, jobs, printing).
- `static/index.html` — the whole frontend (vanilla JS; the server serves exactly this file at `/`).
- `README.md` — user-facing docs (deployment, permissions, systemd, API).
- `dev/` — development notes (changelog); never needed at runtime.

## Verification habits

- Run `python3 -m py_compile server.py` after touching it.
- For behavior changes, start the server on a scratch port with `--printer-dev` pointed at a throwaway file (e.g. `/tmp/fakeprinter`) and exercise the affected endpoints with curl — the same technique used in the build session.
- On macOS there is no `/dev/usb`; real-device testing happens on the user's Linux box.
