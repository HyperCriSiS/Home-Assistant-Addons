#!/usr/bin/env python3
"""Ingress-only tunnel control and local health for OpenAI and Cloudflare."""
from __future__ import annotations

import json
import logging
import os
import re
import secrets
import signal
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from tunnel_diagnostics import TunnelLog, redact
from tailscale_gateway import TailscaleGateway

OPTIONS = Path('/data/options.json')
CF_SECRET = Path('/data/secrets/cloudflare_tunnel_token')
CF_CLIENT_KEY = Path('/data/secrets/mcphub_cloudflare_client_key')
TS_CLIENT_KEY = Path('/data/secrets/mcphub_tailscale_client_key')
PORT = ('127.0.0.1', 8093)
PATH = re.compile(r'^/mcp(?:/[A-Za-z0-9._$-]+){0,2}$')
CLIENT_KEY = re.compile(r'^[A-Za-z0-9_-]{32,256}$')
LOG = logging.getLogger('tunnel-control')


def valid_mcp_route(route):
    return bool(PATH.fullmatch(route)) and all(
        part not in ('.', '..') for part in route.split('/')[2:])


def options():
    data = json.loads(OPTIONS.read_text(encoding='utf-8'))
    if not isinstance(data, dict):
        raise ValueError('Invalid Home Assistant App options')
    value = dict(data)
    for group in ('openai', 'cloudflare', 'tailscale', 'home_assistant', 'github', 'logging'):
        if isinstance(data.get(group), dict):
            value.update(data[group])
    return value


def check(url, expected=200):
    try:
        with urlopen(Request(url, headers={'Cache-Control': 'no-store'}), timeout=2) as response:
            return response.status == expected
    except HTTPError as error:
        return error.code == expected
    except (URLError, TimeoutError, OSError):
        return False


def save_secret(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    temp = path.with_suffix('.tmp')
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            handle.write(value)
        os.chmod(temp, 0o600)
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)


