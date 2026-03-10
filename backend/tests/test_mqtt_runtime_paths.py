import tempfile
import unittest
from pathlib import Path

from app.system.mqtt.runtime_paths import ensure_runtime_dirs


class TestMqttRuntimePaths(unittest.TestCase):
    def test_ensure_runtime_dirs_bootstraps_required_structure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = ensure_runtime_dirs(tmp)
            root = Path(paths["root"])
            self.assertTrue(root.exists())
            self.assertTrue((root / "staged").exists())
            self.assertTrue((root / "live").exists())
            self.assertTrue((root / "data").exists())
            self.assertTrue((root / "logs").exists())
            self.assertEqual((root / "data").stat().st_mode & 0o777, 0o777)
            self.assertEqual((root / "logs").stat().st_mode & 0o777, 0o777)


if __name__ == "__main__":
    unittest.main()
