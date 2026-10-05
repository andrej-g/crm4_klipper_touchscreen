"""python -m crm4bridge [-c crm4bridge.cfg] [--moonraker URL] [--screen SPEC] [--live]"""
import argparse
import logging
import sys

from .bridge import Bridge
from .config import Config


def main(argv=None):
    ap = argparse.ArgumentParser(prog='python -m crm4bridge',
                                 description='Drive the CR-M4 stock touchscreen from Klipper/Moonraker.')
    ap.add_argument('-c', '--config', help='INI file (see crm4bridge.example.cfg)')
    ap.add_argument('--moonraker', help='Moonraker URL, e.g. http://klipper.lan:7125')
    ap.add_argument('--screen', help='serial:/dev/ttyAMA0[@115200] or tcp:127.0.0.1:7901 (emulator)')
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument('--live', action='store_true', help='actually send commands to Klipper')
    mode.add_argument('--dry-run', action='store_true', help='only log commands (default)')
    ap.add_argument('--state-file', help='where screen-edited values (presets, language) are kept')
    ap.add_argument('-v', '--verbose', action='store_true')
    a = ap.parse_args(argv)

    logging.basicConfig(level=logging.DEBUG if a.verbose else logging.INFO,
                        format='%(asctime)s %(levelname)-7s %(name)s: %(message)s', datefmt='%H:%M:%S')
    overrides = {'moonraker': a.moonraker, 'screen': a.screen, 'state_file': a.state_file}
    if a.live:
        overrides['dry_run'] = 'false'
    elif a.dry_run:
        overrides['dry_run'] = 'true'
    cfg = Config(a.config, overrides)
    try:
        Bridge(cfg).run()
    except KeyboardInterrupt:
        return 0


if __name__ == '__main__':
    sys.exit(main())