class Cloudflare:
    def __init__(self):
        self.proc = None
        self.desired = False
        self.state = 'stopped'
        self.error = ''
        self.checked = 0.0
        self.retry_at = 0.0
        self.failed = 0
        self.started = 0.0
        self.degraded_at = 0.0
        self.route = '/mcp'
        self.configured = False
        self.logs = TunnelLog()
        self.logs.add('Cloudflare Tunnelverwaltung gestartet')
        self.reload()

    def stop_process(self):
        proc, self.proc = self.proc, None
        if proc:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=5)
            else:
                proc.wait()

    def start_process(self, now):
        try:
            opts = options()
            self.configured = bool(opts.get('cloudflare_tunnel_enabled'))
            self.route = str(opts.get('cloudflare_mcp_path') or '/mcp')
            token = str(opts.get('cloudflare_tunnel_token') or '').strip()
            key = CF_CLIENT_KEY.read_text(encoding='utf-8').strip() if CF_CLIENT_KEY.is_file() else ''
            if not self.configured or not token or not valid_mcp_route(self.route) or not CLIENT_KEY.fullmatch(key):
                raise ValueError('Cloudflare tunnel configuration is incomplete or disabled')
            save_secret(CF_SECRET, token)
            self.proc = subprocess.Popen([
                '/usr/local/bin/cloudflared', 'tunnel', '--no-autoupdate',
                '--metrics', '127.0.0.1:20091',
                'run', '--token-file', str(CF_SECRET)
            ], stdin=subprocess.DEVNULL,
               stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
               text=True, errors='replace', bufsize=1)
            self.logs.follow(self.proc, (token, key))
            self.logs.add('Tunnelprozess gestartet')
            self.state = 'starting'
            self.started = now
            self.degraded_at = 0.0
            self.error = ''
        except (ValueError, OSError, subprocess.SubprocessError) as error:
            self.stop_process()
            self.desired = False
            self.state = 'error'
            self.error = str(error)
            self.logs.add('Start fehlgeschlagen (Einstellungen prüfen)')

    def reload(self):
        self.stop_process()
        self.failed = 0
        self.retry_at = 0.0
        self.checked = 0.0
        try:
            config = options()
            self.configured = bool(config.get('cloudflare_tunnel_enabled'))
            self.route = str(config.get('cloudflare_mcp_path') or '/mcp')
        except (ValueError, OSError):
            self.configured = False
        self.desired = self.configured
        self.state = 'starting' if self.desired else 'stopped'

    def command(self, action):
        self.logs.add('Aktion: ' + action)
        if action == 'stop':
            self.desired = False
            self.stop_process()
            self.state = 'stopped'
            self.error = ''
        elif action == 'reload':
            self.reload()
            if self.desired:
                self.start_process(time.monotonic())
        elif action == 'start':
            self.desired = True
            self.retry_at = self.failed = 0
            if self.proc is None:
                self.start_process(time.monotonic())
        else:
            raise ValueError('Invalid action')

    def fail(self, message, now):
        self.stop_process()
        self.failed += 1
        delay = min(5 * 2 ** min(self.failed - 1, 6), 300)
        self.retry_at = now + delay
        self.error = message
        self.logs.add('Fehler: ' + message)
        self.state = 'retrying'
        self.degraded_at = 0.0
        LOG.warning('Cloudflare: %s; retry in %s seconds', message, delay)

    def tick(self, now):
        if not self.desired:
            return
        if self.proc is None:
            if now >= self.retry_at:
                self.start_process(now)
            return
        rc = self.proc.poll()
        if rc is not None:
            self.fail('cloudflared exited (code %s)' % rc, now)
            return
        self.checked = now
        connected = check('http://127.0.0.1:20091/ready')
        origin = check('http://127.0.0.1:8098' + self.route, expected=401)
        if connected and origin:
            self.state = 'ready'
            self.degraded_at = 0.0
            self.failed = 0
            self.error = ''
        else:
            self.state = 'starting' if now - self.started < 35 else 'degraded'
            self.error = 'Cloudflare connector unready' if not connected else 'MCP origin unready'
            self.degraded_at = self.degraded_at or now
            if now - self.started >= 35 and now - self.degraded_at > 180:
                self.fail(self.error, now)

    def status(self, now):
        # A previously ready connector is never reported healthy if its checks stopped.
        fresh = bool(self.checked) and now - self.checked <= 20
        visible_state = 'stale' if self.desired and self.state == 'ready' and not fresh else self.state
        return {
            'state': visible_state, 'configured': self.configured, 'requested': self.desired,
            'process_alive': self.proc is not None and self.proc.poll() is None,
            'transport_ready': visible_state == 'ready', 'last_error': self.error,
            'route': self.route, 'health_age_seconds': round(now - self.checked) if self.checked else None,
            'retry_in_seconds': max(0, round(self.retry_at - now)) if self.state == 'retrying' else 0,
            'control_type': 'process'
        }


