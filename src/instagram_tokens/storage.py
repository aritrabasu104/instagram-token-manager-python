"""An optional explicit SQLite checkpoint store; never stores token values."""

import hashlib
import json
import os
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

from .errors import ConfigurationError


@dataclass(frozen=True)
class Snapshot:
    payload: dict
    revision: int


class StateConflict(ConfigurationError):
    """A concurrent owner changed the expected checkpoint."""


class SQLiteStore:
    """One current record per namespace/key, with atomic revision checks.

    Applications with an existing durable store should supply its get/put
    adapter instead. This class opens only the explicitly supplied path.
    """

    def __init__(self, path):
        self.path = Path(path).absolute()
        if self.path.is_symlink():
            raise ConfigurationError("State database cannot be a symlink")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
        os.close(fd)
        with closing(self._connect()) as db, db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS checkpoints("
                "namespace TEXT NOT NULL, key TEXT NOT NULL, revision INTEGER NOT NULL, "
                "payload TEXT NOT NULL, digest TEXT NOT NULL, PRIMARY KEY(namespace,key))"
            )

    def _connect(self):
        if self.path.is_symlink():
            raise ConfigurationError("State database cannot be a symlink")
        db = sqlite3.connect(self.path, timeout=30)
        db.execute("PRAGMA synchronous=FULL")
        return db

    def get(self, namespace, key):
        with closing(self._connect()) as db, db:
            row = db.execute(
                "SELECT revision,payload,digest FROM checkpoints WHERE namespace=? AND key=?",
                (namespace, key),
            ).fetchone()
        if not row:
            return None
        if hashlib.sha256(row[1].encode()).hexdigest() != row[2]:
            raise ConfigurationError("State checkpoint integrity check failed")
        return Snapshot(json.loads(row[1]), row[0])

    def put(self, namespace, key, payload, *, expected_revision):
        raw = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        )
        if len(raw.encode()) > 1024 * 1024:
            raise ConfigurationError("State checkpoint exceeds its metadata budget")
        sha = hashlib.sha256(raw.encode()).hexdigest()
        with closing(self._connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT revision FROM checkpoints WHERE namespace=? AND key=?", (namespace, key)
            ).fetchone()
            current = row[0] if row else 0
            if current != expected_revision:
                raise StateConflict("State checkpoint changed concurrently")
            revision = current + 1
            db.execute(
                "INSERT INTO checkpoints VALUES(?,?,?,?,?) ON CONFLICT(namespace,key) "
                "DO UPDATE SET revision=excluded.revision,payload=excluded.payload,"
                "digest=excluded.digest",
                (namespace, key, revision, raw, sha),
            )
        return Snapshot(payload, revision)
