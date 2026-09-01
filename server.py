#!/usr/bin/env python3
"""
Vinyl Cutter Web UI — minimal, zero-dependency server (Python 3 stdlib only).

Uploads HPGL files over HTTP (stored in an upload folder on the server) and
prints them raw to the cutter exactly the way you already do it in bash:

    cat <file> > /dev/usb/lp1

Run:
    python3 server.py
    python3 server.py --port 8080 --printer-dev /dev/usb/lp1 --upload-dir /var/lib/vinylcutter

Everything can also be configured via environment variables:
    PORT, BIND, UPLOAD_DIR, PRINTER_DEV, ALLOWED_EXTS, PRINT_TIMEOUT, MAX_UPLOAD_MB, DEV_SCAN, SYSFS
"""

from __future__ import annotations

import argparse
import fnmatch
import glob
import json
import mimetypes
import os
import re
import shlex
import stat
import subprocess
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from queue import Queue
from urllib.parse import parse_qs, urlparse

APP_DIR = Path(__file__).resolve().parent
STATIC_DIR = APP_DIR / "static"

# sysfs root; overridable (SYSFS env) for testing or non-standard mounts.
SYSFS = Path(os.environ.get("SYSFS", "/sys"))

# Filled in from CLI/env in main().
CFG: dict = {}

# --------------------------------------------------------------------------
# Print jobs
# --------------------------------------------------------------------------

MAX_JOBS = 50
_jobs: dict = {}
_jobs_lock = threading.Lock()
_queue: "Queue[str]" = Queue()


def _update_job(job_id: str, **fields) -> None:
    with _jobs_lock:
        job = _jobs.get(job_id)
        if job is not None:
            job.update(fields)


def _enqueue_job(filename: str) -> dict:
    job = {
        "id": uuid.uuid4().hex[:8],
        "file": filename,
        "status": "queued",  # queued | printing | done | error
        "message": "waiting in queue",
        "hint": "",  # optional remediation text, set when an error has a known fix
        "created": time.time(),
        "started": None,
        "finished": None,
    }
    with _jobs_lock:
        _jobs[job["id"]] = job
        if len(_jobs) > MAX_JOBS:
            oldest = sorted(_jobs, key=lambda k: _jobs[k]["created"])[: len(_jobs) - MAX_JOBS]
            for k in oldest:
                _jobs.pop(k, None)
    _queue.put(job["id"])
    return job


def _run_job(job_id: str) -> None:
    with _jobs_lock:
        job = _jobs.get(job_id)
    if job is None:
        return

    upload_dir = CFG["upload_dir"].resolve()
    path = (upload_dir / job["file"]).resolve()
    try:
        path.relative_to(upload_dir)
    except ValueError:
        _update_job(job_id, status="error", message="invalid path", finished=time.time())
        return
    if not path.is_file():
        _update_job(job_id, status="error", message="file no longer exists", finished=time.time())
        return

    device = CFG["printer_dev"]
    # Exactly the bash equivalent of:  cat <file> > /dev/usb/lp1
    cmd = f"cat {shlex.quote(str(path))} > {shlex.quote(device)}"

    started = time.time()
    _update_job(job_id, status="printing", message=f"cat → {device}", started=started)

    try:
        size = path.stat().st_size
        proc = subprocess.run(["sh", "-c", cmd], capture_output=True, timeout=CFG["print_timeout"])
    except subprocess.TimeoutExpired:
        _update_job(job_id, status="error",
                    message=f"timed out after {CFG['print_timeout']:.0f}s",
                    started=started, finished=time.time())
        return
    except OSError as exc:
        _update_job(job_id, status="error", message=str(exc),
                    started=started, finished=time.time())
        return

    hint = ""
    if proc.returncode < 0:
        message = f"cat terminated by signal {-proc.returncode} (printer offline or busy?)"
        status = "error"
    elif proc.returncode != 0:
        err = proc.stderr.decode("utf-8", "replace").strip()
        message = (err or f"exit code {proc.returncode}")[:300]
        status = "error"
        if "permission denied" in err.lower():
            hint = (
                "fix on the server machine:\n"
                "  1) sudo usermod -aG lp $USER      # add your user to the printer group\n"
                "  2) log out and log back in, then restart the vinyl cutter web ui\n"
                f"  3) verify: : > {device} && echo ok"
            )
    else:
        message = f"{size} bytes written to {device}"
        status = "done"

    _update_job(job_id, status=status, message=message, hint=hint, finished=time.time())


