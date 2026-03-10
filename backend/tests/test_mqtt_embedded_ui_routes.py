import unittest

from fastapi.testclient import TestClient

from app.main import create_app


class TestMqttEmbeddedUiRoutes(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(create_app())

    def test_root_ui_page_contains_setup_shell(self) -> None:
        res = self.client.get("/api/addons/mqtt")
        self.assertEqual(res.status_code, 200, res.text)
        self.assertIn("Synthia MQTT Setup", res.text)
        self.assertIn("Save and Initialize", res.text)
        self.assertIn("Local broker", res.text)
        self.assertIn("External broker", res.text)
        self.assertIn("Check Health", res.text)
        self.assertIn("data-runtime-action='start'", res.text)
        self.assertIn('id="host"', res.text)
        self.assertIn('id="port"', res.text)
        self.assertIn('id="username"', res.text)
        self.assertIn('id="password"', res.text)
        self.assertIn("Test Connection", res.text)
        self.assertIn("data-section=\"overview\"", res.text)
        self.assertIn("data-section=\"principals\"", res.text)
        self.assertIn("data-section=\"users\"", res.text)
        self.assertIn("data-section=\"runtime\"", res.text)
        self.assertIn("data-section=\"audit\"", res.text)
        self.assertIn("data-section=\"noisy-clients\"", res.text)
        self.assertIn(".pill {", res.text)
        self.assertIn(".stats {", res.text)
        self.assertIn("data-filter='principals-q'", res.text)
        self.assertIn("data-filter='principals-type'", res.text)
        self.assertIn(">System</option>", res.text)
        self.assertIn(">Generic</option>", res.text)
        self.assertIn("Add User", res.text)
        self.assertIn("data-ui-action='open-add-user'", res.text)
        self.assertIn("id='create-user-username'", res.text)
        self.assertIn("id='create-user-prefix'", res.text)
        self.assertIn("data-generic-action='rotate'", res.text)
        self.assertIn("Topic Prefix", res.text)
        self.assertIn("Core Managed", res.text)
        self.assertIn("System principals are Core-managed", res.text)
        self.assertIn("data-filter='users-q'", res.text)
        self.assertIn("data-filter='audit-q'", res.text)
        self.assertIn("data-filter='noisy-q'", res.text)

    def test_subroute_ui_page_serves_same_shell(self) -> None:
        res = self.client.get("/api/addons/mqtt/principals")
        self.assertEqual(res.status_code, 200, res.text)
        self.assertIn("Synthia MQTT Setup", res.text)
        self.assertIn("data-section=\"principals\"", res.text)


if __name__ == "__main__":
    unittest.main()
