from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from app.store.models import ReleaseManifest
from app.store.router import _atomic_install_or_update


def _manifest(addon_id: str, version: str = "1.0.0") -> ReleaseManifest:
    return ReleaseManifest(
        id=addon_id,
        name=addon_id,
        version=version,
        core_min_version="0.1.0",
        core_max_version=None,
        dependencies=[],
        conflicts=[],
        checksum="deadbeef",
        publisher_id="pub-1",
        permissions=["filesystem.read"],
        signature={"publisher_id": "pub-1", "signature": "c2ln"},
        compatibility={
            "core_min_version": "0.1.0",
            "core_max_version": None,
            "dependencies": [],
            "conflicts": [],
        },
    )


def _build_addon_zip(zip_path: Path, addon_id: str, version: str, valid_layout: bool = True) -> None:
    manifest = {"id": addon_id, "name": addon_id, "version": version}
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr(f"{addon_id}/manifest.json", json.dumps(manifest))
        if valid_layout:
            zf.writestr(f"{addon_id}/backend/addon.py", "addon = None\n")


class TestStoreRouterAtomic(unittest.TestCase):
    def test_atomic_install_success(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            addons_root = root / "addons"
            addons_root.mkdir(parents=True, exist_ok=True)
            package = root / "pkg.zip"
            _build_addon_zip(package, "addon_ok", "1.0.0", valid_layout=True)

            with patch("app.store.router._addons_root", return_value=addons_root):
                result = _atomic_install_or_update(
                    manifest=_manifest("addon_ok", "1.0.0"),
                    package_path=package,
                    allow_replace=False,
                )

            self.assertTrue((addons_root / "addon_ok").exists())
            self.assertEqual(result.installed_manifest["id"], "addon_ok")

    def test_update_rolls_back_on_failure(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            addons_root = root / "addons"
            target = addons_root / "addon_x"
            (target / "backend").mkdir(parents=True, exist_ok=True)
            (target / "manifest.json").write_text(
                json.dumps({"id": "addon_x", "name": "addon_x", "version": "1.0.0"}),
                encoding="utf-8",
            )
            (target / "backend" / "addon.py").write_text("addon = None\n", encoding="utf-8")
            marker = target / "marker.txt"
            marker.write_text("old", encoding="utf-8")

            bad_package = root / "bad.zip"
            _build_addon_zip(bad_package, "addon_x", "2.0.0", valid_layout=False)

            with patch("app.store.router._addons_root", return_value=addons_root):
                with self.assertRaises(RuntimeError):
                    _atomic_install_or_update(
                        manifest=_manifest("addon_x", "2.0.0"),
                        package_path=bad_package,
                        allow_replace=True,
                    )

            self.assertTrue(marker.exists())
            self.assertEqual(marker.read_text(encoding="utf-8"), "old")


if __name__ == "__main__":
    unittest.main()
