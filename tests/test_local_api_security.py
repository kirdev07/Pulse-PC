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

    async def test_unexpected_exception_does_not_leak_details(self):
        with patch("modules.local_api.mobile_access.authenticate", return_value={"id": "test"}), \
             patch("modules.monitor.workstation_locked", return_value=False), \
             patch("modules.local_api.load_programs", side_effect=RuntimeError("secret-path-C:/private")):
            response = await self.client.request("GET", "/api/programs", headers={"Authorization": "Bearer test"})
            self.assertEqual(response.status, 500)
            body = await response.text()
            self.assertNotIn("secret-path", body)
            self.assertIn("Внутренняя ошибка", body)


if __name__ == "__main__":
    unittest.main()
