#!/usr/bin/env python3
"""Ingress-only multi-tunnel control: OpenAI, Cloudflare, Tailscale access gates."""
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
from urllib.request import Request, urlopen

OPTIONS = Path('/data/options.json')
CF_SECRET = Path('/data/secrets/cloudflare_tunnel_token')
GATE_FILE = Path('/data/secrets/mcphub_tailscale_control_state.json')
PORT = ('127.0.0.1', 8093)
PATH = re.compile(r'^/mcp(?:/[A-Za-z0-9._$-]+){0,2}$')
CLIENT_KEY = re.compile(r'^[A-Za-z0-9_-]{32,256}$')
LOG = logging.getLogger('tunnel-control')

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
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write(value)
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
            key = str(opts.get('cloudflare_access_token') or '').strip()
            if not self.configured or not token or not PATH.fullmatch(self.route) or not CLIENT_KEY.fullmatch(key):
                raise ValueError('Cloudflare tunnel configuration is incomplete or disabled')
            save_secret(CF_SECRET, token)
            self.proc = subprocess.Popen([
                '/usr/local/bin/cloudflared', 'tunnel', '--no-autoupdate',
                '--metrics', '127.0.0.1:20091',
                'run', '--token-file', str(CF_SECRET)
            ], stdin=subprocess.DEVNULL)
            self.state = 'starting'
            self.started = now
            self.degraded_at = 0.0
            self.error = ''
        except (ValueError, OSError, subprocess.SubprocessError) as error:
            self.stop_process()
            self.desired = False
            self.state = 'error'
            self.error = str(error)

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

class Tailscale:
    def __init__(self):
        self.gates = {'serve': True, 'funnel': True}
        if GATE_FILE.exists():
            try:
                saved = json.loads(GATE_FILE.read_text(encoding='utf-8'))
                for mode in self.gates:
                    if type(saved.get(mode)) is bool:
                        self.gates[mode] = saved[mode]
            except (ValueError, OSError):
                self.gates = {'serve': False, 'funnel': False}

    def configured(self, mode, cfg):
        return (
            bool(cfg.get('tailscale_' + mode + '_enabled')) and
            bool(PATH.fullmatch(str(cfg.get('tailscale_' + mode + '_mcp_path') or ''))) and
            bool(CLIENT_KEY.fullmatch(str(cfg.get('tailscale_' + mode + '_access_token') or '')))
        )

    def allowed(self, mode):
        try:
            return self.gates[mode] and self.configured(mode, options())
        except (ValueError, OSError, KeyError):
            return False

    def command(self, mode, action):
        if action not in ('start', 'stop', 'reload'):
            raise ValueError('Invalid action')
        if action != 'stop' and not self.configured(mode, options()):
            raise ValueError('Tailscale origin not configured')
        # This gates MCP access; the external Tailscale listener is not controlled here.
        self.gates[mode] = action != 'stop'
        save_secret(GATE_FILE, json.dumps(self.gates, sort_keys=True))

    def status(self, mode):
        try:
            cfg = options()
            configured = self.configured(mode, cfg)
            path = str(cfg.get('tailscale_' + mode + '_mcp_path') or '/mcp')
        except (ValueError, OSError):
            configured, path = False, '/mcp'
        enabled = configured and self.gates[mode]
        port = 8094 if mode == 'serve' else 8095
        healthy = check('http://127.0.0.1:%s%s' % (port, path), expected=401) if enabled else False
        return {
            'state': ('origin_ready' if healthy else 'unverified') if enabled else 'stopped',
            'configured': configured, 'requested': enabled,
            'origin_ready': healthy, 'transport_ready': None, 'route': path,
            'control_type': 'access_gate',
            'last_error': 'Local MCP origin not responding' if enabled and not healthy else '',
            'note': 'Only MCP access is gated. External Tailscale listener state is not verifiable or controllable from MCPHub.'
        }

class Controls:
    def __init__(self):
        self.lock = threading.RLock()
        self.cloudflare = Cloudflare()
        self.tailscale = Tailscale()

    def openai(self, action=None):
        headers = {'Cache-Control': 'no-store'}
        if action:
            headers.update({'Content-Type': 'application/json', 'X-MCPHub-Tunnel-Control': '1'})
        req = Request('http://127.0.0.1:8096/api/' + (action or 'status'),
                      headers=headers, data=b'{}' if action else None,
                      method='POST' if action else 'GET')
        try:
            with urlopen(req, timeout=3) as response:
                return json.load(response)
        except (HTTPError, URLError, ValueError, OSError, TimeoutError):
            return {'state': 'unavailable', 'last_error': 'OpenAI control is not available'}

    def snapshot(self):
        with self.lock:
            status = self.openai()
            age = status.get('health_age_seconds')
            if status.get('state') == 'ready' and (age is None or age > 20):
                status['state'] = 'stale'
                status['last_error'] = 'OpenAI health result is stale'
            status['transport_ready'] = status.get('state') == 'ready' if status.get('state') != 'unavailable' else None
            status['control_type'] = 'process'
            return {
                'openai': status,
                'cloudflare': self.cloudflare.status(time.monotonic()),
                'serve': self.tailscale.status('serve'),
                'funnel': self.tailscale.status('funnel'),
            }

    def command(self, mode, action):
        with self.lock:
            if mode == 'openai':
                return self.openai(action)
            if mode == 'cloudflare':
                self.cloudflare.command(action)
                return self.cloudflare.status(time.monotonic())
            if mode in ('serve', 'funnel'):
                self.tailscale.command(mode, action)
                return self.tailscale.status(mode)
            raise ValueError('Unknown tunnel')

    def tick(self):
        with self.lock:
            self.cloudflare.tick(time.monotonic())

