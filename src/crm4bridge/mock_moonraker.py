"""A tiny simulated printer behind a Moonraker-compatible HTTP API, for
developing the bridge without a real printer.

    python -m crm4bridge.mock_moonraker [--port 7125] [--print-seconds 600]

Implements the endpoints the bridge uses. Heaters move towards their targets,
prints advance in real time, and a handful of G-codes are interpreted. A 50x50
bed mesh (tilted, slightly bowed) is loaded unless --no-mesh; PID_CALIBRATE
makes the heater oscillate around its target for --pid-seconds, then finishes.
"""
import argparse
import json
import math
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

FILES = [
    ('benchy.gcode', 2 * 3600 + 5 * 60, 14230.0, 240, 0.2),
    ('cr-m4 tool holder v3.gcode', 5 * 3600, 52010.0, 410, 0.2),
    ('calibration cube.gcode', 25 * 60, 3100.0, 100, 0.2),
    ('lito_x1_case_zaba.gcode', 9 * 3600 + 40 * 60, 98000.0, 590, 0.16),
]

# (id, vendor, name, material, colour, remaining g, filament weight g)
SPOOLS = [
    (1, 'Generic', 'Basic White', 'PLA', 'FFFFFF', 640.0, 1000),
    (2, 'Generic', 'Matte Sky Blue', 'PLA', '5FB0C7', 194.0, 1000),
    (3, 'Generic', 'Hyper Speed Black', 'PETG', '313131', 227.0, 1000),
    (4, 'Generic', 'Carbon Fibre Black', 'PLA-CF', '222222', 480.0, 1000),
    (5, 'Generic', 'Tough Grey CF', 'PETG-CF', '757470', 900.0, 1000),
    (6, 'Generic', 'Silk Gold Sample With A Very Long Name', 'PLA', 'C9A227', 20.0, 50),
    (7, 'Generic', 'Translucent Red', 'ASA', 'BF4140', 750.0, 1000),
]


MESH_MIN, MESH_MAX, MESH_N = (50.0, 18.0), (420.0, 420.0), 50
PID_CYCLES = 5              # oscillations per simulated autotune


def make_mesh(seed=0, n=MESH_N):
    """A plausible 50x50 mesh: a plane tilted a little in X and Y with a shallow bowl in the
    middle, about -0.13..+0.02 mm like the real bed. ``seed`` shifts it slightly so a
    re-probe gives different numbers."""
    (x0, y0), (x1, y1) = MESH_MIN, MESH_MAX
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    rows = []
    for j in range(n):
        y = y0 + (y1 - y0) * j / (n - 1)
        row = []
        for i in range(n):
            x = x0 + (x1 - x0) * i / (n - 1)
            bowl = ((x - cx) / (x1 - x0)) ** 2 + ((y - cy) / (y1 - y0)) ** 2    # 0 centre .. 0.5 corner
            z = -0.06 + 0.00012 * (x - cx) - 0.00008 * (y - cy) - 0.10 * bowl + 0.003 * seed
            row.append(round(z + 0.0015 * math.sin(i * 1.7 + j * 0.9 + seed), 6))
        rows.append(row)
    return rows


