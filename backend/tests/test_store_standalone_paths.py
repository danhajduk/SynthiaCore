import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.store.standalone_paths import (
    service_addon_dir,
    service_current_link,
    service_version_dir,
    service_versions_dir,
    services_root,
    synthia_addons_dir,
)


class TestStoreStandalonePaths(unittest.TestCase):
    def test_default_synthia_addons_dir_under_repo_root(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            path = synthia_addons_dir()
        self.assertEqual(path.name, "SynthiaAddons")
        self.assertTrue(path.is_absolute())

    def test_relative_env_path_resolves_from_backend_dir(self) -> None:
        with patch.dict(os.environ, {"SYNTHIA_ADDONS_DIR": "../CustomAddons"}, clear=False):
            path = synthia_addons_dir()
        self.assertEqual(path.name, "CustomAddons")
        self.assertTrue(path.is_absolute())

    def test_helpers_create_directories_lazily(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir) / "addons"
            with patch.dict(os.environ, {"SYNTHIA_ADDONS_DIR": str(base)}, clear=False):
                root = services_root(create=False)
                self.assertFalse(root.exists())

                addon_dir = service_addon_dir("mqtt", create=True)
                versions_dir = service_versions_dir("mqtt", create=True)
                version_dir = service_version_dir("mqtt", "0.1.0", create=True)
                current = service_current_link("mqtt")

            self.assertTrue(addon_dir.exists())
            self.assertTrue(versions_dir.exists())
            self.assertTrue(version_dir.exists())
            self.assertEqual(current, addon_dir / "current")

    def test_invalid_segments_raise(self) -> None:
        with self.assertRaises(ValueError):
            service_addon_dir("../bad")
        with self.assertRaises(ValueError):
            service_version_dir("mqtt", "v1/../../oops")


if __name__ == "__main__":
    unittest.main()
