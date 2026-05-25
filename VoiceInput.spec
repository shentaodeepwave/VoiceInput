# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for VoiceInput.

Build command:
    pyinstaller VoiceInput.spec

Output will be in dist/VoiceInput/
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(SPECPATH)  # directory containing this .spec file

# Locate correct OpenSSL DLLs — avoid Git/mingw64 copies on PATH
_PYTHON_DLLS = Path(sys.base_prefix) / "DLLs"

a = Analysis(
    [str(PROJECT_ROOT / "run.py")],
    pathex=[str(PROJECT_ROOT / "voiceinput")],
    binaries=[
        (str(_PYTHON_DLLS / "libcrypto-3-x64.dll"), "."),
        (str(_PYTHON_DLLS / "libssl-3-x64.dll"), "."),
    ],
    datas=[
        (str(PROJECT_ROOT / "voiceinput" / "config.yaml"), "."),
    ],
    hiddenimports=[
        "sounddevice",
        "numpy",
        "PySide6.QtCore",
        "PySide6.QtGui",
        "PySide6.QtWidgets",
        "websocket",
        "keyboard",
        "pynput",
        "pyperclip",
        "yaml",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter",
        "matplotlib",
        "pandas",
        "scipy",
        "PIL",
        "curses",
        "email",
        "urllib3",
        "setuptools",
        "pip",
        "pytest",
        "sqlite3",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=None,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=None)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="VoiceInput",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,                # No console window
    disable_windowed_traceback=False,
    target_arch=sys.maxsize > 2**32 and "x86_64" or "x86",
    codesign_identity=None,
    entitlements_file=None,
    icon=None,                    # Add icon path here: str(PROJECT_ROOT / "icon.ico"),
)
