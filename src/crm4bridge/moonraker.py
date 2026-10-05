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

    def _req(self, method, path, params=None, timeout=None, json_body=None):
        q = ('?' + urllib.parse.urlencode(params, safe=',')) if params else ''
        data = json.dumps(json_body).encode() if json_body is not None else None
        req = urllib.request.Request(self.url + path + q, data=data, method=method)
        if data is not None:
            req.add_header('Content-Type', 'application/json')
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

    # ---- Spoolman (through Moonraker's [spoolman] component) ------------------------------
    def spoolman_status(self):
        """{'spoolman_connected': bool, 'spool_id': int | None, 'pending_reports': [...]}"""
        return self.get('/server/spoolman/status', timeout=3)

    def spoolman_set_spool(self, spool_id):
        return self._req('POST', '/server/spoolman/spool_id', json_body={'spool_id': spool_id})

    def spoolman_request(self, method, path, query=None, body=None):
        """Spoolman API call through Moonraker's proxy, e.g. ('GET', '/v1/spool/13')."""
        req = {'use_v2_response': True, 'request_method': method, 'path': path}
        if query:
            req['query'] = query
        if body is not None:
            req['body'] = body
        res = self._req('POST', '/server/spoolman/proxy', json_body=req, timeout=5)
        if isinstance(res, dict) and 'response' in res:
            if res.get('error'):
                raise MoonrakerError(f"Spoolman: {res['error'].get('message', res['error'])}")
            return res['response']
        return res

    def spoolman_spools(self):
        """All spools that aren't archived."""
        res = self.spoolman_request('GET', '/v1/spool', query='allow_archived=false')
        return list(res or [])

    def spoolman_spool(self, spool_id):
        return self.spoolman_request('GET', f'/v1/spool/{int(spool_id)}')

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

    def machine_reboot(self):
        return self.post('/machine/reboot')

    def machine_shutdown(self):
        return self.post('/machine/shutdown')


def tasmota_delayed_off(address, delay_s, output=1, user=None, password=None, timeout=5.0):
    """Ask a Tasmota plug to switch itself off after delay_s seconds (max 360).

    The plug runs the delay itself, so it still switches off after this host
    has shut down. Uses Tasmota's HTTP command API: Backlog Delay <0.1 s>; Power<n> Off.
    """
    delay = max(2, min(3600, int(round(delay_s * 10))))
    base = address if '://' in address else f'http://{address}'
    params = {'cmnd': f'Backlog Delay {delay}; Power{int(output)} Off'}
    if user:
        params['user'] = user
    if password:
        params['password'] = password
    url = base.rstrip('/') + '/cm?' + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            body = json.loads(r.read() or b'{}')
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise MoonrakerError(f'plug {address}: {e}') from e
    if isinstance(body, dict) and ('Command' in body and body['Command'] == 'Unknown'
                                   or 'WARNING' in body):
        raise MoonrakerError(f'plug {address}: {body}')
    return body
