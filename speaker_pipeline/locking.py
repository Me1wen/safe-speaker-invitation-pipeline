"""Cross-process advisory locks for canonical CSV ledgers.

The lock lives beside the ledger instead of locking the CSV itself.  Atomic CSV
replacement therefore does not invalidate the held lock.  Every read/modify/
write workflow must use the same ``<ledger>.lock`` path.
"""

from __future__ import annotations

import errno
import json
import os
import socket
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO

if os.name == "nt":  # pragma: no cover - exercised on Windows CI
    import msvcrt
else:  # pragma: no cover - the branch itself is platform-specific
    import fcntl


class LockTimeoutError(TimeoutError):
    """Raised when another process keeps a ledger locked past the timeout."""


def lock_path_for(ledger_path: str | os.PathLike[str]) -> Path:
    """Return the stable sidecar lock path for a canonical ledger."""

    path = Path(ledger_path)
    return path.with_name(f"{path.name}.lock")


class LedgerLock:
    """Exclusive, process-scoped lock for one canonical ledger."""

    def __init__(
        self,
        ledger_path: str | os.PathLike[str],
        *,
        timeout: float = 10.0,
        poll_interval: float = 0.05,
    ) -> None:
        if timeout < 0:
            raise ValueError("Lock timeout must be zero or greater.")
        if poll_interval <= 0:
            raise ValueError("Lock poll interval must be greater than zero.")
        self.ledger_path = Path(ledger_path)
        self.path = lock_path_for(self.ledger_path)
        self.timeout = timeout
        self.poll_interval = poll_interval
        self._handle: BinaryIO | None = None

    def _try_lock(self, handle: BinaryIO) -> bool:
        try:
            if os.name == "nt":  # pragma: no cover - exercised on Windows CI
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            if exc.errno not in {errno.EACCES, errno.EAGAIN}:
                raise
            return False
        return True

    def acquire(self) -> LedgerLock:
        if self._handle is not None:
            raise RuntimeError("This LedgerLock instance is already acquired.")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # A byte must exist for msvcrt.locking(); leaving the sidecar in place is
        # intentional and avoids an unlink/recreate race between waiting processes.
        handle = self.path.open("a+b")
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
        deadline = time.monotonic() + self.timeout
        while not self._try_lock(handle):
            if time.monotonic() >= deadline:
                handle.close()
                raise LockTimeoutError(
                    f"Timed out waiting for ledger lock {self.path}. "
                    "Another import, generation, or live-send process may be running."
                )
            time.sleep(min(self.poll_interval, max(0.0, deadline - time.monotonic())))

        self._handle = handle
        metadata = {
            "pid": os.getpid(),
            "host": socket.gethostname(),
            "acquired_at": time.time(),
            "ledger": str(self.ledger_path),
        }
        encoded = (json.dumps(metadata, sort_keys=True) + "\n").encode("utf-8")
        handle.seek(0)
        handle.truncate()
        handle.write(encoded)
        handle.flush()
        return self

    def release(self) -> None:
        handle = self._handle
        if handle is None:
            return
        try:
            if os.name == "nt":  # pragma: no cover - exercised on Windows CI
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()
            self._handle = None

    def __enter__(self) -> LedgerLock:
        return self.acquire()

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.release()


@contextmanager
def ledger_lock(
    ledger_path: str | os.PathLike[str],
    *,
    timeout: float = 10.0,
    poll_interval: float = 0.05,
) -> Iterator[LedgerLock]:
    """Acquire the canonical lock used by import, generation, and live send."""

    with LedgerLock(ledger_path, timeout=timeout, poll_interval=poll_interval) as acquired:
        yield acquired


# Descriptive alias for CLI code which holds the lock from its initial ledger
# read through every Sending/Sent/Failed persistence write.
live_send_lock = ledger_lock


__all__ = [
    "LedgerLock",
    "LockTimeoutError",
    "ledger_lock",
    "live_send_lock",
    "lock_path_for",
]
