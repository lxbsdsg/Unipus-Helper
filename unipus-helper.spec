# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller specification for the Windows single-file Web UI build."""

from PyInstaller.utils.hooks import collect_submodules

hiddenimports = collect_submodules("unipus_web") + collect_submodules("uvicorn")

a = Analysis(
    ["unipus_helper_entry.py"],
    pathex=[],
    binaries=[],
    datas=[("unipus_web/web", "unipus_web/web")],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="UnipusHelper",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
)