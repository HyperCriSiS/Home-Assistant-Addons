"""Regression checks for the optional native LAN port."""
from pathlib import Path
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[1]

class LanAccessTests(unittest.TestCase):
    def test_native_lan_port_enabled_by_default(self):
        config = yaml.safe_load((ROOT / "config.yaml").read_text())
        self.assertEqual(config["ports"]["3001/tcp"], 3001)
        self.assertIn("3001/tcp", config["ports_description"])
        self.assertIn("Standardport 3001", config["ports_description"]["3001/tcp"])
        self.assertIn("Feld leeren", config["ports_description"]["3001/tcp"])
        self.assertTrue(config["ingress"])
        self.assertTrue(config["panel_admin"])
        self.assertFalse(config.get("host_network", False))

    def test_native_proxy_has_no_ingress_privilege(self):
        text = (ROOT / "ingress.conf").read_text()
        ingress, lan = text.split("server {\n    listen 3001;", 1)
        self.assertIn("allow 172.30.32.2;", ingress)
        self.assertIn("__HA_INGRESS_PROXY_SECRET__", ingress)
        self.assertIn("location / {", lan)
        self.assertIn("proxy_pass http://127.0.0.1:3000;", lan)
        for header in (
            "X-MCPHub-HA-Proxy-Secret", "X-Remote-User-Id",
            "X-Remote-User-Name", "X-Remote-User-Display-Name",
            "X-Remote-User-Email", "X-Remote-User-Groups",
            "X-Forwarded-Prefix", "Proxy-Authorization",
        ):
            self.assertIn(f'proxy_set_header {header} "";', lan)
        self.assertNotIn("proxy_set_header Authorization ", lan)
        self.assertIn("proxy_set_header Upgrade $http_upgrade;", lan)

    def test_native_auth_remains_enabled(self):
        prepare = (ROOT / "prepare_config.py").read_text()
        self.assertIn('routing["skipAuth"] = False', prepare)
        self.assertIn('routing["enableBearerAuth"] = True', prepare)

if __name__ == "__main__":
    unittest.main()
