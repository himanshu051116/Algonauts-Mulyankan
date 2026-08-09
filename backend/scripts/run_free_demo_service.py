"""Run the API and ARQ worker together for a free, demonstration-only host.

Paid hosts should run the API and worker as separate services. This launcher is
deliberately limited to the free deployment blueprint, whose web service may
sleep or restart at any time.
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import threading
from collections.abc import Sequence


RESTART_DELAY_SECONDS = 3


def _run_initialization() -> None:
    """Apply migrations and seed governed reference data before serving."""

    result = subprocess.run(
        [sys.executable, "-m", "scripts.seed_data"],
        check=False,
    )
    if result.returncode:
        raise SystemExit(result.returncode)


def _worker_command() -> Sequence[str]:
    arq_command = shutil.which("arq")
    if arq_command:
        return (arq_command, "app.worker.WorkerSettings")
    return (sys.executable, "-m", "arq", "app.worker.WorkerSettings")


def _terminate(process: subprocess.Popen[object] | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def main() -> int:
    _run_initialization()

    stopping = threading.Event()
    worker_lock = threading.Lock()
    worker_process: subprocess.Popen[object] | None = None
    api_process: subprocess.Popen[object] | None = None

    def stop_worker() -> None:
        nonlocal worker_process
        with worker_lock:
            _terminate(worker_process)
            worker_process = None

    def worker_supervisor() -> None:
        nonlocal worker_process
        while not stopping.is_set():
            with worker_lock:
                worker_process = subprocess.Popen(_worker_command())
                current_worker = worker_process
            exit_code = current_worker.wait()
            with worker_lock:
                if worker_process is current_worker:
                    worker_process = None
            if not stopping.is_set():
                print(
                    f"ARQ worker exited with {exit_code}; restarting in "
                    f"{RESTART_DELAY_SECONDS} seconds.",
                    flush=True,
                )
                stopping.wait(RESTART_DELAY_SECONDS)

    def request_shutdown(_signal: int, _frame: object) -> None:
        stopping.set()
        _terminate(api_process)
        stop_worker()

    signal.signal(signal.SIGTERM, request_shutdown)
    signal.signal(signal.SIGINT, request_shutdown)

    worker_thread = threading.Thread(
        target=worker_supervisor,
        name="arq-worker-supervisor",
        daemon=True,
    )
    worker_thread.start()

    port = os.environ.get("PORT", "8000")
    api_process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "0.0.0.0",
            "--port",
            port,
        ]
    )

    try:
        return api_process.wait()
    finally:
        stopping.set()
        _terminate(api_process)
        stop_worker()
        worker_thread.join(timeout=10)


if __name__ == "__main__":
    raise SystemExit(main())
