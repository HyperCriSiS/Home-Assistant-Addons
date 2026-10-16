#!/usr/bin/env python3
"""Ingress-only administration and process control for optional MCP tunnels.

The HTTP service only binds to loopback and rejects requests without the
per-installation Ingress proxy secret. Never expose this port in the App metadata.
"""
from __future__ import annotations

import hmac
import json
import os
from pathlib import Path
import re
import secrets
import signal
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

DATA = Path('/data')
SECRETS = DATA / 'secrets'
OPTIONS = DATA / 'options.json'
PREFS = DATA / 'tunnel_control.json'
CLIENT_KEY = SECRETS / 'mcphub_client_key'
PROXY_SECRET = SECRETS / 'mcphub_ha_ingress_proxy_secret'
OPENAI_KEY = SECRETS / 'openai_runtime_api_key'
OPENAI_AUTH = SECRETS / 'mcphub_tunnel_authorization'
CF_TOKEN = SECRETS / 'cloudflare_tunnel_token'
APP_PREFIX = '/_addon/'


def atomic_secret(path: Path, value: str) -> None:
    tmp = path.with_suffix('.tmp')
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, 'w', encoding='utf8') as out:
            out.write(value)
        os.replace(tmp, path)
        os.chmod(path, 0o600)
    finally:
        tmp.unlink(missing_ok=True)


def options() -> dict:
    with OPTIONS.open(encoding='utf8') as f:
        return json.load(f)


