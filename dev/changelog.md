# Development Changelog

Running log of every change to this project. **Oldest first** — read top to bottom to see how the project evolved. If you are picking this up from a previous session, read this file first.

**Conventions**

- Append new entries to the **bottom** of "Completed work" (before "Open work"). Never rewrite or reorder existing entries.
- Every meaningful change (code, config, docs, behavior) gets an entry, containing:
  - `## YYYY-MM-DD — short title`
  - **Goal / why** — what was being solved and why
  - **Changes** — files touched and what changed in each
  - **Decisions** — non-obvious design choices, so they aren't "re-discovered" or accidentally undone
  - **Verification** — what was actually run/tested to confirm it works
- See `AGENTS.md` for the full project rules (all coding agents must follow them).

---

## Completed work

## 2026-08-29 → 2026-08-30 — Initial build: upload + print web UI

**Goal / why.** User (Finnish speaker, working on macOS dev machine; the app targets the Linux box where the cutter is attached) wanted a minimal web UI to:

1. upload HPGL files to a folder on the server, and
2. press a print button that sends the selected file raw to the cutter — the printing workflow is known to work in bash as `cat file.hpgl > /dev/usb/lp1`, so the app had to reproduce exactly that.

**Changes.** (repo was empty; everything below is new)

| File | What |
|---|---|
| `server.py` (437 lines) | Zero-dependency Python 3 stdlib HTTP server (`ThreadingHTTPServer`). Serves the UI; endpoints: `GET /api/files`, `POST /api/upload` (multipart, multi-file), `DELETE /api/files?name=`, `POST /api/print` (JSON, enqueues jobs), `GET /api/jobs`, `GET /api/config`. Minimal hand-rolled multipart parser. Print jobs run on a **single worker thread** (printer takes one job at a time). Config via CLI flags + env: `--bind/--port/--upload-dir/--printer-dev/--allowed-exts/--print-timeout/--max-upload-mb` (defaults: `0.0.0.0:8080`, `./uploads`, `/dev/usb/lp1`, `hpgl,hgl`, 600 s, 100 MB). |
| `static/index.html` (350 lines) | Single-file dark UI, vanilla JS, no frameworks: drag & drop upload zone, file table (name/size/mtime + Print/Delete per row), "Print all" button, live job list with status pills (queued/printing/done/error) polled every 2.5 s, toasts. UI reads `/api/config` for device name, upload dir and accept-filter. |
| `README.md` | Quick start, config table, printer permission options (root / `lp` group / udev rule), how to find the right `lpX`, systemd unit, API table, security notes. |
| `.gitignore` | `uploads/`, `__pycache__/`, `*.pyc`. |

**Decisions (why they exist — don't silently undo).**

- **Zero dependencies (stdlib only):** deployment to the cutter box is "copy two files". No venv, no pip, no Node.
- **Print = `sh -c 'cat <abs path> > <device>'`** via `subprocess.run` with `shlex.quote` on both operands — literal bash semantics the user already trusts. Do not "improve" this to a direct Python file copy unless asked; the raw `cat > /dev/usb/lpX` path is the proven workflow.
- **One worker thread + queue:** LP devices can't take concurrent writes; jobs are serialized in enqueue order. Job states: `queued → printing → done | error`; `returncode < 0` is reported as "killed by signal N (printer offline or busy?)" (that's what SIGPIPE from a dead printer looks like).
- **Filenames sanitized to `[A-Za-z0-9._-]`** (basename + non-alnum → `_`); all user-supplied paths are resolved and checked `relative_to(upload_dir)` to block traversal.
- **Re-upload with same name replaces the file** (intentional: re-uploading a fixed design keeps the same name).
- **Only allowed extensions upload** (`hpgl,hgl` by default); other types get a 400 with the reason. Non-printable files would still appear in the file list, so `printable` flag is carried per file.
- Job history is in-memory only, capped at 50, newest-first in the API. Files on disk are the source of truth; the `uploads/` dir survives restarts, the job list does not.

**Bug found & fixed during this session.**

- Extension check compared a dotless name (`"hpgl"`) against dotted entries (`".hpgl"`) → every upload was rejected, and the error message showed `..hpgl, ..hgl`. Fix: `CFG["allowed_exts"]` stores **dotless** names; `_is_printable()` strips the dot from the suffix; the upload check reuses `_is_printable()` so there is one source of truth.

**Verification.** Ran the server locally (`--printer-dev /tmp/fakeprinter`, a temp file standing in for the raw device, since macOS has no `/dev/usb`) and exercised the whole API with curl:

- upload `.hpgl` → saved; upload `.txt` → 400; re-upload same name → replaced
- print → job `done`, "13 bytes written", and the fake device contained the exact file bytes (confirms the `cat >` mechanics)
- two prints queued back-to-back → both ran serially, both done
- missing file / `../` traversal on print and delete → 400; delete → works; UI page + config endpoint serve correctly
- `python3 -m py_compile server.py` passes
- User then used the live UI in a browser and uploaded a real design (`napit.hpgl`, ~3.5 KB) — no errors.

---

## 2026-08-30 — Dev changelog + agent conventions

**Goal / why.** User wants a persistent, human-readable record of what was done and **why**, that survives session closures and can be continued later.

**Changes.**

| File | What |
|---|---|
| `dev/changelog.md` | This file — back-filled with the full initial-build history above. |
| `AGENTS.md` | New workspace instruction file: tells every coding agent working in this repo to read `dev/changelog.md` first and append an entry after each meaningful change; restates the non-negotiables (zero deps, cat-based printing, no auth assumption). |

**Decisions.**

- Changelog lives in `dev/` (not repo root) to keep the deployable app (`server.py` + `static/`) visually separate from development notes.
- Chronological, append-only: reading top→bottom = project history; agents only ever append.
- `AGENTS.md` is the cross-session mechanism — it's what future agents load before acting, so the "note things down" habit persists without the user repeating it.

**Verification.** Files created and reviewed; nothing else touched.

---

## 2026-08-30 — Removed "Print all" button from UI

**Goal / why.** User: a bulk "Print all" button is not usable for a vinyl cutter — every design is a separate physical cut job, so batch printing from one button makes no sense. Remove it; printing stays an explicit per-file action.

**Changes.**

| File | What |
|---|---|
| `static/index.html` | Removed the `#print-all` button from the header (and the now-unused `.spacer` flex spacer next to it), its `disabled` toggle in `renderFiles()`, its `onclick` wiring, and the two now-dead CSS rules (`.spacer`, `button#print-all`). Per-row **Print** buttons and the shared `printFiles()` helper stay — printing several files = press Print per row. |
| `README.md` | Features bullet: "per file (or *Print all*)" → "per file". |

**Decisions.**

- Deliberate UI simplification, not a capability removal: the `POST /api/print` API still accepts a list (`{"files": [...]}`) and the server queue still serializes jobs; only the UI no longer offers one-click bulk printing. If the user later wants batch printing back, it's a 2-line UI addition.
- Earlier changelog entries still mention "Print all" as part of the initial build — left untouched (append-only log).

