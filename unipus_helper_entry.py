"""PyInstaller entry point that preserves the unipus_web package context."""

from unipus_web.__main__ import main

if __name__ == "__main__":
    raise SystemExit(main())