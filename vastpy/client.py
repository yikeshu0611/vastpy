"""Localhost client for the Vast macOS large-file viewer."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


def api_candidates() -> list[Path]:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", ""))
        return [
            base / "com.zhangjing.Vast" / "api.json",
            base / "com.qo.vast" / "api.json",
        ]
    home = Path.home()
    return [
        home / "Library" / "Application Support" / "com.zhangjing.Vast" / "api.json",
        home
        / "Library"
        / "Containers"
        / "com.zhangjing.Vast"
        / "Data"
        / "Library"
        / "Application Support"
        / "com.zhangjing.Vast"
        / "api.json",
        # Legacy bundle id (pre-0.6.36)
        home / "Library" / "Application Support" / "com.qo.vast" / "api.json",
        home
        / "Library"
        / "Containers"
        / "com.qo.vast"
        / "Data"
        / "Library"
        / "Application Support"
        / "com.qo.vast"
        / "api.json",
    ]


def log_path() -> Path:
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA", "")) / "com.zhangjing.Vast" / "vast.log"
    home = Path.home()
    cands = [
        home / "Library" / "Application Support" / "com.zhangjing.Vast" / "vast.log",
        home
        / "Library"
        / "Containers"
        / "com.zhangjing.Vast"
        / "Data"
        / "Library"
        / "Application Support"
        / "com.zhangjing.Vast"
        / "vast.log",
    ]
    for p in cands:
        if p.exists():
            return p
    return cands[0]


def app_path() -> Path:
    if sys.platform == "win32":
        for p in (
            Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Vast" / "Vast.exe",
            Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Vast" / "Vast.exe",
        ):
            if p.exists():
                return p
        return Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Vast" / "Vast.exe"
    return Path("/Applications/Vast.app")


def pid_running(pid: Any) -> bool:
    try:
        pid_i = int(pid)
    except (TypeError, ValueError):
        return False
    if pid_i <= 0:
        return False
    if sys.platform == "win32":
        out = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid_i}", "/NH"],
            capture_output=True,
            text=True,
            check=False,
        )
        return str(pid_i) in (out.stdout or "")
    out = subprocess.run(
        ["ps", "-p", str(pid_i), "-o", "pid="],
        capture_output=True,
        text=True,
        check=False,
    )
    return str(pid_i) in (out.stdout or "")


def api_file() -> Path:
    cands = api_candidates()
    existing = [p for p in cands if p.exists()]
    if not existing:
        return cands[0]
    newest = existing[0]
    newest_mtime = -1.0
    for f in existing:
        try:
            mt = f.stat().st_mtime
        except OSError:
            continue
        if mt >= newest_mtime:
            newest_mtime = mt
            newest = f
        try:
            info = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if pid_running(info.get("pid")):
            return f
    return newest


def api_info() -> dict[str, Any] | None:
    f = api_file()
    if not f.exists():
        return None
    try:
        info = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not info.get("port") or not info.get("token"):
        return None
    if not pid_running(info.get("pid")):
        return None
    return info


def is_running() -> bool:
    return api_info() is not None


def ensure(timeout: float = 15.0) -> dict[str, Any]:
    info = api_info()
    if info is not None:
        return info
    app = app_path()
    if sys.platform == "win32":
        if not app.exists():
            raise RuntimeError(r"Vast.exe not found. Install to Program Files\Vast\Vast.exe")
        subprocess.Popen(
            [str(app), "--api"],
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    else:
        if not app.is_dir():
            raise RuntimeError("Vast.app not found. Install to /Applications/Vast.app")
        rc = subprocess.call(
            ["open", "-g", "-j", "-a", str(app), "--args", "--api"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if rc != 0:
            raise RuntimeError("Failed to launch Vast")
    t0 = time.time()
    while True:
        info = api_info()
        if info is not None:
            return info
        if time.time() - t0 > timeout:
            raise RuntimeError("Vast launched but the API is not ready. Require app version >= 0.6.2")
        time.sleep(0.2)


def request(
    method: str,
    route: str,
    body: dict[str, Any] | None = None,
    timeout: float = 30.0,
) -> dict[str, Any]:
    info = ensure()
    url = f"http://127.0.0.1:{info['port']}{route}"
    data = None
    headers = {
        "X-Vast-Token": str(info["token"]),
        "Content-Type": "application/json",
    }
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method=method.upper())
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            text = resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        text = e.read().decode("utf-8", errors="replace")
    except urllib.error.URLError as e:
        raise RuntimeError(f"Vast API request failed: {e}") from e

    try:
        parsed = json.loads(text) if text else {}
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Vast API request failed: {text}") from e
    if parsed.get("ok") is False:
        raise RuntimeError(parsed.get("error") or "request failed")
    return parsed


def cache_path() -> Path:
    # Mirror R: parent of session tempdir / vast.txt
    return Path(os.environ.get("TMPDIR") or os.environ.get("TMP") or "/tmp") / "vast.txt"


def normalize_delim(delim: Any) -> str | None:
    if delim is None:
        return None
    if delim is True:
        return ","
    if delim is False:
        return ""
    d = str(delim)
    low = d.lower()
    if low in ("none", "off", "false"):
        return ""
    if low in ("tab", "\\t", "tsv") or d == "\t":
        return "tab"
    if low in ("comma", "csv", ",") or d == ",":
        return ","
    return d


def delim_for_api(delim: Any) -> str | None:
    if delim is None or not str(delim):
        return None
    d = str(delim)
    if d == "\t" or d.lower() in ("tab", "tsv"):
        return "tab"
    if d == "," or d.lower() in ("comma", "csv"):
        return ","
    if d.lower() in ("none", "off"):
        return ""
    return d