def _job_worker() -> None:
    """Single worker thread: print jobs run one at a time, in queue order."""
    while True:
        _run_job(_queue.get())


# --------------------------------------------------------------------------
# Path helpers
# --------------------------------------------------------------------------

def _sanitize(name: str) -> str:
    """Make an uploaded filename safe to use on disk."""
    name = Path(name).name
    name = re.sub(r"[^A-Za-z0-9._-]", "_", name).strip(".")
    return name or "upload"


def _upload_path(name: str):
    """Resolve a user-supplied filename inside the upload dir, or None if unsafe."""
    if not name or name in (".", "..") or "/" in name or "\\" in name:
        return None
    path = (CFG["upload_dir"] / _sanitize(name)).resolve()
    try:
        path.relative_to(CFG["upload_dir"].resolve())
    except ValueError:
        return None
    return path


def _is_printable(path: Path) -> bool:
    return path.suffix.lower().lstrip(".") in CFG["allowed_exts"]


def _sysfs_text(path: Path, max_bytes: int = 64) -> str:
    try:
        return path.read_bytes()[:max_bytes].decode("utf-8", "replace").strip()
    except OSError:
        return ""


def _usb_label_from_syslink(link: Path) -> str | None:
    """Walk a /sys/dev/char/M:m entry up to the USB device and read its identity."""
    if not link.is_symlink():
        return None
    try:
        dev = (link.parent / os.readlink(link)).resolve()
    except OSError:
        return None
    # Kernel device dir; `device` points at the physical (USB) device.
    if (dev / "device").is_symlink():
        dev = (dev / "device").resolve()
    # USB interface dirs (usb/lp or lp class) have no idVendor — walk up to the usb device.
    for _ in range(6):
        if (dev / "idVendor").is_file():
            break
        if dev.parent == dev:
            return None
        dev = dev.parent
    if not (dev / "idVendor").is_file():
        return None
    name = " ".join(
        part for part in (_sysfs_text(dev / "manufacturer"), _sysfs_text(dev / "product")) if part)
    if name:
        return name
    vid, pid = _sysfs_text(dev / "idVendor"), _sysfs_text(dev / "idProduct")
    if vid and pid:
        return f"{vid}:{pid}"
    return None


def _usb_label(device_path: str) -> str | None:
    """Human-readable identity of a device node (e.g. "samsung 2010").

    Resolves the node's major:minor through sysfs — works for both the raw
    /dev/usb/lpX nodes (usb/lp driver) and /dev/lpX class nodes (lp driver).
    None when undeterminable (non-Linux host, missing node, non-USB device)."""
    try:
        st = os.stat(device_path)
    except OSError:
        return None
    if not stat.S_ISCHR(st.st_mode):
        return None
    link = SYSFS / "dev" / "char" / f"{os.major(st.st_rdev)}:{os.minor(st.st_rdev)}"
    return _usb_label_from_syslink(link)


def _list_printer_devices() -> list:
    """Auto-detected LP devices (dev-scan globs) plus the currently configured one."""
    found: dict = {}
    for pat in CFG["dev_scan"]:
        for p in glob.glob(pat):
            found[p] = True
    found.setdefault(CFG["printer_dev"], os.path.exists(CFG["printer_dev"]))
    return [{"path": p, "exists": e, "label": _usb_label(p)} for p, e in sorted(found.items())]


