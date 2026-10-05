"""Browser front-end and host link for the screen emulator (stdlib only).

    python -m crm4ui.emulator <stock private/> [--http 8090] [--link tcp:127.0.0.1:7901]

Open http://127.0.0.1:8090 and point the bridge at the link
(``--screen tcp:127.0.0.1:7901``). ``--link serial:COM7`` exposes the emulator
on a serial port instead (pyserial; e.g. one end of a com0com / socat pair).
"""
import argparse
import os
import io
import json
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from .. import dgus
from ..project import Project
from .screen import ScreenSim

PAGE_HTML = r"""<!doctype html>
<html><head><meta charset="utf-8"><title>CR-M4 screen emulator</title>
<style>
 :root { color-scheme: dark; }
 body { margin: 0; font: 13px/1.4 system-ui, sans-serif; background: #111; color: #ddd; display: flex; gap: 16px; padding: 16px; }
 #frame { position: relative; border: 10px solid #2a2a2a; border-radius: 14px; background: #000; flex: none; }
 #screen { display: block; width: 480px; height: 800px; cursor: crosshair; user-select: none; }
 #side { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 8px; height: 820px; }
 #bar { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; }
 #log { flex: 1; overflow: auto; background: #0b0b0b; border: 1px solid #333; padding: 6px; font: 12px/1.35 ui-monospace, monospace; white-space: pre; }
 .h2s { color: #8fd; } .s2h { color: #fc8; } .local { color: #999; }
 input[type=number] { width: 60px; }
 code { color: #fff; }
</style></head><body>
<div id="frame"><img id="screen" src="/screen.png" draggable="false" alt="screen"></div>
<div id="side">
 <div id="bar">
  <span>page <code id="page">?</code></span>
  <span>host link <code id="link">?</code></span>
  <label><input type="checkbox" id="ov"> touch areas</label>
  <label>go to page <input type="number" id="goto" min="0" max="255"></label>
  <span>click = touch at panel coordinates <code id="xy"></code></span>
 </div>
 <div id="log"></div>
</div>
<script>
const img = document.getElementById('screen'), log = document.getElementById('log');
let ver = 0;
function refresh() { img.src = '/screen.png?v=' + ver + (document.getElementById('ov').checked ? '&overlay=1' : ''); }
img.addEventListener('click', e => {
  const r = img.getBoundingClientRect();
  const x = Math.round((e.clientX - r.left) * 480 / r.width), y = Math.round((e.clientY - r.top) * 800 / r.height);
  fetch('/touch?x=' + x + '&y=' + y, {method: 'POST'});
});
img.addEventListener('mousemove', e => {
  const r = img.getBoundingClientRect();
  document.getElementById('xy').textContent = Math.round((e.clientX - r.left) * 480 / r.width) + ',' + Math.round((e.clientY - r.top) * 800 / r.height);
});
document.getElementById('ov').addEventListener('change', refresh);
document.getElementById('goto').addEventListener('change', e => fetch('/page?n=' + e.target.value, {method: 'POST'}));
const es = new EventSource('/events');
es.onmessage = ev => {
  const m = JSON.parse(ev.data);
  if (m.version !== ver) { ver = m.version; refresh(); }
  document.getElementById('page').textContent = m.page;
  document.getElementById('link').textContent = m.link;
  for (const [seq, t, dir, hex, note] of m.log) {
    const div = document.createElement('div');
    div.className = dir === 'host->scr' ? 'h2s' : dir === 'scr->host' ? 's2h' : 'local';
    div.textContent = `${t} ${dir.padEnd(9)} ${note.padEnd(28)} ${hex}`;
    log.appendChild(div);
  }
  while (log.childNodes.length > 600) log.removeChild(log.firstChild);
  if (m.log.length) log.scrollTop = log.scrollHeight;
};
</script></body></html>"""


