from __future__ import annotations

import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from app.store.router import _cleanup_store_workdirs


class TestStoreCleanupPolicy(unittest.TestCase):
    def test_prunes_old_backups_and_staging_dirs(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "addons"
            backup_root = root / ".store_backup"
            staging_root = root / ".store_staging"
            backup_root.mkdir(parents=True, exist_ok=True)
            staging_root.mkdir(parents=True, exist_ok=True)

            # Create 4 backup dirs; keep newest 2.
            backups = []
            for idx in range(4):
                d = backup_root / f"addon-{idx}"
                d.mkdir()
                now = time.time() - (100 - idx)
                Path(d / "x").write_text("x", encoding="utf-8")
                # Newer dirs have higher mtime.
                os_time = (now, now)
                os.utime(d, os_time)
                backups.append(d)

            old_stage = staging_root / "old-stage"
            old_stage.mkdir()
            old_ts = time.time() - (3 * 3600)
            os.utime(old_stage, (old_ts, old_ts))

            new_stage = staging_root / "new-stage"
            new_stage.mkdir()

            with patch("app.store.router._addons_root", return_value=root):
                out = _cleanup_store_workdirs(backup_retention=2, staging_ttl_minutes=60)

            self.assertEqual(out["backup_pruned"], 2)
            self.assertEqual(out["staging_pruned"], 1)
            self.assertTrue(new_stage.exists())
            self.assertFalse(old_stage.exists())
            self.assertEqual(len([p for p in backup_root.iterdir() if p.is_dir()]), 2)


if __name__ == "__main__":
    unittest.main()
