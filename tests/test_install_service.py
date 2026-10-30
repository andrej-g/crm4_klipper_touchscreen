"""User unit rendering: protect paths and keep real commands opt-in through config."""
import importlib.util
from pathlib import Path, PurePosixPath
import unittest

source = Path(__file__).resolve().parents[1] / 'scripts/install_service.py'
spec = importlib.util.spec_from_file_location('install_service', source)
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class UnitTest(unittest.TestCase):
    def test_paths_and_systemd_specifiers(self):
        text = installer.render_unit(PurePosixPath('/home/test/100% repo'), PurePosixPath('/home/test/my config.cfg'))
        self.assertIn('100%% repo/.venv/bin/python"', text)
        self.assertIn('--config "/home/test/my config.cfg"', text)
        self.assertIn('Type=notify', text)
        self.assertIn('RestartPreventExitStatus=2', text)
        self.assertNotIn('--live', text)
        self.assertNotIn('User=', text)

    def test_newline_path_cannot_inject_unit_directives(self):
        with self.assertRaises(ValueError):
            installer.quote('/home/test\nExecStart=/bad')


if __name__ == '__main__':
    unittest.main()