class Manager:
    def __init__(self):
        self.lock = threading.RLock()
        self.config = options()
        self.prefs = json.loads(PREFS.read_text()) if PREFS.exists() else {}
        self.procs: dict[str, subprocess.Popen | None] = {'cloudflare': None, 'openai': None}
        self.errors: dict[str, str] = {'cloudflare': '', 'openai': ''}
        self.close_requested = False
        self._start_initial()

    def _save_prefs(self):
        tmp = PREFS.with_suffix('.tmp')
        tmp.write_text(json.dumps(self.prefs, indent=2) + '\n', encoding='utf8')
        os.chmod(tmp, 0o600)
        tmp.replace(PREFS)

    def enabled(self, service: str) -> bool:
        key = 'cloudflare_tunnel_enabled' if service == 'cloudflare' else 'tunnel_enabled'
        return bool(self.prefs.get(service, self.config.get(key, False)))

    def configured(self, service: str) -> bool:
        if service == 'cloudflare':
            return bool(str(self.config.get('cloudflare_tunnel_token', '')).strip())
        tunnel_id = str(self.config.get('tunnel_id', '')).strip()
        return bool(str(self.config.get('openai_runtime_api_key', '')).strip()) and bool(re.fullmatch(r'tunnel_[0-9a-f]{32}', tunnel_id))

    def _start_initial(self):
        for service in self.procs:
            if self.enabled(service):
                self._start(service)

    def _start(self, service: str):
        if not self.configured(service):
            self.errors[service] = 'Zugangsdaten fehlen oder sind ungültig. Bitte in der Home-Assistant-App-Konfiguration hinterlegen.'
            return False
        if self.procs[service] and self.procs[service].poll() is None:
            return True
        if service == 'cloudflare':
            atomic_secret(CF_TOKEN, str(self.config['cloudflare_tunnel_token']).strip())
            cmd = ['/usr/local/bin/cloudflared', 'tunnel', '--no-autoupdate', 'run', '--token-file', str(CF_TOKEN)]
            env = os.environ.copy()
        else:
            atomic_secret(OPENAI_KEY, str(self.config['openai_runtime_api_key']).strip())
            env = os.environ.copy()
            env.update({
                'CONTROL_PLANE_TUNNEL_ID': str(self.config['tunnel_id']),
                'MCP_SERVER_URL': 'http://127.0.0.1:3000' + str(self.config.get('tunnel_mcp_path') or '/mcp'),
                'MCP_EXTRA_HEADERS': 'Authorization: file:' + str(OPENAI_AUTH),
                'MCP_DISCOVERY_EXTRA_HEADERS': 'Authorization: file:' + str(OPENAI_AUTH),
                'MCP_STARTUP_WAIT_TIMEOUT': '30s',
                'MCP_MAX_CONCURRENT_REQUESTS': '20',
                'HEALTH_LISTEN_ADDR': '127.0.0.1:8080',
                'LOG_LEVEL': str(self.config.get('tunnel_log_level', 'info')),
                'LOG_FORMAT': 'struct-text',
                'LOG_HTTP_RAW_UNSAFE': 'false',
            })
            cmd = ['/usr/local/bin/tunnel-client', 'run', '--control-plane.api-key=file:' + str(OPENAI_KEY)]
        try:
            self.procs[service] = subprocess.Popen(cmd, env=env)
            self.errors[service] = ''
            return True
        except OSError:
            self.errors[service] = 'Tunnel-Prozess konnte nicht gestartet werden. App-Protokoll prüfen.'
            return False

    def _stop(self, service: str):
        proc = self.procs[service]
        self.procs[service] = None
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=3)

    def set_enabled(self, service: str, enabled: bool):
        with self.lock:
            if enabled and not self.configured(service):
                return False
            self.prefs[service] = enabled
            self._save_prefs()
            if enabled:
                return self._start(service)
            self._stop(service)
            self.errors[service] = ''
            return True

    def restart(self, service: str):
        with self.lock:
            if not self.enabled(service):
                return False
            self._stop(service)
            return self._start(service)

    def status(self) -> dict:
        with self.lock:
            state = {}
            for service, proc in self.procs.items():
                exit_code = proc.poll() if proc else None
                running = proc is not None and exit_code is None
                error = self.errors[service]
                if proc and exit_code is not None and not error:
                    error = f'Prozess beendet (Exit-Code {exit_code}). App-Protokoll prüfen.'
                state[service] = {
                    'enabled': self.enabled(service),
                    'configured': self.configured(service),
                    'running': running,
                    'error': error,
                }
            return {
                'tunnels': state,
                'cloudflare_path': self.config.get('cloudflare_mcp_path') or '/mcp',
                'openai_path': self.config.get('tunnel_mcp_path') or '/mcp',
                'lan_path': self.config.get('lan_mcp_path') or '/mcp',
            }

    def rotate(self) -> str:
        with self.lock:
            previous = CLIENT_KEY.read_text().strip()
            next_key = secrets.token_urlsafe(48)
            atomic_secret(CLIENT_KEY, next_key)
            try:
                subprocess.run(['/usr/local/bin/prepare_proxy_config.py'], check=True, capture_output=True)
                subprocess.run(['nginx', '-t'], check=True, capture_output=True)
                subprocess.run(['nginx', '-s', 'reload'], check=True, capture_output=True)
            except (OSError, subprocess.CalledProcessError):
                atomic_secret(CLIENT_KEY, previous)
                subprocess.run(['/usr/local/bin/prepare_proxy_config.py'], check=False, capture_output=True)
                raise RuntimeError('Proxy-Aktualisierung fehlgeschlagen; bisheriger Schlüssel bleibt gültig')
            return next_key

    def shutdown(self):
        with self.lock:
            self.close_requested = True
            for service in self.procs:
                self._stop(service)


