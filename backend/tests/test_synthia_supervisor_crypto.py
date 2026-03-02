from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from synthia_supervisor.crypto import _load_publishers_registry


class TestSynthiaSupervisorCrypto(unittest.TestCase):
    def test_load_publishers_registry_uses_runtime_cache_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            cwd = Path(tmpdir)
            target = cwd / "runtime" / "store" / "cache" / "official" / "publishers.json"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps({"publishers": []}), encoding="utf-8")

            old_cwd = Path.cwd()
            os.chdir(cwd)
            try:
                with patch.dict(os.environ, {}, clear=False):
                    payload = _load_publishers_registry()
            finally:
                os.chdir(old_cwd)

        self.assertEqual(payload, {"publishers": []})


if __name__ == "__main__":
    unittest.main()
