# -*- mode: python ; coding: utf-8 -*-

a = Analysis(
    ["entrypoint.py"],
    binaries=[],
    datas=[("cpah/resources", "resources/."), ("VERSION", ".")],
    hiddenimports=["PySide6.QtXml", "PySide6.QtUiTools"],
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="cpah",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    # The console is intentional: CPAH 2.0 exposes --version and the read-only
    # --analyze-screenshot diagnostic interface from the portable executable.
    console=True,
    icon="cpah/resources/images/icon.ico",
)
