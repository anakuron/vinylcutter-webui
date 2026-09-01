# Vinyl Cutter Web UI

Minimal web UI for uploading HPGL files and printing them to a vinyl cutter
over raw USB — zero dependencies, Python 3 standard library only.

It does exactly what you do in bash:

```bash
cat design.hpgl > /dev/usb/lp1
```

## Features

- **Upload** HPGL files from a browser (drag & drop, multiple files). Files are
  saved into an upload folder on the server (default `./uploads`).
- **Cut** button per file. The server runs
  `cat <file> > <printer-dev>` for you; jobs run one at a time in queue order.
- **Switch the printer from the page header** — a dropdown lists every auto-detected
  device, so boxes with several `lpX` nodes (or a `vinylcutter` symlink) can change
  the print target without restarting the server. Each entry shows the device's USB
  identity (manufacturer + product) when it can be read from sysfs,
  e.g. `/dev/usb/lp0 - samsung 2010` — no `lsusb` or extra packages needed; if the
  identity can't be read (non-Linux host, non-USB device) the bare path is shown.
- **Search box** to filter the file list by name (client-side, no reload).
- **Preview** button per file — opens a 2D drawing of the cut in a modal. The HPGL
  is parsed in the browser (no server-side rendering); pen-up travel shows as a faint
  dashed line, the cut path in blue, with the drawing size in inches. Binary HPGL/2
  files (large-format plotters) can't be rendered and show `hpgl/2 not supported` —
  printing them still works as usual.
- **Sortable file list** — click the Name, Size or Uploaded column headers to sort
  ascending/descending (click again to flip direction).
- Live job status (queued → printing → done / error) and file deletion from the UI.
- Single file to deploy: `server.py` + `static/index.html`.

## Quick start

On the machine with the cutter:

```bash
python3 server.py
```

Then open `http://<server-ip>:8080` in a browser on the LAN.

## Configuration

CLI flags or environment variables:

| Flag | Env | Default | Description |
|---|---|---|---|
| `--bind` | `BIND` | `0.0.0.0` | Interface to listen on |
| `--port` | `PORT` | `8080` | HTTP port |
| `--upload-dir` | `UPLOAD_DIR` | `./uploads` | Where uploads are stored |
| `--printer-dev` | `PRINTER_DEV` | `/dev/usb/lp1` | Raw printer device to `cat` into |
| `--allowed-exts` | `ALLOWED_EXTS` | `hpgl,hgl` | Accepted file extensions |
| `--print-timeout` | `PRINT_TIMEOUT` | `600` | Seconds to wait for a print job |
| `--dev-scan` | `DEV_SCAN` | `/dev/usb/lp*,/dev/lp*` | Comma-separated globs for auto-detecting printer devices in the UI dropdown |
| `--max-upload-mb` | `MAX_UPLOAD_MB` | `100` | Max upload size |
| — | `SYSFS` | `/sys` | sysfs root, used to read the USB identity shown next to each printer device |

Example:

```bash
python3 server.py --port 9000 --printer-dev /dev/usb/lp0 --upload-dir /var/lib/vinylcutter
```

Selecting a printer in the UI dropdown only changes the **running** instance —
it is not saved anywhere. To make a choice permanent across restarts, set
`--printer-dev` / `PRINTER_DEV` in the command line or the systemd unit.

## Printer permissions (non-root)

The server process needs **write** access to the raw device. If you see
`sh: 1: cannot create /dev/usb/lp1: Permission denied`, the node exists but
its group doesn't include your user. Don't run as root — grant your user the
printer instead:

```bash
# 1. see who owns the node (Debian/Ubuntu/Raspbian: usually "root lp", mode 660)
ls -l /dev/usb/lp*

# 2. add yourself to that group (substitute the group from step 1 if it differs)
sudo usermod -aG lp $USER

# 3. log out and back in — group memberships only apply to new sessions,
#    then restart the server (a running process keeps its old groups)

# 4. verify without cutting anything
groups                           # should list lp
: > /dev/usb/lp1 && echo ok      # opens the device for write, sends no data

# 5. optional: cut a tiny 10-unit square to confirm end-to-end
printf 'IN;SF;XY0,0X10,10;SP;' > /dev/usb/lp1
```

Pin the permissions in udev so reboots and re-plugging the cutter can't
revert them:

```bash
sudo tee /etc/udev/rules.d/99-vinylcutter.rules <<'EOF'
KERNEL=="lp[0-9]*", MODE="0660", GROUP="lp"
EOF
sudo udevadm control --reload && sudo udevadm trigger
```

