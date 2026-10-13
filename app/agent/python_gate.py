"""Windows installer runtime probe; run from a file, never through python -c.

Reason: Windows PowerShell 5.1 can strip embedded quotes passed to python -c.
This module must stay importable on Python 3.10 and up.
"""
import sys
import struct
import venv
import ensurepip


def runtime_facts():
    return {
        "PYTHON_PATH": sys.executable,
        "PYTHON_VERSION": sys.version.split()[0],
        "PYTHON_BITS": str(struct.calcsize("P") * 8),
        "PYTHON_VENV": "OK" if hasattr(venv, "EnvBuilder") else "FAIL",
        "PYTHON_ENSUREPIP": "OK" if callable(ensurepip.version) else "FAIL",
    }


def main():
    for key, value in runtime_facts().items():
        print(key + "=" + value, flush=True)
    if sys.version_info < (3, 10) or struct.calcsize("P") * 8 != 64:
        print("ERROR: 64-bit Python >=3.10 is required", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