PAGE = '''<!doctype html><html lang="de"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>MCPHub Tunnelverwaltung</title><style>
:root{font-family:system-ui,sans-serif;color-scheme:light dark}body{max-width:850px;margin:2rem auto;padding:0 1rem}
section{border:1px solid #9997;border-radius:8px;padding:1rem;margin:1rem 0}button{font:inherit;padding:.5rem;margin:.2rem}
p{line-height:1.5}small{opacity:.8}
</style></head><body><h1>MCPHub Tunnelverwaltung</h1><p>Vier unabhängige Zugänge.</p>
<div id="items"></div><p><small>Tailscale: Start/Stop steuert nur den MCP-Zugang, nicht den externen Tailscale-Daemon.
Ohne eine sichere Add-on-Steuerschnittstelle ist dessen tatsächlicher Listener-Status unbekannt.</small></p>
<script src="app.js" defer></script></body></html>'''
SCRIPT = '''const tunnels=[['openai','OpenAI Secure Tunnel'],['cloudflare','Cloudflare Tunnel'],['serve','Tailscale Serve'],['funnel','Tailscale Funnel']];
for(const [id,name] of tunnels){const box=document.createElement('section');box.id='i-'+id;let h=document.createElement('h2');h.textContent=name;box.append(h);
let st=document.createElement('p');st.className='status';box.append(st);let info=document.createElement('p');info.className='detail';box.append(info);
for(const action of ['start','stop','reload']){let b=document.createElement('button');b.textContent=(id==='serve'||id==='funnel')?({start:'MCP-Zugang freigeben',stop:'MCP-Zugang sperren',reload:'Prüfen'}[action]):({start:'Start',stop:'Stop',reload:'Reload'}[action]);
b.onclick=async()=>{b.disabled=true;try{let r=await fetch('api/control/'+id+'/'+action,{method:'POST',headers:{'Content-Type':'application/json','X-MCPHub-Tunnel-Control':'1'},body:'{}'});if(!r.ok)info.textContent='Steuerung abgewiesen: '+r.status;await refresh();}catch(e){info.textContent='Steuerung nicht erreichbar';}finally{b.disabled=false;}};box.append(b);}document.getElementById('items').append(box);}
async function refresh(){try{let r=await fetch('api/status',{cache:'no-store'});if(!r.ok)throw Error();let all=await r.json();for(const [id] of tunnels){let item=document.getElementById('i-'+id),d=all[id]||{};item.querySelector('.status').textContent='Status: '+(d.state||'unbekannt')+(d.control_type==='access_gate'?' · Externer Tailscale-Status unbekannt':'');item.querySelector('.detail').textContent=d.last_error||d.note||'';}}catch(e){for(const [id] of tunnels)document.querySelector('#i-'+id+' .status').textContent='Status nicht erreichbar';}}refresh();setInterval(refresh,5000);'''

def handler_for(manager):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, message, *args):
            LOG.debug(message, *args)

        def send(self, status, body=b'', mime='application/json'):
            self.send_response(status)
            for key,value in (
                ('Content-Type', mime), ('Content-Length', str(len(body))),
                ('Cache-Control', 'no-store'), ('X-Content-Type-Options', 'nosniff'),
                ('X-Frame-Options', 'SAMEORIGIN'),
                ('Content-Security-Policy', "default-src 'none'; script-src 'self'; connect-src 'self'; style-src 'unsafe-inline'; base-uri 'none'; frame-ancestors 'self'"),
            ):
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path in ('/', '/index.html'):
                self.send(200, PAGE.encode(), 'text/html; charset=utf-8')
            elif self.path == '/app.js':
                self.send(200, SCRIPT.encode(), 'text/javascript; charset=utf-8')
            elif self.path == '/api/status':
                self.send(200, json.dumps(manager.snapshot()).encode())
            elif self.path in ('/api/gate/serve', '/api/gate/funnel'):
                self.send(204 if manager.tailscale.allowed(self.path.rsplit('/',1)[-1]) else 403)
            else:
                self.send(404, b'Not found', 'text/plain')

        def do_POST(self):
            parts = self.path.split('/')
            if (len(parts) != 5 or parts[:3] != ['', 'api', 'control']
                or parts[3] not in ('openai', 'cloudflare', 'serve', 'funnel')
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
                self.send(409, b'Configuration not ready', 'text/plain')
                return
            self.send(200, json.dumps(result).encode())
    return Handler

def main():
    logging.basicConfig(level=logging.INFO, format='[%(levelname)s] [tunnel-control] %(message)s')
    manager = Controls()
    server = ThreadingHTTPServer(PORT, handler_for(manager))
    server.daemon_threads = True
    halt = threading.Event()
    def stop(_signal, _frame):
        halt.set()
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        while not halt.is_set():
            manager.tick()
            halt.wait(5)
    finally:
        server.shutdown()
        server.server_close()
        manager.cloudflare.stop_process()

if __name__ == '__main__':
    main()