**Verification.** Grep confirms zero remaining `print-all` / `spacer` / `Print all` references in `static/index.html`. The still-running test server (:8099) reads the static file from disk per request; curled `/` → HTTP 200, 0 references in served HTML, header badges intact. `server.py` untouched.

---

## 2026-08-30 — Non-root printer permissions (docs)

**Goal / why.** User tried the app on the real device (Linux box; dash `sh: 1:` error format → Debian/Ubuntu/Raspbian) and got `sh: 1: cannot create /dev/usb/lp1: Permission denied` — the device node exists (right `lpX` found) but is `660 root:lp` and the server user isn't in that group. User explicitly wants the printer granted to the user, **not** running the server as root.

**Changes.** (docs only — `server.py` untouched; the app already surfaces exactly this stderr text in the job list)

| File | What |
|---|---|
| `README.md` | Replaced "Printer permissions" section: non-root path is now the documented default — `usermod -aG lp` + logout/login + server restart, a udev rule pinning `MODE=0660, GROUP=lp` for all `lp[0-9]*` nodes (survives reboot/replug), a no-cut verify step (`: > /dev/usb/lp1`), a minimal 10-unit test-cut command, a dedicated-`vinyl`-group variant, and the systemd `SupplementaryGroups=lp` gotcha. Running as root demoted to "last resort". The systemd unit example now uses `User=youruser` + `SupplementaryGroups=lp` instead of `User=root`. |

**Decisions.**

- Non-root is now the documented deployment default, per user decision. The `SupplementaryGroups=` note matters: systemd does not reliably apply `usermod`-added groups to a service, so the unit spells the group out.
- udev pins mode `660` + group (not `666`) — least privilege; world-writable device nodes are no longer suggested.

**Verification.** Not run — documentation only; the commands must be executed on the user's Linux box (macOS dev machine has no `/dev/usb`). Steps follow standard udev/LP semantics. User is expected to confirm on the device.

---

## 2026-08-30 — Real-device facts: node is `lp0` + stable-symlink recipe (docs)

**Goal / why.** User ran `ls -l /dev/usb/lp*` on the Linux box: `crw-rw---- 1 root lp 180, 0 ... /dev/usb/lp0` — two facts follow:

1. Group is `lp`, mode 660 → the standard non-root recipe applies unchanged (the earlier `usermod -aG lp` steps, aimed at `lp0` now).
2. **Only `lp0` exists** — but the earlier permission error was against `lp1` (and the app's default is `/dev/usb/lp1`). Node numbers evidently shifted at some point (classic udev renumbering on replug/reboot), so a fixed `--printer-dev /dev/usb/lpN` is fragile.

**Changes.** (docs only)

| File | What |
|---|---|
| `README.md` | Added a "Stable device name (recommended)" block to the permissions section: `lsusb` → note `<vendor>:<product>` → add a udev line `SUBSYSTEM=="lp", ATTRS{idVendor}=="...", ATTRS{idProduct}=="...", SYMLINK+="vinylcutter", MODE="0660", GROUP="lp"` (vendor/product placeholders), then run the app with `--printer-dev /dev/vinylcutter` so renumbering stops mattering. |

**Decisions.**

- App default stays `/dev/usb/lp1`; per-machine node/symlink is configuration, not code. The user's box needs `--printer-dev /dev/usb/lp0` (or the `vinylcutter` symlink once the udev line is in).
- The symlink rule matches the `lp` subsystem filtered by the cutter's USB IDs, so other USB printers on the same box are unaffected.

**Verification.** Not run — documentation only. Needs the user's `lsusb` output to produce the exact vendor/product IDs; user is expected to confirm `usermod` + `: > /dev/usb/lp0` on the box.

---

## 2026-08-30 — Permission-error fix hint in the UI

**Goal / why.** User hits `Permission denied` when pressing Print on the real machine and the raw error (`sh: 1: cannot create /dev/usb/lp1: Permission denied`) doesn't say how to fix it. Request: when a print fails with a permission error, show the fix steps (add user to printer group, re-login, verify) directly in the UI.

**Changes.**

| File | What |
|---|---|
| `server.py` | Jobs now carry a `hint` field (default `""`). In `_run_job()`, when `sh` exits non-zero and stderr contains `permission denied` (case-insensitive), the job gets a 3-step fix hint using the **configured** `printer_dev` path: 1) `sudo usermod -aG lp $USER` 2) log out and back in **and restart the app** 3) `: > <device> && echo ok`. The raw stderr stays as the job message. |
| `static/index.html` | Job rows wrapped in a `.job-block`; when a job has a hint, an amber monospace `.job-hint` block renders under the row (via `textContent` — no HTML injection). `.file`/`.msg` spans got `title` tooltips so truncated text is hover-readable. |
| `README.md` | "How printing works" notes that permission errors carry a fix hint in the UI. |

**Decisions.**