PAGE = '''<!doctype html><html lang="de"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>MCPHub – Netzwerk und Tunnel</title>
<style>body{font:16px system-ui,sans-serif;margin:auto;max-width:820px;padding:24px;color:#202630;background:#f8f9fb}
section{background:white;border:1px solid #dce0e5;border-radius:12px;padding:20px;margin:16px 0}
button{padding:9px 16px;margin:5px 8px 5px 0;cursor:pointer;border:1px solid #aab;border-radius:8px;background:#f7f7ff}
button:disabled{opacity:.45;cursor:not-allowed}code{overflow-wrap:anywhere}p{line-height:1.5}
small{color:#545f70}.bad{color:#ab1b1b}.good{color:#067042}a{color:#2253a2}</style></head><body>
<h1>Netzwerk und Tunnel</h1><p>Diese Verwaltung ist nur über den Home-Assistant-Adminzugang erreichbar.</p>
<section><h2>Client Key</h2><p>Wird automatisch generiert und lokal gespeichert. Nicht bei Cloudflare hinterlegen. Für Claude als HTTP-Header <code>Authorization: Bearer &lt;Client Key&gt;</code> nutzen.</p>
<button id="copy">Client Key kopieren</button><button id="rotate">Neuen Schlüssel erzeugen</button>
<small>Beim Erneuern funktionieren bereits verbundene externe Clients erst nach Aktualisierung ihres Schlüssels wieder.</small></section>
<section><h2>Cloudflare Tunnel</h2><div id="cloudflare">Status wird geladen …</div><button id="cloudflare-toggle">Ein-/Ausschalten</button><button id="cloudflare-restart">Neu verbinden</button>
<p><small>Cloudflare Tunnel Token und MCP-Pfad werden unter Home Assistant → MCPHub → Konfiguration hinterlegt. Öffentlicher Hostname muss im Cloudflare Dashboard auf <code>http://127.0.0.1:8098</code> zeigen.</small></p></section>
<section><h2>OpenAI Secure MCP Tunnel</h2><div id="openai">Status wird geladen …</div><button id="openai-toggle">Ein-/Ausschalten</button><button id="openai-restart">Neu verbinden</button><p><small>Runtime API Key und Tunnel ID unter Home Assistant → MCPHub → Konfiguration hinterlegen.</small></p></section>
<section><h2>LAN-Zugriff</h2><p>Unter Home Assistant → MCPHub → Netzwerk einen Host-Port (z. B. 3000) eintragen, um den abgesicherten MCP-Endpunkt im LAN verfügbar zu machen. Feld leer lassen, um LAN-Zugriff zu deaktivieren.</p>
<p><small>Der LAN-Endpunkt erwartet denselben Client Key und veröffentlicht nicht das MCPHub-Dashboard.</small></p></section>
<p id="message" role="status"></p><p><a href="../">Zurück zu MCPHub</a></p>
<script>
const api='./api/';
async function request(path,opts={}){const r=await fetch(api+path,{cache:'no-store',credentials:'same-origin',...opts});
const v=await r.json();if(!r.ok)throw Error(v.error||'HTTP '+r.status);return v;}
async function update(){try{const s=await request('status');for(const name of ['cloudflare','openai']){
const t=s.tunnels[name];document.getElementById(name).innerHTML='<strong class="'+(t.running?'good':'bad')+'">'+(t.running?'Prozess läuft':'Prozess gestoppt')+'</strong> · '+(t.enabled?'aktiviert':'deaktiviert')+' · '+(t.configured?'Zugangsdaten vorhanden':'Zugangsdaten fehlen')+(t.error?' · '+esc(t.error):'');
document.getElementById(name+'-toggle').textContent=t.enabled?'Deaktivieren':'Aktivieren';
document.getElementById(name+'-toggle').disabled=!t.enabled&&!t.configured;
document.getElementById(name+'-restart').disabled=!t.enabled;
}}catch(e){msg(e.message,true)}}
function esc(s){const d=document.createElement('div');d.textContent=s;return d.innerHTML}
function msg(s,bad=false){const e=document.getElementById('message');e.textContent=s;e.className=bad?'bad':'good'}
async function post(path,payload){return request(path,{method:'POST',headers:{'Content-Type':'application/json','X-MCPHub-Control':'1'},body:JSON.stringify(payload)})}
for(const name of ['cloudflare','openai']){
document.getElementById(name+'-toggle').onclick=async()=>{try{const s=await request('status');await post('toggle',{service:name,enabled:!s.tunnels[name].enabled});msg('Tunnel-Einstellung übernommen.');await update()}catch(e){msg(e.message,true)}};
document.getElementById(name+'-restart').onclick=async()=>{try{await post('restart',{service:name});msg('Neuverbinden gestartet.');await update()}catch(e){msg(e.message,true)}}}
document.getElementById('copy').onclick=async()=>{try{const k=await request('client-key');if(navigator.clipboard?.writeText){try{await navigator.clipboard.writeText(k.key);msg('Client Key in die Zwischenablage kopiert.');return}catch(e){}}const old=document.getElementById('key-fallback');if(old)old.remove();const field=document.createElement('textarea');field.id='key-fallback';field.value=k.key;field.readOnly=true;field.rows=3;field.style.width='100%';document.getElementById('copy').after(field);field.select();msg('Schlüssel markieren und mit Strg+C kopieren.')}catch(e){msg(e.message,true)}};
document.getElementById('rotate').onclick=async()=>{if(!confirm('Den Client Key jetzt erneuern? Alle verbundenen Clients benötigen anschließend den neuen Schlüssel.'))return;
try{await post('rotate',{});msg('Neuer Schlüssel aktiv. Bitte mit „Client Key kopieren“ in Claude aktualisieren.')}catch(e){msg(e.message,true)}};
update();setInterval(update,10000);
</script></body></html>'''


