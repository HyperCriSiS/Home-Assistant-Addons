#!/usr/bin/env python3
"""Ingress-only tunnel control and local health for OpenAI and Cloudflare."""
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
from urllib.request import Request, urlopen

OPTIONS = Path('/data/options.json')
CF_SECRET = Path('/data/secrets/cloudflare_tunnel_token')
PORT = ('127.0.0.1', 8093)
PATH = re.compile(r'^/mcp(?:/[A-Za-z0-9._$-]+){0,2}$')
CLIENT_KEY = re.compile(r'^[A-Za-z0-9_-]{32,256}$')
LOG = logging.getLogger('tunnel-control')


def options():
    data = json.loads(OPTIONS.read_text(encoding='utf-8'))
    if not isinstance(data, dict):
        raise ValueError('Invalid Home Assistant App options')
    value = dict(data)
    for group in ('openai', 'cloudflare', 'home_assistant', 'github', 'logging'):
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


class Controls:
    def __init__(self):
        self.lock = threading.RLock()
        self.cloudflare = Cloudflare()

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
            raise ValueError('Unknown tunnel')

    def tick(self):
        with self.lock:
            self.cloudflare.tick(time.monotonic())


PAGE = '''<!doctype html>
<html lang="de"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>MCPHub – Tunnelverwaltung</title><style>
:root{font-family:system-ui,sans-serif;color-scheme:light dark}
body{max-width:820px;margin:2rem auto;padding:0 1rem;line-height:1.5}
nav{display:flex;gap:1.3rem;margin-bottom:1.5rem}nav a{color:inherit;text-underline-offset:.3rem}
section{border:1px solid #9997;border-radius:8px;padding:1rem;margin:1rem 0}
button{font:inherit;padding:.5rem;margin:.2rem;cursor:pointer}
button:disabled{opacity:.6;cursor:wait}small{opacity:.8}
</style></head><body>
<nav aria-label="MCPHub-Verwaltung"><a href="#tunnel">Tunnel</a><a href="#lan">LAN-Zugriff</a></nav>
<main><h1 id="tunnel">Tunnelverwaltung</h1>
<p>OpenAI und Cloudflare unabhängig starten, stoppen und überwachen – ohne MCPHub neu zu starten.</p>
<div id="items"></div>
<p><small>Health prüft die lokalen Tunnelprozesse, deren Readiness und bei Cloudflare den MCP-Ursprung.
Die Erreichbarkeit aus dem öffentlichen Internet wird hier nicht geprüft.</small></p>
<section id="lan"><h2>LAN-Zugriff</h2>
<p>MCPHub unterstützt direkten Zugriff im lokalen Netzwerk. Die Portfreigabe erfolgt unten in
<strong>Home Assistant → Apps → MCPHub → Netzwerk</strong>.</p>
<p><small>„Deaktivierte Ports einblenden“, links z. B. 3000 eintragen; ist der Port belegt,
einen anderen freien Port wählen. 3001/tcp rechts ist der interne Port.
Für LAN gilt die MCPHub-Anmeldung.</small></p></section>
</main><script src="app.js" defer></script></body></html>'''

SCRIPT = '''const tunnels=[['openai','OpenAI Secure Tunnel'],['cloudflare','Cloudflare Tunnel']];
for(const [id,name] of tunnels){
  const box=document.createElement('section');box.id='t-'+id;
  const title=document.createElement('h2');title.textContent=name;box.append(title);
  const status=document.createElement('p');status.className='status';status.setAttribute('aria-live','polite');box.append(status);
  const info=document.createElement('p');info.className='detail';box.append(info);
  for(const action of ['start','stop','reload']){
    const button=document.createElement('button');button.textContent={start:'Start',stop:'Stop',reload:'Neu laden'}[action];
    button.addEventListener('click',async()=>{
      button.disabled=true;
      try{
        const response=await fetch('api/control/'+id+'/'+action,{
          method:'POST',headers:{'Content-Type':'application/json','X-MCPHub-Tunnel-Control':'1'},body:'{}'
        });
        if(!response.ok)throw Error('HTTP '+response.status);
        await refresh();
      }catch(error){info.textContent='Steuerung fehlgeschlagen: '+error.message;}
      finally{button.disabled=false;}
    });box.append(button);
  }
  document.getElementById('items').append(box);
}
async function refresh(){
  try{
    const response=await fetch('api/status',{cache:'no-store'});
    if(!response.ok)throw Error('HTTP '+response.status);
    const all=await response.json();
    for(const [id] of tunnels){
      const el=document.getElementById('t-'+id),data=all[id]||{};
      const ready=data.transport_ready===true?'lokal bereit':'nicht bereit';
      const age=typeof data.health_age_seconds==='number'?' · Prüfung vor '+data.health_age_seconds+' s':'';
      el.querySelector('.status').textContent='Status: '+(data.state||'unbekannt')+' · '+ready+age;
      el.querySelector('.detail').textContent=data.last_error||(
        data.state==='retrying'?'Neuer Versuch in '+data.retry_in_seconds+' s':''
      );
    }
  }catch(error){
    for(const [id] of tunnels)document.querySelector('#t-'+id+' .status').textContent='Status nicht erreichbar';
  }
}
refresh();setInterval(refresh,5000);'''


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
            else:
                self.send(404, b'Not found', 'text/plain')

        def do_POST(self):
            parts = self.path.split('/')
            if (len(parts) != 5 or parts[:3] != ['', 'api', 'control']
                    or parts[3] not in ('openai', 'cloudflare')
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
