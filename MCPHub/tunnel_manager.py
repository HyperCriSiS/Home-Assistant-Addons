#!/usr/bin/env python3
"""Isolated OpenAI tunnel supervisor and Ingress-only local control UI.

Only the Nginx Home Assistant Ingress adapter may proxy this loopback service.
Credentials are never returned through its API, logs, or status endpoint.
"""

from __future__ import annotations

import json
import logging
import os
import re
import signal
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import urlopen
from tunnel_diagnostics import TunnelLog

OPTIONS_FILE = Path('/data/options.json')
KEY_FILE = Path('/data/secrets/openai_runtime_api_key')
AUTH_FILE = Path('/data/secrets/mcphub_tunnel_authorization')
CLIENT = '/usr/local/bin/tunnel-client'
CONTROL_ADDR = ('127.0.0.1', 8096)
HEALTH_BASE = 'http://127.0.0.1:8080'
MCP_PATH = re.compile(r'^/mcp(?:/[A-Za-z0-9._$-]+){0,2}$')
TUNNEL_ID = re.compile(r'^tunnel_[0-9a-f]{32}$')
CHECK_INTERVAL = 5
STARTUP_GRACE = 45
LIVENESS_TIMEOUT = 60
READINESS_TIMEOUT = 600
MAX_BACKOFF = 300
LOG = logging.getLogger('tunnel-manager')


def options() -> dict:
    data = json.loads(OPTIONS_FILE.read_text(encoding='utf-8'))
    if not isinstance(data, dict):
        raise ValueError('Home Assistant options must be a JSON object')
    result = dict(data)
    for group in ('openai', 'cloudflare', 'home_assistant', 'github', 'logging'):
        section = data.get(group)
        if isinstance(section, dict):
            result.update(section)
    return result


def valid_mcp_route(route):
    return bool(MCP_PATH.fullmatch(route)) and all(
        part not in ('.', '..') for part in route.split('/')[2:])


def probe(route: str) -> bool:
    try:
        with urlopen(f'{HEALTH_BASE}{route}', timeout=2) as response:
            return response.status == 200
    except (HTTPError, URLError, TimeoutError, OSError):
        return False


def private_key_file(value: str) -> None:
    KEY_FILE.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(KEY_FILE.parent, 0o700)
    # Replace the key atomically without ever creating world-readable files.
    temporary = KEY_FILE.with_suffix('.tmp')
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as handle:
            handle.write(value)
        os.chmod(temporary, 0o600)
        temporary.replace(KEY_FILE)
    finally:
        temporary.unlink(missing_ok=True)


