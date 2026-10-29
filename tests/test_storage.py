import tempfile
import unittest
from pathlib import Path

from instagram_tokens import SQLiteStore
from instagram_tokens.storage import StateConflict


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "state.sqlite3"
        self.store = SQLiteStore(self.path)

    def test_compare_and_swap_rejects_stale_writers(self):
        self.store.put("example", "session", {"status": "pending"}, expected_revision=0)
        with self.assertRaises(StateConflict):
            self.store.put("example", "session", {"status": "another"}, expected_revision=0)
        self.assertEqual(self.store.get("example", "session").revision, 1)

    def test_store_survives_reopening_without_a_shadow_copy(self):
        self.store.put("example", "session", {"status": "pending"}, expected_revision=0)
        self.assertEqual(
            SQLiteStore(self.path).get("example", "session").payload, {"status": "pending"}
        )
        self.assertEqual(list(self.path.parent.glob("*.json")), [])
