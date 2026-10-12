from __future__ import annotations

import os
import subprocess
import sys
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo


SHANGHAI = ZoneInfo("Asia/Shanghai")


def next_run(now: datetime | None = None, hour: int = 8, minute: int = 0) -> datetime:
    current = (now or datetime.now(SHANGHAI)).astimezone(SHANGHAI)
    target = current.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= current:
        target += timedelta(days=1)
    return target


def run_daily(db_path: str, *, hour: int = 8, minute: int = 0) -> None:
    while True:
        target = next_run(hour=hour, minute=minute)
        seconds = max(1.0, (target - datetime.now(SHANGHAI)).total_seconds())
        print(f"[SCHEDULE] next collection: {target.isoformat()}", flush=True)
        time.sleep(seconds)
        commands = [
            [sys.executable, "-m", "phone_watch", "--db", db_path, "collect"],
            [sys.executable, "-m", "phone_watch", "--db", db_path, "collect-news"],
        ]
        for command in commands:
            result = subprocess.run(command, check=False, env=os.environ.copy())
            if result.returncode:
                print(f"[SCHEDULE] command failed ({result.returncode}): {' '.join(command)}", flush=True)