class Handler(BaseHTTPRequestHandler):
    server_version = 'MCPHubAddonControl'

    def log_message(self, *_args):
        pass  # Never log secrets or query strings.

    def _auth(self) -> bool:
        expected = PROXY_SECRET.read_text().strip()
        supplied = self.headers.get('X-MCPHub-HA-Proxy-Secret', '')
        return bool(supplied) and hmac.compare_digest(expected, supplied)

    def _respond(self, status: int, payload, typ='application/json; charset=utf-8'):
        raw = json.dumps(payload).encode() if not isinstance(payload, str) else payload.encode()
        self.send_response(status)
        self.send_header('Content-Type', typ)
        self.send_header('Content-Length', str(len(raw)))
        self.send_header('Cache-Control', 'no-store, private')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'SAMEORIGIN')
        if typ.startswith('text/html'):
            self.send_header('Content-Security-Policy', "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; base-uri 'none'; form-action 'none'")
        self.end_headers()
        self.wfile.write(raw)

    def _route(self):
        return self.path.partition('?')[0]

    def do_GET(self):
        if not self._auth():
            return self._respond(403, {'error':'Forbidden'})
        path = self._route()
        if path in (APP_PREFIX, APP_PREFIX+'index.html'):
            return self._respond(200, PAGE, 'text/html; charset=utf-8')
        if path == APP_PREFIX+'api/status':
            return self._respond(200, self.server.manager.status())
        if path == APP_PREFIX+'api/client-key':
            return self._respond(200, {'key': CLIENT_KEY.read_text().strip()})
        return self._respond(404, {'error':'Not found'})

    def do_POST(self):
        if not self._auth() or self.headers.get('X-MCPHub-Control') != '1':
            return self._respond(403, {'error':'Forbidden'})
        origin = self.headers.get('Origin')
        if origin and urlparse(origin).netloc != self.headers.get('Host', ''):
            return self._respond(403, {'error':'Invalid origin'})
        if self.headers.get('Content-Type','').split(';')[0] != 'application/json':
            return self._respond(415, {'error':'Expected JSON'})
        try:
            size = int(self.headers.get('Content-Length','0'))
            if size < 0 or size > 4096:
                return self._respond(413, {'error':'Body too large'})
            body = json.loads(self.rfile.read(size))
            if not isinstance(body, dict):
                raise ValueError()
        except (ValueError, json.JSONDecodeError):
            return self._respond(400, {'error':'Invalid JSON'})
        manager = self.server.manager
        path = self._route()
        if path == APP_PREFIX+'api/rotate':
            try:
                manager.rotate()
                return self._respond(200, {'ok': True})
            except RuntimeError as exc:
                return self._respond(500, {'error': str(exc)})
        service = body.get('service')
        if service not in manager.procs:
            return self._respond(400, {'error':'Unknown tunnel'})
        if path == APP_PREFIX+'api/toggle' and type(body.get('enabled')) is bool:
            ok = manager.set_enabled(service, body['enabled'])
        elif path == APP_PREFIX+'api/restart':
            ok = manager.restart(service)
        else:
            return self._respond(400, {'error':'Unknown operation'})
        return self._respond(200 if ok else 409, {'ok':ok, 'error':None if ok else 'Tunnel nicht konfiguriert oder nicht aktiviert'})


def main():
    manager = Manager()
    server = ThreadingHTTPServer(('127.0.0.1', 8097), Handler)
    server.manager = manager
    def stop(*_args):
        manager.shutdown()
        threading.Thread(target=server.shutdown, daemon=True).start()
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        server.serve_forever(poll_interval=0.2)
    finally:
        manager.shutdown()
        server.server_close()


if __name__ == '__main__':
    main()