Prefer a dedicated group instead of `lp`? `sudo groupadd vinyl`, use
`GROUP="vinyl"` in the rule, `sudo usermod -aG vinyl $USER`.

**Stable device name (recommended).** The `lpX` number can change when the
cutter is re-plugged or after a reboot, which silently breaks a
`--printer-dev /dev/usb/lpN` setting. Pin a symlink named after your cutter
instead. Find its USB IDs:

```bash
lsusb    # note the <vendor>:<product> of the cutter line, e.g. 0403:6001
```

and add this line to the same rules file (it matches only your cutter's node
— `ATTRS{idVendor}` walks up to the parent USB device):

```bash
SUBSYSTEM=="lp", ATTRS{idVendor}=="0403", ATTRS{idProduct}=="6001", SYMLINK+="vinylcutter", MODE="0660", GROUP="lp"
```

Then `sudo udevadm control --reload && sudo udevadm trigger`, and run the app with `--printer-dev /dev/vinylcutter` — renumbering
stops mattering.

**systemd gotcha:** if the server runs as a service under a normal user, add
the group explicitly — systemd doesn't always honor `usermod` for a running
service:

```ini
[Service]
User=youruser
SupplementaryGroups=lp
```

then `sudo systemctl daemon-reload && sudo systemctl restart vinylcutter-webui`.

Last resort only: run the server as root (it works, but don't).

To find which `lpX` node your cutter is on:

```bash
lsusb                      # identify the device
sudo cat test.hpgl > /dev/usb/lp0   # try each node until the cutter runs
```

## systemd service (optional)

`/etc/systemd/system/vinylcutter-webui.service`:

```ini
[Unit]
Description=Vinyl Cutter Web UI
After=network-online.target

[Service]
WorkingDirectory=/opt/vinylcutter-webui
ExecStart=/usr/bin/python3 /opt/vinylcutter-webui/server.py --upload-dir /var/lib/vinylcutter --printer-dev /dev/usb/lp1
Restart=on-failure
User=youruser
SupplementaryGroups=lp

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now vinylcutter-webui
```

## How printing works

- `POST /api/print {"files": ["design.hpgl"]}` enqueues a job.
- A single worker thread runs jobs serially (the printer can only take one job):
  `sh -c 'cat <abs path> > <currently selected device>'` (default `/dev/usb/lp1`),
  then reports byte count or the error.
- If the machine has several `lpX` nodes, pick the right one in the page header —
  each dropdown entry shows the USB identity read from sysfs (manufacturer + product,
  or `idVendor:idProduct` as a fallback) so `lp0`/`lp1` can be told apart;
  the selected device is shown in the `cat →` job message and in the fix hint.
- A non-zero exit / signal (e.g. the device rejecting writes when the printer is
  offline) is reported in the job list.
- A **permission error** (your user lacks write access to the device) is reported
  with a fix hint right in the UI: `sudo usermod -aG lp $USER`, re-login,
  restart, and the `: > <device> && echo ok` check — see Printer permissions.
- The job list is in-memory (capped at 50) and can be cleared from the UI with
  **Clear all**; only *finished* jobs are removed, running jobs keep going and
  stay visible until they complete.

## API

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/files` | List uploaded files (name, size, mtime, printable) |
| `GET` | `/api/file?name=design.hpgl` | Raw file bytes (for the in-browser drawing preview) |
| `POST` | `/api/upload` | `multipart/form-data`, field `files` (multiple allowed) |
| `DELETE` | `/api/files?name=design.hpgl` | Delete an uploaded file |
| `DELETE` | `/api/jobs` | Clear finished jobs from the in-memory log (`{"cleared": n}`) |
| `POST` | `/api/print` | `{"files": ["a.hpgl", "b.hpgl"]}` or `{"file": "a.hpgl"}` — enqueues jobs |
| `GET` | `/api/jobs` | Job queue/status (newest first) |
| `GET` | `/api/config` | Printer device, upload dir, allowed extensions |
| `GET` | `/api/devices` | Auto-detected devices (`[{path, exists, label}]`) + currently selected one |
| `POST` | `/api/devices` | `{"device": "/dev/usb/lp0"}` — switch print target (affects subsequent jobs only) |

## Security notes

- Binds to all interfaces by default so LAN devices can reach it. Keep it behind
  a firewall/trust your network, or use `--bind 127.0.0.1` + SSH tunnel
  (`ssh -L 8080:localhost:8080 user@server`).
- There is no authentication by design (it's a small LAN tool). Upload names are
  sanitized to `[A-Za-z0-9._-]` and only the allowed extensions are accepted.

## License

MIT — see [LICENSE](LICENSE).
