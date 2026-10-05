"""Minimal Moonraker HTTP client (stdlib only)."""
import json
import urllib.error
import urllib.parse
import urllib.request


class MoonrakerError(Exception):
    pass


class Moonraker:
    def __init__(self, url, api_key=None, timeout=5.0):
        self.url = url.rstrip('/')
        self.api_key = api_key
        self.timeout = timeout

    def _req(self, method, path, params=None, timeout=None):
        q = ('?' + urllib.parse.urlencode(params, safe=',')) if params else ''
        req = urllib.request.Request(self.url + path + q, method=method)
        if self.api_key:
            req.add_header('X-Api-Key', self.api_key)
        try:
            with urllib.request.urlopen(req, timeout=timeout or self.timeout) as r:
                body = json.loads(r.read() or b'{}')
        except urllib.error.HTTPError as e:
            try:
                msg = json.loads(e.read()).get('error', {}).get('message', str(e))
            except Exception:
                msg = str(e)
            raise MoonrakerError(msg) from e
        except (urllib.error.URLError, OSError, ValueError) as e:
            raise MoonrakerError(str(e)) from e
        return body.get('result', body)

    def get(self, path, params=None, timeout=None):
        return self._req('GET', path, params, timeout)

    def post(self, path, params=None, timeout=None):
        return self._req('POST', path, params, timeout)

    # ---- queries -----------------------------------------------------------------------
    def server_info(self):
        return self.get('/server/info')

    def printer_info(self):
        return self.get('/printer/info')

    def query(self, objects: dict):
        """objects: {'extruder': ['temperature', 'target'], 'fan': None, ...}"""
        params = {name: (','.join(attrs) if attrs else '') for name, attrs in objects.items()}
        return self.get('/printer/objects/query', params).get('status', {})

    def files(self):
        return self.get('/server/files/list', {'root': 'gcodes'})

    def metadata(self, filename):
        return self.get('/server/files/metadata', {'filename': filename})

    def history_totals(self):
        return self.get('/server/history/totals')

    # ---- actions -------------------------------------------------------------------------
    def gcode(self, script, timeout=600):
        return self.post('/printer/gcode/script', {'script': script}, timeout=timeout)

    def print_start(self, filename):
        return self.post('/printer/print/start', {'filename': filename})

    def pause(self):
        return self.post('/printer/print/pause')

    def resume(self):
        return self.post('/printer/print/resume')

    def cancel(self):
        return self.post('/printer/print/cancel')

    def emergency_stop(self):
        return self.post('/printer/emergency_stop')

    def firmware_restart(self):
        return self.post('/printer/firmware_restart')

    def restart(self):
        return self.post('/printer/restart')
