"""Explicit account lock paths and bounded independent-account concurrency."""

import os
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path

from .errors import ConfigurationError

DEFAULT_MAX_PARALLEL_REQUESTS = 10


class FileLock:
    """Blocking POSIX flock; applications may inject their existing lock instead."""

    def __init__(self, path):
        self.path = Path(path).absolute()

    @contextmanager
    def __call__(self):
        try:
            import fcntl
        except ImportError:
            raise ConfigurationError(
                "Use an application-provided cross-process lock on this platform"
            ) from None
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(
            self.path, os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600
        )
        with os.fdopen(descriptor, "a+") as stream:
            fcntl.flock(stream, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(stream, fcntl.LOCK_UN)


def map_accounts(function, accounts, *, max_workers=DEFAULT_MAX_PARALLEL_REQUESTS):
    if type(max_workers) is not int or not 1 <= max_workers <= DEFAULT_MAX_PARALLEL_REQUESTS:
        raise ValueError("Account concurrency must be between 1 and 10")
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        return list(pool.map(function, accounts))
