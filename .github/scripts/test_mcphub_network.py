#!/usr/bin/env python3
"""Offline regression tests for generated network configuration and tunnel controls."""
from __future__ import annotations
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2] / 'MCPHub'

def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

class NetworkTest(unittest.TestCase):
    def test_auto_key_and_migration(self):
        mod = module('config_test', ROOT / 'prepare_config.py')
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            data = root / 'mcphub'
            secrets = root / 'secrets'
            opts = root / 'options.json'
            legacy = 'L' * 48
            opts.write_text(json.dumps({'cloudflare_access_token': legacy, 'cloudflare_mcp_path':'/mcp/safe'}))
            for k, v in {'DATA_DIR':data,'SECRET_DIR':secrets,'OPTIONS_FILE':opts,'SETTINGS_FILE':data/'mcp_settings.json',
                         'JWT_SECRET_FILE':secrets/'jwt','OPENAI_TOKEN_FILE':secrets/'openai','OPENAI_AUTH_FILE':secrets/'openai-auth',
                         'HA_INGRESS_PROXY_SECRET_FILE':secrets/'ingress','LEGACY_INGRESS_TOKEN_FILE':secrets/'legacy',
                         'CLOUDFLARE_INTERNAL_TOKEN_FILE':secrets/'cf','LAN_INTERNAL_TOKEN_FILE':secrets/'lan',
                         'CLIENT_KEY_FILE':secrets/'client','GITHUB_TOKEN_FILE':secrets/'github'}.items(): setattr(mod,k,v)
            mod.main()
            self.assertEqual((secrets/'client').read_text(),legacy)
            self.assertIn('Home Assistant LAN MCP',str(json.loads((data/'mcp_settings.json').read_text())['bearerKeys']))
            self.assertEqual((secrets/'client').stat().st_mode & 0o777,0o600)
            (secrets/'client').write_text('X'*48)
            mod.main()
            self.assertEqual((secrets/'client').read_text(),'X'*48)
            (secrets/'client').unlink()
            opts.write_text('{}')
            mod.main()
            self.assertTrue(len((secrets/'client').read_text()) >= 32)

    def test_nginx_origin_scope_and_syntax(self):
        mod=module('proxy_test',ROOT/'prepare_proxy_config.py')
        secret='Ab_12'*12
        cf=mod.cloudflare_server_block(enabled=True,mcp_path='/mcp/office',client_token=secret,internal_token='private')
        lan=mod.lan_server_block('/mcp/office',secret,'lan-secret')
        self.assertIn('listen 0.0.0.0:3001',lan)
        self.assertIn('location ~ ^/mcp/office$',lan)
        self.assertIn('return 404',cf)
        with self.assertRaises(ValueError):mod.lan_server_block('/admin',secret,'internal')
        with tempfile.TemporaryDirectory() as td:
            output=Path(td)/'nginx.conf'
            output.write_text('pid ' + str(Path(td)/'nginx.pid') + ';\nevents {}\nhttp {\n'+(ROOT/'ingress.conf').read_text().replace('__HA_INGRESS_PROXY_SECRET__','safe-secret')
                    .replace('__CLOUDFLARE_SERVER_BLOCK__',cf).replace('__LAN_SERVER_BLOCK__',lan)+'\n}\n')
            if Path('/usr/sbin/nginx').exists():
                r=subprocess.run(['/usr/sbin/nginx','-t','-c',str(output)],capture_output=True,text=True)
                self.assertEqual(r.returncode,0,r.stderr)

    def test_controllers_protected(self):
        mod=module('controller_test',ROOT/'tunnel_control.py')
        self.assertIn("X-MCPHub-HA-Proxy-Secret",mod.Handler._auth.__code__.co_consts)
        self.assertIn('X-MCPHub-Control',mod.Handler.do_POST.__code__.co_consts)
        self.assertNotIn('Client Key',mod.Handler.log_message.__code__.co_consts)

if __name__=='__main__':unittest.main()
