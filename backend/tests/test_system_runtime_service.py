from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from app.system.runtime import StandaloneRuntimeService


class TestStandaloneRuntimeService(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "SynthiaAddons" / "services"
        self.root.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _service(self, *, cmd_runner=None) -> StandaloneRuntimeService:
        return StandaloneRuntimeService(
            cmd_runner=cmd_runner,
            services_root_resolver=lambda create=False: self.root,
            service_addon_dir_resolver=lambda addon_id, create=False: self.root / addon_id,
        )

    def test_snapshot_handles_missing_files(self) -> None:
        runtime = self._service()
        snapshot = runtime.get_standalone_addon_runtime_snapshot("mqtt")
        payload = snapshot.runtime.model_dump(mode="python")

        self.assertEqual(payload["addon_id"], "mqtt")
        self.assertEqual(payload["desired_state"], "unknown")
        self.assertEqual(payload["runtime_state"], "unknown")
        self.assertEqual(payload["health_status"], "unknown")
        self.assertIsNone(payload["container_name"])
        self.assertIsNone(snapshot.runtime_error)

    def test_snapshot_merges_desired_runtime_and_docker_metadata(self) -> None:
        addon_dir = self.root / "mqtt"
        addon_dir.mkdir(parents=True, exist_ok=True)
        (addon_dir / "desired.json").write_text(
            json.dumps(
                {
                    "ssap_version": "1.0",
                    "addon_id": "mqtt",
                    "mode": "standalone_service",
                    "desired_state": "running",
                    "pinned_version": "1.2.3",
                    "install_source": {
                        "type": "catalog",
                        "catalog_id": "official",
                        "release": {"artifact_url": "https://example.test/mqtt.tgz"},
                    },
                    "runtime": {
                        "project_name": "synthia-addon-mqtt",
                        "network": "synthia_net",
                        "ports": [{"host": 1883, "container": 1883, "protocol": "tcp"}],
                    },
                }
            ),
            encoding="utf-8",
        )
        (addon_dir / "runtime.json").write_text(
            json.dumps(
                {
                    "ssap_version": "1.0",
                    "addon_id": "mqtt",
                    "state": "running",
                    "active_version": "1.2.3",
                }
            ),
            encoding="utf-8",
        )

        def cmd_runner(cmd: list[str]):
            if cmd[:2] == ["docker", "ps"]:
                row = {
                    "Names": "synthia-addon-mqtt-main-1",
                    "Status": "Up 3 minutes",
                }
                return 0, json.dumps(row) + "\n", ""
            if cmd[:2] == ["docker", "inspect"]:
                payload = [
                    {
                        "Name": "/synthia-addon-mqtt-main-1",
                        "State": {
                            "Running": True,
                            "Status": "running",
                            "RestartCount": 2,
                            "StartedAt": "2026-03-07T10:00:00Z",
                            "Health": {
                                "Status": "healthy",
                                "Log": [{"Output": "service healthy"}],
                            },
                        },
                        "HostConfig": {"NetworkMode": "synthia_net"},
                        "NetworkSettings": {
                            "Ports": {
                                "1883/tcp": [{"HostIp": "127.0.0.1", "HostPort": "1883"}],
                            }
                        },
                    }
                ]
                return 0, json.dumps(payload), ""
            raise AssertionError(f"unexpected command: {cmd}")

        runtime = self._service(cmd_runner=cmd_runner)
        snapshot = runtime.get_standalone_addon_runtime_snapshot("mqtt")
        payload = snapshot.runtime.model_dump(mode="python")

        self.assertEqual(payload["desired_state"], "running")
        self.assertEqual(payload["runtime_state"], "running")
        self.assertEqual(payload["active_version"], "1.2.3")
        self.assertEqual(payload["target_version"], "1.2.3")
        self.assertEqual(payload["container_name"], "synthia-addon-mqtt-main-1")
        self.assertEqual(payload["container_status"], "running")
        self.assertTrue(payload["running"])
        self.assertEqual(payload["restart_count"], 2)
        self.assertEqual(payload["health_status"], "healthy")
        self.assertIn("127.0.0.1:1883->1883/tcp", payload["published_ports"])


if __name__ == "__main__":
    unittest.main()
