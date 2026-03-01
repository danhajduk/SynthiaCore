import os
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.admin import router as admin_router


class TestAdminSessionAuth(unittest.TestCase):
    def setUp(self) -> None:
        self.env_patch = patch.dict(
            os.environ,
            {
                "SYNTHIA_ADMIN_TOKEN": "test-token",
                "SYNTHIA_ADMIN_COOKIE_SECURE": "0",
                "SYNTHIA_ADMIN_SESSION_TTL_SECONDS": "3600",
            },
            clear=False,
        )
        self.env_patch.start()
        app = FastAPI()
        app.include_router(admin_router, prefix="/api")
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.env_patch.stop()

    def test_login_cookie_allows_admin_endpoint(self) -> None:
        status_before = self.client.get("/api/admin/session/status")
        self.assertEqual(status_before.status_code, 200, status_before.text)
        self.assertFalse(status_before.json()["authenticated"])

        denied = self.client.get("/api/admin/reload/status")
        self.assertEqual(denied.status_code, 401, denied.text)

        login = self.client.post("/api/admin/session/login", json={"token": "test-token"})
        self.assertEqual(login.status_code, 200, login.text)
        self.assertTrue(login.json()["authenticated"])

        status_after = self.client.get("/api/admin/session/status")
        self.assertEqual(status_after.status_code, 200, status_after.text)
        self.assertTrue(status_after.json()["authenticated"])

        allowed = self.client.get("/api/admin/reload/status")
        self.assertEqual(allowed.status_code, 200, allowed.text)

        logout = self.client.post("/api/admin/session/logout")
        self.assertEqual(logout.status_code, 200, logout.text)

        status_final = self.client.get("/api/admin/session/status")
        self.assertEqual(status_final.status_code, 200, status_final.text)
        self.assertFalse(status_final.json()["authenticated"])

        denied_again = self.client.get("/api/admin/reload/status")
        self.assertEqual(denied_again.status_code, 401, denied_again.text)

    def test_login_rejects_invalid_token(self) -> None:
        login = self.client.post("/api/admin/session/login", json={"token": "wrong"})
        self.assertEqual(login.status_code, 401, login.text)


if __name__ == "__main__":
    unittest.main()
