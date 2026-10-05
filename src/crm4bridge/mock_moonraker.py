"""A tiny simulated printer behind a Moonraker-compatible HTTP API, for
developing the bridge without a real printer.

    python -m crm4bridge.mock_moonraker [--port 7125] [--print-seconds 600]

Implements the endpoints the bridge uses. Heaters move towards their targets,
prints advance in real time, and a handful of G-codes are interpreted.
"""
import argparse
import json
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


def spool_json(s):
    sid, vendor, name, mat, colour, rem, weight = s
    return {'id': sid, 'remaining_weight': rem, 'used_weight': weight - rem,
            'remaining_length': rem / (1.24 * 3.1416 * 0.0875 ** 2) * 10,     # 1.75 mm, ~1.24 g/cm3, mm
            'archived': False, 'location': 'Dryer' if sid == 3 else 'Shelf',
            'last_used': f'2026-09-{28 - sid:02d}T10:00:00Z' if sid < 6 else None,
            'filament': {'id': sid, 'name': name, 'material': mat, 'color_hex': colour, 'weight': weight,
                         'density': 1.24, 'diameter': 1.75, 'vendor': {'id': 1, 'name': vendor}}}


class Printer:
    def __init__(self, print_seconds):
        self.lock = threading.Lock()
        self.print_seconds = print_seconds
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
            for h in self.t.values():
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
            elif u.startswith(('PID_CALIBRATE', 'BED_MESH_CALIBRATE')):
                time.sleep(5)
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
                                         'object_height': layers * lh, 'layer_height': lh})
                return self._ok('file not found', 404)
            if p == '/server/spoolman/status':
                return self._ok({'spoolman_connected': pr.spoolman_connected, 'pending_reports': [],
                                 'spool_id': pr.spool_id})
            if p == '/server/spoolman/spool_id':
                return self._ok({'spool_id': pr.spool_id})
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
    a = ap.parse_args(argv)
    pr = Printer(a.print_seconds)

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
