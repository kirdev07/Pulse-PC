import unittest
from unittest.mock import patch

from aiohttp.test_utils import AioHTTPTestCase
from modules.local_api import make_app


class LocalApiSecurityTests(AioHTTPTestCase):
    async def get_application(self):
        return make_app()

    async def test_protected_endpoint_requires_device_token(self):
        response = await self.client.request("GET", "/api/status")
        self.assertEqual(response.status, 401)
        data = await response.json()
        self.assertFalse(data["ok"])

    async def test_invalid_bearer_token_is_rejected(self):
        response = await self.client.request("GET", "/api/status", headers={"Authorization": "Bearer invalid-token"})
        self.assertEqual(response.status, 401)

    async def test_pairing_attempts_are_rate_limited(self):
        with patch("modules.local_api.mobile_access.load", return_value={"allow_pairing": True}), \
             patch("modules.local_api.is_private_ip", return_value=True), \
             patch("modules.local_api.ask_owner", return_value=False):
            statuses = []
            for _ in range(4):
                response = await self.client.request("POST", "/api/pair", json={"device": "Test"})
                statuses.append(response.status)
            self.assertEqual(statuses, [403, 403, 403, 429])

    async def test_unexpected_exception_does_not_leak_details(self):
        with patch("modules.local_api.mobile_access.authenticate", return_value={"id": "test"}), \
             patch("modules.monitor.workstation_locked", return_value=False), \
             patch("modules.local_api.load_programs", side_effect=RuntimeError("secret-path-C:/private")):
            response = await self.client.request("GET", "/api/programs", headers={"Authorization": "Bearer test"})
            self.assertEqual(response.status, 500)
            data = await response.json()
            self.assertNotIn("secret-path", data["error"])
            self.assertIn("Внутренняя ошибка", data["error"])


if __name__ == "__main__":
    unittest.main()