class Controls:
    def __init__(self):
        self.lock = threading.RLock()
        self.cloudflare = Cloudflare()
        self.tailscale = TailscaleGateway(options)

    def openai(self, action=None):
        headers = {'Cache-Control': 'no-store'}
        if action:
            headers.update({'Content-Type': 'application/json', 'X-MCPHub-Tunnel-Control': '1'})
        request = Request(
            'http://127.0.0.1:8096/api/' + (action or 'status'),
            headers=headers,
            data=b'{}' if action else None,
            method='POST' if action else 'GET',
        )
        try:
            with urlopen(request, timeout=3) as response:
                return json.load(response)
        except (HTTPError, URLError, ValueError, OSError, TimeoutError):
            return {'state': 'unavailable', 'last_error': 'OpenAI control is unavailable'}

    def snapshot(self):
        with self.lock:
            openai = self.openai()
            age = openai.get('health_age_seconds')
            if openai.get('state') == 'ready' and (age is None or age > 20):
                openai['state'] = 'stale'
                openai['last_error'] = 'OpenAI health check is stale'
            openai['transport_ready'] = openai.get('state') == 'ready'
            openai['control_type'] = 'process'
            return {
                'openai': openai,
                'cloudflare': self.cloudflare.status(time.monotonic()),
                'tailscale': self.tailscale.status(),
            }

    def command(self, mode, action):
        with self.lock:
            if action not in ('start', 'stop', 'reload'):
                raise ValueError('Unsupported action')
            if mode == 'openai':
                return self.openai(action)
            if mode == 'cloudflare':
                self.cloudflare.command(action)
                return self.cloudflare.status(time.monotonic())
            if mode == 'tailscale':
                return self.tailscale.command(action)
            raise ValueError('Unknown tunnel')

    def logs(self, mode):
        """Return separately buffered logs; never expose the HA App log globally."""
        with self.lock:
            if mode == 'cloudflare':
                return self.cloudflare.logs.snapshot()
            if mode == 'tailscale':
                return {'lines': ['Tailscale-Daemon-Protokolle sind nur im Tailscale-Add-on abrufbar.'], 'limited': True}
            if mode == 'openai':
                try:
                    with urlopen('http://127.0.0.1:8096/api/logs', timeout=3) as response:
                        return json.loads(response.read(70000))
                except (HTTPError, URLError, OSError, ValueError, TimeoutError):
                    return {'lines': ['OpenAI-Protokoll aktuell nicht erreichbar'], 'limited': True}
            raise ValueError('Unknown tunnel')

    def diagnostics(self, mode):
        """Bounded local component diagnostics; do not return raw configuration."""
        if mode == 'openai':
            if not self.openai().get('process_alive'):
                return {'note': 'OpenAI-Tunnelprozess ist nicht aktiv'}
            try:
                with urlopen('http://127.0.0.1:8080/health?details=true', timeout=3) as response:
                    report = json.loads(response.read(65536))
                components = {}
                for name in ('mcp', 'control-plane', 'response-delivery', 'queue', 'proxy'):
                    item = report.get('components', {}).get(name)
                    if isinstance(item, dict):
                        components[name] = {
                            k: item[k] for k in ('status', 'state', 'reason_code', 'observed_at')
                            if k in item and isinstance(item[k], (str, bool, int))
                        }
                return {
                    'live': report.get('live') is True,
                    'ready': report.get('ready') is True,
                    'components': components,
                }
            except (HTTPError, URLError, OSError, ValueError, TimeoutError):
                return {'note': 'OpenAI-Komponentendiagnose nicht erreichbar'}
        if mode == 'tailscale':
            return {'note': 'Tailscale Funnel wird vom separaten Tailscale-Add-on betrieben. Das MCP-Gateway hier steuert nur den lokalen, authentifizierten Zugriff.'}
        if mode == 'cloudflare':
            if not self.cloudflare.proc or self.cloudflare.proc.poll() is not None:
                return {'note': 'Cloudflare-Tunnelprozess ist nicht aktiv'}
            try:
                with urlopen('http://127.0.0.1:20091/diag/precheck', timeout=3) as response:
                    if response.status == 204:
                        return {'note': 'Precheck-Ergebnisse noch nicht verfügbar'}
                    report = json.loads(response.read(32768))
                results = []
                for item in report.get('results', [])[:20]:
                    if isinstance(item, dict):
                        results.append({
                            k: redact(item[k])
                            for k in ('component', 'status', 'details', 'action')
                            if isinstance(item.get(k), str)
                        })
                return {'hard_fail': report.get('hard_fail') is True,
                        'suggested_protocol': redact(report.get('suggested_protocol', '')),
                        'prechecks': results}
            except (HTTPError, URLError, OSError, ValueError, TimeoutError):
                return {'note': 'Cloudflare-Netzwerkdiagnose nicht verfügbar'}
        raise ValueError('Unknown tunnel')

    def client_key(self):
        with self.lock:
            key = CF_CLIENT_KEY.read_text(encoding='utf-8').strip()
            if not CLIENT_KEY.fullmatch(key):
                raise ValueError('The local Cloudflare client key is missing or invalid')
            return {'key': key}

    def rotate_client_key(self):
        """Atomically swap key and reload Nginx; restore old key on any failure."""
        with self.lock:
            old = CF_CLIENT_KEY.read_text(encoding='utf-8').strip()
            if not CLIENT_KEY.fullmatch(old):
                raise ValueError('The current Cloudflare client key is invalid')
            new = secrets.token_urlsafe(48)
            save_secret(CF_CLIENT_KEY, new)
            try:
                subprocess.run(['/usr/local/bin/prepare_proxy_config.py'],
                               check=True, timeout=15, capture_output=True)
                subprocess.run(['nginx', '-t'], check=True, timeout=10, capture_output=True)
                subprocess.run(['nginx', '-s', 'reload'],
                               check=True, timeout=10, capture_output=True)
            except (OSError, subprocess.SubprocessError) as error:
                save_secret(CF_CLIENT_KEY, old)
                # Always attempt restoring the previous proxy config and revocation state.
                try:
                    subprocess.run(['/usr/local/bin/prepare_proxy_config.py'],
                                   check=True, timeout=15, capture_output=True)
                    subprocess.run(['nginx', '-s', 'reload'],
                                   check=True, timeout=10, capture_output=True)
                except (OSError, subprocess.SubprocessError):
                    # Inability to restore is critical: shut down the remote tunnel.
                    self.cloudflare.command('stop')
                    LOG.error('Cloudflare key rollback failed; connector stopped')
                raise RuntimeError('Cloudflare client key rotation failed') from error
            LOG.info('Cloudflare client key rotated')
            return {'rotated': True}

    def tailscale_client_key(self):
        with self.lock:
            key = TS_CLIENT_KEY.read_text(encoding='utf-8').strip()
            if not CLIENT_KEY.fullmatch(key):
                raise ValueError('Tailscale client key missing or invalid')
            return {'key': key}

    def rotate_tailscale_client_key(self):
        """Revoke old external key by reloading Nginx; fail closed on rollback problems."""
        with self.lock:
            old = TS_CLIENT_KEY.read_text(encoding='utf-8').strip()
            if not CLIENT_KEY.fullmatch(old):
                raise ValueError('Existing Tailscale client key invalid')
            new = secrets.token_urlsafe(48)
            save_secret(TS_CLIENT_KEY, new)
            try:
                subprocess.run(['/usr/local/bin/prepare_proxy_config.py'],
                               check=True, timeout=15, capture_output=True)
                subprocess.run(['nginx', '-t'], check=True, timeout=10, capture_output=True)
                subprocess.run(['nginx', '-s', 'reload'],
                               check=True, timeout=10, capture_output=True)
            except (OSError, subprocess.SubprocessError) as error:
                save_secret(TS_CLIENT_KEY, old)
                try:
                    subprocess.run(['/usr/local/bin/prepare_proxy_config.py'],
                                   check=True, timeout=15, capture_output=True)
                    subprocess.run(['nginx', '-s', 'reload'],
                                   check=True, timeout=10, capture_output=True)
                except (OSError, subprocess.SubprocessError):
                    self.tailscale.command('stop')
                    LOG.error('Tailscale key rollback failed; MCP gateway stopped')
                raise RuntimeError('Tailscale client key rotation failed') from error
            LOG.info('Tailscale client key rotated')
            return {'rotated': True}

    def tick(self):
        with self.lock:
            self.cloudflare.tick(time.monotonic())