- Hint is generated server-side with the *configured* device path (not hardcoded `lp0`) — this also surfaces the earlier lp0/lp1 mismatch: if the app is still pointed at the wrong node, the hint shows exactly which node it tried.
- Step 2 explicitly says **restart the app** — a running process keeps its old groups; without it, `usermod` appears to "not work" (the user's exact pain point from the previous message).
- Only permission errors get a hint; other failures keep the current raw error/signal text. The `hint` field makes it trivial to add more known-fix hints later (e.g. `No such file or directory` → check `ls /dev/usb/lp*`).

**Verification.** `py_compile` OK. Restarted the scratch server (:8099) with `--printer-dev /tmp/rodev/lp` inside a `chmod 555` dir → printed → job `error`, message `sh: /tmp/rodev/lp: Permission denied`, hint = 3-step text with the real path (confirmed via `/api/jobs`). Restarted with a working `/tmp/fakeprinter` → job `done`, `hint: ""`. Served `/` contains the new `job-block`/`job-hint` code. (On the user's dash box the message reads `sh: 1: cannot create ...` — the check matches `permission denied` either way.)

---

## 2026-08-30 — Selectable printer device in the page header

**Goal / why.** User: *"can you make it so that the printer is selectable in the top of the page so it's possible to change the device directly there if there's multiple printers available".* The real machine has **both** `/dev/usb/lp0` and `/dev/usb/lp1`, and LP node numbers can shift on replug/reboot — so the user should not have to edit `--printer-dev` / restart the service just to point at the right node.

**Changes.**

| File | What |
|---|---|
| `server.py` | New helpers `_list_printer_devices()` (expands the `dev_scan` globs + always includes the currently configured device, with an `exists` flag, sorted) and `_valid_device_path()` (security guard: rejects `..`, requires `/[A-Za-z0-9._/-]+`, then requires `/dev/` prefix **or** a match against a dev-scan pattern). New routes `GET /api/devices` → `{devices, current}` and `POST /api/devices` → `_api_devices_set()` (validates, then swaps `CFG["printer_dev"]` at runtime). New `--dev-scan` / `DEV_SCAN` flag (default `/dev/usb/lp*,/dev/lp*`, also in the docstring env list); startup banner gains a `devices : ...` line. `import fnmatch`, `import glob` added. |
| `static/index.html` | Header printer badge is now a `<select id="printer-select">` (`.badge select` CSS keeps the pill look); `state.devicesKey` + `loadDevices()` polls `/api/devices` on every refresh but only rebuilds options when the list/current actually changed (an open dropdown isn't disturbed; missing devices show "(missing)" instead of being hidden); `change` listener POSTs the new device, toasts `printer → X`, and reverts the selection on error. Dead `cfg-dev` init line removed. |
| `README.md` | Features bullet for header switching; `--dev-scan`/`DEV_SCAN` config-table row; `GET`/`POST /api/devices` API rows; explicit note that **UI selection is per-instance only** (permanent = `--printer-dev`/`PRINTER_DEV`/systemd); "How printing works" now says jobs go to the *currently selected* device. |

**Decisions.**

- **Runtime-only, no persistence file.** Choosing in the UI changes the running process only; the durable knob stays the CLI/env/systemd setting. Keeps the config model single-sourced (one `CFG["printer_dev"]`, no new state file) and survives the zero-deps, copy-two-files deployment story. Persistence listed under Open work if ever requested.
- **Whitelist on the POST (unauthenticated client):** the web client is on the trusted LAN with no auth, so `_api_devices_set` refuses anything that is not under `/dev/` or matched a `--dev-scan` glob. This blocks e.g. `cat file > /etc/passwd` via the device endpoint; the safe-charset regex also blocks shell metacharacters (harmless anyway — `shlex.quote` is applied in `_run_job`).
- **`--dev-scan` globs** (default `/dev/usb/lp*,/dev/lp*`) double as the knob for the user's planned stable `/dev/vinylcutter` symlink — set `--dev-scan /dev/vinylcutter` and it appears in the dropdown. The currently configured device is always listed (with `exists` false if the node is gone) so the UI never loses the active target.
- Missing devices are rendered as "(missing)" rather than disabled: the node can come back on replug without a page refresh, and the user may still want to queue against it.
- The permission-error fix hint (previous entry) reads `CFG["printer_dev"]` at job time, so it automatically tracks the newly selectable device — no change needed there.

**Verification.** `py_compile` OK. Scratch server on `:8099` restarted with the new code (`--printer-dev /dev/null --dev-scan "/dev/null,/tmp/printer*"`; macOS has no `/dev/usb`, so `/tmp/printer0` + `/tmp/printer1` empty files stand in for the LP nodes):

- `GET /api/devices` → 3 entries (`/dev/null`, `/tmp/printer0`, `/tmp/printer1`), `current` = `/dev/null`
- `POST {"device":"/tmp/printer0"}` → 200 `{"current":"/tmp/printer0"}`; then uploaded `design.hpgl` and printed → job `done`, `13 bytes written to /tmp/printer0`, and the fake device contained the exact file bytes (the switched target is what `cat >` actually used)
- switched back to `/dev/null` → next print wrote to `/dev/null`; `/tmp/printer0` content untouched
- `POST` `/etc/passwd`, `../etc/passwd`, empty → all rejected 400 (whitelist works)
- served `/` contains `printer-select` (3×) and `loadDevices` (3×); zero `print-all` references remain; UI opened in the in-app browser

---

## 2026-08-30 — Fixed Print/Delete button placement in the file table

**Goal / why.** User: *"can you fix the position of print and delete buttons, they are not in correct position in the table under the actions".* Root cause: in `renderFiles()` the `.row-actions` div was `tr.appendChild()`-ed as a **direct child of `<tr>`** — a `<div>` is not legal table markup, so browsers foster-parent it (move it out of the table entirely). The buttons therefore rendered outside/below the table instead of in the Actions cell. (Latent since the initial build; the header's `text-align:right` on the Actions column made the misalignment visible.)

**Changes.**

| File | What |
|---|---|
| `static/index.html` | `renderFiles()` now emits a fourth `<td class="actions">` in the row markup and appends the buttons div into `tr.lastElementChild` (a real cell). CSS: `.row-actions` changed from `display: flex` to `display: inline-flex` and new `td.actions { text-align: right; }` so the buttons sit right-aligned, flush under the right-aligned "Actions" header. Added a comment explaining why the td wrapper exists, so it doesn't get "cleaned up" again. |

**Decisions.**

- Kept the existing `.row-actions` flex row (button spacing/gap) rather than laying the buttons out individually in the cell — `inline-flex` + right-align is the minimal correct fix.
- No backend/API change; `server.py` untouched.

**Verification.** `server.py` untouched (no compile needed). The still-running scratch server (:8099) reads `static/index.html` from disk per request, so no restart was needed: served `/` now contains `td.actions` rule, `inline-flex`, the `<td class="actions">` markup and `lastElementChild`; `/api/files` returns the 3 uploaded files so rows render; page opened in the in-app browser — buttons now sit inside the Actions column, right-aligned. `server.py` untouched.

---

## 2026-08-30 — Search filter for the file list

**Goal / why.** User: *"create a search filter for the files so it's possible to quickly find a file from the list".* With a running cutter the upload folder accumulates designs; scrolling through the table to find one is slow. A name filter makes the list instantly browsable.

**Changes.**

| File | What |
|---|---|
| `static/index.html` | New `<input type="search" id="file-search">` in the Files card header (right side via `margin-left:auto`; `.card h2 input` CSS; 110 px on ≤640 px screens). `state.search` added; `renderFiles()` now renders a case-insensitive substring match on the filename. While filtering, the count shows `matched/total` (e.g. `1/3`) and the empty state reads `No files match “…”` (vs “No files uploaded yet.”). `input` event re-renders immediately; the state survives the 2.5 s background refreshes so the filter persists while the list updates. |
| `README.md` | Features bullet for the search box. |

**Decisions.**

- **Client-side only, no API change.** `GET /api/files` already returns the whole list and the upload folder is small (a few designs); filtering in JS is instant and keeps `server.py` untouched (no compile/deploy impact beyond the one static file). A server-side query param can be added later if the folder ever gets big.
- Case-insensitive substring match on the full filename (not a prefix match) — closest to how people type when hunting a file.
- Filter state lives in `state` (not the input) and the input is never rebuilt on refresh, so typing is never disturbed by the poll cycle.

**Verification.** `server.py` untouched. The still-running scratch server (:8099) reads `static/index.html` per request (no restart needed): served `/` contains the `file-search` input (2×: markup + listener) and the `No files match` message; the page was opened in the in-app browser — the 3 uploaded files render and the filter box sits right-aligned in the Files header. Filter behavior (substring match, count `n/total`, empty message) is plain JS over the loaded list; the served markup/JS was confirmed present.

---

## 2026-08-30 — Per-file button relabeled Print → Cut

**Goal / why.** User: *"can you change the print buttons to say 'cut' instead".* The machine is a vinyl **cutter** — the action it performs is cutting, so the button should say that, not "Print".

**Changes.**

| File | What |
|---|---|
| `static/index.html` | Per-file action button text `"▶ Print"` → `"✂ Cut"` (scissors glyph matches the header logo; tooltip `cat <file> > <device>` and click behavior unchanged). |
| `README.md` | Features bullet "**Print** button per file" → "**Cut** button per file". |

**Decisions.**

- Only the button label changed; the internal `printFiles()` helper, job states, the "Print jobs" card, toasts and API names (`/api/print`, "queued for printing") intentionally stay print-flavored — the *mechanism* really is printing to an LP device, and the user only asked for the button text. Rename the rest only if the user wants it.
- Glyph: `✂` (not `▶`) to signal the physical action; swap back to `▶` in one character if it looks off next to the scissor logo.

**Verification.** `server.py` untouched. The still-running scratch server (:8099) re-serves the static file per request: served `/` contains `✂ Cut` (1×) and zero `▶ Print` references; page opened in the in-app browser with the 3 uploaded files — buttons render as "✂ Cut" per row.

---

## 2026-08-30 — "Clear all" button for the print jobs log

**Goal / why.** User: *"add a 'clear all' button to top of the print jobs so that the log can be cleaned if users wants to do so".* The job list is an in-memory log (capped at 50); on a machine in production it fills up with old done/error entries and the user wants a way to wipe it.

**Changes.**

| File | What |
|---|---|
| `server.py` | New `DELETE /api/jobs` → `_api_jobs_clear()`: removes all jobs whose status is `done` or `error` from the in-memory history, returns `{"cleared": n}`. Wired into `do_DELETE` (with an explicit `return` after the branch). |
| `static/index.html` | **Clear all** button (`.small.danger`, right side via `margin-left:auto`) in the Print jobs card header; disabled whenever no finished jobs exist; click calls `DELETE /api/jobs`, toasts `Cleared N finished job(s)`, refreshes. `renderJobs()` updates the disabled state each poll. |
| `README.md` | "How printing works" note (in-memory log, Clear all semantics) + `DELETE /api/jobs` API-table row. |

**Decisions.**

- **Clears *finished* jobs only.** A `queued`/`printing` job is never removed from the list: the `cat` process must run to completion (killing it would abort the physical cut mid-design), and the user should see its final result. The in-flight `cat` continues regardless of list bookkeeping — this change only touches the history dict, never the subprocess.
- Button disabled state (not removal) when nothing is finished, so the affordance is always visible and self-explanatory (tooltip: "Remove finished jobs from the list (running jobs keep going)").
- No persistence exists for jobs, so nothing else needs clearing; the upload folder is deliberately untouched.

**Verification.** `py_compile` OK. Scratch server (:8099) restarted with the new code; `dev-scan` includes `/tmp/printer*`, so a **FIFO** (`/tmp/printerSlow`) with a 3 s-delayed reader stood in for a slow cutter:

- fresh start → `GET /api/jobs` empty
- print #1 to `/dev/null` → `done`
- switched device to the FIFO, print #2 → job sat `printing` for the ~3 s window
- `DELETE /api/jobs` **mid-run** → `{"cleared": 1}` (only the finished job); the printing job stayed listed
- after the reader started, job #2 completed normally → `done | 13 bytes written to /tmp/printerSlow` (active job unaffected, result reported)
- second `DELETE` → `{"cleared": 1}` (the just-finished one)
- served `/` contains the button wiring (3× `jobs-clear`); UI opened in the in-app browser

---

## 2026-08-31 — Sortable file list (click column headers)

**Goal / why.** User: *"add sorting features to files section so that the list can be sorted to asceding or descending from the name, size and upload date".* With a growing upload folder the server's fixed newest-first order isn't always what the user wants — e.g. hunting for a file alphabetically or finding the biggest design.

**Changes.**

| File | What |
|---|---|
| `static/index.html` | Name/Size/Uploaded `<th>`s are now clickable (`.sortable`, `data-key`, hover highlight, accent `▲`/`▼` indicator on the active column). New `sortFiles()` sorts by `name` (locale-aware, case-insensitive), `size` or `mtime` (numeric); `state.sort = {key:"mtime", dir:"desc"}` matches the previous server order as the default. Click a column → ascending; click the same column again → flip direction. `renderFiles()` applies the sort **after** the name filter and updates the arrow indicators each render, so both features compose and persist across the 2.5 s refreshes. |
| `README.md` | Features bullet for sortable columns. |

**Decisions.**

- **Client-side only, `server.py` untouched.** `GET /api/files` already returns name/size/mtime per file and the folder is small; the server's fixed mtime-desc order stays as the initial order, the browser re-sorts it. No API change (a `?sort=` param can be added later if the folder ever grows large).
- Arrow indicator on the active header (blank on others) instead of styling all three, so the current sort is unambiguous.
- Case-insensitive `localeCompare` for names so `design` sorts next to `Design`.

**Verification.** `server.py` untouched (no compile). The still-running scratch server (:8099) re-serves the static file: served `/` contains the sortable headers (5× `data-key`), `sortFiles` (1×) and the `#file-headers` wiring (3×); page opened in the in-app browser with the 3 uploaded files — default order (newest first) unchanged, headers show pointer cursor, and clicking a header re-sorts with the direction arrow. Sort/filter interaction (both live in `state`, both re-applied per render) follows the same pattern as the verified search filter.

---

## 2026-08-31 — Project moved under git + MIT license (user change)

**Goal / why.** User: *"I have added this to git and added .git folder and license"* — the project is now a proper git repository with an explicit license, so the history (and this changelog) can be shared/forked.

**Changes.** (made by the user, not an agent — recorded here so future sessions know the baseline)

| File | What |
|---|---|
| `.git` | Repo initialized. Two commits: `12e1155` "Initial commit" (2-line placeholder README + LICENSE) and `3288b1d` "initial commit" (the full project: `server.py`, `static/index.html`, `README.md`, `dev/changelog.md`, `AGENTS.md`, `.gitignore`). Working tree clean. |
| `LICENSE` | New: MIT, copyright 2026 anakuron. |
| `README.md` | Added a one-line "License" section pointing at LICENSE. (The user's placeholder 2-line README was replaced by the full README in the second commit.) |
| `.gitignore` | Unchanged — `uploads/`, `__pycache__/`, `*.pyc`. Confirmed `git ls-files` tracks only the app files; user uploads are never committed. |

**Decisions.**

- MIT is a permissive license — fits the "copy two files and deploy" spirit; no change to the zero-deps or no-auth design.
- The `uploads/` upload dir stays out of git (user data, gitignored) — a fresh clone starts with an empty upload folder by design.

**Verification.** `git status` clean; `git ls-tree HEAD` = `.gitignore AGENTS.md LICENSE README.md dev server.py static`; LICENSE is the standard MIT text. No code touched.

---

## 2026-08-31 — Consistent button styling: Cut button de-emojied + blue highlight

**Goal / why.** User: *"the buttons are not consistent at the moment… Cut button has a emoji, but other buttons don't so remove the emoji from the cut button, keep it in the page logo only… the cut button has it's own hover color it should be blue instead like in the upload section. Change only these and nothing else".*

**Changes.**

| File | What |
|---|---|
| `static/index.html` | (1) Per-file button text `"✂ Cut"` → `"Cut"` — the ✂️ glyph now exists only in the page logo. (2) Button gets the existing `button.primary` class: blue (`--accent`) background with lighter-blue hover (`#6fd0ff`), dark text — the same highlight language the upload dropzone uses on hover. Non-printable files still render it disabled (opacity .45 via the existing `button:disabled` rule). CSS untouched. |

**Decisions.**

- Reused `button.primary` instead of adding a new hover rule: it *is* the page's blue-highlight style (and the lighter-blue hover of `.primary:hover` is the only blue hover in the sheet), so the main action now matches the accent color used for success-ish highlighting. All other buttons keep their current styling (Delete / Clear all: neutral with red hover, per the red-for-destructive convention).
- `button.primary` rules sit after `button:hover` in the sheet, so on hover the border stays accent-colored and only the background lightens — consistent with the dropzone's accent border on hover.

**Verification.** `server.py` untouched. The running scratch server (:8099) re-serves the static file: served `/` contains exactly one ✂ (the logo) and the `className = "primary"` wiring (1×); page opened in the in-app browser — Cut buttons render blue, Delete/Clear-all unchanged. One pre-existing inconsistency was flagged to the user for a decision (amber warning color, see below); no other buttons touched.

---

## 2026-08-31 — Design decisions confirmed: keep amber, keep red Delete/Clear-all

**Goal / why.** Follow-up to the button-consistency change: user confirmed *"let's keep the amber color, clear all and delete buttons are correct as well"* — closing the two open design questions so a future session doesn't "fix" them.

**Changes.** None (code/docs unchanged — the current styling is now the confirmed baseline). This entry only records the decisions; the Open work bullet for the palette question was removed.

**Decisions (binding for future styling work).**

- **The UI palette is intentionally 4 colors:** blue (`--accent`) = highlight/primary action, red = error & removal, green = success/done, **amber = warning** (warning toasts, e.g. skipped file types; permission-error job-hint block). Do not collapse amber into the other three.
- **"Delete" and "Clear all" keep the neutral button + red hover** (`.danger`) — both are removal actions, and this is confirmed correct by the user.

**Verification.** Not needed — no code or docs changed; decision recorded for future sessions.

---

## 2026-08-31 — Actions column left-aligned like the other columns

**Goal / why.** User: *"in the files tile, all other titles are aligned to left, but actions is aligned to right, it should also be aligned left so it's consistent".*

**Changes.**

| File | What |
|---|---|
| `static/index.html` | Removed the `style="text-align:right"` from the Actions `<th>` and deleted the `td.actions { text-align: right; }` rule — header **and** the button cells now inherit the base left alignment of every other column (the `.row-actions` inline-flex row simply sits at the left). |

**Decisions.**

- The buttons were also moved left (not just the header): a left-aligned header over right-hanging buttons would have looked less consistent than the current all-left layout.

**Verification.** `server.py` untouched. The running scratch server (:8099) re-serves the static file: served `/` contains no `td.actions` and no `text-align:right` at all; page opened in the in-app browser — Actions header and buttons left-aligned, flush with the Name column's text.

---

## 2026-08-31 — Actions cell: header left, Delete pinned to the column's right edge

**Goal / why.** Follow-up to the left-alignment change: with everything left-aligned the Actions column left an ugly gap at the right end of the table. User: *"can you align the last column actions so that the last item of it (delete) aligns to the end".*

**Changes.**

| File | What |
|---|---|
| `static/index.html` | `.row-actions` switched from `inline-flex` (content-width, hugs left) to `display: flex; justify-content: space-between` — a block-level flex row that spans the full cell: Cut stays left (under the left header) while Delete is pushed to the right edge of the table. No other rules touched. |

**Decisions.**

- `space-between` (rather than `margin-left:auto` on Delete) — same result with two buttons, and it degrades sensibly if a third action button is ever added.
- Keeps the previously confirmed layout: all column headers left-aligned, no right-aligned header.

**Verification.** `server.py` untouched. The running scratch server (:8099) re-serves the static file with the new rule (confirmed in served HTML); page opened in the in-app browser — Cut sits under the Actions header, Delete aligns with the table's right edge, no dead space.

---

## 2026-08-31 — Actions column shrink-to-fit: buttons hug right edge, title stays left

**Goal / why.** Correction of the previous layout attempt: `space-between` stretched the buttons across a wide Actions column, which the user didn't want. Their intent: *"shrink the whole column size, since the width is too long so that it hugs the contents and aligns the whole section to the right end but still keeps the title at the left".*

**Changes.**

| File | What |
|---|---|
| `static/index.html` | `.row-actions` back to `inline-flex` (content-width, no stretching) + re-added `td.actions { text-align: right }` so the content-width button row hugs the right edge of the cell. The Actions column is now only as wide as its content (buttons); in the auto table layout the break-all **Name** column absorbs the remaining table width, so the narrow Actions column sits at the table's right end. Header "Actions" keeps the base left alignment, as previously requested. |

**Decisions.**

- Content-width row + right-aligned cell instead of `space-between`: the column hugs the buttons (no dead space *inside* the column), and the slack moves entirely to the Name column — exactly the layout the user described.
- Header left inside the narrow column is the confirmed target (left headers were a firm requirement from the previous round).

**Verification.** `server.py` untouched. The running scratch server (:8099) re-serves the static file (new rules confirmed in served HTML); page opened in the in-app browser — Actions column is now narrow (button-width), Delete ends at the table's right edge, "Actions" title left-aligned in the column, Name column takes the slack.

---

## 2026-08-31 — File table: deterministic column widths, "Actions" title lines up with Cut

**Goal / why.** Follow-up correction: with the shrink-to-fit attempt the Actions column was still browser-stretched wider than its buttons, so the left-aligned "Actions" title no longer sat above the Cut button. User's spec: *"a full width table inside the card, but the last section (actions) is aligned to the right in a way that the headline is aligned vertically to the left item (cut) so it's consistent to other items in the table, there can be empty space between the actions and uploaded".*

**Changes.**

| File | What |
|---|---|
| `static/index.html` | `table-layout: fixed` + explicit widths on the non-Name columns: Size 90 px, Uploaded 110 px, **Actions 150 px** (≈ exact button-row width incl. cell padding); only the Name column is variable, so it absorbs all the table slack and the table stays full-width. Numeric columns got `overflow: hidden` against locale/size string surprises. Button row is `flex; justify-content: space-between` across the narrow fixed cell — Cut's left edge now lands exactly under the (left-aligned) header, Delete ends at the table's right edge, with at most a few px between the two. |

**Decisions.**

- `table-layout: fixed` is the key: with auto layout the browser distributes leftover width to *all* columns (not only Name), which is what kept stretching the Actions column and misaligning the title. Fixed widths make the geometry deterministic; the 150 px Actions width has ~4 px of headroom over the measured button row (≈126 px + 20 px cell padding), so even if button text metrics drift slightly, Cut stays flush under the header.
- `space-between` is back on purpose: with a *fixed narrow* column (unlike the earlier wide-column version that the user rejected), the internal Cut–Delete gap is a few pixels — invisible — while space-between guarantees header/Cut alignment regardless of width drift.
- The slack lives in the Name column (long names wrap, as before) rather than between Uploaded and Actions; either way the user accepted "empty space between actions and uploaded" as tolerable, and the visual result matches their spec: Actions block at the right end, title above Cut.

**Verification.** `server.py` untouched. The running scratch server (:8099) re-serves the static file (fixed-layout rules confirmed in served HTML); page opened in the in-app browser — table is full-width, Size/Uploaded/Actions columns hug their content, "Actions" title sits directly above Cut, Delete ends at the card's right edge, Name absorbs the remainder. Mobile (≤640 px) hides the Uploaded column as before; fixed widths still apply.

---

## 2026-08-31 — File table: spacer-column layout (logged late) + mobile-overflow finding

**Goal / why.** The previous logged round ("File table: deterministic column widths") solved the Actions alignment with `table-layout: fixed` + explicit widths (90/110/150 px). The user then reported a new symptom: *"now the actions section is good, however uploaded column content is now cut, can you make it so that name, size and uploaded are hugged and aligned to the left so if there's empty space in the table it's located between uploaded and actions."* Fixed widths were clipping the Uploaded cell, so the table was re-laid-out with an **auto-layout spacer column** that absorbs the slack. The user committed this round as **`ff237ef` "ui fixes" before it was ever logged here** — so the changelog's last entry (fixed-width) no longer matched the code. This entry logs that round to fix the record.

**Changes.**

| File | What |
|---|---|
| `static/index.html` | Replaced `table-layout: fixed` + explicit column widths with an **auto-layout spacer column**: a 5th empty column (`th.spacer, td.spacer { width: 100% }`) between Uploaded and Actions. In the auto table layout it absorbs *all* the leftover width, so Name/Size/Uploaded hug their content (left-aligned, never clipped) and the Actions column (sized to its buttons) stays pinned to the right edge with the left-aligned "Actions" header above Cut. `td.name` switched from `word-break: break-all` to `white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 560px` (break-all let the auto layout squeeze the Name column below its content and wrap short names — the "desi / gn.h / pgL" symptom; nowrap keeps the name on one line, max-width bounds pathologically long names, and a JS-set `title` tooltip — only when actually clipped — covers the tail). `.table-wrap { overflow-x: auto }` added as a last-resort containment so an extreme name can't spill the card. `.row-actions` → `flex; justify-content: space-between; gap: 6px; white-space: nowrap` (Cut's left edge under the header, Delete at the right edge). Mobile (≤640 px): the spacer and Uploaded columns are hidden and `td.name` switches back to `white-space: normal; word-break: break-all; max-width: 100%` so names wrap and rows fit narrow screens. |
| `README.md` | No change — the table layout is a pure-frontend concern the README doesn't document. (The `ff237ef` commit also added the one-line License section, but that is already covered by the "Project moved under git + MIT license" entry above.) |

**Decisions.**

- **Auto layout + spacer instead of `table-layout: fixed`**: fixed widths were the source of the Uploaded clipping. With auto layout, Name/Size/Uploaded size to their content and the `width: 100%` spacer column soaks up the remaining space, landing the gap *between* Uploaded and Actions — exactly the layout the user described. The Actions column stays button-width at the right edge; the left-aligned "Actions" header sits above Cut (the confirmed target from the prior rounds).
- **Name = nowrap + max-width + conditional tooltip** (see Changes) — deliberate: unbreakable names, a hard cap for pathological filenames, and a hover tooltip only when the name is actually elided.
- **The earlier "mobile body overflow" was a test artifact, not a CSS bug.** A previous measurement reported the cards "wider than the 400 px viewport." dump-dom via headless Chrome showed `--window-size=400,800` in **new** headless Chrome yields `innerWidth=500` — new headless Chrome clamps the window to a **500 px minimum**. At the clamped 500 px all geometry is exactly correct (body = 500 = viewport; cards = 468 = 500 − 2×16; table = 434; no overflow), confirmed identical on the git-baseline file `3288b1d`. So there is no overflow bug to fix; **real phone widths below 500 px simply cannot be exercised in new headless Chrome** (noted under Open work).

**Verification.** The layout is the state committed as `ff237ef`; confirmed the current `static/index.html` table CSS matches that commit (spacer column, nowrap+ellipsis name, `.table-wrap`, `.row-actions` space-between, mobile rules). This session's headless-Chrome screenshots show: desktop (1280) → Name/Size/Uploaded left-hug, gap between Uploaded and Actions, "Actions" header above Cut, Delete at the card's right edge; mobile (500, the headless floor) → Uploaded column hidden, names wrap, the three action buttons fit, **no body overflow**. The 500 px clamp was verified via dump-dom (`innerWidth=500` at `--window-size=400`) for both the current file and baseline `3288b1d`. `server.py` untouched.

---

## 2026-08-31 → 2026-09-01 — Per-file Preview: in-browser HPGL drawing in a modal

**Goal / why.** User: *"create a preview button for each file which would open a 2D drawing of the hpgl file"* … *"create it as a modal, hpgl/2 format can give error 'hpgl/2 not supported'. set some values for the store and such and let's tweak it later if necessary, preview button should be located in the actions."* So: a per-row Preview button that fetches the file and renders its cut path + pen travel as an SVG in a modal; binary HPGL/2 (large-format plotters) shows the user-requested error.

**Changes.**

| File | What |
|---|---|
| `server.py` | New `GET /api/file?name=NAME` → `_api_file()`: returns the raw file bytes as `application/octet-stream` with `Cache-Control: no-store`, reusing the existing `_upload_path()` traversal guard (missing / `..` / empty → 404). octet-stream on purpose — binary HPGL/2 must reach the browser byte-exact so the UI can detect and reject it. |
| `static/index.html` | (1) **Preview button** in the per-row actions between Cut and Delete (neutral style, no class; tooltip "Open a 2D drawing of the cut"; always enabled → `previewFile(name)`). (2) **Modal** (`#preview.modal-overlay[hidden]`): head with `#preview-name` (monospace, ellipsis) + `#preview-dims` + Close; `#preview-body` (the SVG canvas); `#preview-legend`. Closes via button, backdrop click, or Escape; a `previewToken` counter invalidates an in-flight fetch when the modal is closed or superseded. (3) **CSS** block: overlay `fixed; inset:0; rgba(5,8,12,.72); flex; z-index:100` with `[hidden]{display:none}` (required — the `display:flex` would otherwise beat the `hidden` attribute); `.modal{width:min(880px,100%); max-height:100%}`; `#preview-body{height:min(58vh,560px)}`; legend swatches (solid accent = cut, dashed dim = pen travel); `.preview-msg[.error]` centered (error = `--red`). (4) **`parseHPGL(text)`**: splits on `;`; command regex `^([A-Za-z]{1,3})(.*)$` *without requiring a separator* (real cutter files write `PU359,1011`); pairs all numbers. PU/SU/XY = pen-up, PD/SD/SP = cut, bare coords repeat the last motion (spec), `IN` reset, `SF` scale (inches/unit), `AM` relative, `AC` polar; everything else ignored. (5) **`isBinaryHPGL(bytes)`**: any byte outside printable ASCII (except tab/LF/CR) → binary → preview shows `hpgl/2 not supported`. (6) **`renderHpglPreview()`**: bbox from cuts (fallback moves; zero-area guard), 5% pad, **y-flip** (HPGL y-up → SVG y-down), one `<path>` for moves (dashed `--dim` 1 px) + one for cuts (solid `--accent` 1.5 px, round caps), both `vector-effect:non-scaling-stroke`; `viewBox` + `preserveAspectRatio="xMidYMid meet"` = automatic zoom-to-fit. Dims line `≈ W × H in` (bbox × SF scale, adaptive decimals); legend lists only what's present. |
| `README.md` | Features bullet for Preview (incl. the hpgl/2 note + "printing them still works") + a `GET /api/file?name=design.hpgl` API-table row. |

**Decisions.**

- **`GET /api/file` returns raw octet-stream** (not a rendered image or a download link): the browser needs the exact bytes to (a) detect binary HPGL/2 and (b) parse text HPGL client-side. Rendering stays 100% in the browser, so the server stays stdlib-only / zero-deps.
- **Preview button is neutral-styled (no class), order Cut | Preview | Delete** — matches the confirmed convention that only Cut (primary/blue) and Delete / Clear-all (red hover) carry special colors; Preview is a read-only action.
- **Moves-only files render as dashed pen travel** (honest: the cutter would cut nothing) rather than an error — the geometry is still shown. No coordinates at all → red "no drawing found".
- **Binary detection = full byte scan** (any non-printable byte) → the user-requested `hpgl/2 not supported`.
- **Placeholder render values (the user explicitly said "set some values… and let's tweak it later"):** cut stroke `--accent` 1.5 px, pen travel `--dim` 1 px dashed `3 3`, non-scaling strokes, 5% bbox pad, `#preview-body` `min(58vh,560px)`, modal `min(880px,100%)`, dims `≈ W × H in`, and **default scale = 1.0 inch/unit when a file has no `SF`**. None of the current uploads carry an `SF`, so `napit.hpgl` reads `≈ 3712 × 4660 in` — the relative geometry is correct but the absolute inch readout is a placeholder pending the user's unit convention (see Open work).
- **Parser v1 limitations**: the spec's interleaved `X1 2 3 Y4 5 6` list form parses as sequential pairs; a trailing unpaired number is dropped; colors/fills/arcs/text are ignored.

**Verification.** `python3 -m py_compile server.py` OK. Screenshots via headless Chrome against a throwaway scratch server (:8098, sharing `uploads/`; a temporary router line let it serve the debug auto-open pages — reverted afterward): `napit.hpgl` → modal with 6 circles (blue cuts) + dashed pen travel, both legend items, `≈ 3712 × 4660 in`; `sample_logo.hpgl` (`IN;SF;XY0,0X120,0Y120,120X0,120;SP;`) → dashed 120×120 square, "pen travel" legend only; an 11-byte binary HPGL/2 → centered red `hpgl/2 not supported`; mobile (500 px, the new-headless floor) → the modal fits the viewport. Desktop + mobile table screenshots confirm the 3-button actions row and the spacer layout are intact. `GET /api/file` via curl: `napit.hpgl` → 3530 bytes identical to the file; missing / `../server.py` / `..` / empty → all 404. Parser: re-ran the 20-case unit suite — all PASS (all 3 real files, AM1 relative accumulation, polar diamond closes at origin, bare-pair repetition, motion-tracking PD→PU, SF with/without space, lowercase commands, binary detection, empty input). Cleaned up after: removed the 3 throwaway `static/_dbg_p*.html` pages (static/ = `index.html` only), deleted the `fake_hpgl2.hpgl` test upload, killed the :8098 scratch server, reverted the temporary router patch (server.py diff vs HEAD = only the `/api/file` route + `_api_file`).

---

## 2026-09-01 — Printer dropdown shows USB identity (e.g. `/dev/usb/lp0 - samsung 2010`)

**Goal / why.** User: *"when selecting the printer like /dev/usb/lp0 it's hard to see which device it is, can you add a detail after the device address … this info can be obtained with lsusb or some other way if there's a better way to identify it from the actual device".* The real box has both `lp0` and `lp1` (and numbers shift on replug), so bare node names in the dropdown are indistinguishable.

**Changes.**

| File | What |
|---|---|
| `server.py` | New `_usb_label(path)`: `stat`s the node, resolves its major:minor through sysfs (`/sys/dev/char/M:m` symlink), follows the kernel device's `device` link, then walks **up** the sysfs tree (≤6 levels) to the USB device dir; label = `manufacturer product` (trimmed), falling back to `idVendor:idProduct` when the name strings are empty, else `None`. `SYSFS` env var (default `/sys`) makes the sysfs root overridable (testing / non-standard mounts). `GET /api/devices` entries now carry `label`; the `POST` switch response returns the label of the newly selected device; the startup `devices :` banner prints `path - label`. |
| `static/index.html` | Dropdown option text is now `path - label` (plus the existing ` (missing)` suffix when the node is gone); the label is part of the change-detection key so a (re)plugged device rebuilding its identity refreshes the options; the `printer → …` toast includes the label. |
| `README.md` | Features bullet (identity in the dropdown, `lsusb`-free, bare-path fallback), `SYSFS` config-table row, "How printing works" note (identity lets lp0/lp1 be told apart), `/api/devices` API row now `[{path, exists, label}]`. |

**Decisions.**

- **sysfs instead of parsing `lsusb` output.** Zero dependencies (no `subprocess`, no `usbutils` install) and *exact*: the node's own major:minor via `/sys/dev/char` maps to precisely that device, with no bus/address matching heuristics. It also works identically for `/dev/usb/lpX` (usb/lp raw driver) and `/dev/lpX` (lp class driver) — the `device`-link follow + up-walk covers both sysfs shapes. The strings read (`manufacturer`, `product`) are the same ones `lsusb` displays, so users can still cross-check against `lsusb`.
- **Fallback chain** manufacturer+product → `idVendor:idProduct` → bare path (`label: null`); non-Linux hosts, missing nodes and non-USB devices just show the path as before (no crash, no clutter).
- **No caching** — the label is re-read on every device poll (a few tiny sysfs reads per 2.5 s, negligible), so a replugged/re-identified device is always fresh.
- The label is **display-only**: the actual `cat >` command, the `cat →` job message and the permission fix hint keep using the bare path (that's what the shell targets).

**Verification.** `py_compile` OK. 12-case suite against fake sysfs trees (built via the `SYSFS` override): usb/lp-shaped node → `samsung 2010`; USB dev without name strings → `05e3:0430` fallback (both via direct link and via a nested lp-class link that needed the up-walk); non-USB virtual device → `None`; dangling chardev symlink → `None`; regular file / missing path → `None`. End-to-end on a throwaway server (:8098, `SYSFS` pointed at a fake tree where `/dev/null`'s real major:minor maps to a fake samsung/2010 USB device): `GET /api/devices` → `label: "samsung 2010"`, `POST` switch returns it, served index contains the label code, startup banner prints `/dev/null - samsung 2010`. Live :8099 instance restarted with the new code — on this Mac all labels are `null` (no sysfs USB identity), so the dropdown is unchanged there. **Not verified on the user's Linux box** — user to confirm the dropdown shows the real names for `lp0`/`lp1`.

---

## 2026-09-01 — Quiet refresh: no-op polls stop touching the DOM, scroll never jumps

**Goal / why.** User: *"when running in actual server with many files (16) the page reloads or refreshes continuously (every 2sec or so) and when it reloads it scrolls to the top of the page which makes this hard to use".* The page never actually reloads — the 2.5 s background poll unconditionally rebuilt the whole file table and the job list (`innerHTML = ""` + re-append every 2.5 s), and each rebuild makes the browser's scroll anchoring re-evaluate the viewport, so with a tall list the view jumped while reading.

**Changes.** (`static/index.html` only — `server.py` untouched, and the server serves the static file per request, so no restart is needed to deploy this)

| File | What |
|---|---|
| `static/index.html` | (1) `renderFiles()` now computes a render key — `JSON.stringify([filter, sort, cfg.printer_dev, files])` — and returns early when it equals the previous render: in steady state the poll does **not** touch the table at all (no flicker, no layout churn). `cfg.printer_dev` is in the key so switching the printer in the header re-renders the rows and the per-row Cut tooltips (which embed the device path) stay current. (2) `renderJobs()` gets the same early return, keyed on the whole jobs payload. (3) New `withPreservedScroll(fn)` helper: saves `scrollTop` of `document.scrollingElement` and every `.table-wrap`, runs `fn`, restores immediately **and** again on a double `requestAnimationFrame` (after the new frame has laid out and the browser's scroll anchoring has had its say). `refresh()` wraps both renders in it, and so do the search-filter and sort-click handlers. |
| `README.md` | One sentence on the job-status feature bullet: polls every 2.5 s, re-renders only on real change, never moves your scroll position. |

**Decisions.**

- **Two-layer fix, in that order.** The key comparison kills the churn in the common case (nothing changed between polls → the page is literally static, which is what "constantly refreshing" was); scroll preservation covers the cases that *do* rebuild (new job, file added/deleted, filter/sort, printer switch) so the viewport stays where the user is even though content below/around them changes. Lengthening the poll interval was deliberately **not** done — it would only delay job-status updates and would still jump on the changes that do happen.
- Full `JSON.stringify` comparison (no diffing library, zero deps): the payloads are tiny (a few dozen entries) and the cost is negligible against the 2.5 s cycle.
- The device select was already change-gated (`devicesKey`) in an earlier round; it needed no change. The toast is `position:fixed` and never affects layout, so it's outside the concern.

**Verification.** Frontend-only round; verified in **real headless Chrome driven over CDP** (Node's built-in WebSocket, no deps) against a scratch server on :8097 with a scratch upload dir containing **16** `.hpgl` files (the user's trigger case), window 1280×600 — all 10 checks PASS:

- page renders 16 rows; scrolled to `y=300`
- 8 s of polling (3+ cycles, identical data) → the first row's **original DOM node is still in place** (zero rebuilds) and `scrollY` is still 300
- triggered a print (job queued→done) → the job list rebuilt, the file-table row node was **kept**, `scrollY` 300, pill shows `done`
- `DELETE`d one file → the file table rebuilt (15 rows, the marked row gone) and `scrollY` still 300
- zero page JS exceptions across the whole run

Scratch server + fake files removed after the test. `server.py` untouched (no compile needed). **Not verified on the user's Linux box** — user to confirm the list no longer jumps with their 16 files.

---

## Open work / ideas

Not started — add new bullet points here as they come up, and move them into a dated entry when they get done.

- **Deploy on the Linux cutter box — IN PROGRESS.** Printing fails with `Permission denied`; `sudo usermod -aG lp $USER` reportedly did not help and `chmod` on the node resets at boot. Known facts: node is `crw-rw---- root lp` (mode 660, group `lp`); the machine currently has **both** `/dev/usb/lp0` and `/dev/usb/lp1` (numbers shift between boots/replugs). Remaining steps for the user: re-login (groups apply to new sessions only) → **restart the app** (a running process keeps its old groups — most likely why `usermod` "didn't help") → `: > /dev/usb/lp0 && echo ok`. If it still fails: is the app run under a systemd service? Then add `SupplementaryGroups=lp` (documented in README). If the node's group is not `lp` on that distro, the in-UI fix hint + `ls -l /dev/usb/lp*` will show which group is required. The new header dropdown now lists both `lp0`/`lp1` automatically, and each entry shows the USB identity read from sysfs (see the 2026-09-01 entry), so the two nodes can be told apart in the UI without running `lsusb`. Still open: user to paste the cutter's `lsusb` vendor:product IDs so we can write the exact stable-`/dev/vinylcutter` udev symlink rule (recipe with placeholders is in the README).
- **A live test instance is still running** on this Mac: pid in `/tmp/vcwui.pid`, port **8099**, started with `--printer-dev /dev/null --dev-scan "/dev/null,/tmp/printer*"` (fake LP nodes in `/tmp`; stop: `kill $(cat /tmp/vcwui.pid)`). In **zsh** the `--dev-scan` value must stay quoted — an unquoted `/tmp/printer*` glob aborts startup if nothing matches. This running instance now includes the `GET /api/file` preview endpoint and the device USB-identity feature (labels are `null` on the Mac — no sysfs USB; on the Linux box they will show).
- **Preview scale/unit — pending user input.** Files without an `SF` command assume **1 unit = 1 inch**, so `napit.hpgl` reads `≈ 3712 × 4660 in` (the relative geometry is correct; the absolute inch readout is a placeholder). User to confirm the unit convention / a default scale factor so the size readout matches the real design size. (The other preview values — stroke widths, 5% pad, body/modal sizes, dims format — are also placeholders the user said to "tweak later".)
- **<500 px phone widths can't be verified in new headless Chrome** — it clamps the window to a 500 px minimum (a test artifact, not a layout bug; see the 2026-08-31 table entry). Mobile layout is verified down to 500 px only.
- Ideas not yet requested (do only if the user asks): print progress via bytes written, job cancel, basic auth token, persisting the UI device choice across restarts (currently runtime-only on purpose).
