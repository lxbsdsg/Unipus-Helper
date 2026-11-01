"""Build the Windows single-file executable."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "unipus-helper.spec"
OUTPUT = ROOT / "dist" / "UnipusHelper.exe"


def main() -> int:
    subprocess.run(
        [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", str(SPEC)],
        cwd=ROOT,
        check=True,
    )
    if not OUTPUT.is_file():
        raise SystemExit(f"Build did not create {OUTPUT}")
    print(f"Built {OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())