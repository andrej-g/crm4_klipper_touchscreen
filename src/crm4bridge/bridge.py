"""The bridge: Moonraker state -> screen VPs, screen touches -> Klipper actions.

Everything that changes the printer goes through ``_gcode`` / ``_api``, which
only log in dry-run mode. Reads (status, files, metadata) always run.
"""
import logging
import os
import queue
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from crm4ui import dgus

from . import ui
from .config import State
from .link import ScreenLink
from .moonraker import Moonraker, MoonrakerError

log = logging.getLogger('crm4bridge')

REPAINT_EVERY = 30.0      # s: full repaint in case the screen rebooted


def _hm(seconds):
    m = int(max(0, seconds) // 60)
    return m // 60, m % 60


def _dur(seconds):
    h, m = _hm(seconds)
    return f'{h}h {m:02d}m' if h else f'{m}m'


class Bridge:
    def __init__(self, cfg, moon=None, link=None):
        self.cfg = cfg
        self.moon = moon or Moonraker(cfg.moonraker, cfg.api_key)
        self.link = link or ScreenLink(cfg.screen, on_connect=self._on_screen_connect)
        self.state = State(cfg.state_file)
        self.cache = {}
        self.cache_lock = threading.Lock()
        self.status = {}
        self.klippy = None
        self.klippy_msg = ''
        self.print_state = None
        self.print_file = None
        self.est_time = None
        self.files = []
        self.selected = None
        self.page = None
        self.page_before_popup = ui.PAGE_MAIN
        self.boot_anim = 0
        self.jobs = ThreadPoolExecutor(1, thread_name_prefix='klipper-action')
        self.stop = threading.Event()
        self._repaint = threading.Event()
        macro, _, var = cfg.autolevel_variable.partition(':')
        self.autolevel = (f'gcode_macro {macro}', var.lower()) if macro and var else None
        self.sensor_obj = f'filament_switch_sensor {cfg.filament_sensor}' if cfg.filament_sensor else None

    # ======================================================================== screen I/O
    def _send(self, frame):
        self.link.send(frame)

    def _write(self, vp, payload: bytes, force=False):
        with self.cache_lock:
            if not force and self.cache.get(vp) == payload:
                return
            self.cache[vp] = payload
        self._send(dgus.write_bytes(vp, payload))

    def word(self, vp, value, force=False):
        self._write(vp, (int(value) & 0xFFFF).to_bytes(2, 'big'), force)

    def text(self, vpn, s, force=False):
        vp, n = vpn
        raw = str(s).encode(dgus.TEXT_ENCODING, 'replace')[:n]
        self._write(vp, raw + b'\x00' * (n - len(raw)), force)

    def set_page(self, page, why=''):
        if page != ui.PAGE_NOT_SUPPORTED and page != ui.PAGE_ERROR:
            self.page_before_popup = page
        self.page = page
        log.debug('page %s %s', page, why)
        self._send(dgus.set_page(page))

    def _on_screen_connect(self):
        with self.cache_lock:
            self.cache.clear()
        self._repaint.set()

    # ======================================================================== actions
    def _gcode(self, script, label=None, then=None):
        return self._job(label or script.replace('\n', ' | '), lambda: self.moon.gcode(script), then)

    def _api(self, label, fn, then=None):
        return self._job(label, fn, then)

    def _job(self, label, fn, then):
        if self.cfg.dry_run:
            log.info('DRY-RUN: %s', label)
            if then:
                then(True)
            return

        def run():
            ok = True
            try:
                log.info('-> %s', label)
                fn()
            except MoonrakerError as e:
                ok = False
                log.warning('%s failed: %s', label, e)
                self.text(ui.TXT_ERROR, str(e)[:20])
                self.text(ui.TXT_MACHINE_MSG, str(e))
                self.set_page(ui.PAGE_ERROR, 'action failed')
            if then:
                then(ok)
        self.jobs.submit(run)

    def _not_supported(self):
        self.set_page(ui.PAGE_NOT_SUPPORTED, 'not supported under Klipper')

    def _printing_page(self):
        return {'printing': ui.PAGE_PRINTING, 'paused': ui.PAGE_PAUSED}.get(self.print_state, ui.PAGE_MAIN)

    # ======================================================================== main loop
    def run(self):
        log.info('bridge: moonraker %s, screen %s, %s', self.cfg.moonraker, self.cfg.screen,
                 'DRY-RUN (no commands are sent)' if self.cfg.dry_run else 'LIVE')
        self.link.start()
        next_poll = next_repaint = 0.0
        while not self.stop.is_set():
            try:
                f = self.link.rx.get(timeout=0.05)
                self.handle_frame(f)
            except queue.Empty:
                pass
            now = time.monotonic()
            if self._repaint.is_set() or now >= next_repaint:
                reconnected = self._repaint.is_set()
                self._repaint.clear()
                with self.cache_lock:
                    self.cache.clear()
                self.push_static()
                # Only force the page after a (re)connect. The screen switches pages
                # by itself for most buttons, so the bridge's idea of the current
                # page is often stale; re-sending it periodically would yank the
                # user back to an older page.
                if reconnected and self.page is not None:
                    self.set_page(self.page, 'reconnect')
                next_repaint = now + REPAINT_EVERY
                next_poll = 0
            if now >= next_poll:
                self.poll()
                next_poll = now + self.cfg.poll_interval

    # ======================================================================== state -> screen
    def push_static(self):
        self.word(ui.VP_LANGUAGE, self.cfg.language)
        self.word(ui.VP_MASCOT, 4)
        for name, (vn, vb) in ui.PRESETS.items():
            n, b = self._preset(name)
            self.word(vn, n)
            self.word(vb, b)
        self.word(ui.VP_FEED_LEN, self.state.get('feed_len', 500))
        self.word(ui.VP_RETRACT_LEN, self.state.get('retract_len', 500))
        self.word(ui.VP_PID_NOZZLE_TEMP, self.state.get('pid_nozzle', 210))
        self.word(ui.VP_PID_BED_TEMP, self.state.get('pid_bed', 60))
        self.word(ui.VP_PID_NOZZLE_CYCLES, 5)
        self.word(ui.VP_PID_BED_CYCLES, 5)
        self.word(ui.VP_TOGGLE_SLEEP, ui.TOGGLE_ON if self.state.get('sleep', True) else ui.TOGGLE_OFF)
        self.word(ui.VP_TOGGLE_VOLUME, ui.TOGGLE_ON if self.state.get('volume', True) else ui.TOGGLE_OFF)
        self._push_language_ticks()
        self.text(ui.TXT_ABOUT['model'], self.cfg.model_name)
        self.text(ui.TXT_ABOUT['size'], self.cfg.print_size)
        self.text(ui.TXT_ABOUT['web'], self.cfg.mainsail_url.replace('http://', '').replace('https://', ''))
        self.text(ui.TXT_ABOUT['hw'], 'Klipper host')

    def _push_language_ticks(self):
        lang = self.cfg.language
        for i, vp in enumerate(ui.VP_LANG_CHECK):
            self.word(vp, 1 if i == lang else 0)
        self.word(0x421E, lang)

    def _preset(self, name):
        p = self.state.get('presets', {}).get(name)
        return tuple(p) if p else self.cfg.presets.get(name, (200, 60))

    def _objects(self):
        objs = {'webhooks': ['state', 'state_message'],
                'extruder': ['temperature', 'target', 'can_extrude'],
                'heater_bed': ['temperature', 'target'],
                'fan': ['speed'],
                'gcode_move': ['speed_factor', 'homing_origin', 'gcode_position'],
                'toolhead': ['homed_axes', 'max_accel', 'max_velocity', 'square_corner_velocity'],
                'print_stats': ['state', 'filename', 'print_duration', 'message'],
                'display_status': ['progress', 'message'],
                'idle_timeout': ['state']}
        if self.sensor_obj:
            objs[self.sensor_obj] = ['enabled', 'filament_detected']
        if self.autolevel:
            objs[self.autolevel[0]] = [self.autolevel[1]]
        return objs

    def poll(self):
        try:
            info = self.moon.server_info()
            klippy = info.get('klippy_state', 'disconnected')
            status = self.moon.query(self._objects()) if klippy == 'ready' else {}
        except MoonrakerError as e:
            klippy, status = 'offline', {}
            self.klippy_msg = f'Moonraker: {e}'
        if klippy != self.klippy:
            self._klippy_changed(klippy)
        if klippy == 'ready' and status:
            self.status = status
            self.push_dynamic(status)
        elif klippy in ('startup', 'disconnected', 'offline'):
            self.boot_anim = (self.boot_anim + 10) % 110
            self.word(ui.VP_BOOT_PROGRESS, min(self.boot_anim, 100))
        self.text(ui.TXT_MACHINE_STATE, f'{klippy}: {self.klippy_msg}'[:40] if self.klippy_msg else klippy)

    def _klippy_changed(self, klippy):
        old, self.klippy = self.klippy, klippy
        log.info('klippy state %s -> %s', old, klippy)
        if klippy == 'ready':
            self.klippy_msg = ''
            try:
                pi = self.moon.printer_info()
                self.text(ui.TXT_ABOUT['fw'], pi.get('software_version', '')[:20])
                self.text(ui.TXT_ABOUT['mac'], pi.get('hostname', '')[:20])
                tot = self.moon.history_totals().get('job_totals', {})
                self.word(ui.VP_TOTAL_HOURS, int(tot.get('total_print_time', 0) / 360))
            except MoonrakerError:
                pass
            self.print_state = None          # force page choice on next status
            self.set_page(ui.PAGE_MAIN, 'klippy ready')
        elif klippy in ('shutdown', 'error'):
            try:
                self.klippy_msg = self.moon.printer_info().get('state_message', '').strip().splitlines()[0]
            except (MoonrakerError, IndexError, AttributeError):
                self.klippy_msg = klippy
            self.text(ui.TXT_ERROR, self.klippy_msg[:20] or klippy)
            self.set_page(ui.PAGE_ERROR, f'klippy {klippy}')
        else:
            self.set_page(ui.PAGE_BOOT, f'klippy {klippy}')

    def push_dynamic(self, s):
        ex, bed = s.get('extruder', {}), s.get('heater_bed', {})
        self.word(ui.VP_NOZZLE, round(ex.get('temperature', 0)))
        self.word(ui.VP_NOZZLE_TARGET, round(ex.get('target', 0)))
        self.word(ui.VP_BED, round(bed.get('temperature', 0)))
        self.word(ui.VP_BED_TARGET, round(bed.get('target', 0)))
        gm = s.get('gcode_move', {})
        self.word(ui.VP_SPEED, round(gm.get('speed_factor', 1) * 100))
        self.word(ui.VP_ZOFFSET, round((gm.get('homing_origin') or [0, 0, 0])[2] * 100))
        pos = gm.get('gcode_position') or [0, 0, 0, 0]
        self.word(ui.VP_POS_X, round(pos[0] * 10))
        self.word(ui.VP_POS_Y, round(pos[1] * 10))
        self.word(ui.VP_POS_Z, round(pos[2] * 10))
        th = s.get('toolhead', {})
        for vp in ui.VP_MAX_ACCEL[:2]:
            self.word(vp, round(th.get('max_accel', 0)))
        for vp in ui.VP_MAX_SPEED[:2]:
            self.word(vp, round(th.get('max_velocity', 0)))
        for vp in ui.VP_MAX_CORNER[:2]:
            self.word(vp, round(th.get('square_corner_velocity', 0)))
        self.word(ui.VP_TOGGLE_FAN, ui.TOGGLE_ON if s.get('fan', {}).get('speed', 0) > 0 else ui.TOGGLE_OFF)
        if self.sensor_obj and self.sensor_obj in s:
            self.word(ui.VP_TOGGLE_RUNOUT, ui.TOGGLE_ON if s[self.sensor_obj].get('enabled') else ui.TOGGLE_OFF)
        if self.autolevel and self.autolevel[0] in s:
            on = int(s[self.autolevel[0]].get(self.autolevel[1], 0) or 0)
            self.word(ui.VP_TOGGLE_AUTOLEVEL, ui.TOGGLE_ON if on else ui.TOGGLE_OFF)
        motors = 'xyz' in (th.get('homed_axes') or '')
        self.word(ui.VP_TOGGLE_MOTORS, 10 if motors else 11)
        self._push_print(s)

    def _push_print(self, s):
        ps = s.get('print_stats', {})
        state, fn = ps.get('state'), ps.get('filename') or ''
        progress = s.get('display_status', {}).get('progress', 0) or 0
        if fn != self.print_file:
            self.print_file = fn
            self.est_time = None
            if fn:
                try:
                    self.est_time = self.moon.metadata(fn).get('estimated_time')
                except MoonrakerError:
                    pass
        self.text(ui.TXT_FILENAME, os.path.splitext(os.path.basename(fn))[0])
        pct = int(progress * 100)
        self.word(ui.VP_PROGRESS_BAR, pct)
        self.word(ui.VP_PROGRESS, pct)
        dur = ps.get('print_duration', 0) or 0
        h, m = _hm(dur)
        self.word(ui.VP_ELAPSED_H, h)
        self.word(ui.VP_ELAPSED_M, m)
        if self.est_time:
            remain = max(0, self.est_time - dur)
        elif progress > 0.01:
            remain = dur / progress - dur
        else:
            remain = 0
        h, m = _hm(remain)
        self.word(ui.VP_REMAIN_H, h)
        self.word(ui.VP_REMAIN_M, m)
        if state != self.print_state:
            old, self.print_state = self.print_state, state
            log.info('print state %s -> %s', old, state)
            self._print_state_changed(old, state, s)

    def _print_state_changed(self, old, new, s):
        if new == 'printing':
            if self.page not in (ui.PAGE_TUNE, ui.PAGE_ZOFFSET_TUNE):
                self.set_page(ui.PAGE_PRINTING, 'printing')
        elif new == 'paused':
            runout = self.sensor_obj and s.get(self.sensor_obj, {}).get('filament_detected') is False
            self.set_page(ui.PAGE_RUNOUT if runout else ui.PAGE_PAUSED, 'paused')
        elif new == 'complete' and old in ('printing', 'paused'):
            self.set_page(ui.PAGE_PRINT_DONE, 'complete')
        elif new in ('cancelled', 'standby') and old in ('printing', 'paused'):
            self.set_page(ui.PAGE_MAIN, new)
        elif new == 'error':
            self.text(ui.TXT_ERROR, (s.get('print_stats', {}).get('message') or 'print error')[:20])
            self.set_page(ui.PAGE_ERROR, 'print error')
        elif old is None and self.page in (None, ui.PAGE_BOOT, ui.PAGE_ERROR):
            self.set_page(ui.PAGE_MAIN, 'initial')

    # ======================================================================== screen -> actions
    def handle_frame(self, f: dgus.Frame):
        if f.cmd != dgus.CMD_READ or f.value is None:
            return
        vp, v = f.vp, f.value
        log.debug('screen 0x%04X = %d', vp, v)
        h = KEYS.get(vp)
        if h:
            return h(self, v)
        h = VALUES.get(vp)
        if h:
            return h(self, vp, dgus.to_signed(v))
        log.info('unhandled screen event 0x%04X = 0x%04X', vp, v)

    # ---- keys -------------------------------------------------------------------
    def k_main(self, k):
        if k == 1:
            self.load_files()
            self.set_page(ui.PAGE_FILES[0], 'file list')
        elif k == 2:
            self.set_page(ui.PAGE_MAIN, 'finish')
        elif k == 3:
            self.set_page(ui.PAGE_PREPARE, 'prepare')
        elif k == 5:
            self.set_page(self._printing_page(), 'print tab')
        elif k == 6:
            self.set_page(ui.PAGE_MAIN, 'language confirmed')

    def k_tune(self, k):
        s = self.status
        if k == 2:
            self.set_page(self._printing_page(), 'tune back')
        elif k == 3:
            on = s.get('fan', {}).get('speed', 0) > 0
            self._gcode('M107' if on else 'M106 S255')
        elif k == 4 and self.autolevel:
            on = int(s.get(self.autolevel[0], {}).get(self.autolevel[1], 0) or 0)
            macro = self.autolevel[0].split(' ', 1)[1]
            self._gcode(f'SET_GCODE_VARIABLE MACRO={macro} VARIABLE={self.autolevel[1]} VALUE={0 if on else 1}')
        elif k == 5:
            if self.klippy == 'ready':
                self.set_page(ui.PAGE_MAIN, 'boot touch')
        elif k == 7 and self.sensor_obj:
            on = s.get(self.sensor_obj, {}).get('enabled', True)
            self._gcode(f'SET_FILAMENT_SENSOR SENSOR={self.cfg.filament_sensor} ENABLE={0 if on else 1}')
        elif k == 9:
            on = not self.state.get('sleep', True)
            self.state.set('sleep', on)
            self.word(ui.VP_TOGGLE_SLEEP, ui.TOGGLE_ON if on else ui.TOGGLE_OFF)

    def k_stop(self, k):
        if k == 0xF1:
            self._api('cancel print', self.moon.cancel)
            self.set_page(ui.PAGE_MAIN, 'cancel')
        elif k == 0xF0:
            self.set_page(self._printing_page(), 'cancel aborted')

    def k_pause(self, k):
        if k == 0xF1:
            self._api('pause print', self.moon.pause)
            self.set_page(ui.PAGE_PAUSED, 'pause')
        elif k == 0xF0:
            self.set_page(ui.PAGE_PRINTING, 'pause aborted')

    def k_resume(self, k):
        if k == 1:
            self._api('resume print', self.moon.resume)
            self.set_page(ui.PAGE_PRINTING, 'resume')
        elif k == 2:
            self.set_page(ui.PAGE_FEED, 'runout: change filament')

    def k_popup_yes(self, k):
        if k == 0xF1:
            self._not_supported()

    def k_preheat(self, k):
        names = {5: 'PLA', 6: 'ABS', 7: 'PETG', 8: 'TPU', 9: 'Nylon', 10: 'PA', 11: 'Custom'}
        if k == 3:
            on = self.status.get('fan', {}).get('speed', 0) > 0
            self._gcode('M107' if on else 'M106 S255')
        elif k == 4:
            self._gcode('TURN_OFF_HEATERS')
        elif k in names:
            n, b = self._preset(names[k])
            self._gcode(f'SET_HEATER_TEMPERATURE HEATER=extruder TARGET={n}\n'
                        f'SET_HEATER_TEMPERATURE HEATER=heater_bed TARGET={b}', f'preheat {names[k]} {n}/{b}')

    def k_prepare(self, k):
        if k == 1:
            self.set_page(ui.PAGE_AUTOLEVEL, 'auto level')
        elif k == 2:
            self.set_page(ui.PAGE_FEED, 'feed')
        elif k == 3:
            self.set_page(ui.PAGE_MOVE[0], 'move')
        elif k == 6:
            self._gcode('M84', 'motors off')
        elif k == 9 and not self.cfg_machine_page():
            self._not_supported()
        elif k == 0xA:
            self.set_page(ui.PAGE_MAIN, 'usb popup')
        elif k == 0xB:
            self.set_page(self.page_before_popup or ui.PAGE_MAIN, 'popup closed')

    def cfg_machine_page(self):
        return bool(getattr(self.cfg, 'machine_page', False))

    def k_back(self, k):
        if k == 1:
            self.set_page(ui.PAGE_PREPARE, 'back')

    def k_level(self, k):
        if k == 0xF1:
            self.set_page(ui.PAGE_LEVELING, 'leveling')
            self._gcode(self.cfg.mesh_gcode, 'bed mesh',
                        then=lambda ok: self.set_page(ui.PAGE_AUTOLEVEL, 'leveling done'))

    def k_home(self, k):
        axes = {3: 'X', 4: 'Y', 5: 'Z', 6: ''}
        if k in axes:
            back = self.page if self.page in ui.PAGE_MOVE else ui.PAGE_MOVE[0]
            self.set_page(ui.PAGE_HOMING, 'homing')
            self._gcode(f'G28 {axes[k]}'.strip(), then=lambda ok: self.set_page(back, 'homed'))

    def k_extrude(self, k):
        if k in (1, 2):
            if self.status and not self.status.get('extruder', {}).get('can_extrude', False):
                self.set_page(ui.PAGE_NEED_HEAT, 'too cold to extrude')
                return
            length = self.state.get('feed_len' if k == 2 else 'retract_len', 500) / 10
            sign = '' if k == 2 else '-'
            self._gcode(f'M83\nG1 E{sign}{length:.1f} F{self.cfg.extrude_feedrate}',
                        f'{"feed" if k == 2 else "retract"} {length:.1f} mm')
        elif k == 5:
            n, _ = self._preset('PLA')
            self._gcode(f'SET_HEATER_TEMPERATURE HEATER=extruder TARGET={n}')
            self.set_page(ui.PAGE_FEED, 'heating for extrusion')
        elif k == 6:
            self.set_page(ui.PAGE_FEED, 'heat declined')

    def k_files(self, k):
        if k == 0:
            self.set_page(ui.PAGE_MAIN, 'files back')
        elif k == 1 and self.selected:
            path = self.selected['path']
            self._api(f'start print {path}', lambda: self.moon.print_start(path))
            if self.cfg.dry_run:
                self.set_page(ui.PAGE_MAIN, 'dry-run start')
        elif k == 9:
            self.set_page(ui.PAGE_FILES[0], 'preview back')

    def k_file_row(self, k):
        i = k - 1
        if 0 <= i < len(self.files):
            self.show_preview(self.files[i])

    def k_adv(self, k):
        if k in (7, 8):
            self._not_supported()

    def k_adv2(self, k):
        if k in (1, 2, 3, 4, 5):
            self._not_supported()
        elif k == 6:
            on = not self.state.get('volume', True)
            self.state.set('volume', on)
            self.word(ui.VP_TOGGLE_VOLUME, ui.TOGGLE_ON if on else ui.TOGGLE_OFF)

    def k_pid(self, k):
        if k in (1, 3):
            heater = 'extruder' if k == 1 else 'heater_bed'
            target = self.state.get('pid_nozzle' if k == 1 else 'pid_bed', 210 if k == 1 else 60)
            run, done = ((ui.PAGE_PID_NOZZLE_RUN, ui.PAGE_PID_NOZZLE_DONE) if k == 1
                         else (ui.PAGE_PID_BED_RUN, ui.PAGE_PID_BED_DONE))
            self.set_page(run, 'pid')
            self._gcode(f'PID_CALIBRATE HEATER={heater} TARGET={target}',
                        then=lambda ok: self.set_page(done if ok else ui.PAGE_ERROR, 'pid done'))
        elif k in (2, 4):
            self._gcode('SAVE_CONFIG', 'SAVE_CONFIG (Klipper restarts)')
            self.set_page(ui.PAGE_SETTINGS, 'pid saved')
        elif k in (5, 6):
            self.set_page(ui.PAGE_SETTINGS, 'pid discarded')

    def k_language(self, k):
        # The language is fixed by the config (English by default); the klipper_ui build
        # removes the language tile, and on a stock UI a pick is ignored and undone.
        log.info('language selection ignored (fixed to %d by the config)', self.cfg.language)
        self.word(ui.VP_LANGUAGE, self.cfg.language)
        self._push_language_ticks()

    def k_machine(self, k):
        if k == 1:
            self._api('EMERGENCY STOP', self.moon.emergency_stop)
        elif k == 2:
            self._api('FIRMWARE_RESTART', self.moon.firmware_restart)
        elif k == 3:
            self._api('RESTART', self.moon.restart)

    def k_ignore(self, k):
        pass

    def k_not_supported(self, k):
        self._not_supported()

    def k_resume_power_loss(self, k):
        self.set_page(ui.PAGE_MAIN, 'no power-loss recovery')

    def k_page26(self, k):
        self.set_page(ui.PAGE_AUTOLEVEL, 'leveling point popup')

    # ---- values -----------------------------------------------------------------
    def v_temp(self, vp, v):
        heater = 'extruder' if vp == ui.VP_NOZZLE_TARGET else 'heater_bed'
        self._gcode(f'SET_HEATER_TEMPERATURE HEATER={heater} TARGET={v}')

    def v_speed(self, vp, v):
        self._gcode(f'M220 S{v}')

    def v_zoffset(self, vp, v):
        homed = 'z' in (self.status.get('toolhead', {}).get('homed_axes') or '')
        self._gcode(f'SET_GCODE_OFFSET Z={v / 100:.2f}' + (' MOVE=1' if homed else ''))

    def v_move(self, vp, v):
        axis = {ui.VP_POS_X: 'X', ui.VP_POS_Y: 'Y', ui.VP_POS_Z: 'Z'}[vp]
        homed = self.status.get('toolhead', {}).get('homed_axes') or ''
        if self.print_state in ('printing', 'paused'):
            log.info('move refused while printing')
        elif axis.lower() not in homed:
            log.info('move %s refused: axis not homed', axis)
        else:
            feed = self.cfg.z_feedrate if axis == 'Z' else self.cfg.move_feedrate
            self._gcode(f'G90\nG1 {axis}{v / 10:.1f} F{feed}', f'move {axis} to {v / 10:.1f}')
            return
        # put the real position back on the screen
        with self.cache_lock:
            self.cache.pop(vp, None)
        pos = (self.status.get('gcode_move', {}).get('gcode_position') or [0, 0, 0])['XYZ'.index(axis)]
        self.word(vp, round(pos * 10))

    def v_store(self, vp, v):
        key = {ui.VP_FEED_LEN: 'feed_len', ui.VP_RETRACT_LEN: 'retract_len',
               ui.VP_PID_NOZZLE_TEMP: 'pid_nozzle', ui.VP_PID_BED_TEMP: 'pid_bed'}[vp]
        self.state.set(key, v)
        self.word(vp, v)

    def v_preset(self, vp, v):
        for name, (vn, vb) in ui.PRESETS.items():
            if vp in (vn, vb):
                n, b = self._preset(name)
                n, b = (v, b) if vp == vn else (n, v)
                presets = dict(self.state.get('presets', {}))
                presets[name] = [n, b]
                self.state.set('presets', presets)
                self.word(vp, v)

    def v_velocity(self, vp, v):
        if vp in ui.VP_MAX_ACCEL[:2]:
            self._gcode(f'SET_VELOCITY_LIMIT ACCEL={v}')
        elif vp in ui.VP_MAX_SPEED[:2]:
            self._gcode(f'SET_VELOCITY_LIMIT VELOCITY={v}')
        elif vp in ui.VP_MAX_CORNER[:2]:
            self._gcode(f'SET_VELOCITY_LIMIT SQUARE_CORNER_VELOCITY={v}')
        else:
            self._not_supported()

    def v_not_supported(self, vp, v):
        self._not_supported()

    # ======================================================================== files
    def load_files(self):
        try:
            files = self.moon.files()
        except MoonrakerError as e:
            log.warning('file list failed: %s', e)
            files = []
        files = sorted(files, key=lambda f: f.get('modified', 0), reverse=True)[:24]
        self.files = files
        for i, (vpn, icon) in enumerate(zip(ui.TXT_FILE_ROWS, ui.VP_FILE_ICONS)):
            if i < len(files):
                self.text(vpn, os.path.splitext(os.path.basename(files[i]['path']))[0])
                self.word(icon, 1)
            else:
                self.text(vpn, '')
                self.word(icon, 0)

    def show_preview(self, f):
        self.selected = f
        name = os.path.splitext(os.path.basename(f['path']))[0]
        self.text(ui.TXT_FILENAME, name)
        self.text(ui.TXT_FILENAME_LONG, name)
        meta = {}
        try:
            meta = self.moon.metadata(f['path'])
        except MoonrakerError as e:
            log.warning('metadata failed: %s', e)
        est = meta.get('estimated_time')
        fil = meta.get('filament_total')
        layers = meta.get('layer_count')
        if not layers and meta.get('object_height') and meta.get('layer_height'):
            layers = round(meta['object_height'] / meta['layer_height'])
        self.text(ui.TXT_EST_TIME, _dur(est) if est else '-')
        self.text(ui.TXT_FILAMENT, f'{fil / 1000:.2f} m' if fil else '-')
        self.text(ui.TXT_LAYERS, str(layers) if layers else '-')
        self.set_page(ui.PAGE_FILE_PREVIEW, 'preview')


KEYS = {
    ui.K_MAIN: Bridge.k_main, ui.K_TUNE: Bridge.k_tune, ui.K_STOP: Bridge.k_stop,
    ui.K_PAUSE: Bridge.k_pause, ui.K_RESUME: Bridge.k_resume,
    ui.K_RESET_CFG: Bridge.k_popup_yes, ui.K_RESTORE_NET: Bridge.k_popup_yes,
    ui.K_PREHEAT: Bridge.k_preheat, ui.K_PREPARE: Bridge.k_prepare, ui.K_BACK: Bridge.k_back,
    ui.K_LEVEL: Bridge.k_level, ui.K_HOME: Bridge.k_home, ui.K_EXTRUDE: Bridge.k_extrude,
    ui.K_FILES: Bridge.k_files, ui.K_FILE_ROW: Bridge.k_file_row, ui.K_ADV: Bridge.k_adv,
    ui.K_ADV2: Bridge.k_adv2, ui.K_PID: Bridge.k_pid, ui.K_PID_NAV: Bridge.k_ignore,
    ui.K_LANGUAGE: Bridge.k_language, ui.K_MACHINE: Bridge.k_machine,
    0x410C: Bridge.k_not_supported,        # set home offsets
    0x405F: Bridge.k_resume_power_loss,    # "resume previous print?"
    0x1008: Bridge.k_page26,
    0x0000: Bridge.k_ignore,               # plain page jumps
}

VALUES = {
    ui.VP_NOZZLE_TARGET: Bridge.v_temp, ui.VP_BED_TARGET: Bridge.v_temp,
    ui.VP_SPEED: Bridge.v_speed, ui.VP_ZOFFSET: Bridge.v_zoffset,
    ui.VP_POS_X: Bridge.v_move, ui.VP_POS_Y: Bridge.v_move, ui.VP_POS_Z: Bridge.v_move,
    ui.VP_FEED_LEN: Bridge.v_store, ui.VP_RETRACT_LEN: Bridge.v_store,
    ui.VP_PID_NOZZLE_TEMP: Bridge.v_store, ui.VP_PID_BED_TEMP: Bridge.v_store,
}
for _vn, _vb in ui.PRESETS.values():
    VALUES[_vn] = VALUES[_vb] = Bridge.v_preset
for _vp in ui.VP_MAX_ACCEL + ui.VP_MAX_SPEED + ui.VP_MAX_CORNER:
    VALUES[_vp] = Bridge.v_velocity
for _vp in ui.VP_PID['extruder'] + ui.VP_PID['heater_bed'] + ui.VP_STEPS + (0x7078, 0x707A):
    VALUES[_vp] = Bridge.v_not_supported
