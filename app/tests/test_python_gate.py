"""Regression: launch installer probe from .py (no PowerShell -c quoting)."""
from pathlib import Path
import re
import subprocess
import sys
import unittest


class PythonGateTests(unittest.TestCase):
    def test_external_probe_script(self):
        root = Path(__file__).resolve().parents[1]
        probe = root / "agent" / "python_gate.py"
        result = subprocess.run([sys.executable, str(probe)], text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                timeout=20, check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("PYTHON_PATH=", result.stdout)
        self.assertIn("PYTHON_VERSION=", result.stdout)
        self.assertIn("PYTHON_BITS=64", result.stdout)
        self.assertIn("PYTHON_VENV=OK", result.stdout)
        self.assertIn("PYTHON_ENSUREPIP=OK", result.stdout)
        self.assertNotIn("Traceback", result.stderr)

    def test_python_probe_module_importable(self):
        from agent.python_gate import runtime_facts
        self.assertEqual(runtime_facts()["PYTHON_VENV"], "OK")


if __name__ == "__main__":
    unittest.main()