def _valid_device_path(p: str) -> bool:
    """A device a web client may select: safe chars, no '..', and /dev/* or a dev-scan match."""
    if not p or ".." in p or not re.fullmatch(r"/[A-Za-z0-9._/-]+", p):
        return False
    if p.startswith("/dev/"):
        return True
    return any(fnmatch.fnmatchcase(p, pat) for pat in CFG["dev_scan"])


def _parse_multipart(body: bytes, content_type: str):
    """Minimal multipart/form-data parser. Returns list of (headers_dict, content_bytes)."""
    m = re.search(r"boundary=([^;]+)", content_type or "")
    if not m:
        return []
    boundary = m.group(1).strip().strip('"').encode("latin-1")
    delim = b"--" + boundary

    parts = []
    for seg in body.split(delim):
        if seg in (b"", b"--", b"--\r\n", b"--\n"):
            continue
        if seg.startswith(b"\r\n"):
            seg = seg[2:]
        elif seg.startswith(b"\n"):
            seg = seg[1:]
        else:
            continue  # preamble
        if seg.endswith(b"\r\n"):
            seg = seg[:-2]
        elif seg.endswith(b"\n"):
            seg = seg[:-1]
        head, sep, content = seg.partition(b"\r\n\r\n")
        if not sep:
            head, sep, content = seg.partition(b"\n\n")
        if not sep:
            continue
        headers = {}
        for line in head.decode("latin-1").splitlines():
            if ":" in line:
                key, val = line.split(":", 1)
                headers[key.strip().lower()] = val.strip()
        parts.append((headers, content))
    return parts


