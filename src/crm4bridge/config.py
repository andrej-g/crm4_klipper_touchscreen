"""Bridge configuration: INI file + command-line overrides."""
import configparser
import json
import math
from urllib.parse import urlsplit
import os
from .link import parse_screen_spec

DEFAULTS = {
    'moonraker': 'http://127.0.0.1:7125',
    'api_key': '',
    'screen': 'tcp:127.0.0.1:7901',
    'screen_startup_timeout': '5',
    'dry_run': 'true',
    'poll_interval': '1.0',
    'language': '1',
    'filament_sensor': 'filament_sensor',
    'mesh_gcode': 'G28\nBED_MESH_CALIBRATE METHOD=rapid_scan',
    'autolevel_variable': 'PRINT_START:per_print_mesh',
    'mainsail_url': '',
    'model_name': 'CR-M4',
    'print_size': '450x450x470',
    'state_file': '~/.crm4bridge.json',
    'move_feedrate': '6000',
    'z_feedrate': '600',
    'extrude_feedrate': '300',
    'machine_page': 'true',
    'shutdown_plug': '',
    'shutdown_plug_user': '',
    'shutdown_plug_password': '',
    'shutdown_plug_output': '1',
    'shutdown_plug_delay': '60',
    'thumbnails': 'true',
    'brightness': '',
    'standby_brightness': '',
    'standby_timeout': '',
    'spoolman': 'true',
    'spoolman_interval': '10',
    'mesh_grid': '5',
    'curve_interval': '1.0',
    'curve_byte_gap': '0.0008',
}

DEFAULT_PRESETS = {'PLA': (200, 60), 'ABS': (240, 100), 'PETG': (235, 75), 'TPU': (225, 50),
                   'Nylon': (250, 80), 'PA': (260, 90), 'Custom': (210, 60)}


class Config:
    def __init__(self, path=None, overrides=None):
        cp = configparser.ConfigParser(interpolation=None)
        cp.read_dict({'bridge': DEFAULTS})
        if path:
            if not cp.read(path):
                raise FileNotFoundError(path)
        for k, v in (overrides or {}).items():
            if v is not None:
                cp['bridge'][k] = str(v)
        b = cp['bridge']
        self.moonraker = b['moonraker']
        self.api_key = b['api_key'] or None
        self.screen = b['screen']
        parse_screen_spec(self.screen)
        self.screen_startup_timeout = b.getfloat('screen_startup_timeout')
        if not math.isfinite(self.screen_startup_timeout) or self.screen_startup_timeout <= 0:
            raise ValueError('screen_startup_timeout must be finite and greater than zero')
        url = urlsplit(self.moonraker)
        if url.scheme not in ('http', 'https') or not url.hostname:
            raise ValueError('moonraker must be an http:// or https:// URL with a host')
        _ = url.port  # Reject malformed/out-of-range ports before any worker starts.
        if url.username or url.password or url.query or url.fragment:
            raise ValueError('moonraker URL must not contain credentials, a query or a fragment; use api_key separately')
        self.dry_run = b.getboolean('dry_run')
        self.poll_interval = b.getfloat('poll_interval')
        self.language = b.getint('language')
        self.filament_sensor = b['filament_sensor']
        self.mesh_gcode = b['mesh_gcode'].replace('\\n', '\n')
        self.autolevel_variable = b['autolevel_variable']
        self.mainsail_url = b['mainsail_url']
        self.model_name = b['model_name']
        self.print_size = b['print_size']
        self.state_file = os.path.expanduser(b['state_file'])
        self.move_feedrate = b.getint('move_feedrate')
        self.z_feedrate = b.getint('z_feedrate')
        self.extrude_feedrate = b.getint('extrude_feedrate')
        self.machine_page = b.getboolean('machine_page')
        self.shutdown_plug = b['shutdown_plug'].strip()
        self.shutdown_plug_user = b['shutdown_plug_user'] or None
        self.shutdown_plug_password = b['shutdown_plug_password'] or None
        self.shutdown_plug_output = b.getint('shutdown_plug_output')
        self.shutdown_plug_delay = b.getfloat('shutdown_plug_delay')
        self.thumbnails = b.getboolean('thumbnails')
        opt = lambda k: b.getint(k) if b[k].strip() else None
        self.brightness, self.standby_brightness = opt('brightness'), opt('standby_brightness')
        self.standby_timeout = opt('standby_timeout')
        self.spoolman = b.getboolean('spoolman')
        self.spoolman_interval = b.getfloat('spoolman_interval')
        self.mesh_grid = b.getint('mesh_grid')                  # 5 (pages 28/135) or 4 (27/134)
        if self.mesh_grid not in (4, 5):
            raise ValueError('mesh_grid must be 4 or 5')
        self.curve_interval = b.getfloat('curve_interval')      # s between PID graph points
        self.curve_byte_gap = b.getfloat('curve_byte_gap')      # s between the bytes of a curve write, 0 = off
        self.presets = dict(DEFAULT_PRESETS)
        if cp.has_section('presets'):
            canon = {k.lower(): k for k in DEFAULT_PRESETS}
            for name, val in cp['presets'].items():
                n, b_ = (int(x) for x in val.split(','))
                self.presets[canon.get(name, name)] = (n, b_)


class State:
    """Small persistent store for values the screen lets you edit (presets, lengths)."""

    def __init__(self, path):
        self.path = path
        self.data = {}
        try:
            with open(path, 'r', encoding='utf-8') as f:
                self.data = json.load(f)
        except (OSError, ValueError):
            pass

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, value):
        self.data[key] = value
        try:
            with open(self.path, 'w', encoding='utf-8') as f:
                json.dump(self.data, f, indent=1)
        except OSError:
            pass