def _thumb_png(name, w, h):
    """A made-up slicer thumbnail (needs Pillow; None without it)."""
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return None
    import io
    im = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    dr = ImageDraw.Draw(im)
    hue = sum(name.encode()) % 6
    col = [(230, 90, 60), (60, 160, 230), (90, 200, 90), (230, 200, 60), (180, 90, 220), (230, 130, 40)][hue]
    dr.rounded_rectangle([w * 0.15, h * 0.3, w * 0.85, h * 0.85], radius=w // 12, fill=col + (255,))
    dr.ellipse([w * 0.3, h * 0.1, w * 0.7, h * 0.5], fill=tuple(c // 2 for c in col) + (255,))
    dr.text((w * 0.2, h * 0.88), name[:24], fill=(255, 255, 255, 255))
    out = io.BytesIO()
    im.save(out, 'PNG')
    return out.getvalue()


def _thumbs(name):
    """Moonraker-style thumbnail list (the cube has none)."""
    if name.startswith('calibration'):
        return []
    stem = name.rsplit('.', 1)[0]
    return [{'width': w, 'height': h, 'size': 1000, 'relative_path': f'.thumbs/{stem}-{w}x{h}.png'}
            for w, h in ((32, 32), (300, 300))]


def spool_json(s):
    sid, vendor, name, mat, colour, rem, weight = s
    return {'id': sid, 'remaining_weight': rem, 'used_weight': weight - rem,
            'remaining_length': rem / (1.24 * 3.1416 * 0.0875 ** 2) * 10,     # 1.75 mm, ~1.24 g/cm3, mm
            'archived': False, 'location': 'Dryer' if sid == 3 else 'Shelf',
            'last_used': f'2026-09-{28 - sid:02d}T10:00:00Z' if sid < 6 else None,
            'filament': {'id': sid, 'name': name, 'material': mat, 'color_hex': colour, 'weight': weight,
                         'density': 1.24, 'diameter': 1.75, 'vendor': {'id': 1, 'name': vendor}}}


class Printer:
    def __init__(self, print_seconds, pid_seconds=40.0, mesh=True):
        self.lock = threading.Lock()
        self.print_seconds = print_seconds
        self.pid_seconds = pid_seconds
        self.mesh_seed = 0
        self.mesh = make_mesh() if mesh else None
        self.mesh_name = 'default' if mesh else ''
        self.pid = None                                      # {'heater', 'target', 't0'} while PID_CALIBRATE runs
        self.klippy = 'ready'
        self.klippy_msg = 'Printer is ready'
        self.t = {'extruder': [23.0, 0.0], 'heater_bed': [23.0, 0.0]}
        self.fan = 0.0
        self.speed = 1.0
        self.zoff = 0.0
        self.pos = [0.0, 0.0, 0.0, 0.0]
        self.homed = ''
        self.sensor = {'enabled': True, 'filament_detected': True}
        self.per_print_mesh = 0
        self.max_accel, self.max_velocity, self.scv = 1700.0, 500.0, 5.0
        self.print = {'state': 'standby', 'filename': '', 'print_duration': 0.0, 'message': ''}
        self.progress = 0.0
        self.mtime = time.time()
        self.busy_until = 0
        self.spools = [list(s) for s in SPOOLS]
        self.spool_id = 3
        self.host_actions = []
        self.spoolman_connected = True

    def tick(self, dt):
        with self.lock:
            pid = self.pid
            for name, h in self.t.items():
                if pid and pid['heater'] == name:
                    # autotune: relay oscillation around the target, amplitude settling 10 -> 3 C
                    el = time.monotonic() - pid['t0']
                    amp = max(3.0, 10.0 - 7.0 * el / self.pid_seconds)
                    h[0] = pid['target'] + amp * math.sin(2 * math.pi * PID_CYCLES * el / self.pid_seconds)
                    h[1] = pid['target']
                    if el >= self.pid_seconds:
                        self.pid = None
                    continue
                goal = h[1] if h[1] > 23 else 23.0
                h[0] += (goal - h[0]) * min(1.0, dt * (0.15 if h[1] else 0.03))
            if self.print['state'] == 'printing':
                self.print['print_duration'] += dt
                self.progress = min(1.0, self.progress + dt / self.print_seconds)
                for s in self.spools:                       # ~0.05 g/s on the active spool
                    if s[0] == self.spool_id:
                        s[5] = max(0.0, s[5] - 0.05 * dt)
                if self.progress >= 1.0:
                    self.print['state'] = 'complete'

    def status(self, wanted):
        ex, bed = self.t['extruder'], self.t['heater_bed']
        all_ = {
            'webhooks': {'state': self.klippy, 'state_message': self.klippy_msg},
            'extruder': {'temperature': ex[0], 'target': ex[1], 'can_extrude': ex[0] >= 170},
            'heater_bed': {'temperature': bed[0], 'target': bed[1]},
            'fan': {'speed': self.fan},
            'gcode_move': {'speed_factor': self.speed, 'homing_origin': [0, 0, self.zoff, 0],
                           'gcode_position': list(self.pos)},
            'toolhead': {'homed_axes': self.homed, 'max_accel': self.max_accel,
                         'max_velocity': self.max_velocity, 'square_corner_velocity': self.scv},
            'print_stats': dict(self.print),
            'display_status': {'progress': self.progress, 'message': None},
            'virtual_sdcard': {'progress': self.progress, 'is_active': self.print['state'] == 'printing'},
            'idle_timeout': {'state': 'Printing' if self.print['state'] == 'printing' else 'Idle'},
            'filament_switch_sensor filament_sensor': dict(self.sensor),
            'gcode_macro PRINT_START': {'per_print_mesh': self.per_print_mesh},
            'bed_mesh': {'profile_name': self.mesh_name if self.mesh else '',
                         'mesh_min': list(MESH_MIN) if self.mesh else [0, 0],
                         'mesh_max': list(MESH_MAX) if self.mesh else [0, 0],
                         'probed_matrix': self.mesh or [[]], 'mesh_matrix': self.mesh or [[]],
                         'profiles': {'default': {}}},
        }
        return {k: v for k, v in all_.items() if k in wanted}

    def gcode(self, script):
        for line in script.splitlines():
            line = line.strip()
            u = line.upper()
            m = re.match(r'SET_HEATER_TEMPERATURE HEATER=(\w+) TARGET=([\d.]+)', u)
            if m:
                self.t[m.group(1).lower()][1] = float(m.group(2))
            elif u.startswith('TURN_OFF_HEATERS'):
                for h in self.t.values():
                    h[1] = 0.0
            elif u.startswith('M106'):
                s = re.search(r'S(\d+)', u)
                self.fan = (int(s.group(1)) if s else 255) / 255
            elif u.startswith('M107'):
                self.fan = 0.0
            elif u.startswith('M220'):
                self.speed = int(re.search(r'S(\d+)', u).group(1)) / 100
            elif u.startswith('G28'):
                time.sleep(2)
                axes = re.findall(r'[XYZ]', u[3:]) or ['X', 'Y', 'Z']
                for a in axes:
                    self.pos['XYZ'.index(a)] = 0.0
                self.homed = ''.join(sorted(set(self.homed) | {a.lower() for a in axes}, key='xyz'.index))
            elif u.startswith('G1'):
                for a, v in re.findall(r'([XYZE])(-?[\d.]+)', u):
                    if a != 'E':
                        self.pos['XYZ'.index(a)] = float(v)
            elif u.startswith('M84'):
                self.homed = ''
            elif u.startswith('SET_GCODE_OFFSET'):
                self.zoff = float(re.search(r'Z=(-?[\d.]+)', u).group(1))
            elif u.startswith('SET_FILAMENT_SENSOR'):
                self.sensor['enabled'] = u.rstrip().endswith('ENABLE=1')
            elif u.startswith('SET_GCODE_VARIABLE') and 'PER_PRINT_MESH' in u:
                self.per_print_mesh = int(u.rsplit('=', 1)[1])
            elif u.startswith('SET_VELOCITY_LIMIT'):
                for k, v in re.findall(r'(\w+)=([\d.]+)', u):
                    if k == 'ACCEL':
                        self.max_accel = float(v)
                    elif k == 'VELOCITY':
                        self.max_velocity = float(v)
                    elif k == 'SQUARE_CORNER_VELOCITY':
                        self.scv = float(v)
            elif u.startswith('PID_CALIBRATE'):
                m = re.search(r'HEATER=(\w+)', u)
                t = re.search(r'TARGET=([\d.]+)', u)
                heater = (m.group(1).lower() if m else 'extruder')
                if heater not in self.t:
                    raise ValueError(f'unknown heater {heater}')
                with self.lock:
                    self.pid = {'heater': heater, 'target': float(t.group(1)) if t else 200.0,
                                't0': time.monotonic()}
                while self.pid:                              # Moonraker blocks until the script is done
                    time.sleep(0.2)
            elif u.startswith('BED_MESH_CALIBRATE'):
                time.sleep(5)
                m = re.search(r'PROFILE=(\S+)', line, re.I)
                with self.lock:
                    self.mesh_seed += 1
                    self.mesh, self.mesh_name = make_mesh(self.mesh_seed), (m.group(1) if m else 'default')
            elif u.startswith('BED_MESH_CLEAR'):
                with self.lock:
                    self.mesh, self.mesh_name = None, ''
            elif u.startswith('BED_MESH_PROFILE'):
                m = re.search(r'LOAD=(\S+)', line, re.I)
                if m:
                    with self.lock:
                        self.mesh, self.mesh_name = make_mesh(self.mesh_seed), m.group(1)
            elif u == 'SAVE_CONFIG':
                self._restart(3)
            elif u.startswith('RUNOUT'):            # mock-only helper: simulate a runout pause
                self.sensor['filament_detected'] = False
                self.print['state'] = 'paused'

    def _restart(self, seconds):
        def run():
            with self.lock:
                self.klippy, self.klippy_msg = 'startup', 'Printer is restarting'
            time.sleep(seconds)
            with self.lock:
                self.klippy, self.klippy_msg = 'ready', 'Printer is ready'
                self.print = {'state': 'standby', 'filename': '', 'print_duration': 0.0, 'message': ''}
                self.progress = 0.0
        threading.Thread(target=run, daemon=True).start()


def make_handler(pr: Printer):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _ok(self, result, code=200):
            body = json.dumps({'result': result} if code == 200 else {'error': {'message': result}}).encode()
            self.send_response(code)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _spoolman_proxy(self, q):
            if not pr.spoolman_connected:
                return self._ok('Spoolman not connected', 503)
            method, path = q.get('request_method', 'GET'), q.get('path', '')

            def answer(resp, err=None):
                if q.get('use_v2_response') in (True, 'true', 'True', 1):
                    return self._ok({'response': resp, 'response_headers': {}, 'error': err})
                return self._ok(resp) if err is None else self._ok(err['message'], err['status_code'])
            with pr.lock:
                spools = {s[0]: spool_json(s) for s in pr.spools}
            if method == 'GET' and path == '/v1/spool':
                return answer(list(spools.values()))
            m = re.fullmatch(r'/v1/spool/(\d+)', path)
            if method == 'GET' and m:
                s = spools.get(int(m.group(1)))
                if s is None:
                    return answer(None, {'status_code': 404, 'message': f'No spool with ID {m.group(1)}'})
                return answer(s)
            return answer(None, {'status_code': 404, 'message': f'mock: {method} {path} not implemented'})

        def do_GET(self):
            u = urlparse(self.path)
            q = {k: v[0] for k, v in parse_qs(u.query, keep_blank_values=True).items()}
            p = u.path
            if p == '/server/info':
                return self._ok({'klippy_state': pr.klippy, 'klippy_connected': True})
            if p == '/printer/info':
                return self._ok({'state': pr.klippy, 'state_message': pr.klippy_msg, 'hostname': 'mock-printer',
                                 'software_version': 'v0.13.0-mock'})
            if p == '/printer/objects/query':
                with pr.lock:
                    return self._ok({'eventtime': time.time(), 'status': pr.status(set(q))})
            if p == '/server/files/list':
                return self._ok([{'path': f[0], 'modified': pr.mtime - i * 3600, 'size': 1000000}
                                 for i, f in enumerate(FILES)])
            if p == '/server/files/metadata':
                for name, est, fil, layers, lh in FILES:
                    if name == q.get('filename'):
                        return self._ok({'filename': name, 'estimated_time': est, 'filament_total': fil,
                                         'object_height': layers * lh, 'layer_height': lh,
                                         'thumbnails': _thumbs(name)})
                return self._ok('file not found', 404)
            if p == '/server/spoolman/status':
                return self._ok({'spoolman_connected': pr.spoolman_connected, 'pending_reports': [],
                                 'spool_id': pr.spool_id})
            if p == '/server/spoolman/spool_id':
                return self._ok({'spool_id': pr.spool_id})
            if p.startswith('/server/files/gcodes/'):
                from urllib.parse import unquote
                rel = unquote(p[len('/server/files/gcodes/'):])
                folder, _, base = rel.rpartition('/')
                if folder.endswith('.thumbs') and base.endswith('.png'):
                    stem, _, dims = base[:-4].rpartition('-')
                    w, _, h = dims.partition('x')
                    png = _thumb_png(stem, int(w), int(h)) if w.isdigit() and h.isdigit() else None
                    if png:
                        self.send_response(200)
                        self.send_header('Content-Type', 'image/png')
                        self.send_header('Content-Length', str(len(png)))
                        self.end_headers()
                        self.wfile.write(png)
                        return
                return self._ok('file not found', 404)
            if p == '/server/history/totals':
                return self._ok({'job_totals': {'total_print_time': 123.4 * 3600}})
            return self._ok('not found', 404)

        def do_POST(self):
            u = urlparse(self.path)
            q = {k: v[0] for k, v in parse_qs(u.query, keep_blank_values=True).items()}
            p = u.path
            n = int(self.headers.get('Content-Length') or 0)
            try:
                body = json.loads(self.rfile.read(n) or b'{}') if n else {}
            except ValueError:
                body = {}
            q.update({k: v for k, v in body.items()})
            if p == '/server/spoolman/spool_id':
                sid = q.get('spool_id')
                pr.spool_id = int(sid) if sid not in (None, '', 'null') else None
                return self._ok({'spool_id': pr.spool_id})
            if p == '/server/spoolman/proxy':
                return self._spoolman_proxy(q)
            if p in ('/machine/reboot', '/machine/shutdown'):
                print(f'mock: host {p.rsplit("/", 1)[1]} requested (ignored)')
                pr.host_actions.append(p.rsplit('/', 1)[1])
                return self._ok('ok')
            if pr.klippy != 'ready' and p not in ('/printer/firmware_restart', '/printer/restart'):
                return self._ok('Klippy not ready', 503)
            if p == '/printer/gcode/script':
                pr.gcode(q.get('script', ''))
                return self._ok('ok')
            if p == '/printer/print/start':
                with pr.lock:
                    pr.print = {'state': 'printing', 'filename': q.get('filename', ''), 'print_duration': 0.0,
                                'message': ''}
                    pr.progress = 0.0
                    pr.sensor['filament_detected'] = True
                return self._ok('ok')
            if p in ('/printer/print/pause', '/printer/print/resume', '/printer/print/cancel'):
                with pr.lock:
                    pr.print['state'] = {'pause': 'paused', 'resume': 'printing',
                                         'cancel': 'cancelled'}[p.rsplit('/', 1)[1]]
                    pr.sensor['filament_detected'] = True
                return self._ok('ok')
            if p == '/printer/emergency_stop':
                with pr.lock:
                    pr.klippy, pr.klippy_msg = 'shutdown', 'Shutdown due to M112 command'
                    pr.print['state'] = 'error'
                return self._ok('ok')
            if p in ('/printer/firmware_restart', '/printer/restart'):
                pr._restart(3)
                return self._ok('ok')
            return self._ok('not found', 404)
    return H


def main(argv=None):
    ap = argparse.ArgumentParser(prog='python -m crm4bridge.mock_moonraker')
    ap.add_argument('--host', default='127.0.0.1')
    ap.add_argument('--port', type=int, default=7125)
    ap.add_argument('--print-seconds', type=float, default=600, help='how long a simulated print takes')
    ap.add_argument('--pid-seconds', type=float, default=40, help='how long a simulated PID autotune takes')
    ap.add_argument('--no-mesh', action='store_true', help='start with no bed mesh loaded')
    a = ap.parse_args(argv)
    pr = Printer(a.print_seconds, a.pid_seconds, mesh=not a.no_mesh)

    def ticker():
        last = time.monotonic()
        while True:
            time.sleep(0.5)
            now = time.monotonic()
            pr.tick(now - last)
            last = now
    threading.Thread(target=ticker, daemon=True).start()
    srv = ThreadingHTTPServer((a.host, a.port), make_handler(pr))
    srv.daemon_threads = True
    print(f'mock moonraker on http://{a.host}:{a.port}')
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
