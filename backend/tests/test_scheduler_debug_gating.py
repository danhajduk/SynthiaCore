from __future__ import annotations

import unittest

from app.main import app


class TestSchedulerDebugGating(unittest.TestCase):
    def test_debug_queue_route_is_hidden_by_default(self) -> None:
        paths = {route.path for route in app.routes}
        self.assertNotIn("/api/system/scheduler/debug/queue", paths)


if __name__ == "__main__":
    unittest.main()