# --------------------------------------------------------------------------
# HTTP handler
# --------------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    server_version = "VinylCutterWebUI/1.0"
    protocol_version = "HTTP/1.1"

    # -- plumbing ----------------------------------------------------------

    def _json(self, code: int, payload) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _error(self, code: int, message: str) -> None:
        self._json(code, {"error": message})

    def _body(self) -> bytes:
        length = int(self.headers.get("Content-Length") or 0)
        if length > CFG["max_upload_bytes"]:
            raise ValueError(f"body too large (max {CFG['max_upload_mb']} MB)")
        return self.rfile.read(length) if length else b""

    def log_message(self, fmt: str, *args) -> None:
        print(f"[{self.log_date_time_string()}] {self.address_string()} — {fmt % args}", flush=True)

    # -- static -------------------------------------------------------------

    def _serve_static(self) -> None:
        url = urlparse(self.path).path
        name = "index.html" if url in ("", "/") else url.lstrip("/")
        static_dir = STATIC_DIR.resolve()
        path = (static_dir / name).resolve()
        if not path.is_file() or not str(path).startswith(str(static_dir)):
            self._error(404, "not found")
            return
        ctype, _ = mimetypes.guess_type(str(path))
        self.send_response(200)
        self.send_header("Content-Type", ctype or "application/octet-stream")
        self.send_header("Content-Length", str(path.stat().st_size))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(path.read_bytes())

    # -- GET -----------------------------------------------------------------

    def do_GET(self) -> None:
        url = urlparse(self.path)
        try:
            if url.path in ("/", "/index.html"):
                self._serve_static()
            elif url.path == "/api/files":
                self._api_files()
            elif url.path == "/api/file":
                self._api_file()
            elif url.path == "/api/jobs":
                with _jobs_lock:
                    jobs = sorted(_jobs.values(), key=lambda j: j["created"], reverse=True)
                self._json(200, {"jobs": [dict(j) for j in jobs]})
            elif url.path == "/api/config":
                self._json(200, {
                    "printer_dev": CFG["printer_dev"],
                    "upload_dir": str(CFG["upload_dir"]),
                    "allowed_exts": [e.lstrip(".") for e in CFG["allowed_exts"]],
                })
            elif url.path == "/api/devices":
                self._json(200, {
                    "devices": _list_printer_devices(),
                    "current": CFG["printer_dev"],
                })
            else:
                self._error(404, "not found")
        except BrokenPipeError:
            pass
        except Exception as exc:  # noqa: BLE001
            self._error(500, f"internal error: {exc}")

    def _api_file(self) -> None:
        """Raw file bytes for the in-browser drawing preview (GET /api/file?name=NAME).

        octet-stream on purpose: binary HPGL/2 files must reach the browser
        byte-exact so the UI can detect and reject them."""
        qs = parse_qs(urlparse(self.path).query)
        name = (qs.get("name") or [""])[0]
        path = _upload_path(name)
        if path is None or not path.is_file():
            self._error(404, "file not found")
            return
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _api_files(self) -> None:
        files = []
        upload_dir = CFG["upload_dir"]
        if upload_dir.is_dir():
            for p in sorted(upload_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
                if not p.is_file():
                    continue
                st = p.stat()
                files.append({
                    "name": p.name,
                    "size": st.st_size,
                    "mtime": st.st_mtime,
                    "printable": _is_printable(p),
                })
        self._json(200, {"files": files})

    # -- POST -----------------------------------------------------------------

    def do_POST(self) -> None:
        url = urlparse(self.path)
        try:
            if url.path == "/api/upload":
                self._api_upload()
            elif url.path == "/api/print":
                self._api_print()
            elif url.path == "/api/devices":
                self._api_devices_set()
            else:
                self._error(404, "not found")
        except BrokenPipeError:
            pass
        except Exception as exc:  # noqa: BLE001
            self._error(500, f"internal error: {exc}")

    def _api_upload(self) -> None:
        ctype = self.headers.get("Content-Type", "")
        if "multipart/form-data" not in ctype:
            self._error(400, "expected multipart/form-data")
            return

        body = self._body()
        saved, skipped = [], []
        for headers, content in _parse_multipart(body, ctype):
            m = re.search(r'filename="?([^";]+)"?', headers.get("content-disposition", ""))
            if not m:
                continue  # plain form field, not a file
            original = m.group(1)
            name = _sanitize(original)
            if not _is_printable(Path(name)):
                skipped.append(
                    f"{original}: not an allowed file type ({', '.join('.' + e for e in CFG['allowed_exts'])})")
                continue
            dest = CFG["upload_dir"] / name
            dest.write_bytes(content)  # re-uploading the same name replaces the old copy
            saved.append({"name": name, "size": len(content)})

        if not saved and skipped:
            self._error(400, "; ".join(skipped))
        else:
            self._json(200, {"saved": saved, "skipped": skipped})

    def _api_print(self) -> None:
        try:
            data = json.loads(self._body() or b"{}")
        except (ValueError, json.JSONDecodeError):
            self._error(400, "invalid JSON")
            return

        names = data.get("files")
        if names is None and data.get("file"):
            names = [data["file"]]
        if isinstance(names, str):
            names = [names]
        if not names:
            self._error(400, "no files to print")
            return

        jobs, skipped = [], []
        for name in names:
            name = str(name)
            path = _upload_path(name)
            if path is None or not path.is_file():
                skipped.append(f"{name}: not in upload folder")
                continue
            if not _is_printable(path):
                skipped.append(f"{name}: file type not allowed")
                continue
            jobs.append(_enqueue_job(path.name))

        if jobs:
            self._json(200, {"jobs": [{"id": j["id"], "file": j["file"]} for j in jobs],
                             "skipped": skipped})
        else:
            self._error(400, "; ".join(skipped))

    def _api_devices_set(self) -> None:
        """Switch the print target at runtime (affects subsequent print jobs)."""
        try:
            data = json.loads(self._body() or b"{}")
        except (ValueError, json.JSONDecodeError):
            self._error(400, "invalid JSON")
            return
        dev = str(data.get("device") or "")
        if not _valid_device_path(dev):
            self._error(400, "device must be a /dev/... path or match a --dev-scan pattern")
            return
        CFG["printer_dev"] = dev
        self._json(200, {"current": dev, "label": _usb_label(dev)})

    # -- DELETE ----------------------------------------------------------------

    def _api_jobs_clear(self) -> None:
        """Clear finished jobs from the in-memory log; running jobs keep going."""
        with _jobs_lock:
            finished = [k for k, j in _jobs.items() if j["status"] in ("done", "error")]
            for k in finished:
                _jobs.pop(k, None)
        self._json(200, {"cleared": len(finished)})

    def do_DELETE(self) -> None:
        url = urlparse(self.path)
        try:
            if url.path == "/api/jobs":
                self._api_jobs_clear()
                return
            elif url.path != "/api/files":
                self._error(404, "not found")
                return
            qs = parse_qs(url.query)
            name = (qs.get("name") or [""])[0]
            path = _upload_path(name)
            if path is None:
                self._error(400, "invalid file name")
                return
            if path.is_file():
                path.unlink()
                self._json(200, {"deleted": path.name})
            else:
                self._error(404, "file not found")
        except BrokenPipeError:
            pass
        except Exception as exc:  # noqa: BLE001
            self._error(500, f"internal error: {exc}")


# --------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Minimal vinyl cutter web UI (upload HPGL files, print via cat > /dev/usb/lpX)")
    parser.add_argument("--bind", default=os.environ.get("BIND", "0.0.0.0"),
                        help="interface to listen on (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8080")))
    parser.add_argument("--upload-dir", default=os.environ.get("UPLOAD_DIR", str(APP_DIR / "uploads")),
                        help="where uploaded files are stored")
    parser.add_argument("--printer-dev", default=os.environ.get("PRINTER_DEV", "/dev/usb/lp1"),
                        help="raw printer device, e.g. /dev/usb/lp1")
    parser.add_argument("--allowed-exts", default=os.environ.get("ALLOWED_EXTS", "hpgl,hgl"),
                        help="comma-separated allowed file extensions (default: hpgl,hgl)")
    parser.add_argument("--print-timeout", type=float,
                        default=float(os.environ.get("PRINT_TIMEOUT", "600")),
                        help="seconds to wait for a print job (default: 600)")
    parser.add_argument("--dev-scan", default=os.environ.get("DEV_SCAN", "/dev/usb/lp*,/dev/lp*"),
                        help="comma-separated glob patterns for auto-detecting printer devices "
                             "(default: /dev/usb/lp*,/dev/lp*)")
    parser.add_argument("--max-upload-mb", type=int,
                        default=int(os.environ.get("MAX_UPLOAD_MB", "100")))
    args = parser.parse_args()

    CFG.update({
        "upload_dir": Path(args.upload_dir).expanduser().resolve(),
        "printer_dev": args.printer_dev,
        "allowed_exts": tuple(e.strip().lstrip(".").lower()
                              for e in args.allowed_exts.split(",") if e.strip()),
        "print_timeout": args.print_timeout,
        "max_upload_mb": args.max_upload_mb,
        "max_upload_bytes": args.max_upload_mb * 1024 * 1024,
        "dev_scan": tuple(p.strip() for p in args.dev_scan.split(",") if p.strip()),
    })
    CFG["upload_dir"].mkdir(parents=True, exist_ok=True)

    threading.Thread(target=_job_worker, daemon=True, name="print-queue").start()

    httpd = ThreadingHTTPServer((args.bind, args.port), Handler)
    exts = ", ".join("." + e.lstrip(".") for e in CFG["allowed_exts"])
    print(f"Vinyl Cutter Web UI → http://{args.bind}:{args.port}")
    print(f"  uploads : {CFG['upload_dir']}   (accepted: {exts})")
    print(f"  printer : {CFG['printer_dev']}   (cat <file> > {CFG['printer_dev']})")
    found = ", ".join(
        d["path"] + (f" - {d['label']}" if d["label"] else "")
        for d in _list_printer_devices())
    print(f"  devices : {found or '(none found)'}   (switchable in the UI)")
    print("  ctrl-c to stop", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
