"""python -m crm4bridge [-c crm4bridge.cfg] [--moonraker URL] [--screen SPEC] [--live]"""
import argparse
import logging
import os
import sys
import configparser

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
    ap.add_argument('--log-file', help='also write the log to this file (always at debug level)')
    a = ap.parse_args(argv)

    fmt = logging.Formatter('%(asctime)s %(levelname)-7s %(name)s: %(message)s', datefmt='%H:%M:%S')
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    console = logging.StreamHandler()
    console.setLevel(logging.DEBUG if a.verbose else logging.INFO)
    console.setFormatter(fmt)
    root.addHandler(console)
    if a.log_file:
        os.makedirs(os.path.dirname(os.path.abspath(a.log_file)), exist_ok=True)
        fh = logging.FileHandler(a.log_file, encoding='utf-8')
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(fmt)
        root.addHandler(fh)
    overrides = {'moonraker': a.moonraker, 'screen': a.screen, 'state_file': a.state_file}
    if a.live:
        overrides['dry_run'] = 'false'
    elif a.dry_run:
        overrides['dry_run'] = 'true'
    try:
        cfg = Config(a.config, overrides)
        Bridge(cfg).run()
    except KeyboardInterrupt:
        return 0
    except (ValueError, configparser.Error) as e:
        logging.getLogger('crm4bridge').error('configuration error: %s', e)
        return 2
    except (OSError, ImportError) as e:
        logging.getLogger('crm4bridge').error('startup failed: %s', e)
        return 1


if __name__ == '__main__':
    sys.exit(main())
