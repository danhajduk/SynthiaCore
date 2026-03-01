import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.addons.discovery import discover_backend_addons


class TestAddonsDiscovery(unittest.TestCase):
    def test_discovery_ignores_hidden_store_folders(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / ".store_backup" / "backend").mkdir(parents=True, exist_ok=True)
            (base / ".store_staging" / "backend").mkdir(parents=True, exist_ok=True)

            with patch("app.addons.discovery.addons_dir", return_value=base), patch(
                "app.addons.discovery.log.warning"
            ) as warning_log:
                results = discover_backend_addons()

        self.assertEqual(results, [])
        warning_log.assert_not_called()


if __name__ == "__main__":
    unittest.main()