# The standalone management console is never injected into MCPHub's SPA.
PAGE = Path(__file__).with_name('tunnel_dashboard.html').read_text(encoding='utf-8')
SCRIPT = Path(__file__).with_name('tunnel_dashboard.js').read_text(encoding='utf-8')


def handler_for(manager):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            LOG.debug(fmt, *args)

        def send(self, status, body=b'', mime='application/json'):
            self.send_response(status)
            for name, value in (
                ('Content-Type', mime),
                ('Content-Length', str(len(body))),
                ('Cache-Control', 'no-store'),
                ('X-Content-Type-Options', 'nosniff'),
                ('X-Frame-Options', 'SAMEORIGIN'),
                ('Content-Security-Policy', "default-src 'none'; script-src 'self'; connect-src 'self'; style-src 'unsafe-inline'; base-uri 'none'; frame-ancestors 'self'"),
            ):
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path in ('/', '/index.html'):
                self.send(200, PAGE.encode(), 'text/html; charset=utf-8')
            elif self.path == '/app.js':
                self.send(200, SCRIPT.encode(), 'text/javascript; charset=utf-8')
            elif self.path == '/api/status':
                self.send(200, json.dumps(manager.snapshot()).encode())
            elif self.path == '/api/tailscale/gate':
                # This controller listens on container loopback only; Nginx
                # exposes the subrequest location as internal, never public.
                self.send(204 if manager.tailscale.authorized() else 403)
            elif self.path == '/api/tailscale/https-check':
                if self.headers.get('X-MCPHub-Tunnel-Control') != '1':
                    self.send(403, b'Forbidden', 'text/plain')
                    return
                try:
                    self.send(200, json.dumps(manager.tailscale.check_https()).encode())
                except (OSError, ValueError):
                    self.send(409, b'Invalid or missing Funnel URL', 'text/plain')
            elif self.path == '/api/tailscale/client-key':
                if self.headers.get('X-MCPHub-Tunnel-Control') != '1':
                    self.send(403, b'Forbidden', 'text/plain')
                    return
                try:
                    self.send(200, json.dumps(manager.tailscale_client_key()).encode())
                except (OSError, ValueError):
                    self.send(503, b'Key unavailable', 'text/plain')
            elif self.path in ('/api/logs/openai', '/api/logs/cloudflare', '/api/logs/tailscale'):
                self.send(200, json.dumps(manager.logs(self.path.rsplit('/', 1)[-1])).encode())
            elif self.path in ('/api/diagnostics/openai', '/api/diagnostics/cloudflare', '/api/diagnostics/tailscale'):
                self.send(200, json.dumps(manager.diagnostics(self.path.rsplit('/', 1)[-1])).encode())
            elif self.path == '/api/client-key':
                if self.headers.get('X-MCPHub-Tunnel-Control') != '1':
                    self.send(403, b'Forbidden', 'text/plain')
                    return
                try:
                    self.send(200, json.dumps(manager.client_key()).encode())
                except (OSError, ValueError):
                    self.send(503, b'Key unavailable', 'text/plain')
            else:
                self.send(404, b'Not found', 'text/plain')

        def do_POST(self):
            if self.path == '/api/tailscale/client-key/rotate':
                if (self.headers.get('X-MCPHub-Tunnel-Control') != '1'
                    or self.headers.get('Content-Type', '').split(';')[0] != 'application/json'
                    or self.headers.get('Content-Length') != '2'):
                    self.send(403, b'Forbidden', 'text/plain')
                    return
                if self.rfile.read(2) != b'{}':
                    self.send(400, b'Bad request', 'text/plain')
                    return
                try:
                    self.send(200, json.dumps(manager.rotate_tailscale_client_key()).encode())
                except (OSError, ValueError, RuntimeError):
                    self.send(503, b'Key rotation failed', 'text/plain')
                return
            if self.path == '/api/client-key/rotate':
                if (self.headers.get('X-MCPHub-Tunnel-Control') != '1'
                    or self.headers.get('Content-Type', '').split(';')[0] != 'application/json'
                    or self.headers.get('Content-Length') != '2'):
                    self.send(403, b'Forbidden', 'text/plain')
                    return
                if self.rfile.read(2) != b'{}':
                    self.send(400, b'Bad request', 'text/plain')
                    return
                try:
                    self.send(200, json.dumps(manager.rotate_client_key()).encode())
                except (OSError, ValueError, RuntimeError):
                    self.send(503, b'Key rotation failed', 'text/plain')
                return
            parts = self.path.split('/')
            if (len(parts) != 5 or parts[:3] != ['', 'api', 'control']
                    or parts[3] not in ('openai', 'cloudflare', 'tailscale')
                    or parts[4] not in ('start', 'stop', 'reload')
                    or self.headers.get('X-MCPHub-Tunnel-Control') != '1'
                    or self.headers.get('Content-Type', '').split(';')[0] != 'application/json'
                    or self.headers.get('Content-Length') != '2'):
                self.send(403, b'Forbidden', 'text/plain')
                return
            if self.rfile.read(2) != b'{}':
                self.send(400, b'Bad request', 'text/plain')
                return
            try:
                result = manager.command(parts[3], parts[4])
            except (ValueError, OSError):
                self.send(409, b'Configuration unavailable', 'text/plain')
                return
            self.send(200, json.dumps(result).encode())
    return Handler


def main():
    logging.basicConfig(level=logging.INFO, format='[%(levelname)s] [tunnel-control] %(message)s')
    manager = Controls()
    server = ThreadingHTTPServer(PORT, handler_for(manager))
    server.daemon_threads = True
    stopped = threading.Event()

    def stop(_signum, _frame):
        stopped.set()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        while not stopped.is_set():
            manager.tick()
            stopped.wait(5)
    finally:
        server.shutdown()
        server.server_close()
        manager.cloudflare.stop_process()


if __name__ == '__main__':
    main()