class TunnelManager:
    def __init__(self, *, enabled: bool = False):
        self.lock = threading.RLock()
        self.requested = enabled
        self.process: subprocess.Popen | None = None
        self.state = 'stopped'
        self.last_error = ''
        self.failure_count = 0
        self.next_attempt = 0.0
        self.started = 0.0
        self.ready_since = 0.0
        self.not_live_since = 0.0
        self.not_ready_since = 0.0
        self.last_checked = 0.0
        self.logs = TunnelLog()
        self.logs.add('OpenAI Tunnelverwaltung gestartet')

    def _stop(self) -> None:
        proc = self.process
        self.process = None
        if proc is None:
            return
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
        else:
            proc.wait()

    def _fail(self, reason: str, now: float) -> None:
        self._stop()
        self.failure_count += 1
        delay = min(5 * (2 ** min(self.failure_count - 1, 6)), MAX_BACKOFF)
        self.next_attempt = now + delay
        self.state = 'retrying'
        self.last_error = reason
        self.logs.add('Fehler: ' + reason)
        self.ready_since = self.not_live_since = self.not_ready_since = 0.0
        LOG.warning('%s; retry in %d seconds', reason, delay)

    def _start(self, now: float) -> None:
        try:
            values = options()
            key = str(values.get('openai_runtime_api_key') or '').strip()
            tunnel_id = str(values.get('tunnel_id') or '').strip()
            route = str(values.get('tunnel_mcp_path') or '/mcp')
            level = str(values.get('tunnel_log_level') or 'info')
            if not key or not tunnel_id:
                raise ValueError('OpenAI Runtime API Key or Tunnel ID is missing')
            if not TUNNEL_ID.fullmatch(tunnel_id):
                raise ValueError('OpenAI Tunnel ID is invalid')
            if not valid_mcp_route(route):
                raise ValueError('OpenAI MCP route is invalid')
            if level not in ('debug', 'info', 'warn'):
                raise ValueError('OpenAI log level is invalid')
            if not AUTH_FILE.is_file():
                raise ValueError('MCPHub tunnel authorization file is missing')
            private_key_file(key)
            env = os.environ.copy()
            env.update({
                'CONTROL_PLANE_TUNNEL_ID': tunnel_id,
                'MCP_SERVER_URL': f'http://127.0.0.1:3000{route}',
                'MCP_EXTRA_HEADERS': f'Authorization: file:{AUTH_FILE}',
                'MCP_DISCOVERY_EXTRA_HEADERS': f'Authorization: file:{AUTH_FILE}',
                'MCP_STARTUP_WAIT_TIMEOUT': '30s',
                'MCP_MAX_CONCURRENT_REQUESTS': '20',
                'HEALTH_LISTEN_ADDR': '127.0.0.1:8080',
                'LOG_LEVEL': level,
                'LOG_FORMAT': 'struct-text',
                'LOG_HTTP_RAW_UNSAFE': 'false',
            })
            self.process = subprocess.Popen(
                [CLIENT, 'run', f'--control-plane.api-key=file:{KEY_FILE}'],
                env=env, stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, errors='replace', bufsize=1,
            )
            self.logs.follow(self.process, (key, tunnel_id))
            self.logs.add('Tunnelprozess gestartet')
            self.started = now
            self.ready_since = self.not_live_since = self.not_ready_since = 0.0
            self.state = 'starting'
            self.last_error = ''
            LOG.info('Started optional OpenAI tunnel process (pid %d)', self.process.pid)
        except (ValueError, OSError, subprocess.SubprocessError) as exc:
            # Invalid configuration requires a manual change/reload. Do not churn.
            self._stop()
            self.state = 'error'
            self.requested = False
            self.last_error = str(exc)
            self.logs.add('Start fehlgeschlagen (Einstellungen prüfen)')
            LOG.warning('OpenAI tunnel not started: %s', exc)

    def tick(self, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        with self.lock:
            if not self.requested:
                return
            if self.process is None:
                if now >= self.next_attempt:
                    self._start(now)
                return
            exit_code = self.process.poll()
            if exit_code is not None:
                self._fail(f'OpenAI tunnel exited (code {exit_code})', now)
                return
            live = probe('/healthz')
            ready = probe('/readyz') if live else False
            self.last_checked = now
            if live:
                self.not_live_since = 0.0
            else:
                self.not_live_since = self.not_live_since or now
            if ready:
                if not self.ready_since:
                    self.ready_since = now
                self.not_ready_since = 0.0
                self.state = 'ready'
                self.last_error = ''
                if now - self.ready_since >= 90:
                    self.failure_count = 0
            else:
                self.ready_since = 0.0
                self.not_ready_since = self.not_ready_since or now
                self.state = 'degraded' if live else 'starting'
            if now - self.started < STARTUP_GRACE:
                return
            if not live and now - self.not_live_since >= LIVENESS_TIMEOUT:
                self._fail('OpenAI tunnel health endpoint is not responding', now)
            elif live and not ready and now - self.not_ready_since >= READINESS_TIMEOUT:
                self._fail('OpenAI tunnel readiness has been unavailable for 10 minutes', now)

    def command(self, action: str) -> dict:
        with self.lock:
            if action not in ('start', 'stop', 'reload'):
                raise ValueError('Unsupported action')
            if action in ('stop', 'reload'):
                self._stop()
            self.logs.add('Aktion: ' + action)
            if action == 'stop':
                self.requested = False
                self.state = 'stopped'
                self.last_error = ''
                self.next_attempt = 0
            else:
                self.requested = True
                self.next_attempt = 0
                self.failure_count = 0
                if self.process is None:
                    self._start(time.monotonic())
            return self.snapshot()

    def snapshot(self) -> dict:
        with self.lock:
            now = time.monotonic()
            return {
                'state': self.state,
                'requested': self.requested,
                'process_alive': self.process is not None and self.process.poll() is None,
                'last_error': self.last_error,
                'failed_attempts': self.failure_count,
                'retry_in_seconds': max(0, round(self.next_attempt - now)) if self.state == 'retrying' else 0,
                'health_checked': bool(self.last_checked),
                'health_age_seconds': round(now - self.last_checked) if self.last_checked else None,
            }

    def shutdown(self) -> None:
        with self.lock:
            self.requested = False
            self._stop()


PAGE = '''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>OpenAI Tunnel Control</title><style>
:root{font-family:system-ui,sans-serif;color-scheme:light dark}body{max-width:650px;margin:3rem auto;padding:0 1rem;line-height:1.5}
button{font:inherit;padding:.55rem .9rem;margin:.25rem .4rem .25rem 0;cursor:pointer}button:disabled{cursor:wait;opacity:.5}
pre{white-space:pre-wrap;overflow-wrap:anywhere;padding:1rem;border:1px solid #777;border-radius:.4rem}
</style></head><body><h1>OpenAI Secure Tunnel</h1><p>Manage the tunnel without restarting MCPHub.</p>
<p><strong id="state">Checking…</strong></p><p id="detail" aria-live="polite"></p>
<div><button data-action="start">Start</button><button data-action="stop">Stop</button><button data-action="reload">Reload</button></div>
<p>Health monitoring checks the local tunnel process and readiness. Temporary network failures are left to the client;
prolonged failures trigger a delayed restart. Changes to MCPHub bearer-key scopes may still require an App restart.</p>
<script src="app.js" defer></script></body></html>'''

SCRIPT = '''async function refresh(){try{const r=await fetch('api/status',{cache:'no-store'});
const d=await r.json();document.getElementById('state').textContent=d.state;
document.getElementById('detail').textContent=d.last_error || (d.state==='retrying'?`Retry in ${d.retry_in_seconds}s`:'');
}catch(_){document.getElementById('state').textContent='Status unavailable';}}
document.querySelectorAll('button[data-action]').forEach(b=>b.addEventListener('click',async()=>{
for(const x of document.querySelectorAll('button'))x.disabled=true;
try{await fetch('api/'+b.dataset.action,{method:'POST',headers:{'Content-Type':'application/json','X-MCPHub-Tunnel-Control':'1'},body:'{}'});await refresh();}
finally{for(const x of document.querySelectorAll('button'))x.disabled=false;}}));
refresh();setInterval(refresh,5000);'''


def handler_for(manager: TunnelManager):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args) -> None:
            LOG.debug('Control HTTP: ' + format, *args)

        def send(self, content: bytes, mime: str, status: int = 200) -> None:
            self.send_response(status)
            self.send_header('Content-Type', mime)
            self.send_header('Content-Length', str(len(content)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Security-Policy',
                             "default-src 'none'; script-src 'self'; connect-src 'self'; style-src 'unsafe-inline'; base-uri 'none'; frame-ancestors 'self'")
            self.end_headers()
            self.wfile.write(content)

        def do_GET(self):
            if self.path in ('/', '/index.html'):
                self.send(PAGE.encode(), 'text/html; charset=utf-8')
            elif self.path == '/app.js':
                self.send(SCRIPT.encode(), 'text/javascript; charset=utf-8')
            elif self.path == '/api/status':
                self.send(json.dumps(manager.snapshot()).encode(), 'application/json')
            elif self.path == '/api/logs':
                self.send(json.dumps(manager.logs.snapshot()).encode(), 'application/json')
            else:
                self.send(b'Not found', 'text/plain', 404)

        def do_POST(self):
            action = self.path.removeprefix('/api/')
            if (self.path not in ('/api/start', '/api/stop', '/api/reload')
                    or self.headers.get('X-MCPHub-Tunnel-Control') != '1'
                    or self.headers.get('Content-Type', '').split(';')[0] != 'application/json'
                    or self.headers.get('Content-Length', '0') != '2'):
                self.send(b'Forbidden', 'text/plain', 403)
                return
            self.rfile.read(2)
            self.send(json.dumps(manager.command(action)).encode(), 'application/json')

    return Handler


def main() -> None:
    logging.basicConfig(level=logging.INFO, format='[%(levelname)s] [tunnel-manager] %(message)s')
    try:
        enabled = bool(options().get('tunnel_enabled', False))
    except (ValueError, OSError):
        enabled = False
        LOG.warning('Could not read tunnel settings; starting disabled')
    manager = TunnelManager(enabled=enabled)
    server = ThreadingHTTPServer(CONTROL_ADDR, handler_for(manager))
    server.daemon_threads = True
    halted = threading.Event()

    def stop(_signum, _frame):
        halted.set()
        # shutdown() must be called by another thread, not the signal handler.

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    LOG.info('OpenAI tunnel control is available on loopback only')
    try:
        while not halted.is_set():
            manager.tick()
            halted.wait(CHECK_INTERVAL)
    finally:
        server.shutdown()
        server.server_close()
        manager.shutdown()


if __name__ == '__main__':
    main()
