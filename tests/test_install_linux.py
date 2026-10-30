"""Exercise installer/update/uninstall with isolated HOME and fake privileged commands."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


@unittest.skipUnless(sys.platform == 'linux' and os.geteuid() != 0, 'non-root Linux smoke test')
class InstallerSmokeTest(unittest.TestCase):
    def test_install_preserves_config_and_uninstall_preserves_data(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo = root / '100% clone with spaces'
            source = Path(__file__).resolve().parents[1]
            (repo / 'scripts').mkdir(parents=True)
            for name in ('install.sh', 'install_service.py', 'uninstall.sh'):
                shutil.copy2(source / 'scripts' / name, repo / 'scripts' / name)
            home, commands = root / 'home', root / 'commands'
            home.mkdir()
            commands.mkdir()
            log = root / 'calls'
            env = dict(os.environ, HOME=str(home), XDG_CONFIG_HOME=str(home / '.config'),
                       PATH=str(commands) + ':' + os.environ['PATH'], CRM4_SMOKE_LOG=str(log))
            def executable(name, text):
                path = commands / name
                path.write_text('#!/bin/bash\nset -eu\n' + text)
                path.chmod(0o755)
            executable('sudo', 'printf "sudo %s\\n" "$*" >> "$CRM4_SMOKE_LOG"\n')
            executable('systemctl', 'printf "systemctl %s\\n" "$*" >> "$CRM4_SMOKE_LOG"\n'
                       '[[ "$*" != *is-active* ]]\n')
            # No apt/pip/systemd actions: delegate only stdlib helper execution.
            executable('python3', '''if [[ "$*" == '-m venv '* ]]; then
mkdir -p "$3/bin"
cat > "$3/bin/python" <<'SH'
#!/bin/bash
if [[ "$1" == '-m' ]]; then exit 0; fi
exec /usr/bin/python3 "$@"
SH
chmod +x "$3/bin/python"
else
exec /usr/bin/python3 "$@"
fi
''')
            def run(script, *args):
                return subprocess.run(['bash', str(repo / 'scripts' / script), *args],
                                      env=env, check=True, capture_output=True, text=True)
            run('install.sh', '--install-deps', '--enable', '--start', '--linger')
            config = home / '.config/crm4bridge/crm4bridge.cfg'
            unit = home / '.config/systemd/user/crm4bridge.service'
            self.assertIn('dry_run = true', config.read_text())
            self.assertEqual(config.stat().st_mode & 0o777, 0o600)
            calls = log.read_text()
            self.assertIn('sudo apt-get update', calls)
            self.assertIn('sudo loginctl enable-linger', calls)
            self.assertIn('systemctl --user enable crm4bridge.service', calls)
            self.assertIn('systemctl --user start crm4bridge.service', calls)
            if shutil.which('systemd-analyze'):
                validation = subprocess.run(['systemd-analyze', '--user', 'verify', str(unit)],
                                            env=env, capture_output=True, text=True)
                self.assertEqual(validation.returncode, 0, validation.stderr)
            custom = config.read_text().replace('dry_run = true', 'dry_run = false')
            config.write_text(custom)
            log.write_text('')
            run('install.sh')
            self.assertEqual(config.read_text(), custom)
            self.assertNotIn('systemctl --user start ', log.read_text())
            run('uninstall.sh')
            self.assertFalse(unit.exists())
            self.assertEqual(config.read_text(), custom)
            self.assertTrue((repo / '.venv').exists())


if __name__ == '__main__':
    unittest.main()
