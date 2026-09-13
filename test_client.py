"""Compile all Lua and exercise handlers with a simulated game, never an executor."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


class LuaTests(unittest.TestCase):
    @unittest.skipUnless(os.environ.get('LUAU_EXE'), 'Set LUAU_EXE to a Luau CLI binary')
    def test_connector(self):
        source = Path('client.lua').read_text()
        prefix = source.split('env.WYATT_BRIDGE_STOP = function()')[0]
        def quote(text):
            marker = '='
            while ']' + marker + ']' in text: marker += '='
            return '[' + marker + '[' + text + ']' + marker + ']'
        harness = ('local FULL_SOURCE = ' + quote(source) + '\nlocal HANDLER_SOURCE = ' + quote(prefix) + '\n'
                   + Path('lua_test_template.luau').read_text())
        with tempfile.TemporaryDirectory(dir='.') as directory:
            file = Path(directory) / 'test.luau'; file.write_text(harness)
            result = subprocess.run([os.environ['LUAU_EXE'], str(file)], capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__': unittest.main()
