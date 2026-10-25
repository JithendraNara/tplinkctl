"""Exercise the real SG request stack against observed wire contracts."""

import json
import unittest
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit

from tplink_admin import cli


class SgVpnTransportTests(unittest.TestCase):
    def setUp(self):
        self.router = cli.TplinkRouterSG("http://router.invalid", "test-password")
        self.router._logged = True
        self.router._stok = "test-session"
        self.router._sysauth = "test-cookie"
        self.router._aes_key = "0123456789abcdef"
        self.router._aes_iv = "abcdef0123456789"

    def respond(self, payload):
        response = Mock()
        response.json.return_value = {
            "data": self.router._aes_encrypt(json.dumps(payload))
        }
        return response

    def test_client_status_preserves_vpn_form_body_through_encryption(self):
        """JSON conversion must not turn an enabled client into an API error."""
        fixtures = {
            "enable": ("read", {"enable": "on"}),
            "server": ("load", [
                {"key": "test-profile", "des": "Example VPN", "type": "openvpn",
                 "enable": "on", "status": "connected"},
            ]),
            "vpn_user_list": ("load", [
                {"mac": "02-00-00-00-00-01", "name": "Test phone", "access": "on"},
            ]),
        }
        seen = []

        def post(url, data, **kwargs):
            query = parse_qs(urlsplit(url).query)
            form = query["form"][0]
            encrypted = parse_qs(data)["data"][0]
            plaintext = self.router._aes_decrypt(encrypted)
            operation, result = fixtures[form]
            seen.append(form)
            self.assertEqual(plaintext, "operation=" + operation)
            return self.respond({"success": True, "data": result})

        with patch("tplinkrouterc6u.client.sg.post", side_effect=post):
            status = cli.to_plain(self.router.get_vpn_client_status())
        self.assertTrue(status["enabled"])
        self.assertEqual(status["servers"][0]["status"], "connected")
        self.assertTrue(status["devices"][0]["enabled"])
        self.assertEqual(set(seen), set(fixtures))

    def test_vpn_collection_uses_form_encoding_without_query_payload_copy(self):
        """Doctor/raw/device helpers must honor the same VPN wire contract."""
        def post(url, data, **kwargs):
            self.assertEqual(parse_qs(urlsplit(url).query),
                             {"form": ["vpn_user_list"], "operation": ["load"]})
            plaintext = self.router._aes_decrypt(parse_qs(data)["data"][0])
            self.assertEqual(plaintext, "operation=load")
            return self.respond({"success": True, "data": [
                {"name": "Test phone", "access": "on"},
            ]})
        with patch("tplinkrouterc6u.client.sg.post", side_effect=post), \
             patch.object(cli.requests, "post", side_effect=post):
            result = cli.load_collection(self.router, "admin/vpn?form=vpn_user_list")
        self.assertEqual(result, [{"name": "Test phone", "access": "on"}])

    def test_non_vpn_json_conversion_is_unchanged(self):
        """Keep the existing SG JSON workaround outside the VPN controller."""
        for path in ("admin/status?form=all", "admin/vpnconn?form=config"):
            with self.subTest(path=path):
                def post(url, data, **kwargs):
                    plaintext = self.router._aes_decrypt(parse_qs(data)["data"][0])
                    self.assertEqual(json.loads(plaintext), {"operation": "read"})
                    return self.respond({"success": True, "data": {"ok": True}})
                with patch("tplinkrouterc6u.client.sg.post", side_effect=post):
                    self.assertEqual(self.router.request(path, "operation=read"), {"ok": True})

    def test_explicit_json_and_request_flags_are_preserved(self):
        """An intentional raw JSON probe stays raw; error flags still work."""
        body = '{"operation":"read"}'
        def post(url, data, **kwargs):
            plaintext = self.router._aes_decrypt(parse_qs(data)["data"][0])
            self.assertEqual(plaintext, body)
            return self.respond({"success": False, "errorcode": "no such callback"})
        with patch("tplinkrouterc6u.client.sg.post", side_effect=post):
            result = self.router.request("admin/vpn?form=enable", body, False, True)
            self.assertEqual(result, {"success": False, "errorcode": "no such callback"})
            self.assertIsNone(self.router.request("admin/vpn?form=enable", body, True))


if __name__ == "__main__":
    unittest.main()