class Link:
    """Host link: TCP server (one client at a time) or a serial port."""

    def __init__(self, sim, spec):
        self.sim, self.spec, self.status = sim, spec, 'waiting'
        self._out = None
        sim.send = self.send

    def send(self, frame):
        out = self._out
        if out is not None:
            try:
                out(frame.to_bytes())
            except OSError:
                self._out = None

    def start(self):
        kind, _, arg = self.spec.partition(':')
        target = self._serve_tcp if kind == 'tcp' else self._serve_serial
        threading.Thread(target=target, args=(arg,), daemon=True).start()

    def _pump(self, read):
        parser = dgus.Parser()
        while True:
            data = read()
            if not data:
                return
            for f in parser.feed(data):
                self.sim.handle_host(f)

    def _serve_tcp(self, arg):
        host, _, port = arg.rpartition(':')
        srv = socket.create_server((host or '127.0.0.1', int(port)))
        while True:
            self.status = f'listening tcp:{host or "127.0.0.1"}:{port}'
            conn, addr = srv.accept()
            conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            self.status = f'host connected {addr[0]}:{addr[1]}'
            self._out = conn.sendall
            try:
                self._pump(lambda: conn.recv(4096))
            except OSError:
                pass
            self._out = None
            conn.close()

    def _serve_serial(self, arg):
        import serial
        port, _, baud = arg.partition('@')
        ser = serial.Serial(port, int(baud or 115200), timeout=0.05)
        self.status = f'serial {port}'
        self._out = ser.write
        parser = dgus.Parser()
        while True:
            data = ser.read(256)
            if data:
                for f in parser.feed(data):
                    self.sim.handle_host(f)


def make_handler(sim, link):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, ctype, body):
            self.send_response(code)
            self.send_header('Content-Type', ctype)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            u = urlparse(self.path)
            q = parse_qs(u.query)
            if u.path == '/':
                self._send(200, 'text/html; charset=utf-8', PAGE_HTML.encode())
            elif u.path == '/screen.png':
                buf = io.BytesIO()
                sim.render(overlay='overlay' in q).save(buf, 'PNG')
                self._send(200, 'image/png', buf.getvalue())
            elif u.path == '/state':
                self._send(200, 'application/json', json.dumps({'page': sim.page, 'version': sim.version}).encode())
            elif u.path == '/events':
                self._events()
            else:
                self._send(404, 'text/plain', b'not found')

        def do_POST(self):
            u = urlparse(self.path)
            q = parse_qs(u.query)
            if u.path == '/touch':
                d = sim.touch(int(q['x'][0]), int(q['y'][0]))
                self._send(200, 'application/json', json.dumps(d).encode())
            elif u.path == '/page':
                sim.set_page(int(q['n'][0]), 'manual')
                self._send(200, 'application/json', b'{}')
            else:
                self._send(404, 'text/plain', b'not found')

        def _events(self):
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            seen, last_status = 0, None
            try:
                while True:
                    with sim.changed:
                        sim.changed.wait(timeout=1.0)
                        entries = [e for e in sim.log if e[0] > seen]
                        msg = {'version': sim.version, 'page': sim.page, 'link': link.status, 'log': entries}
                    if entries:
                        seen = entries[-1][0]
                    self.wfile.write(f'data: {json.dumps(msg)}\n\n'.encode())
                    self.wfile.flush()
                    last_status = link.status
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                return
    return Handler


def main(argv=None):
    ap = argparse.ArgumentParser(prog='python -m crm4ui.emulator', description='CR-M4 screen emulator (browser UI)')
    ap.add_argument('private', help='stock (or built) screen private/ directory')
    ap.add_argument('--http', default='127.0.0.1:8090', help='[host:]port for the browser UI')
    ap.add_argument('--link', default='tcp:127.0.0.1:7901', help='tcp:[host:]port or serial:PORT[@baud]')
    ap.add_argument('--page', type=int, default=0, help='start page (default 0, the splash)')
    ap.add_argument('--lang', type=int, help='preset UI language VP 0x5247 (1 = English); normally the host sets it')
    ap.add_argument('--no-ack', action='store_true', help='do not answer VP writes with 5A A5 03 82 4F 4B')
    ap.add_argument('--log', help='append every touch / frame / page change to this text file')
    a = ap.parse_args(argv)

    sim = ScreenSim(Project(a.private), start_page=a.page, lang=a.lang, ack_writes=not a.no_ack)
    sim.log_file = a.log
    if a.log:
        os.makedirs(os.path.dirname(os.path.abspath(a.log)), exist_ok=True)
    link = Link(sim, a.link)
    link.start()
    host, _, port = a.http.rpartition(':')
    httpd = ThreadingHTTPServer((host or '127.0.0.1', int(port)), make_handler(sim, link))
    httpd.daemon_threads = True
    print(f'emulator: http://{host or "127.0.0.1"}:{port}  host link: {a.link}')
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
