from __future__ import annotations

import unittest

from app.system.scheduler.models import RequestLeaseRequest


class TestRequestLeaseCapabilitiesField(unittest.TestCase):
    def test_capabilities_is_optional_and_accepted(self) -> None:
        body = RequestLeaseRequest(worker_id="worker-1", capabilities=["gpu", "vision"], max_units=5)
        self.assertEqual(body.worker_id, "worker-1")
        self.assertEqual(body.capabilities, ["gpu", "vision"])
        self.assertEqual(body.max_units, 5)

    def test_capabilities_defaults_to_empty(self) -> None:
        body = RequestLeaseRequest(worker_id="worker-2")
        self.assertEqual(body.capabilities, [])


if __name__ == "__main__":
    unittest.main()
