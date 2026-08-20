"""Dev server launcher that works around uvicorn's flaky --reload restart
on Windows.

Root cause (confirmed by isolated repro, see docs/HOJA_DE_RUTA.md): uvicorn's
Windows reloader signals the worker to stop via
os.kill(worker_pid, signal.CTRL_C_EVENT) (uvicorn/supervisors/basereload.py),
which relies on Windows delivering a console Ctrl event as a KeyboardInterrupt
in the worker's main thread. That delivery is unreliable in this environment
regardless of console ancestry (tested via a plain Start-Process launch) or
asyncio event loop policy (tested Proactor and Selector) -- change DETECTION
(watchfiles) is reliable every time, only the restart SIGNAL is not, and
uvicorn's restart() has no timeout on process.join(), so a single missed
signal hangs the reloader forever.

This script keeps watchfiles for detection (proven reliable) and replaces
the restart step with an unconditional hard kill (taskkill /F /T), which
does not depend on the worker's event loop noticing anything.
"""
import subprocess
import sys
from pathlib import Path

from watchfiles import watch

ROOT = Path(__file__).resolve().parent.parent
WATCH_DIRS = [str(ROOT / "app")]


def _start(port: str) -> subprocess.Popen:
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--port", port],
        cwd=str(ROOT),
    )
    print(f"[dev_reload] worker started, pid={proc.pid}", flush=True)
    return proc


def _kill(proc: subprocess.Popen) -> None:
    subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
    proc.wait()


def main() -> None:
    port = sys.argv[1] if len(sys.argv) > 1 else "8001"
    proc = _start(port)
    try:
        for changes in watch(*WATCH_DIRS):
            print(f"[dev_reload] changes detected: {changes} -- hard-restarting worker", flush=True)
            _kill(proc)
            proc = _start(port)
    except KeyboardInterrupt:
        _kill(proc)


if __name__ == "__main__":
    main()
