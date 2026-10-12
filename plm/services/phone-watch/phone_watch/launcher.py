from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def start_background(
    *,
    db_path: str = "data/phones.sqlite",
    host: str = "127.0.0.1",
    port: int = 8000,
    log_path: str = "server.log",
    pid_path: str = "server.pid",
) -> int:
    root = Path.cwd()
    log_file = root / log_path
    pid_file = root / pid_path
    args = [
        sys.executable,
        "-u",
        "-m",
        "phone_watch",
        "serve",
        "--host",
        host,
        "--db",
        db_path,
        "--port",
        str(port),
    ]
    creationflags = 0
    if os.name == "nt":
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    with log_file.open("ab") as log:
        process = subprocess.Popen(
            args,
            cwd=root,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=log,
            creationflags=creationflags,
            close_fds=True,
        )
    pid_file.write_text(str(process.pid), encoding="utf-8")
    return int(process.pid)

